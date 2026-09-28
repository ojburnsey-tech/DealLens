"""Reusable descriptive analytics; no UI, inferred prices, FX or causal claims.

Cohorts retain currency, financial definitions and premium reference basis. Each
observation carries the original calculation so sample statistics remain auditable.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Literal

from .models import Fact, Result, walk_facts
from .qa import qa_deal
from .research import ResearchDeal, analyse

D = Decimal
Dimension = Literal['sector', 'subsector', 'country', 'buyer_type', 'cross_border',
                    'consideration_type', 'status', 'announcement_year']


@dataclass(frozen=True)
class Observation:
    deal_id: str
    value: Decimal
    metric: str
    unit: str
    basis: str
    currency: str | None
    evidence: Fact | Result


@dataclass(frozen=True)
class Distribution:
    n: int
    minimum: Decimal | None
    q25: Decimal | None
    median: Decimal | None
    mean: Decimal | None
    q75: Decimal | None
    maximum: Decimal | None


def distribution(values: Iterable[Decimal]) -> Distribution:
    """Linear-interpolated quartiles at rank (n-1)*p; no rounding or zero fill."""
    data = list(values)
    if any(not x.is_finite() for x in data):
        raise ValueError('statistics require finite values')
    data.sort()
    n = len(data)
    if not n:
        return Distribution(0, None, None, None, None, None, None)
    def quantile(p: Decimal) -> Decimal:
        position = D(n - 1) * p
        lower = int(position)
        upper = min(lower + 1, n - 1)
        return data[lower] + (data[upper] - data[lower]) * (position - lower)
    return Distribution(n, data[0], quantile(D('.25')), quantile(D('.5')),
                        sum(data, D(0)) / n, quantile(D('.75')), data[-1])


def accepted_deals(records: Iterable[ResearchDeal]) -> tuple[list[ResearchDeal], list[dict[str, Any]]]:
    """Only VERIFIED, publishable inputs; duplicates are errors, not extra samples."""
    selected, excluded = [], []
    seen = set()
    for deal in records:
        if deal.identity.deal_id in seen:
            raise ValueError(f'duplicate deal ID: {deal.identity.deal_id}')
        seen.add(deal.identity.deal_id)
        if deal.review_status != 'VERIFIED':
            excluded.append({'deal_id': deal.identity.deal_id, 'reason': 'not VERIFIED'})
            continue
        report = qa_deal(deal)
        if not report['publishable']:
            excluded.append({'deal_id': deal.identity.deal_id, 'reason': 'QA blocks publication',
                             'flags': report['flags']})
            continue
        selected.append(deal)
    return sorted(selected, key=lambda d: d.identity.deal_id), excluded


def dimension_value(deal: ResearchDeal, dimension: Dimension) -> str:
    if dimension == 'country':
        return deal.target.country
    if dimension == 'status':
        return deal.identity.transaction_status
    if dimension == 'announcement_year':
        return str(deal.identity.announcement_date.year)
    if dimension == 'cross_border':
        # A domestic bid vehicle is not evidence of the ultimate buyer's domicile.
        country = deal.profile.ultimate_bidder_country
        return 'unknown' if country is None else 'domestic' if country == deal.target.country else 'cross_border'
    if dimension in ('sector', 'subsector', 'buyer_type', 'consideration_type'):
        return getattr(deal.profile, dimension) or 'unknown'
    raise ValueError('unsupported grouping dimension')


def observations(deal: ResearchDeal, metric: str) -> list[Observation]:
    """Read existing service results, preserving their exact basis and provenance."""
    calculations = analyse(deal)
    value: Fact | Result | None = None
    if metric == 'disclosed_ev':
        value = deal.transaction_valuation.reported_enterprise_value
    elif metric in ('ev_revenue', 'ev_ebitda', 'ev_ebit', 'equity_net_income'):
        value = calculations.get(metric)
    elif metric == 'premium':
        offer = next((o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id), None)
        result = []
        if offer:
            for ref in deal.unaffected_price:
                item = calculations.get('premiums', {}).get(ref.reference_id)
                if item and item.result is not None:
                    basis = f'{ref.reference_basis}; offer={offer.stage}; {offer.price.definition}'
                    result.append(Observation(deal.identity.deal_id, item.result, metric, 'fraction',
                                              basis, offer.price.currency, item))
        return result
    elif metric in ('cost_synergy_ev', 'cost_synergy_ebitda', 'synergy_adjusted_multiple'):
        value = calculations.get('synergies', {}).get(metric)
    elif metric in ('buyer_standalone_leverage', 'leverage_before_synergy', 'leverage_after_synergy'):
        value = calculations.get('leverage', {}).get(metric)
    else:
        raise ValueError('unsupported portfolio metric')
    if value is None:
        return []
    if isinstance(value, Fact):
        if value.amount is None:
            return []
        return [Observation(deal.identity.deal_id, value.amount, metric, value.unit,
                            value.definition, value.currency, value)]
    if value.result is None or value.qualifications:
        return []
    # A FY multiple is never pooled with LTM; adjusted definitions remain separate.
    period = value.period.basis if value.period else 'not applicable'
    definitions = '; '.join(f'{path}={fact.definition} [{fact.classification}]' for path, fact in walk_facts(value.inputs))
    basis = f'{period}; {value.basis}; {definitions}; illustrative={value.illustrative}'
    if metric in ('ev_revenue', 'ev_ebitda', 'ev_ebit', 'cost_synergy_ev', 'synergy_adjusted_multiple'):
        basis += f'; preferred_ev_basis={deal.transaction_valuation.preferred_ev_basis}'
    return [Observation(deal.identity.deal_id, value.result, metric, value.unit, basis, value.currency, value)]


def metric_summary(records: Iterable[ResearchDeal], metric: str, *, group_by: Dimension | None = None) -> dict:
    deals, excluded = accepted_deals(records)
    groups: dict[tuple, list[Observation]] = defaultdict(list)
    missing, seen = [], set()
    for deal in deals:
        items = observations(deal, metric)
        if not items:
            missing.append(deal.identity.deal_id)
        for item in items:
            category = dimension_value(deal, group_by) if group_by else 'all'
            key = category, item.unit, item.currency or '', item.basis
            unique = deal.identity.deal_id, key
            if unique in seen:
                raise ValueError('multiple observations for one deal and basis; explicitly select a reference')
            seen.add(unique)
            groups[key].append(item)
    cohorts = []
    for (category, unit, currency, basis), items in sorted(groups.items()):
        cohorts.append({'category': category, 'metric': metric, 'unit': unit, 'currency': currency or None,
                        'basis': basis, 'n': len(items), 'statistics': distribution(x.value for x in items),
                        'sum': sum((x.value for x in items), D(0)) if metric == 'disclosed_ev' else None,
                        'observations': items})
    return {'metric': metric, 'eligible_deals': len(deals), 'excluded_deals': excluded,
            'missing_or_nonmeaningful_deals': missing, 'cohorts': cohorts,
            'warning': 'Descriptive sample statistics; comparable selection remains human judgement.'}


def _share(matches: int, known: int, total: int, basis: str) -> dict:
    return {'value': None if known == 0 else D(matches) / known, 'unit': 'fraction',
            'n': known, 'numerator_n': matches, 'missing_n': total - known, 'basis': basis}


def portfolio_summary(records: Iterable[ResearchDeal]) -> dict:
    deals, excluded = accepted_deals(records)
    n = len(deals)
    consideration = [d.profile.consideration_type for d in deals if d.profile.consideration_type]
    border = [dimension_value(d, 'cross_border') for d in deals if d.profile.ultimate_bidder_country]
    completed = [d for d in deals if d.identity.transaction_status == 'COMPLETED']
    days = [D((d.identity.completion_date - d.identity.announcement_date).days)
            for d in completed if d.identity.completion_date is not None]
    result = {'deal_count': {'value': n, 'n': n, 'unit': 'deals', 'basis': 'VERIFIED and publishable'},
              'excluded_deals': excluded,
              'cash_consideration_share': _share(consideration.count('cash'), len(consideration), n,
                                                'Share of classified deals with all-cash consideration, not cash percentage of value'),
              'cross_border_share': _share(border.count('cross_border'), len(border), n,
                                          'Ultimate bidder country versus target country; bid vehicle not inferred'),
              'completion_rate': _share(len(completed), n, n, 'Completed / all tracked verified deals, including pending'),
              'completion_days': {'statistics': distribution(days), 'n': len(days), 'unit': 'calendar days',
                                  'basis': 'Announcement to completion; completed deals only',
                                  'missing_n': len(completed) - len(days)}}
    for metric in ('disclosed_ev', 'ev_ebitda', 'ev_revenue', 'premium'):
        result[metric] = metric_summary(deals, metric)
    return result


def category_counts(records: Iterable[ResearchDeal], dimension: Dimension) -> dict:
    deals, excluded = accepted_deals(records)
    groups: dict[str, list[str]] = defaultdict(list)
    for deal in deals:
        groups[dimension_value(deal, dimension)].append(deal.identity.deal_id)
    return {'dimension': dimension, 'n': len(deals), 'excluded_deals': excluded,
            'categories': [{'category': key, 'n': len(ids), 'deal_ids': ids} for key, ids in sorted(groups.items())]}


def data_quality_summary(records: Iterable[ResearchDeal]) -> dict:
    """Describe research inventory without promoting drafts into financial samples."""
    records = list(records)
    accepted, excluded = accepted_deals(records)
    statuses: dict[str, int] = defaultdict(int)
    for record in records:
        statuses[record.review_status] += 1
    availability = {}
    for metric in ('ev_revenue', 'ev_ebitda', 'premium', 'cost_synergy_ev', 'leverage_before_synergy'):
        available = sum(bool(observations(deal, metric)) for deal in accepted)
        availability[metric] = {'n': available, 'eligible_n': len(accepted), 'missing_n': len(accepted) - available}
    return {'inventory_n': len(records), 'eligible_n': len(accepted), 'review_status_counts': dict(statuses),
            'excluded_deals': excluded, 'availability': availability,
            'basis': 'Availability within VERIFIED and QA-publishable records only; inventory also counts drafts.'}
