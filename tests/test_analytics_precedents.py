"""Synthetic review attestations only; real research stays DRAFT."""
from datetime import date
from decimal import Decimal as D

import pytest

from conftest import fact
from deallens.analytics import category_counts, distribution, metric_summary, portfolio_summary
from deallens.finance import EVAdjustment
from deallens.models import Evidence, Period, Source
from deallens.precedents import Screen, implied_valuation, screen, selected_statistics
from deallens.qa import qa_deal
from deallens.research import (
    Financials, FinancialSeries, Offer, ReferencePrice, ResearchDeal, ResearchProfile, Review, Valuation,
)


@pytest.fixture
def verified(draft, fy):
    return ResearchDeal.model_validate(draft.model_dump() | {
        'review_status': 'VERIFIED',
        'review_notes': Review(reviewer='Synthetic test reviewer', reviewed_at=date(2024, 8, 1),
                               verification_notes='Synthetic fixture, not a real attestation'),
        'profile': ResearchProfile(sector='Consumer', subsector='Beverages', target_type='public',
                                   buyer_type='strategic', consideration_type='cash',
                                   ultimate_bidder_country='DK', transaction_type='scheme', evidence=['E1'],
                                   field_evidence={k: ['E1'] for k in ('sector', 'subsector', 'target_type',
                                       'buyer_type', 'consideration_type', 'ultimate_bidder_country', 'transaction_type')}),
        'sources': [Source(source_id='S1', title='Synthetic source', url='https://example.com/source',
                           publication_date=date(2024, 7, 1), source_type='ANNOUNCEMENT')],
        'field_evidence': [Evidence(evidence_id='E1', source_id='S1', section='Synthetic terms',
                                    reported_unit='GBP', note='Test data only')],
        'offer_terms': [Offer(offer_id='initial', stage='initial', date=date(2024, 7, 1),
                             price=fact(12, 'currency/share', evidence=('E1',)), basis='cash')],
        'selected_offer_id': 'initial',
        'transaction_valuation': Valuation(reported_enterprise_value=fact(1000, definition='Reported EV', evidence=('E1',))),
        'target_financials': Financials(ebitda=FinancialSeries(selected=fact(100, definition='Adjusted EBITDA', period=fy, evidence=('E1',))),
                                       revenue=FinancialSeries(selected=fact(500, definition='Revenue', period=fy, evidence=('E1',)))),
        'unaffected_price': [ReferencePrice(reference_id='close', price=fact(10, 'currency/share', evidence=('E1',)),
                                            reference_date=date(2024, 6, 30), reference_basis='unaffected_close',
                                            selection_notes='Explicit synthetic selection')],
    })


def changed(deal, index=2, **updates):
    return ResearchDeal.model_validate(deal.model_dump() | {'identity': deal.identity.model_dump() | {
        'deal_id': f'DL-{index:05d}'}} | updates)


def test_empty_and_unverified_never_become_dataset(draft):
    result = portfolio_summary([draft])
    assert result['deal_count']['value'] == 0
    assert result['cash_consideration_share']['value'] is None
    assert result['completion_days']['statistics'].median is None
    assert result['disclosed_ev']['cohorts'] == []
    assert len(result['excluded_deals']) == 1


def test_quartiles_independently_calculated():
    result = distribution(map(D, ['10', '20', '40', '50']))
    assert (result.minimum, result.q25, result.median, result.mean, result.q75, result.maximum) == (
        D(10), D('17.5'), D(30), D(30), D('42.5'), D(50))
    assert distribution([]).n == 0
    assert distribution([D(7)]).q75 == 7
    with pytest.raises(ValueError):
        distribution([D('NaN')])


def test_duplicates_rejected(verified):
    with pytest.raises(ValueError, match='duplicate'):
        portfolio_summary([verified, verified])


def test_qa_gates_missing_numerical_and_profile_provenance(verified):
    bad = changed(verified, transaction_valuation=Valuation(reported_enterprise_value=fact(1000)))
    assert portfolio_summary([bad])['deal_count']['n'] == 0
    bad_profile = changed(verified, profile=ResearchProfile(sector='Consumer'))
    assert any(f.code == 'PROFILE_EVIDENCE_REQUIRED' for f in qa_deal(bad_profile)['flags'])
    assert portfolio_summary([bad_profile])['deal_count']['n'] == 0


