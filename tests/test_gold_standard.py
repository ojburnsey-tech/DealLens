"""Provisional primary-source reconciliation, NOT an owner's verified fixture.

Expected arithmetic is transcribed independently from source tables, never copied
from a production calculation. See docs/gold_standard_validation.md.
"""
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import duckdb
import pytest

from deallens.cli import main
from deallens.finance import derived_fact, multiple
from deallens.models import Fact
from deallens.qa import evidence_audit, qa_deal
from deallens.research import analyse, load_research
from deallens.store import Store

CASE = Path(__file__).resolve().parents[1] / 'research/inbox/DL-00001.yml'


@pytest.fixture
def gold():
    return load_research(CASE)


def test_import_provenance_and_no_automatic_verification(tmp_path, gold):
    with Store(tmp_path / 'gold.duckdb') as store:
        store.import_file(CASE)
        loaded = store.show('DL-00001')
        assert loaded == gold
        assert loaded.review_status == 'DRAFT'
        assert evidence_audit(loaded)['missing_evidence'] == []
        assert not evidence_audit(loaded)['human_verification']
        # Full underlying deductions survive YAML -> JSON -> DuckDB -> typed model.
        shares = loaded.transaction_valuation.share_components[0].shares
        assert isinstance(shares.derivation.inputs['EBT'], Fact)
        assert shares.derivation.inputs['EBT'].amount == D('1693930')
        assert shares.evidence == ('ESH',)
        assert loaded.target_financials.ebitda.current_ytd.derivation.inputs['ppe_depreciation'].evidence == ('EHDA',)
        before = {table: store.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('deals', 'sources', 'evidence', 'field_facts')}
        with pytest.raises(duckdb.Error):
            store.import_file(CASE)
        assert before == {table: store.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                          for table in before}


def test_equity_bridge_preserves_reported_value(gold):
    result = analyse(gold)['equity']
    fd = D('248906262') + D('6028506') + D('351897') - D('1693930') - D('1785000')
    assert result['fully_diluted_shares'] == fd == D('251807735')
    assert result['calculated_equity_value'].result == D('13.15') * fd == D('3311271715.25')
    assert result['reported_equity_value'].amount == D('3311000000')
    assert gold.transaction_valuation.reported_transaction_value is None


def test_ev_explicit_adjustments_and_rounding(gold):
    result = analyse(gold)['ev']
    expected = sum(map(D, ['3311', '694', '70', '5.5', '23.9'])) * D('1000000')
    assert result['calculated_enterprise_value'].result == expected == D('4104400000')
    assert result['reported_enterprise_value'].amount == D('4104000000')
    assert result['preferred_ev_basis'] == 'reported'
    assert result['reconciliation']['calculated_minus_reported'] == D('400000')
    assert [a.adjustment_id for a in gold.transaction_valuation.ev_adjustments] == ['net_debt', 'leases', 'buybacks', 'cash_awards']
    # Reported adjusted net debt includes more than loans minus cash.
    assert (D('713.5') + D('29.2') - D('29.8') - D('6.1') - D('12.8')) * D('1000000') == gold.target_financials.net_debt.amount


@pytest.mark.parametrize('metric,fy,cy,py,total', [
    ('revenue', '1748.6', '880.3', '794.0', '1834.9'),
    ('ebitda', '287.6', '132.4', '117.5', '302.5'),
    ('ebit', '218.4', '100.4', '85.3', '233.5'),
    ('net_income', '156.7', '67.0', '58.9', '164.8'),
])
def test_ltm_source_arithmetic_and_periods(gold, metric, fy, cy, py, total):
    result = analyse(gold)[f'ltm_{metric}']
    assert result.result == (D(fy) + D(cy) - D(py)) * D('1000000') == D(total) * D('1000000')
    assert result.period.start == date(2023, 4, 1)
    assert result.period.end == date(2024, 3, 31)
    assert result.period.basis == 'LTM'
    assert all(result.inputs[k].evidence for k in ('latest_fy', 'current_ytd', 'prior_ytd'))


