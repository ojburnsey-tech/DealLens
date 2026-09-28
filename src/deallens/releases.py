"""Deterministic, allowlisted public exports with attestation and integrity gates."""
import csv
import hashlib
import ipaddress
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, parse_qsl

import duckdb

from .qa import qa_deal
from .research import ResearchDeal, jsonable
from .store import Store

METHODOLOGY = '1.0'
COLUMNS = ('deal_id', 'bidder', 'target', 'announcement_date', 'completion_date', 'status',
           'review_status', 'currency', 'sector', 'geography', 'transaction_type',
           'consideration', 'reported_equity_value', 'reported_equity_value_currency',
           'reported_enterprise_value', 'reported_enterprise_value_currency', 'public_record_json')
COMPANY_COLUMNS = ('deal_id', 'role', 'name', 'country', 'company_number')
FILES = {'deals.csv', 'deals.parquet', 'companies.csv', 'data_dictionary.md',
         'methodology_version.txt', 'release_notes.md', 'manifest.json'}
SECRET = re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?i:api[_ -]?key|password|secret|access[_ -]?token)\s*[:=]\s*\S+')
LOCAL = re.compile(r'(?i:file://|[A-Z]:\\|\\\\|/(?:home|Users|workspace|tmp|root|etc)/)')


def canonical(value) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def safe_text(value: str) -> None:
    """Reject detected private content; never silently rewrite research facts."""
    without_urls = re.sub(r'https?://[^\s\"<>]+', '', value)
    if SECRET.search(value) or LOCAL.search(value) or re.search(r'(?<![\w:/])/(?:[\w.-]+/)+[\w.-]+', without_urls):
        raise ValueError('public export contains a credential pattern or local path')


def public_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('public sources require HTTP(S) URLs without credentials')
    host = parsed.hostname.lower()
    if host == 'localhost' or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('private source hostname')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('private source address')
    if any(re.search(r'(?i)token|secret|password|api.?key|sig|credential|auth|^key$', key) for key, _ in parse_qsl(parsed.query)):
        raise ValueError('source URL contains authentication query parameters')
    if SECRET.search(value) or LOCAL.search(value):
        raise ValueError('unsafe source URL')