def test_no_currency_or_definition_pooling(verified):
    eur = changed(verified, transaction_valuation=Valuation(reported_enterprise_value=fact(1000, currency='EUR', definition='Reported EV', evidence=('E1',))),
                  target_financials=Financials())
    cohorts = metric_summary([verified, eur], 'disclosed_ev')['cohorts']
    assert {(c['currency'], c['n'], c['sum']) for c in cohorts} == {('GBP', 1, D(1000)), ('EUR', 1, D(1000))}


def test_no_fy_ltm_mixing(verified):
    ltm = Period(start='2023-07-01', end='2024-06-30', basis='LTM')
    other = changed(verified, target_financials=Financials(ebitda=FinancialSeries(
        selected=fact(50, definition='Adjusted EBITDA', period=ltm, evidence=('E1',)))))
    result = metric_summary([verified, other], 'ev_ebitda')
    assert len(result['cohorts']) == 2
    assert sorted(c['statistics'].median for c in result['cohorts']) == [D(10), D(20)]
    assert all(c['n'] == 1 for c in result['cohorts'])


def test_no_adjusted_statutory_mixing(verified, fy):
    other = changed(verified, target_financials=Financials(ebitda=FinancialSeries(
        selected=fact(50, definition='Statutory EBITDA', period=fy, evidence=('E1',)))))
    assert len(metric_summary([verified, other], 'ev_ebitda')['cohorts']) == 2


@pytest.mark.parametrize('value', [None, 0, -1])
def test_nonmeaningful_multiple_excluded_with_missing_count(verified, fy, value):
    other = changed(verified, target_financials=Financials(ebitda=FinancialSeries(
        selected=fact(value, definition='Adjusted EBITDA', period=fy, evidence=('E1',)))))
    result = metric_summary([verified, other], 'ev_ebitda')
    assert result['cohorts'][0]['n'] == 1
    assert result['missing_or_nonmeaningful_deals'] == ['DL-00002']


def test_premium_bases_kept_separate_and_duplicate_basis_rejected(verified):
    vwap = verified.unaffected_price[0].model_copy(update={'reference_id': 'vwap', 'reference_basis': '3M_VWAP'})
    other = changed(verified, unaffected_price=[vwap])
    cohorts = metric_summary([verified, other], 'premium')['cohorts']
    assert len(cohorts) == 2
    assert all(c['statistics'].median == D('.2') and c['n'] == 1 for c in cohorts)
    duplicate = changed(verified, unaffected_price=[verified.unaffected_price[0],
        verified.unaffected_price[0].model_copy(update={'reference_id': 'another_close'})])
    with pytest.raises(ValueError, match='explicitly select'):
        metric_summary([duplicate], 'premium')


def test_known_denominators_for_classification_shares(verified):
    unknown = changed(verified, profile=ResearchProfile())
    result = portfolio_summary([verified, unknown])
    assert result['deal_count']['n'] == 2
    for key in ('cash_consideration_share', 'cross_border_share'):
        assert result[key]['value'] == 1
        assert result[key]['n'] == 1
        assert result[key]['missing_n'] == 1
    assert result['completion_rate']['value'] == 0
    assert result['completion_rate']['n'] == 2


def test_completion_rate_and_days(verified):
    completed = changed(verified, identity=verified.identity.model_dump() | {
        'deal_id': 'DL-00002', 'completion_date': '2024-07-31', 'transaction_status': 'COMPLETED'})
    result = portfolio_summary([verified, completed])
    assert result['completion_rate']['value'] == D('.5')
    assert result['completion_days']['statistics'].median == 30
    assert result['completion_days']['n'] == 1


@pytest.mark.parametrize('dimension', ['sector', 'subsector', 'country', 'buyer_type', 'cross_border',
                                       'consideration_type', 'status', 'announcement_year'])
def test_grouped_counts_and_metrics(verified, dimension):
    assert category_counts([verified], dimension)['categories'][0]['n'] == 1
    assert metric_summary([verified], 'ev_revenue', group_by=dimension)['cohorts'][0]['n'] == 1


@pytest.mark.parametrize('filters,expected', [
    (Screen(sector='Consumer'), 1), (Screen(subsector='Other'), 0), (Screen(geography='GB'), 1),
    (Screen(announcement_year=2023), 0), (Screen(target_type='private'), 0),
    (Screen(buyer_type='strategic'), 1), (Screen(cross_border=True), 1),
    (Screen(consideration_type='mixed'), 0), (Screen(status='COMPLETED'), 0),
    (Screen(financial_basis='FY'), 1), (Screen(financial_basis='LTM'), 0),
    (Screen(minimum_ev=D(1000), maximum_ev=D(1000), currency='GBP'), 1),
    (Screen(minimum_ev=D(1001), currency='GBP'), 0), (Screen(currency='EUR'), 0),
])
def test_screen_filters(verified, filters, expected):
    assert screen([verified], filters)['n'] == expected


