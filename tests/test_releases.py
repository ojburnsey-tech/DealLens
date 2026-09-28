"""Public release tests use explicitly synthetic human attestations only."""

import pytest

from deallens.cli import main
from deallens.releases import build_release, audit_release, public_url, safe_text
from deallens.research import ResearchDeal, ResearchProfile
from deallens.store import Store
from test_research import sourced


@pytest.fixture
def public_draft(draft):
    deal = sourced(draft)
    return ResearchDeal.model_validate(deal.model_dump() | {'profile': ResearchProfile(
        sector='Consumer', transaction_type='scheme', consideration_type='cash',
        field_evidence={k: ['E1'] for k in ('sector', 'transaction_type', 'consideration_type')})})


def attest(store, deal):
    store.import_deal(deal)
    return store.verify(deal.identity.deal_id, reviewer='Synthetic fixture reviewer',
                        notes='Synthetic verification test only', confirm_manual_review=True)


def test_deterministic_release_and_no_private_notes(tmp_path, public_draft):
    with Store(':memory:') as store:
        attest(store, public_draft)
        for name in ('first', 'second'):
            build_release(store, tmp_path / name, version='test-1')
    first, second = tmp_path / 'first', tmp_path / 'second'
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}
    assert audit_release(first)['deal_count'] == 1
    assert 'Synthetic fixture reviewer' not in (first / 'deals.csv').read_text()
    assert 'verification_notes' not in (first / 'deals.csv').read_text()


def test_draft_excluded_and_empty_release_rejected(tmp_path, public_draft):
    with Store(':memory:') as store:
        store.import_deal(public_draft)
        with pytest.raises(ValueError, match='no attested'):
            build_release(store, tmp_path / 'release', version='test')
    assert not (tmp_path / 'release').exists()


def test_forged_verified_or_mutated_document_rejected(tmp_path, public_draft):
    with Store(':memory:') as store:
        verified = attest(store, public_draft)
        altered = verified.model_copy(update={'identity': verified.identity.model_copy(update={'name': 'Changed after review'})})
        store.connection.execute('UPDATE deals SET document=?', [altered.model_dump_json()])
        with pytest.raises(ValueError, match='attestation'):
            build_release(store, tmp_path / 'release', version='test')
        store.connection.execute('DELETE FROM verification_events')
        with pytest.raises(ValueError, match='attestation'):
            build_release(store, tmp_path / 'release', version='test')
    assert not (tmp_path / 'release').exists()


def test_legacy_attestation_without_document_hash_blocks(tmp_path, public_draft):
    with Store(':memory:') as store:
        attest(store, public_draft)
        store.connection.execute('UPDATE verification_events SET verified_document_sha256=NULL')
        with pytest.raises(ValueError, match='attestation'):
            build_release(store, tmp_path / 'release', version='test')


@pytest.mark.parametrize('url', ['http://localhost/a', 'http://127.0.0.1/a', 'https://10.0.0.1/a',
    'https://example.com/?api_key=abc', 'https://user:pass@example.com/a', 'file:///tmp/a',
    'https://host.internal/a', 'http://[::1]/a'])
def test_private_source_urls_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.parametrize('value', ['/workspace/private/a.pdf', 'file:///tmp/source.pdf',
    'C:\\Users\\owner\\source.pdf', 'api_key=not-public', '-----BEGIN PRIVATE KEY-----'])
def test_unsafe_public_text_rejected(value):
    with pytest.raises(ValueError):
        safe_text(value)


def test_original_draft_not_exported_beside_verified(tmp_path, public_draft):
    with Store(':memory:') as store:
        attest(store, public_draft)
        other = public_draft.model_copy(update={'identity': public_draft.identity.model_copy(update={'deal_id': 'DL-00002'})})
        store.import_deal(other)
        build_release(store, tmp_path / 'release', version='test')
    assert 'DL-00002' not in (tmp_path / 'release' / 'deals.csv').read_text()


@pytest.mark.parametrize('change', ['extra', 'tamper', 'missing', 'symlink'])
def test_audit_rejects_changed_files(tmp_path, public_draft, change):
    root = tmp_path / 'release'
    with Store(':memory:') as store:
        attest(store, public_draft)
        build_release(store, root, version='test')
    if change == 'extra':
        (root / 'source.pdf').write_bytes(b'document')
    elif change == 'tamper':
        (root / 'deals.csv').write_text('altered')
    elif change == 'missing':
        (root / 'companies.csv').unlink()
    else:
        (root / 'companies.csv').unlink()
        (root / 'companies.csv').symlink_to(tmp_path / 'outside.csv')
    with pytest.raises(ValueError):
        audit_release(root)


