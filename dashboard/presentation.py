"""Formatting and explicit-basis filters for the public dashboard."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from deallens.analytics import Observation, dimension_value, observations
from deallens.research import ResearchDeal

D = Decimal


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else D(str(value))


def _trimmed(value: Decimal, places: int = 1) -> str:
    rendered = f"{value:,.{places}f}"
    return rendered.rstrip("0").rstrip(".")


def compact_number(
    value: Decimal | int | float | str | None,
    *,
    currency: str | None = None,
) -> str:
    """Format a base-unit amount without implying currency conversion."""

    if value is None:
        return "Unavailable"
    amount = _decimal(value)
    magnitude = abs(amount)
    scale, suffix = D(1), ""
    for threshold, label in ((D("1e12"), "tn"), (D("1e9"), "bn"), (D("1e6"), "m"), (D("1e3"), "k")):
        if magnitude >= threshold:
            scale, suffix = threshold, label
            break
    rendered = _trimmed(amount / scale, 1) + suffix
    return f"{currency} {rendered}" if currency else rendered


def percent(value: Decimal | int | float | str | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{_trimmed(_decimal(value) * 100, 1)}%"


def multiple(value: Decimal | int | float | str | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{_trimmed(_decimal(value), 1)}x"


def observation_for(
    deal: ResearchDeal,
    metric: str,
    *,
    basis: str | None = None,
    currency: str | None = None,
) -> Observation | None:
    """Return one observation only after any requested basis is matched."""

    matches = [
        item
        for item in observations(deal, metric)
        if (basis is None or item.basis == basis) and (currency is None or item.currency == currency)
    ]
    return matches[0] if matches else None


def _in_range(
    item: Observation | None,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    if minimum is None and maximum is None:
        return True
    if item is None:
        return False
    return not ((minimum is not None and item.value < minimum) or (maximum is not None and item.value > maximum))


def matching_deals(
    deals: Iterable[ResearchDeal],
    *,
    sector: str | None = None,
    country: str | None = None,
    year: int | None = None,
    buyer_type: str | None = None,
    status: str | None = None,
    consideration: str | None = None,
    border: str | None = None,
    ev_currency: str | None = None,
    minimum_ev: Decimal | None = None,
    maximum_ev: Decimal | None = None,
    minimum_multiple: Decimal | None = None,
    maximum_multiple: Decimal | None = None,
    multiple_basis: str | None = None,
    minimum_premium: Decimal | None = None,
    maximum_premium: Decimal | None = None,
    premium_basis: str | None = None,
) -> tuple[ResearchDeal, ...]:
    """Filter deals without pooling currencies or analytical bases."""

    selected: list[ResearchDeal] = []
    for deal in deals:
        if sector is not None and deal.profile.sector != sector:
            continue
        if country is not None and deal.target.country != country:
            continue
        if year is not None and deal.identity.announcement_date.year != year:
            continue
        if buyer_type is not None and deal.profile.buyer_type != buyer_type:
            continue
        if status is not None and deal.identity.transaction_status != status:
            continue
        if consideration is not None and deal.profile.consideration_type != consideration:
            continue
        if border is not None and dimension_value(deal, "cross_border") != border:
            continue

        ev = observation_for(deal, "disclosed_ev", currency=ev_currency)
        if ev_currency is not None and ev is None:
            continue
        if not _in_range(ev, minimum_ev, maximum_ev):
            continue

        valuation = observation_for(deal, "ev_ebitda", basis=multiple_basis)
        if multiple_basis is not None and valuation is None:
            continue
        if not _in_range(valuation, minimum_multiple, maximum_multiple):
            continue

        premium = observation_for(deal, "premium", basis=premium_basis)
        if premium_basis is not None and premium is None:
            continue
        if not _in_range(premium, minimum_premium, maximum_premium):
            continue
        selected.append(deal)

    return tuple(sorted(selected, key=lambda deal: deal.identity.deal_id))
