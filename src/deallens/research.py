"""Strict YAML research documents, explicit calculation requests and safe ingestion."""
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from . import finance as f
from .models import Evidence, Fact, Model, Source, Text, walk_facts


class Company(Model):
    name: Text
    country: Text
    company_number: str | None = None


class Identity(Model):
    deal_id: str = Field(pattern=r"^DL-\d{5}$")
    name: Text
    announcement_date: date
    completion_date: date | None = None
    transaction_status: Literal["ANNOUNCED", "COMPLETED", "LAPSED", "WITHDRAWN", "PENDING"] = "ANNOUNCED"


class Offer(Model):
    offer_id: Text
    stage: Literal["initial", "revised", "final"]
    date: date
    price: Fact
    basis: Text


class ReferencePrice(Model):
    reference_id: Text
    price: Fact
    reference_date: date
    reference_basis: Literal["unaffected_close", "1M_VWAP", "3M_VWAP"]
    selection_notes: Text


class Valuation(Model):
    reported_equity_value: Fact | None = None
    reported_enterprise_value: Fact | None = None
    reported_transaction_value: Fact | None = None
    share_components: list[f.ShareComponent] = Field(default_factory=list)
    share_basis: str | None = None
    equity_for_ev: Fact | None = None
    ev_adjustments: list[f.EVAdjustment] = Field(default_factory=list)
    ev_bridge_basis: str | None = None
    preferred_ev_basis: Literal["reported", "calculated"] = "reported"
    snapshot_alignment_basis: str | None = None


class FinancialSeries(Model):
    latest_fy: Fact | None = None
    current_ytd: Fact | None = None
    prior_ytd: Fact | None = None
    selected: Fact | None = None


class Financials(Model):
    revenue: FinancialSeries = Field(default_factory=FinancialSeries)
    ebitda: FinancialSeries = Field(default_factory=FinancialSeries)
    ebit: FinancialSeries = Field(default_factory=FinancialSeries)
    net_income: FinancialSeries = Field(default_factory=FinancialSeries)
    cash: Fact | None = None
    debt: Fact | None = None
    net_debt: Fact | None = None
    diluted_shares: Fact | None = None


class ConsiderationInput(Model):
    cash: Fact
    exchange_ratio: Fact
    bidder_price: Fact | None = None
    bidder_reference_date: date | None = None
    other: Fact
    structure: Literal["fixed", "floating", "collared"]
    reference_basis: Text


class LeverageInput(Model):
    snapshot_alignment_basis: str | None = None
    buyer_net_debt: Fact
    target_net_debt: Fact
    cash_consideration: Fact
    fees: Fact
    new_equity_proceeds: Fact
    disposal_proceeds: Fact
    buyer_ebitda: Fact
    target_ebitda: Fact
    eligible_cost_synergy: Fact
    adjustments: list[f.Adjustment]
    basis: Text


class AccretionInput(Model):
    buyer_net_income: Fact
    buyer_diluted_shares: Fact
    target_net_income: Fact
    eligible_pretax_synergies: Fact
    tax_rate: Fact
    new_debt: Fact
    incremental_interest_rate: Fact
    new_shares_issued: Fact
    recurring_adjustments: list[f.Adjustment]
    basis: Text


class Financing(Model):
    description: str | None = None
    committed_facility: Fact | None = None
    new_debt: Fact | None = None
    cash_consideration: Fact | None = None
    fees: Fact | None = None
    new_equity_proceeds: Fact | None = None
    disposal_proceeds: Fact | None = None
    evidence: list[str] = Field(default_factory=list)


class Review(Model):
    notes: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_at: date | None = None
    verification_notes: str | None = None


class ResearchProfile(Model):
    """Explicit analyst classifications; unknown is never inferred as domestic/cash."""
    sector: Text | None = None
    subsector: Text | None = None
    target_type: Literal["public", "private"] | None = None
    buyer_type: Literal["strategic", "sponsor"] | None = None
    consideration_type: Literal["cash", "shares", "mixed", "other"] | None = None
    transaction_type: Text | None = None
    ultimate_bidder_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    evidence: list[str] = Field(default_factory=list)
    field_evidence: dict[str, list[str]] = Field(default_factory=dict)
    notes: str | None = None