def _csv(path, columns, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            # Reject spreadsheet formulas in text columns. Numeric negatives remain valid.
            for key, value in row.items():
                text = '' if value is None else str(value)
                if text.lstrip().startswith(('=', '+', '@', '-')):
                    try:
                        from decimal import Decimal
                        number = Decimal(text)
                        if not number.is_finite():
                            raise ValueError('non-finite CSV number')
                    except Exception as exc:
                        raise ValueError(f'unsafe spreadsheet cell: {key}') from exc
            writer.writerow(row)


def _public_record(deal):
    # Deliberately omit private review notes, reviewer identity and analyst narratives.
    fields = ('schema_version', 'identity', 'bidder', 'target', 'review_status', 'profile',
              'offer_terms', 'selected_offer_id', 'transaction_valuation', 'unaffected_price',
              'target_financials', 'buyer_financials', 'synergies', 'financing',
              'sources', 'field_evidence', 'consideration', 'leverage_inputs', 'accretion_inputs')
    data = deal.model_dump(mode='json', include=set(fields))
    data['profile'].pop('notes', None)
    for source in data['sources']:
        public_url(source['url'])
    safe_text(canonical(data))
    return data


def _row(deal, public):
    offer = next(o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id)
    def money(fact):
        return None if fact is None or fact.amount is None else str(fact.amount)
    return dict(zip(COLUMNS, (deal.identity.deal_id, deal.bidder.name, deal.target.name,
    deal.identity.announcement_date.isoformat(),
    deal.identity.completion_date.isoformat() if deal.identity.completion_date else None,
    deal.identity.transaction_status, 'VERIFIED', offer.price.currency, deal.profile.sector,
    deal.target.country, deal.profile.transaction_type, deal.profile.consideration_type,
    money(deal.transaction_valuation.reported_equity_value),
    deal.transaction_valuation.reported_equity_value.currency if deal.transaction_valuation.reported_equity_value else None,
    money(deal.transaction_valuation.reported_enterprise_value),
    deal.transaction_valuation.reported_enterprise_value.currency if deal.transaction_valuation.reported_enterprise_value else None, canonical(public)), strict=True))


def build_release(store: Store, destination: Path, *, version: str) -> dict:
    """Build atomically into a new directory; existing releases are never overwritten."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', version):
        raise ValueError('invalid release version')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('release destination already exists')
    rows, companies = [], []
    # Consistent snapshot across documents and their verification events.
    db = store.connection
    db.execute('BEGIN TRANSACTION')
    try:
        for deal in store.all():
            if deal.review_status != 'VERIFIED':
                continue
            event = db.execute('SELECT verified_document_sha256 FROM verification_events WHERE deal_id=?',
                               [deal.identity.deal_id]).fetchone()
            digest = hashlib.sha256(deal.model_dump_json().encode()).hexdigest()
            if event is None or event[0] != digest:
                raise ValueError(f'{deal.identity.deal_id}: missing or mismatched document attestation')
            if not qa_deal(deal)['publishable']:
                raise ValueError(f'{deal.identity.deal_id}: QA blocks public release')
            offer = next(o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id)
            if not all((deal.profile.sector, deal.profile.transaction_type, deal.profile.consideration_type,
                        deal.target.country, deal.bidder.country, offer.price.currency)):
                raise ValueError(f'{deal.identity.deal_id}: minimum public classifications missing')
            public = _public_record(deal)
            rows.append(_row(deal, public))
            for role in ('bidder', 'target'):
                company = getattr(deal, role)
                companies.append(dict(zip(COMPANY_COLUMNS, (deal.identity.deal_id, role, company.name,
                                      company.country, company.company_number), strict=True)))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    if not rows:
        raise ValueError('no attested VERIFIED deals; refusing an empty public release')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.deallens-release-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'release'
        staging.mkdir()
        _csv(staging / 'deals.csv', COLUMNS, rows)
        _csv(staging / 'companies.csv', COMPANY_COLUMNS, companies)
        with duckdb.connect(':memory:') as export:
            export.execute('SET threads=1')
            export.execute('CREATE TABLE public_deals (' + ','.join(f'{name} VARCHAR' for name in COLUMNS) + ')')
            export.executemany('INSERT INTO public_deals VALUES (' + ','.join('?' for _ in COLUMNS) + ')',
                               [[row[name] for name in COLUMNS] for row in rows])
            export.execute("COPY (SELECT * FROM public_deals ORDER BY deal_id) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                           [str(staging / 'deals.parquet')])
        dictionary = '# Public data dictionary\n\nAll Parquet columns are nullable UTF-8 strings. Decimal values are lossless base-unit strings. CSV empty cells mean unavailable, never zero.\n\n'
        dictionary += '\n'.join(f'- `{name}`: ' + ('Complete public numerical observations, definitions, individual currencies, periods and source/evidence metadata; JSON.' if name == 'public_record_json' else 'Explicit research field; dates are ISO 8601.' ) for name in COLUMNS)
        dictionary += '\n\n`currency` is offer currency only; valuation currencies are in public_record_json and may differ. Companies rows are per deal/role, not deduplicated legal entities. No implicit FX.\n'
        (staging / 'data_dictionary.md').write_text(dictionary, encoding='utf-8')
        (staging / 'methodology_version.txt').write_text(METHODOLOGY + '\n', encoding='utf-8')
        (staging / 'release_notes.md').write_text(f'# DealLens {version}\n\n{len(rows)} attested VERIFIED transactions. Drafts and private review notes excluded. Source documents are not redistributed.\n', encoding='utf-8')
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(staging.iterdir())}
        manifest = {'version': version, 'methodology': METHODOLOGY, 'deal_count': len(rows),
                    'duckdb_version': duckdb.__version__, 'files': hashes}
        (staging / 'manifest.json').write_text(canonical(manifest) + '\n', encoding='utf-8')
        audit_release(staging)
        staging.rename(destination)
    return manifest


def audit_release(directory: Path) -> dict:
    try:
        return _audit_release(directory)
    except (KeyError, TypeError, StopIteration, json.JSONDecodeError) as exc:
        raise ValueError('malformed public release structure') from exc


def _audit_release(directory: Path) -> dict:
    """Validate exact file allowlist, hashes, row parity and public source metadata."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('release must be a real directory')
    paths = list(directory.iterdir())
    if {p.name for p in paths} != FILES or any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError('unexpected, missing or linked release files')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if set(manifest) != {'version', 'methodology', 'deal_count', 'duckdb_version', 'files'}:
        raise ValueError('invalid manifest schema')
    safe_text(canonical(manifest))
    if set(manifest['files']) != FILES - {'manifest.json'}:
        raise ValueError('invalid manifest file allowlist')
    for name, digest in manifest['files'].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'release checksum mismatch: {name}')
        if name != 'deals.parquet':
            safe_text((directory / name).read_text(encoding='utf-8'))
    with (directory / 'deals.csv').open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError('invalid public deal schema')
        rows = list(reader)
    if not rows or len(rows) != manifest['deal_count'] or len({r['deal_id'] for r in rows}) != len(rows):
        raise ValueError('invalid deal count or duplicate IDs')
    expected_companies = []
    for row in rows:
        if row['review_status'] != 'VERIFIED':
            raise ValueError('unverified public record')
        public = json.loads(row['public_record_json'])
        if public.get('review_status') != 'VERIFIED' or public['identity']['deal_id'] != row['deal_id']:
            raise ValueError('public record identity/status mismatch')
        if 'review_notes' in public or not public.get('sources'):
            raise ValueError('private review metadata or missing sources')
        checked = ResearchDeal.model_validate(public | {'review_status': 'DRAFT'})
        if _public_record(checked) != public | {'review_status': 'DRAFT'}:
            raise ValueError('unexpected private or unsupported public fields')
        expected = _row(checked, public)
        if any((expected[name] or '') != row[name] for name in COLUMNS):
            raise ValueError('flat fields do not match public numerical record')
        if not qa_deal(checked, require_verified=False)['publishable']:
            raise ValueError('public financial/provenance QA failed')
        for role in ('bidder', 'target'):
            company = getattr(checked, role)
            expected_companies.append([row['deal_id'], role, company.name, company.country, company.company_number or ''])
        for source in public['sources']:
            public_url(source['url'])
    with (directory / 'companies.csv').open(encoding='utf-8', newline='') as handle:
        company_reader = csv.reader(handle)
        if tuple(next(company_reader, [])) != COMPANY_COLUMNS or list(company_reader) != expected_companies:
            raise ValueError('company records do not match verified public deals')
    with duckdb.connect(':memory:') as db:
        result = db.execute('SELECT * FROM read_parquet(?) ORDER BY deal_id', [str(directory / 'deals.parquet')])
        if tuple(column[0] for column in result.description) != COLUMNS:
            raise ValueError('invalid parquet columns')
        values = [[value or '' for value in row] for row in result.fetchall()]
    if values != [[row[name] for name in COLUMNS] for row in rows]:
        raise ValueError('CSV/Parquet mismatch')
    return {'valid': True, 'version': manifest['version'], 'deal_count': len(rows),
            'notice': 'Integrity audit; hashes are not a cryptographic signature or independent proof of human review.'}
