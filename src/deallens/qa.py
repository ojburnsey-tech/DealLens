"""Financial reasonableness flags and explicit publication gates.

Thresholds request review; they are never automatic allegations of bad data.
"""
from decimal import Decimal
from typing import Literal


from .models import Model, Result, walk_facts
from .research import ResearchDeal, analyse, validate_financial_inputs


class Flag(Model):
    severity: Literal["INFO", "REVIEW", "ERROR", "BLOCK_PUBLISH"]
    code: str
    field: str
    message: str


def evidence_audit(deal: ResearchDeal) -> dict:
    sources = {s.source_id: s for s in deal.sources}
    evidence = {e.evidence_id: e for e in deal.field_evidence}
    missing, fields, unknown = [], [], []
    for path, fact in walk_facts(deal):
        if fact.value is None:
            unknown.append(path)
            continue
        if not fact.evidence:
            missing.append(path)
        references = []
        for key in fact.evidence:
            item = evidence.get(key)
            source = sources.get(item.source_id) if item else None
            if item is None or source is None:
                missing.append(path)
            else:
                references.append({"evidence": item, "source": source})
        fields.append({"field": path, "fact": fact, "references": references})
    return {"deal_id": deal.identity.deal_id, "review_status": deal.review_status,
            "populated_numerical_fields": len(fields), "missing_evidence": sorted(set(missing)),
            "unknown_fields": unknown, "fields": fields,
            "human_verification": deal.review_status == "VERIFIED"}


def _results(value, path=""):
    if isinstance(value, Result):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _results(item, f"{path}.{key}".strip("."))


def qa_deal(deal: ResearchDeal, *, require_verified=True) -> dict:
    """Schema, reasonableness, evidence, reconciliation and publication in one report."""
    flags = []
    def add(severity, code, field, message):
        flags.append(Flag(severity=severity, code=code, field=field, message=message))
    try:
        deal = ResearchDeal.model_validate(deal.model_dump())
        validate_financial_inputs(deal)
        calculations = analyse(deal)
    except ValueError as exc:
        return {"deal_id": deal.identity.deal_id, "publishable": False,
                "flags": [Flag(severity="ERROR", code="SCHEMA_OR_FINANCE", field="deal", message=str(exc))],
                "calculations": {}}
    add("INFO", "VALID_SCHEMA", "deal", "Schema and applicable finance-input checks passed.")
    if require_verified and deal.review_status != "VERIFIED":
        add("BLOCK_PUBLISH", "MANUAL_VERIFICATION_REQUIRED", "review_status", "Owner's manual source and calculation verification is required.")
    selected = next((o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id), None)
    if selected is None or selected.price.value is None:
        add("BLOCK_PUBLISH", "OFFER_REQUIRED", "selected_offer_id", "A sourced selected offer is required for a publishable transaction record.")
    for name in type(deal.profile).model_fields:
        if name not in ('evidence', 'field_evidence', 'notes') and getattr(deal.profile, name) is not None:
            if not deal.profile.field_evidence.get(name):
                add("BLOCK_PUBLISH", "PROFILE_EVIDENCE_REQUIRED", f"profile.{name}",
                    "Each analyst classification requires field-specific source evidence.")
    audit = evidence_audit(deal)
    for path in audit["missing_evidence"]:
        add("BLOCK_PUBLISH", "MISSING_EVIDENCE", path, "Populated numerical field lacks a resolvable source reference.")
    if not deal.sources:
        add("BLOCK_PUBLISH", "SOURCES_REQUIRED", "sources", "Primary source ledger is empty.")
    if deal.identity.completion_date and deal.identity.completion_date < deal.identity.announcement_date:
        add("ERROR", "COMPLETION_BEFORE_ANNOUNCEMENT", "identity.completion_date", "Completion precedes announcement; review the date definitions.")
    if deal.identity.transaction_status == "COMPLETED" and deal.identity.completion_date is None:
        add("BLOCK_PUBLISH", "COMPLETION_DATE_REQUIRED", "identity.completion_date", "A completed transaction requires a sourced completion date.")
    for path, fact in walk_facts(deal):
        if fact.value is None:
            add("REVIEW", "UNKNOWN_VALUE", path, "Explicitly unknown observation; no zero has been inferred.")
        if fact.ambiguity:
            add("REVIEW", "SOURCE_AMBIGUITY", path, fact.ambiguity)
        if fact.classification == "ASSUMPTION":
            add("REVIEW", "ASSUMPTION", path, "Researcher-supplied assumption; assess its stated basis.")
    for path, result in _results(calculations):
        for warning in result.warnings:
            add("REVIEW", "CALCULATION_WARNING", path, warning)
        for qualification in result.qualifications:
            add("BLOCK_PUBLISH", "MATERIAL_QUALIFICATION", path, qualification)
    for key, result in calculations.get("premiums", {}).items():
        if result.result is not None and result.result > 2:
            add("REVIEW", "PREMIUM_ABOVE_200_PERCENT", key, "Premium exceeds 200%; investigate basis and transaction history, not necessarily an error.")
        if result.result is not None and result.result < Decimal("-.2"):
            add("REVIEW", "PREMIUM_BELOW_MINUS_20_PERCENT", key, "Premium is below -20%; investigate basis and transaction history, not necessarily an error.")
    for key, threshold in (("ev_ebitda", 50), ("ev_revenue", 30)):
        result = calculations.get(key)
        if result is not None and result.result is not None and result.result > threshold:
            add("REVIEW", key.upper() + "_HIGH", key, f"Multiple exceeds {threshold}x; a reasonableness flag, not a claim of incorrect data.")
    synergy = calculations.get("synergies")
    target = deal.target_financials.ebitda.selected
    if synergy and target is not None and target.amount is not None:
        cost = synergy["eligible_cost_synergies"]
        if cost is not None and cost > target.amount:
            add("REVIEW", "SYNERGY_ABOVE_TARGET_EBITDA", "synergies", "Eligible annual cost synergies exceed target EBITDA; review scope and timing.")
    ev = calculations.get("ev")
    if ev:
        reconciliation = ev["reconciliation"]
        relative, difference = reconciliation["relative_difference"], reconciliation["calculated_minus_reported"]
        if (relative is not None and abs(relative) > Decimal(".1")) or (relative is None and difference not in (None, 0)):
            add("REVIEW", "EV_RECONCILIATION", "transaction_valuation", "Reported/calculated EV differs by more than 10%, or reported EV is zero with a nonzero difference; review dates and bridge definitions.")
    for metric in ("revenue", "ebitda", "ebit", "net_income"):
        selected_financial = getattr(deal.target_financials, metric).selected
        reconstructed = calculations.get(f"ltm_{metric}")
        if selected_financial is not None and reconstructed is not None and selected_financial.period == reconstructed.period:
            if selected_financial.amount is not None and reconstructed.result is not None and selected_financial.amount != reconstructed.result:
                add("REVIEW", "LTM_RECONCILIATION", f"target_financials.{metric}", "Selected and reconstructed figures differ for the same period; examine definitions and source restatements.")
    return {"deal_id": deal.identity.deal_id, "review_status": deal.review_status,
            "publishable": not any(f.severity in ("ERROR", "BLOCK_PUBLISH") for f in flags),
            "flags": flags, "calculations": calculations}


def qa_summary(reports):
    counts = {severity: 0 for severity in ("INFO", "REVIEW", "ERROR", "BLOCK_PUBLISH")}
    for report in reports:
        for flag in report["flags"]:
            counts[flag.severity] += 1
    return {"deals": len(reports), "publishable_deals": sum(r["publishable"] for r in reports),
            "severity_counts": counts, "reports": reports}
