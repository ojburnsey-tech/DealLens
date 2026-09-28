"""Human-controlled precedent screening and transparent subject valuation."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from . import finance as f
from .analytics import accepted_deals, dimension_value, metric_summary, observations
from .models import Fact
from .research import ResearchDeal


@dataclass(frozen=True)
class Screen:
    sector: str | None = None
    subsector: str | None = None
    geography: str | None = None
    announcement_year: int | None = None
    minimum_ev: Decimal | None = None
    maximum_ev: Decimal | None = None
    currency: str | None = None
    target_type: Literal['public', 'private'] | None = None
    buyer_type: Literal['strategic', 'sponsor'] | None = None
    cross_border: bool | None = None
    consideration_type: Literal['cash', 'shares', 'mixed', 'other'] | None = None
    status: str | None = None
    financial_basis: Literal['FY', 'LTM'] | None = None
    financial_metric: Literal['revenue', 'ebitda'] = 'ebitda'

    def __post_init__(self):
        choices = {'target_type': ('public', 'private'), 'buyer_type': ('strategic', 'sponsor'),
                   'consideration_type': ('cash', 'shares', 'mixed', 'other'),
                   'financial_basis': ('FY', 'LTM'), 'financial_metric': ('revenue', 'ebitda')}
        for name, allowed in choices.items():
            value = getattr(self, name)
            if value is not None and value not in allowed:
                raise ValueError(f'invalid {name}')
        if self.cross_border is not None and type(self.cross_border) is not bool:
            raise ValueError('cross_border must be boolean')
        if self.announcement_year is not None and (type(self.announcement_year) is not int or not 1 <= self.announcement_year <= 9999):
            raise ValueError('invalid announcement year')
        if self.currency is not None and (len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or not self.currency.isupper()):
            raise ValueError('currency must be a three-letter uppercase code')
        if self.minimum_ev is not None or self.maximum_ev is not None:
            if not self.currency:
                raise ValueError('transaction-size filters require an explicit currency; no FX is inferred')
        for value in (self.minimum_ev, self.maximum_ev):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError('EV bounds must be finite and nonnegative')
        if self.minimum_ev is not None and self.maximum_ev is not None and self.minimum_ev > self.maximum_ev:
            raise ValueError('minimum EV exceeds maximum EV')


def screen(records: list[ResearchDeal], filters: Screen) -> dict:
    deals, excluded = accepted_deals(records)
    matches = []
    for deal in deals:
        exact = [(filters.sector, deal.profile.sector), (filters.subsector, deal.profile.subsector),
                 (filters.geography, deal.target.country), (filters.announcement_year, deal.identity.announcement_date.year),
                 (filters.target_type, deal.profile.target_type), (filters.buyer_type, deal.profile.buyer_type),
                 (filters.consideration_type, deal.profile.consideration_type),
                 (filters.status, deal.identity.transaction_status)]
        if any(wanted is not None and wanted != actual for wanted, actual in exact):
            continue
        if filters.cross_border is not None:
            expected = 'cross_border' if filters.cross_border else 'domestic'
            if dimension_value(deal, 'cross_border') != expected:
                continue
        if filters.financial_basis:
            financial = getattr(deal.target_financials, filters.financial_metric).selected
            if financial is None or financial.value is None or financial.period is None or financial.period.basis != filters.financial_basis:
                continue
        # Size always means disclosed reported EV, never a synonym for transaction value.
        if filters.currency or filters.minimum_ev is not None or filters.maximum_ev is not None:
            ev = observations(deal, 'disclosed_ev')
            if not ev or ev[0].currency != filters.currency:
                continue
            if filters.minimum_ev is not None and ev[0].value < filters.minimum_ev:
                continue
            if filters.maximum_ev is not None and ev[0].value > filters.maximum_ev:
                continue
        matches.append(deal)
    return {'n': len(matches), 'candidates': matches, 'excluded_deals': excluded,
            'size_basis': 'Reported enterprise value, base currency units; no currency conversion',
            'warning': 'Screen results are candidates only; the analyst must decide comparability.'}


def selected_statistics(records: list[ResearchDeal], selected_ids: list[str], *, selection_notes: str) -> dict:
    if not selected_ids or len(selected_ids) != len(set(selected_ids)) or not selection_notes.strip():
        raise ValueError('provide unique manually selected deal IDs and selection notes')
    eligible, _ = accepted_deals(records)
    lookup = {d.identity.deal_id: d for d in eligible}
    if set(selected_ids) - lookup.keys():
        raise ValueError('selected precedent is absent, unverified or blocked by QA')
    selected = [lookup[i] for i in selected_ids]
    return {'selected_ids': list(selected_ids), 'selection_notes': selection_notes, 'n': len(selected),
            'statistics': {metric: metric_summary(selected, metric) for metric in ('ev_revenue', 'ev_ebitda', 'premium')}}


def implied_valuation(selected_multiple: Fact, financial: Fact, adjustments: list[f.EVAdjustment], *,
                      metric: Literal['revenue', 'ebitda'], selection_notes: str,
                      selected_deal_ids: list[str], snapshot_alignment_basis: str | None = None) -> dict:
    """Analyst-selected multiple × subject annual metric, then invert EV bridge.

    The function does not derive a selected multiple from screening statistics.
    The analyst supplies it and explains their selected precedent set explicitly.
    """
    if metric not in ('revenue', 'ebitda') or not selection_notes.strip() or not selected_deal_ids:
        raise ValueError('metric, analyst selection notes and selected deal IDs are required')
    if len(selected_deal_ids) != len(set(selected_deal_ids)):
        raise ValueError('duplicate selected precedent ID')
    multiple = f._value(selected_multiple, 'ratio', nonnegative=True)
    amount = f._value(financial, 'currency')
    f._annual(financial)
    if financial.period is None or financial.period.basis not in ('FY', 'LTM'):
        raise ValueError('subject financial requires an annual FY/LTM basis')
    if multiple == 0:
        raise ValueError('selected precedent multiple must be positive')
    warnings = []
    ev_value = None
    if multiple is None or amount is None:
        warnings.append('Missing selected multiple or subject financial; implied valuation unavailable.')
    elif amount <= 0:
        warnings.append('Analytically non-meaningful: subject financial metric is zero or negative.')
    else:
        ev_value = multiple * amount
    inputs = {'selected_multiple': selected_multiple, 'subject_financial': financial,
              'selected_deal_ids': selected_deal_ids, 'selection_notes': selection_notes}
    ev = f._result(ev_value, 'currency',
                formula=f'Selected EV/{metric} multiple × Subject {metric}',
                basis=f'Illustrative subject valuation; {financial.period.basis}; {financial.definition}',
                inputs=inputs, warnings=tuple(warnings), period=financial.period, illustrative=True)
    zero = Fact(value=Decimal(0), unit='currency', currency=financial.currency,
                definition='Algebraic zero to isolate explicit EV adjustments', classification='ASSUMPTION')
    # Reuse the EV service's signs, units, duplicate checks and snapshot safeguards.
    bridge = f.enterprise_value(zero, adjustments, bridge_basis=selection_notes,
                                preferred_ev_basis='calculated', snapshot_alignment_basis=snapshot_alignment_basis)
    adjustment_result = bridge['calculated_enterprise_value']
    total = adjustment_result.result
    equity = f._result(None if ev_value is None or total is None else ev_value - total,
                    'currency',
                    formula='Implied EV - Net debt - Preferred stock - Minority interest + Non-operating investments - Other signed EV adjustments',
                    basis='Illustrative explicit EV-to-equity bridge',
                    inputs={'implied_ev': ev, 'adjustment_calculation': adjustment_result},
                    warnings=tuple(warnings) + adjustment_result.warnings,
                    qualifications=ev.qualifications + adjustment_result.qualifications, illustrative=True)
    return {'implied_enterprise_value': ev, 'implied_equity_value': equity,
            'bridge': [{'adjustment': x['adjustment'],
                        'equity_effect': None if x['signed_amount'] is None else -x['signed_amount']}
                       for x in bridge['bridge']]}