def test_underlying_ebitda_definition_reconciliation(gold):
    financials = gold.target_financials.ebitda
    assert financials.current_ytd.amount == (D('100.4') + D('23.7') + D('4.5') + D('9.6') - D('5.8')) * D('1000000')
    assert financials.prior_ytd.amount == (D('85.3') + D('21.7') + D('5.1') + D('8.0') + D('1.7') - D('4.3')) * D('1000000')
    assert financials.selected.amount == D('303000000')
    calculated = analyse(gold)
    # Rounded source denominator cannot exactly reproduce the headline 13.6x.
    assert calculated['ev_ebitda'].result == D('4104') / D('303')
    reconstructed = multiple('ev_ebitda', gold.transaction_valuation.reported_enterprise_value,
                             derived_fact(calculated['ltm_ebitda']))
    assert reconstructed.result == D('4104') / D('302.5')
    assert reconstructed.result.quantize(D('.1')) == D('13.6')
    assert calculated['ev_ebitda'].result.quantize(D('.1')) == D('13.5')


@pytest.mark.parametrize('name,numerator,denominator', [
    ('ev_revenue', '4104', '1834.9'), ('ev_ebitda', '4104', '303'),
    ('ev_ebit', '4104', '233.5'), ('equity_net_income', '3311', '165'),
])
def test_selected_multiples(gold, name, numerator, denominator):
    result = analyse(gold)[name]
    assert result.result == D(numerator) / D(denominator)
    assert result.period.basis == 'LTM'
    assert result.inputs


@pytest.mark.parametrize('reference,price', [('close_19_june', '970'), ('vwap_3m_19_june', '897')])
def test_premium_reference_and_dividend_basis(gold, reference, price):
    result = analyse(gold)['premiums'][reference]
    assert result.result == D('1315') / D(price) - D(1)
    source_ref = next(r for r in gold.unaffected_price if r.reference_id == reference)
    assert source_ref.reference_date == date(2024, 6, 19)
    assert source_ref.selection_notes


def test_consideration_is_not_buyer_funding(gold):
    assert analyse(gold)['consideration'].result == D('12.90') + D('.25')
    assert gold.consideration.cash.amount == D('12.90')
    assert 'Target-paid' in gold.consideration.other.definition
    assert gold.financing.cash_consideration is None


def test_synergy_illustration_and_unknown_revenue(gold):
    result = analyse(gold)['synergies']
    assert result['eligible_cost_synergies'] == D('100000000')
    assert result['cost_synergy_ev'].result == D('100') / D('4104')
    assert result['cost_synergy_ebitda'].result == D('100') / D('303')
    assert result['synergy_adjusted_multiple'].result == D('4104') / (D('303') + D('100'))
    assert result['synergy_adjusted_multiple'].illustrative
    assert result['explicit_margin_revenue_ebitda'] == 0
    assert gold.synergies[2].amount.value is None  # unknown, not established zero
    assert gold.synergies[1].amount.amount == D('83000000')
    assert not gold.synergies[1].eligible


def test_unestablished_leverage_and_eps_are_withheld(gold):
    assert gold.leverage_inputs is None
    assert gold.accretion_inputs is None
    assert gold.buyer_financials.ebitda.selected is None
    assert gold.financing.new_debt is None
    assert 'leverage' not in analyse(gold)
    assert 'accretion' not in analyse(gold)


def test_qa_keeps_real_case_unverified_and_exposes_reconciliation(gold):
    report = qa_deal(gold)
    assert not report['publishable']
    assert any(f.code == 'MANUAL_VERIFICATION_REQUIRED' for f in report['flags'])
    assert {f.field for f in report['flags'] if f.code == 'LTM_RECONCILIATION'} == {
        'target_financials.ebitda', 'target_financials.net_income'}
    assert not any(f.severity == 'ERROR' for f in report['flags'])


def test_cli_complete_draft_workflow(tmp_path, capsys):
    args = ['--db', str(tmp_path / 'case.duckdb')]
    for command, expected in [(['deal', 'validate', str(CASE)], 0),
                              (['deal', 'import', str(CASE)], 0),
                              (['deal', 'show', 'DL-00001'], 0),
                              (['deal', 'calculate', 'DL-00001'], 0),
                              (['qa', 'deal', 'DL-00001'], 2),
                              (['qa', 'all'], 2), (['qa', 'report'], 2),
                              (['evidence', 'audit', 'DL-00001'], 0)]:
        assert main(args + command) == expected
        capsys.readouterr()