def test_unknown_cross_border_not_assumed_domestic(verified):
    unknown = changed(verified, profile=ResearchProfile())
    assert screen([unknown], Screen(cross_border=False))['n'] == 0
    with pytest.raises(ValueError, match='currency'):
        Screen(minimum_ev=D(10))
    with pytest.raises(ValueError):
        Screen(minimum_ev=D(20), maximum_ev=D(10), currency='GBP')


def test_selection_is_explicit_and_retained(verified, draft):
    result = selected_statistics([verified], ['DL-00001'], selection_notes='Human-selected synthetic comparison')
    assert result['n'] == 1
    assert result['statistics']['ev_ebitda']['cohorts'][0]['statistics'].median == 10
    for records, ids, notes in [([verified], [], 'notes'), ([verified], ['DL-00001'], ''), ([draft], ['DL-00001'], 'notes')]:
        with pytest.raises(ValueError):
            selected_statistics(records, ids, selection_notes=notes)


def test_subject_ev_to_equity_bridge_net_cash_and_provenance(fy):
    multiple = fact(10, 'ratio', evidence=('SELECTED',))
    earnings = fact(20, definition='EBITDA', period=fy, evidence=('FINANCIALS',))
    adjustments = [EVAdjustment(adjustment_id='nd', kind='net_debt', sign=1,
                                amount=fact(-30, as_of=date(2023, 12, 31), evidence=('DEBT',)), basis='Net cash'),
                   EVAdjustment(adjustment_id='pref', kind='preferred_stock', sign=1,
                                amount=fact(5, as_of=date(2023, 12, 31), evidence=('PREF',)), basis='Preferred equity'),
                   EVAdjustment(adjustment_id='inv', kind='non_operating_investments', sign=-1,
                                amount=fact(7, as_of=date(2023, 12, 31), evidence=('INV',)), basis='Investment')]
    result = implied_valuation(multiple, earnings, adjustments, metric='ebitda', selection_notes='Analyst selection', selected_deal_ids=['DL-00001'])
    assert result['implied_enterprise_value'].result == 200
    assert result['implied_equity_value'].result == 200 - (-30) - 5 + 7
    assert [x['equity_effect'] for x in result['bridge']] == [D(30), D(-5), D(7)]
    assert result['implied_equity_value'].inputs['implied_ev'].inputs['subject_financial'].evidence == ('FINANCIALS',)
    assert result['implied_equity_value'].illustrative


@pytest.mark.parametrize('value', [None, 0, -10])
def test_subject_missing_nonpositive_financial_does_not_imply_ev(fy, value):
    result = implied_valuation(fact(10, 'ratio'), fact(value, period=fy), [], metric='revenue',
                               selection_notes='Explicit selected case', selected_deal_ids=['DL-00001'])
    assert result['implied_enterprise_value'].result is None
    assert result['implied_equity_value'].result is None


def test_subject_fx_and_period_mismatch_rejected(fy):
    bad = EVAdjustment(adjustment_id='nd', kind='net_debt', sign=1,
                       amount=fact(30, currency='EUR', as_of=date(2023, 12, 31)), basis='Foreign debt')
    with pytest.raises(ValueError, match='currency'):
        implied_valuation(fact(10, 'ratio'), fact(20, period=fy), [bad], metric='ebitda',
                          selection_notes='Explicit', selected_deal_ids=['DL-00001'])
    with pytest.raises(ValueError):
        implied_valuation(fact(10, 'ratio'), fact(20), [], metric='ebitda',
                          selection_notes='Explicit', selected_deal_ids=['DL-00001'])


def test_different_ev_definitions_never_pool(verified):
    other = changed(verified, transaction_valuation=Valuation(
        reported_enterprise_value=fact(1200, definition='EV excluding leases', evidence=('E1',))))
    result = metric_summary([verified, other], 'ev_ebitda')
    assert len(result['cohorts']) == 2
    assert sorted(c['statistics'].median for c in result['cohorts']) == [D(10), D(12)]