class ResearchDeal(Model):
    schema_version: Literal[1] = 1
    identity: Identity
    bidder: Company
    target: Company
    review_status: Literal["DRAFT", "REVIEWED", "VERIFIED"] = "DRAFT"
    profile: ResearchProfile = Field(default_factory=ResearchProfile)
    offer_terms: list[Offer] = Field(default_factory=list)
    selected_offer_id: str | None = None
    transaction_valuation: Valuation = Field(default_factory=Valuation)
    unaffected_price: list[ReferencePrice] = Field(default_factory=list)
    target_financials: Financials = Field(default_factory=Financials)
    buyer_financials: Financials = Field(default_factory=Financials)
    synergies: list[f.Synergy] = Field(default_factory=list)
    financing: Financing = Field(default_factory=Financing)
    consideration: ConsiderationInput | None = None
    leverage_inputs: LeverageInput | None = None
    accretion_inputs: AccretionInput | None = None
    strategic_rationale: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    field_evidence: list[Evidence] = Field(default_factory=list)
    review_notes: Review = Field(default_factory=Review)

    @model_validator(mode="after")
    def integrity(self):
        collections = [(self.sources, "source_id"), (self.field_evidence, "evidence_id"),
                       (self.offer_terms, "offer_id"), (self.unaffected_price, "reference_id")]
        for items, key in collections:
            ids = [getattr(x, key) for x in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {key}")
        source_ids = {s.source_id for s in self.sources}
        evidence_ids = {e.evidence_id for e in self.field_evidence}
        if any(e.source_id not in source_ids for e in self.field_evidence):
            raise ValueError("evidence references an unknown source")
        for path, fact in walk_facts(self):
            if set(fact.evidence) - evidence_ids:
                raise ValueError(f"{path}: unknown field evidence")
        profile_fields = set(type(self.profile).model_fields) - {'evidence', 'field_evidence', 'notes'}
        if set(self.profile.field_evidence) - profile_fields:
            raise ValueError("unknown profile classification field")
        if any(set(refs) - evidence_ids for refs in self.profile.field_evidence.values()):
            raise ValueError("unknown profile field evidence")
        if set(self.profile.evidence) - evidence_ids:
            raise ValueError("unknown profile evidence")
        if set(self.financing.evidence) - evidence_ids:
            raise ValueError("unknown financing evidence")
        if self.selected_offer_id is not None and self.selected_offer_id not in {o.offer_id for o in self.offer_terms}:
            raise ValueError("selected_offer_id does not exist")
        if self.review_status != "DRAFT" and (not self.review_notes.reviewer or self.review_notes.reviewed_at is None):
            raise ValueError("reviewed records require a named reviewer and review date")
        if self.review_status == "VERIFIED" and not self.review_notes.verification_notes:
            raise ValueError("verified records require explicit manual verification notes")
        return self


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys rather than silently discarding research."""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("YAML mapping keys must be strings")
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
# Read decimals as strings so source precision survives YAML parsing.
def _decimal_scalar(loader: UniqueSafeLoader, node: yaml.Node) -> str:
    if not isinstance(node, yaml.ScalarNode):
        raise ValueError("decimal YAML value must be a scalar")
    return loader.construct_scalar(node)


UniqueSafeLoader.add_constructor("tag:yaml.org,2002:float", _decimal_scalar)


def load_research(path: str | Path) -> ResearchDeal:
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("research file exceeds 2 MB")
    text = path.read_text(encoding="utf-8")
    # Aliases complicate provenance and can create cyclic or explosive structures.
    if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(text)):
        raise ValueError("YAML anchors/aliases are not supported")
    raw = yaml.load(text, Loader=UniqueSafeLoader)
    if not isinstance(raw, dict):
        raise ValueError("research must be a single YAML mapping")
    deal = ResearchDeal.model_validate(raw)
    validate_financial_inputs(deal)
    return deal


def as_kwargs(model):
    return {key: getattr(model, key) for key in type(model).model_fields}


def validate_financial_inputs(deal: ResearchDeal):
    """Check units even when insufficient data prevents a full calculation."""
    for offer in deal.offer_terms:
        f._value(offer.price, "currency/share", nonnegative=True)
        if offer.price.period is not None:
            raise ValueError("offer price cannot be a flow-period metric")
    for ref in deal.unaffected_price:
        value = f._value(ref.price, "currency/share", nonnegative=True)
        if ref.price.period is not None:
            raise ValueError("reference price cannot be a flow-period metric")
        if value == 0:
            raise ValueError("reference price must be positive")
        if ref.price.as_of not in (None, ref.reference_date):
            raise ValueError("reference date mismatch")
    for financials in (deal.target_financials, deal.buyer_financials):
        for metric in ("revenue", "ebitda", "ebit", "net_income"):
            series = getattr(financials, metric)
            for name in type(series).model_fields:
                fact = getattr(series, name)
                f._value(fact, "currency")
                if fact is not None:
                    if fact.period is None or fact.as_of is not None:
                        raise ValueError(f"{metric}.{name} requires flow period dates, not snapshot dates")
                    if name in ("latest_fy", "selected"):
                        f._annual(fact, ("FY",) if name == "latest_fy" else ("FY", "LTM"))
                    elif fact.period.basis != "YTD" or (fact.period.end-fact.period.start).days >= 364:
                        raise ValueError("current/prior YTD requires an interim YTD period")
        for name in ("cash", "debt", "net_debt"):
            fact = getattr(financials, name)
            f._value(fact, "currency", nonnegative=name != "net_debt")
            f._snapshot(fact)
        f._value(financials.diluted_shares, "shares", nonnegative=True)
    valuation = deal.transaction_valuation
    for name in ("reported_equity_value", "reported_enterprise_value", "reported_transaction_value", "equity_for_ev"):
        fact = getattr(valuation, name)
        f._value(fact, "currency", nonnegative=name in ("reported_equity_value", "reported_transaction_value", "equity_for_ev"))
        if fact is not None and fact.period is not None:
            raise ValueError("transaction valuation cannot be an income-statement flow")
    # Invoke component validation even with no selected offer or incomplete EV basis.
    for component in valuation.share_components:
        f.ShareComponent.model_validate(component.model_dump())
    component_ids = [c.component_id for c in valuation.share_components]
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("duplicate share component ID")
    for adjustment in valuation.ev_adjustments:
        f.EVAdjustment.model_validate(adjustment.model_dump())
    adjustment_ids = [a.adjustment_id for a in valuation.ev_adjustments]
    adjustment_kinds = [a.kind for a in valuation.ev_adjustments if a.kind != "other"]
    if len(adjustment_ids) != len(set(adjustment_ids)) or len(adjustment_kinds) != len(set(adjustment_kinds)):
        raise ValueError("duplicate EV adjustment")
    f._snapshot_alignment([a.amount for a in valuation.ev_adjustments if a.kind != "other"], valuation.snapshot_alignment_basis)
    for name in ("committed_facility", "new_debt", "cash_consideration", "fees", "new_equity_proceeds", "disposal_proceeds"):
        fact = getattr(deal.financing, name)
        f._value(fact, "currency", nonnegative=True)
        if fact is not None and fact.period is not None:
            raise ValueError("financing transaction amount cannot be an earnings flow")
    synergy_ids = [s.synergy_id for s in deal.synergies]
    if len(synergy_ids) != len(set(synergy_ids)):
        raise ValueError("duplicate synergy ID")
    for synergy in deal.synergies:
        f.Synergy.model_validate(synergy.model_dump())
    analyse(deal)


def analyse(deal: ResearchDeal) -> dict:
    """Calculate only explicitly selected bases; leave insufficient models absent."""
    out: dict[str, Any] = {}
    offer = next((o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id), None)
    valuation = deal.transaction_valuation
    if offer is not None and valuation.share_basis:
        out["equity"] = f.equity_value(offer.price, valuation.share_components,
                                       share_basis=valuation.share_basis,
                                       reported_equity_value=valuation.reported_equity_value)
    if valuation.equity_for_ev is not None and valuation.ev_bridge_basis:
        out["ev"] = f.enterprise_value(valuation.equity_for_ev, valuation.ev_adjustments,
                                       bridge_basis=valuation.ev_bridge_basis,
                                       reported_enterprise_value=valuation.reported_enterprise_value,
                                       preferred_ev_basis=valuation.preferred_ev_basis,
                                       snapshot_alignment_basis=valuation.snapshot_alignment_basis)
    for metric in ("revenue", "ebitda", "ebit", "net_income"):
        series = getattr(deal.target_financials, metric)
        if series.latest_fy is not None and series.current_ytd is not None:
            out[f"ltm_{metric}"] = f.ltm(metric, series.latest_fy, series.current_ytd, series.prior_ytd)
    ev = valuation.reported_enterprise_value if valuation.preferred_ev_basis == "reported" else None
    if valuation.preferred_ev_basis == "calculated" and "ev" in out:
        result = out["ev"]["calculated_enterprise_value"]
        ev = f.derived_fact(result)
    for metric in ("revenue", "ebitda", "ebit", "net_income"):
        denominator = getattr(deal.target_financials, metric).selected
        numerator = valuation.reported_equity_value if metric == "net_income" else ev
        if numerator is not None and denominator is not None:
            name = "equity_net_income" if metric == "net_income" else f"ev_{metric}"
            out[name] = f.multiple(name, numerator, denominator)
    if offer is not None:
        out["premiums"] = {ref.reference_id: f.premium(offer.price, ref.price,
                            reference_date=ref.reference_date, reference_basis=ref.reference_basis,
                            offer_stage=offer.stage) for ref in deal.unaffected_price}
    if deal.consideration is not None:
        out["consideration"] = f.consideration(**as_kwargs(deal.consideration))
    if deal.synergies and ev is not None and deal.target_financials.ebitda.selected is not None:
        out["synergies"] = f.synergy_analysis(deal.synergies, ev, deal.target_financials.ebitda.selected)
    if deal.leverage_inputs is not None:
        out["leverage"] = f.leverage(**as_kwargs(deal.leverage_inputs))
    if deal.accretion_inputs is not None:
        out["accretion"] = f.accretion(**as_kwargs(deal.accretion_inputs))
    return out


def jsonable(value):
    """Pydantic's JSON encoder retains Decimal strings and ISO dates recursively."""
    from pydantic import TypeAdapter
    return json.loads(TypeAdapter(object).dump_json(value))


def template() -> str:
    """A valid missing-data draft, with all research sections visible."""
    raw = ResearchDeal(identity=Identity(deal_id="DL-00000", name="Bidder / Target",
                         announcement_date=date(2000, 1, 1)),
                       bidder=Company(name="Bidder legal name", country="GB"),
                       target=Company(name="Target legal name", country="GB"))
    return ("# Replace the example identity and date. Null means unknown; zero means established zero.\n"
            "# Monetary values need unit, currency, scale, definition and evidence IDs.\n"
            "# See research/templates/README.md for complete input shapes.\n" +
            yaml.safe_dump(jsonable(raw), sort_keys=False, allow_unicode=True))