def test_output_never_overwritten(tmp_path, public_draft):
    root = tmp_path / 'release'
    root.mkdir()
    (root / 'keep').write_text('original')
    with Store(':memory:') as store:
        attest(store, public_draft)
        with pytest.raises(ValueError, match='already exists'):
            build_release(store, root, version='test')
    assert (root / 'keep').read_text() == 'original'


def test_cli_build_and_audit(tmp_path, public_draft, capsys):
    database = tmp_path / 'test.duckdb'
    with Store(database) as store:
        attest(store, public_draft)
    assert main(['--db', str(database), 'release', 'build', 'test', '--output', str(tmp_path / 'release')]) == 0
    assert main(['release', 'audit', str(tmp_path / 'release')]) == 0
    assert '"valid": true' in capsys.readouterr().out


@pytest.mark.parametrize('value', ['/mnt/private/source.pdf', '/var/data/research.pdf'])
def test_additional_absolute_paths_rejected(value):
    with pytest.raises(ValueError):
        safe_text(value)


@pytest.mark.parametrize('key', ['sig', 'auth', 'key', 'X-Amz-Credential'])
def test_bearer_source_query_rejected(key):
    with pytest.raises(ValueError):
        public_url(f'https://example.com/document.pdf?{key}=sensitive')


def rehash(root):
    import hashlib
    import json
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in manifest['files']}
    (root / 'manifest.json').write_text(json.dumps(manifest))


@pytest.mark.parametrize('change', ['manifest', 'company', 'nested', 'flat_currency'])
def test_semantic_audit_even_after_checksums_updated(tmp_path, public_draft, change):
    import csv
    import json
    import duckdb
    root = tmp_path / 'release'
    with Store(':memory:') as store:
        attest(store, public_draft)
        build_release(store, root, version='test')
    if change == 'manifest':
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['private_note'] = 'api_key=sensitive'
        (root / 'manifest.json').write_text(json.dumps(manifest))
    elif change == 'company':
        with (root / 'companies.csv').open('a') as handle:
            handle.write('DL-99999,target,Unrelated draft company,GB,\n')
    else:
        from deallens.releases import COLUMNS, _csv
        with (root / 'deals.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        if change == 'nested':
            public = json.loads(rows[0]['public_record_json'])
            public['private_extra'] = 'not permitted'
            rows[0]['public_record_json'] = json.dumps(public)
        else:
            rows[0]['currency'] = 'USD'
        _csv(root / 'deals.csv', COLUMNS, rows)
        # Keep Parquet consistent: semantic checks must catch this, not merely parity.
        with duckdb.connect(':memory:') as db:
            db.execute('CREATE TABLE t (' + ','.join(f'{name} VARCHAR' for name in COLUMNS) + ')')
            db.execute('INSERT INTO t VALUES (' + ','.join('?' for _ in COLUMNS) + ')', list(rows[0].values()))
            db.execute('COPY t TO ? (FORMAT PARQUET)', [str(root / 'deals.parquet')])
    rehash(root)
    with pytest.raises(ValueError):
        audit_release(root)


def test_mixed_currency_flat_values_are_explicit(tmp_path, public_draft):
    import csv
    from conftest import fact
    from deallens.research import Valuation
    deal = public_draft.model_copy(update={'transaction_valuation': Valuation(
        reported_equity_value=fact(100, currency='EUR', evidence=('E1',)),
        reported_enterprise_value=fact(120, currency='USD', evidence=('E1',)))})
    with Store(':memory:') as store:
        attest(store, deal)
        build_release(store, tmp_path / 'release', version='test')
    with (tmp_path / 'release' / 'deals.csv').open(newline='') as handle:
        row = next(csv.DictReader(handle))
    assert row['currency'] == 'GBP'
    assert row['reported_equity_value_currency'] == 'EUR'
    assert row['reported_enterprise_value_currency'] == 'USD'


def test_malformed_manifest_is_value_error(tmp_path, public_draft):
    with Store(':memory:') as store:
        attest(store, public_draft)
        build_release(store, tmp_path / 'release', version='test')
    (tmp_path / 'release' / 'manifest.json').write_text('[]')
    with pytest.raises(ValueError):
        audit_release(tmp_path / 'release')