def test_subject_derived_qualifications_and_warnings_propagate(fy):
    from deallens.finance import derived_fact
    from deallens.models import Result
    input_fact = fact(20, period=fy, evidence=('FIN',))
    financial = derived_fact(Result(result=D(20), unit='currency', currency='GBP',
        formula='explicit qualified restatement', basis='EBITDA', period=fy,
        inputs={'reported': input_fact}, warnings=('Definition estimate',), qualifications=('Unresolved restatement',)))
    result = implied_valuation(fact(10, 'ratio'), financial, [], metric='ebitda',
                               selection_notes='Explicit selection', selected_deal_ids=['DL-00001'])
    for name in ('implied_enterprise_value', 'implied_equity_value'):
        assert 'Unresolved restatement' in result[name].qualifications
        assert 'Definition estimate' in result[name].warnings


@pytest.mark.parametrize('metric', ['cost_synergy_ebitda', 'synergy_adjusted_multiple',
                                  'leverage_before_synergy', 'leverage_after_synergy'])
def test_earnings_definitions_separate_derived_cohorts(verified, fy, monkeypatch, metric):
    from deallens.models import Result
    from deallens.analytics import observations
    module = 'synergies' if metric.startswith(('cost_', 'synergy_')) else 'leverage'
    bases = []
    for definition in ('Adjusted EBITDA', 'Unadjusted EBITDA'):
        result = Result(result=D(2), unit='ratio', formula='service ratio', basis='Common annual basis',
                        period=fy, inputs={'ebitda': fact(100, period=fy, definition=definition)})
        monkeypatch.setattr('deallens.analytics.analyse', lambda deal, r=result: {module: {metric: r}})
        bases.append(observations(verified, metric)[0].basis)
    assert bases[0] != bases[1]


def test_derived_multiple_flags_survive_serialization(fy):
    from deallens.finance import derived_fact
    from deallens.models import Result
    multiple = derived_fact(Result(result=D(10), unit='ratio', formula='Selected cohort median',
        basis='Selected comparable subset', inputs={'input': fact(10, 'ratio', evidence=('MULT',))},
        warnings=('Small cohort',), qualifications=('Comparability unresolved',)))
    outputs = implied_valuation(multiple, fact(20, period=fy), [], metric='ebitda',
                                selection_notes='Explicit', selected_deal_ids=['DL-00001'])
    for key in ('implied_enterprise_value', 'implied_equity_value'):
        restored = Result.model_validate_json(outputs[key].model_dump_json())
        assert 'Comparability unresolved' in restored.qualifications
        assert 'Small cohort' in restored.warnings


def test_profile_evidence_is_field_specific(verified):
    profile = verified.profile.model_copy(update={'field_evidence': {'sector': ['E1']}})
    flags = qa_deal(changed(verified, profile=profile))['flags']
    assert any(f.code == 'PROFILE_EVIDENCE_REQUIRED' and f.field == 'profile.ultimate_bidder_country' for f in flags)
    assert not any(f.field == 'profile.sector' for f in flags)


@pytest.mark.parametrize('kwargs', [{'financial_metric': 'net_debt'}, {'financial_basis': 'YTD'},
    {'buyer_type': 'other'}, {'currency': 'gbp'}, {'cross_border': 'false'}, {'announcement_year': True}])
def test_screen_invalid_request_rejects(kwargs):
    with pytest.raises(ValueError):
        Screen(**kwargs)


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-Infinity'])
def test_distribution_mixed_nonfinite(bad):
    with pytest.raises(ValueError, match='finite'):
        distribution([D(1), D(bad)])


def test_equity_numerator_definition_cohorts(verified, fy):
    deals = [changed(verified, index=i, transaction_valuation=Valuation(
        reported_equity_value=fact(1000, definition=definition, evidence=('E1',))),
        target_financials=Financials(net_income=FinancialSeries(selected=fact(100, period=fy, evidence=('E1',)))))
        for i, definition in enumerate(('Ordinary equity', 'Fully diluted equity'), 2)]
    assert len(metric_summary(deals, 'equity_net_income')['cohorts']) == 2


def test_reported_and_calculated_ev_bases_exposed(verified):
    other = changed(verified, transaction_valuation=Valuation(
        equity_for_ev=fact(1000, definition='Explicit equity bridge', evidence=('E1',)),
        ev_bridge_basis='All adjustments explicitly absent', preferred_ev_basis='calculated'))
    cohorts = metric_summary([verified, other], 'ev_ebitda')['cohorts']
    assert len(cohorts) == 2
    assert any('REPORTED' in c['basis'] for c in cohorts)
    assert any('CALCULATED' in c['basis'] for c in cohorts)
