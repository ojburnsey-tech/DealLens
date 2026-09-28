"""Adversarial review regressions: expected values are independently derived."""
from datetime import date
from decimal import Decimal as D

import pytest

from conftest import fact
from deallens import finance as f
from deallens.models import Evidence, Fact, Result, Source
from deallens.research import ResearchDeal, analyse, validate_financial_inputs
from deallens.store import Store
from test_finance import eps_inputs, leverage_inputs, period, synergy


@pytest.mark.parametrize("end", ["2023-01-31", "2024-02-01", "2024-01-02"])
@pytest.mark.parametrize("basis", ["FY", "LTM"])
@pytest.mark.parametrize("model", ["multiple", "leverage", "eps", "synergy"])
def test_h1_annual_models_reject_short_and_extended_periods(end, basis, model):
    p = period("2023-01-01", end, basis)
    with pytest.raises(ValueError, match="annual period"):
        if model == "multiple":
            f.multiple("ev_ebitda", fact(1000), fact(10, period=p))
        elif model == "leverage":
            f.leverage(**leverage_inputs(p))
        elif model == "eps":
            f.accretion(**eps_inputs(p))
        else:
            f.synergy_analysis([], fact(1000), fact(10, period=p))


@pytest.mark.parametrize("start,end", [("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"),
                                      ("2023-01-01", "2023-12-30"), ("2023-01-01", "2024-01-06")])
@pytest.mark.parametrize("basis", ["FY", "LTM"])
def test_h1_calendar_leap_and_52_53_week_periods_are_annual(start, end, basis):
    p = period(start, end, basis)
    assert f.multiple("ev_ebitda", fact(1000), fact(100, period=p)).result == 10
    assert f.leverage(**leverage_inputs(p))["pro_forma_net_debt"].result == 460
    assert f.accretion(**eps_inputs(p))["pro_forma_net_income"].result == 120
    assert f.synergy_analysis([], fact(1000), fact(100, period=p))["synergy_adjusted_multiple"].result == 10


@pytest.mark.parametrize("end,basis", [("2027-12-31", "RUN_RATE"), ("2025-06-30", "RUN_RATE"),
                                      ("2025-06-30", "YTD")])
@pytest.mark.parametrize("model", ["leverage", "eps"])
def test_h2_interim_and_cumulative_synergies_rejected(fy, end, basis, model):
    supplied = fact(120, period=period("2025-01-01", end, basis))
    with pytest.raises(ValueError, match="annual"):
        if model == "leverage":
            f.leverage(**(leverage_inputs(fy) | {"eligible_cost_synergy": supplied}))
        else:
            f.accretion(**(eps_inputs(fy) | {"eligible_pretax_synergies": supplied}))


@pytest.mark.parametrize("value,expected", [(0, 150), (None, None)])
def test_h2_explicit_zero_and_unknown_synergy_do_not_invent_dates(fy, value, expected):
    result = f.leverage(**(leverage_inputs(fy) | {"eligible_cost_synergy": fact(value)}))
    assert result["pro_forma_ebitda_after_synergy"].result == expected
    eps = f.accretion(**(eps_inputs(fy) | {"eligible_pretax_synergies": fact(value)}))
    assert eps["after_tax_synergies"].result == (0 if value == 0 else None)


def test_h2_documented_annual_synergy_example(fy):
    annual = fact(40, period=period("2025-01-01", "2025-12-31", "RUN_RATE"), evidence=("annual",))
    leverage = f.leverage(**(leverage_inputs(fy) | {"eligible_cost_synergy": annual}))
    assert leverage["pro_forma_ebitda_after_synergy"].result == 190
    eps = f.accretion(**(eps_inputs(fy) | {"eligible_pretax_synergies": annual}))
    assert eps["accretion_dilution"].result == D(".1875")
    assert eps["accretion_dilution"].inputs["eligible_pretax_synergies"].evidence == ("annual",)


@pytest.mark.parametrize("supplied", [fact(10), fact(-10), fact(-10, period=period("2022-01-01", "2022-12-31", "FY")),
                                     fact(-10, period=period("2023-01-01", "2023-06-30", "YTD"))])
def test_h2_recurring_adjustment_requires_compatible_annual_basis(fy, supplied):
    adj = f.Adjustment(adjustment_id="ppa", amount=supplied, basis="after-tax amortisation")
    with pytest.raises(ValueError, match="annual"):
        f.accretion(**(eps_inputs(fy) | {"recurring_adjustments": [adj]}))


def test_h2_explicit_forecast_annual_assumption_and_zero_adjustment(fy):
    annual = fact(40, period=period("2025-01-01", "2025-12-31", "FORECAST")).model_copy(update={"classification": "ASSUMPTION"})
    zero = f.Adjustment(adjustment_id="ppa", amount=fact(0), basis="established zero")
    result = f.accretion(**(eps_inputs(fy) | {"eligible_pretax_synergies": annual, "recurring_adjustments": [zero]}))
    assert result["pro_forma_net_income"].result == D("142.5")


@pytest.mark.parametrize("model", ["leverage", "ev"])
@pytest.mark.parametrize("bad", [fact(200), fact(200, period=period("2023-01-01", "2023-12-31", "FY"))])
def test_h3_missing_and_flow_period_debt_rejected(fy, model, bad):
    with pytest.raises(ValueError, match="snapshot"):
        if model == "leverage":
            f.leverage(**(leverage_inputs(fy) | {"buyer_net_debt": bad}))
        else:
            f.enterprise_value(fact(1000), [f.EVAdjustment(adjustment_id="nd", kind="net_debt", amount=bad, sign=1, basis="ND")], bridge_basis="ND only")


def ev_adjustment(kind, value, when):
    return f.EVAdjustment(adjustment_id=kind, kind=kind, amount=fact(value, as_of=when), sign=1, basis="explicit balance")


@pytest.mark.parametrize("model", ["leverage", "ev"])
def test_h3_mismatched_snapshots_require_visible_qualification(fy, model):
    if model == "leverage":
        kwargs = leverage_inputs(fy) | {"buyer_net_debt": fact(300, as_of=date(2010, 1, 1))}
        def calculate(**extra):
            return f.leverage(**(kwargs | extra))["pro_forma_net_debt"]
        expected = 460
    else:
        adjustments = [ev_adjustment("net_debt", 200, date(2010, 1, 1)), ev_adjustment("preferred_stock", 30, fy.end)]
        def calculate(**extra):
            return f.enterprise_value(fact(1000), adjustments, bridge_basis="ND and preferred", **extra)["calculated_enterprise_value"]
        expected = 1230
    with pytest.raises(ValueError, match="snapshot dates differ"):
        calculate()
    result = calculate(snapshot_alignment_basis="Source dates retained; balances assumed unchanged for illustrative comparison; requires human review")
    assert result.result == expected
    assert result.qualifications and "2010-01-01" in result.qualifications[0]
    assert result.inputs["snapshot_alignment_basis"]


def test_h3_same_date_and_established_zero_snapshots(fy):
    result = f.leverage(**(leverage_inputs(fy) | {"target_net_debt": fact(-50, as_of=fy.end)}))
    assert result["pro_forma_net_debt"].result == 360
    assert result["pro_forma_net_debt"].qualifications == ()
    result = f.leverage(**(leverage_inputs(fy) | {"target_net_debt": fact(0)}))
    assert result["pro_forma_net_debt"].result == 410


@pytest.mark.parametrize("section,field,bad", [
    ("transaction_valuation", "reported_equity_value", fact(100, "shares")),
    ("transaction_valuation", "reported_enterprise_value", fact(100, "shares")),
    ("transaction_valuation", "reported_transaction_value", fact(100, "shares")),
    ("transaction_valuation", "equity_for_ev", fact(100, "shares")),
    ("transaction_valuation", "reported_equity_value", fact(-100)),
    ("transaction_valuation", "reported_transaction_value", fact(-100)),
    ("financing", "committed_facility", fact(-100)),
    ("financing", "new_debt", fact(-100)),
    ("financing", "cash_consideration", fact(-100)),
    ("financing", "fees", fact(-100, "shares")),
    ("financing", "fees", fact(-100)),
    ("financing", "new_equity_proceeds", fact(-100)),
    ("financing", "disposal_proceeds", fact(-100)),
    ("financing", "committed_facility", fact(100, "shares")),
    ("financing", "new_debt", fact(100, "shares")),
    ("financing", "cash_consideration", fact(100, "shares")),
    ("financing", "new_equity_proceeds", fact(100, "shares")),
    ("financing", "disposal_proceeds", fact(100, "shares")),
])
def test_h4_invalid_inactive_field_import_is_atomic(draft, section, field, bad):
    raw = draft.model_dump()
    raw[section][field] = bad
    deal = ResearchDeal.model_validate(raw)
    with Store(":memory:") as store:
        with pytest.raises(ValueError):
            store.import_deal(deal)
        for table in ("deals", "sources", "evidence", "field_facts"):
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("component", [
    {"component_id": "s", "kind": "ordinary", "shares": fact(100), "method": "gross", "basis": "ordinary"},
    {"component_id": "s", "kind": "ordinary", "shares": fact(-100, "shares"), "method": "gross", "basis": "ordinary"},
    {"component_id": "s", "kind": "options", "shares": fact(100, "shares"), "method": "treasury_stock", "exercise_price": fact(2), "basis": "options"},
])
def test_h4_inactive_share_components_rejected(draft, component):
    raw = draft.model_dump()
    raw["transaction_valuation"]["share_components"] = [component]
    with pytest.raises(ValueError):
        ResearchDeal.model_validate(raw)


@pytest.mark.parametrize("kind,bad", [("net_debt", fact(100, "shares")), ("net_debt", fact(100)),
                                     ("preferred_stock", fact(-100, as_of=date(2023, 12, 31)))])
def test_h4_inactive_ev_adjustments_rejected(draft, kind, bad):
    raw = draft.model_dump()
    raw["transaction_valuation"]["ev_adjustments"] = [{"adjustment_id": "a", "kind": kind, "amount": bad, "sign": 1, "basis": "explicit"}]
    with pytest.raises(ValueError):
        ResearchDeal.model_validate(raw)


def test_h4_valid_partial_negative_ev_net_cash_and_earnings_import(draft, fy):
    raw = draft.model_dump()
    raw["transaction_valuation"]["reported_enterprise_value"] = fact(-100)
    raw["target_financials"]["net_debt"] = fact(-200, as_of=fy.end)
    raw["target_financials"]["ebitda"]["selected"] = fact(-10, period=fy)
    deal = ResearchDeal.model_validate(raw)
    with Store(":memory:") as store:
        store.import_deal(deal)
        assert store.show("DL-00001").target_financials.net_debt.amount == -200


def lineage_deal(draft, fy):
    raw = draft.model_dump()
    raw["sources"] = [Source(source_id="s", title="Source", url="https://example.com", publication_date=fy.end, source_type="ANNUAL_REPORT")]
    raw["field_evidence"] = [Evidence(evidence_id=e, source_id="s", section="Financials", reported_unit="GBP", note=e) for e in ("equity", "debt", "unused", "preferred")]
    raw["transaction_valuation"] = dict(
        equity_for_ev=fact(1000, evidence=("equity",)),
        ev_adjustments=[f.EVAdjustment(adjustment_id="nd", kind="net_debt", amount=fact(200, as_of=fy.end, evidence=("debt",)), sign=1, basis="target net debt"),
                        f.EVAdjustment(adjustment_id="ps", kind="preferred_stock", amount=fact(30, as_of=date(2022, 12, 31), evidence=("preferred",)), sign=1, basis="preferred stock")],
        reported_transaction_value=fact(9999, evidence=("unused",)), ev_bridge_basis="Equity plus explicit debt and preferred; all others excluded",
        preferred_ev_basis="calculated", snapshot_alignment_basis="Illustrative unchanged preferred balance; dates retained for review")
    raw["target_financials"]["ebitda"]["selected"] = fact(100, period=fy)
    raw["synergies"] = [synergy("cost", 20)]
    return ResearchDeal.model_validate(raw)


@pytest.mark.parametrize("output", ["multiple", "synergy"])
def test_h5_standalone_output_preserves_exact_ev_lineage_after_json(draft, fy, output):
    out = analyse(lineage_deal(draft, fy))
    result = out["ev_ebitda"] if output == "multiple" else out["synergies"]["synergy_adjusted_multiple"]
    raw = Result.model_validate_json(result.model_dump_json()).model_dump(mode="json")
    numerator = raw["inputs"]["numerator" if output == "multiple" else "ev"]
    assert set(numerator["evidence"]) == {"equity", "debt", "preferred"}
    derived = numerator["derivation"]
    assert derived["formula"] == "Equity Value + explicit signed EV adjustments"
    assert derived["inputs"]["equity_value"]["value"] == "1000"
    assert derived["inputs"]["bridge"][0]["signed_amount"] == "200"
    assert derived["inputs"]["bridge"][0]["adjustment"]["amount"]["as_of"] == "2023-12-31"
    assert derived["qualifications"] == raw["qualifications"]
    assert raw["qualifications"]
    assert "unused" not in str(numerator)


def test_h5_derived_warnings_propagate_into_standalone_multiple(fy):
    original = f.enterprise_value(fact(None), [], bridge_basis="missing equity")["calculated_enterprise_value"]
    original = original.model_copy(update={"warnings": ("Specific source bridge warning",)})
    derived = Fact.model_validate_json(f.derived_fact(original).model_dump_json())
    result = f.multiple("ev_ebitda", derived, fact(100, period=fy))
    assert result.result is None
    assert "Specific source bridge warning" in result.warnings
    assert result.inputs["numerator"].derivation.formula == original.formula


def test_m1_valid_53_week_fiscal_ltm_cycle():
    result = f.ltm("ebitda", fact(100, period=period("2023-01-01", "2024-01-06", "FY")),
                   fact(60, period=period("2024-01-07", "2024-07-06", "YTD")),
                   fact(50, period=period("2023-01-01", "2023-07-01", "YTD")))
    assert result.result == 110
    assert (result.period.end - result.period.start).days + 1 == 371
    assert any("53-week" in warning for warning in result.warnings)


@pytest.mark.parametrize("value", [0, -100])
def test_m2_nonpositive_earnings_are_not_mislabelled_missing(fy, value):
    result = f.leverage(**(leverage_inputs(fy) | {"buyer_ebitda": fact(value, period=fy)}))["buyer_standalone_leverage"]
    assert result.result is None
    assert any("zero or negative" in w for w in result.warnings)
    assert not any("Missing" in w for w in result.warnings)
    ratios = f.synergy_analysis([], fact(1000), fact(value, period=fy))
    for name in ("cost_synergy_ebitda", "synergy_adjusted_multiple"):
        assert ratios[name].result is None
        assert any("zero or negative" in w for w in ratios[name].warnings)


def test_m4_direct_ev_api_rejects_invalid_preference():
    with pytest.raises(ValueError, match="preferred_ev_basis"):
        f.enterprise_value(fact(1000), [], bridge_basis="no adjustments", preferred_ev_basis="nonsense")


def test_l1_metric_identity_contract_is_explicit():
    assert "Caller must supply the named metric" in f.multiple.__doc__


@pytest.mark.parametrize("change", [{"value": D(999)}, {"currency": "USD"}, {"unit": "currency/share"},
                                    {"classification": "REPORTED"}, {"evidence": ("unrelated",)},
                                    {"period": period("2023-01-01", "2023-12-31", "FY")}])
def test_h5_supplied_derived_fact_cannot_contradict_its_calculation(change):
    result = f.enterprise_value(fact(1000, evidence=("equity",)), [], bridge_basis="equity only")["calculated_enterprise_value"]
    raw = f.derived_fact(result).model_dump() | change
    with pytest.raises(ValueError, match="deriv"):
        Fact.model_validate(raw)


def test_h5_roundtripped_result_can_be_reused_without_losing_evidence(draft, fy):
    original = analyse(lineage_deal(draft, fy))["ev"]["calculated_enterprise_value"]
    reloaded = Result.model_validate_json(original.model_dump_json())
    fact_again = f.derived_fact(reloaded)
    assert set(fact_again.evidence) == {"equity", "debt", "preferred"}
    result = f.multiple("ev_ebitda", fact_again, fact(100, period=fy))
    assert result.result == D("12.3")
    assert result.qualifications == original.qualifications


@pytest.mark.parametrize("bad", [fact(300), fact(300, period=period("2023-01-01", "2023-12-31", "FY")),
                                 fact(300, as_of=date(2010, 1, 1))])
def test_h3_research_ingestion_rejects_invalid_leverage_snapshots(draft, fy, bad):
    raw = draft.model_dump()
    raw["leverage_inputs"] = leverage_inputs(fy) | {"buyer_net_debt": bad}
    deal = ResearchDeal.model_validate(raw)
    with Store(":memory:") as store:
        with pytest.raises(ValueError, match="snapshot"):
            store.import_deal(deal)
        assert store.all() == []


@pytest.mark.parametrize("section,field", [("target_financials", "revenue"), ("buyer_financials", "ebitda")])
def test_h1_h4_inactive_short_annual_financial_is_rejected(draft, section, field):
    raw = draft.model_dump()
    raw[section][field]["latest_fy"] = fact(100, period=period("2023-01-01", "2023-01-31", "FY"))
    with pytest.raises(ValueError, match="annual period"):
        validate_financial_inputs(ResearchDeal.model_validate(raw))


def test_h4_inactive_synergy_units_and_margin_rejected(draft):
    raw = draft.model_dump()
    raw["synergies"] = [dict(synergy_id="cost", kind="cost", amount=fact(10, "shares"), eligible=False, basis="not yet eligible")]
    with pytest.raises(ValueError, match="currency"):
        ResearchDeal.model_validate(raw)
    raw["synergies"] = [dict(synergy_id="rev", kind="revenue", amount=fact(10), eligible=False,
                             revenue_margin=fact(25, "fraction"), basis="not yet eligible")]
    with pytest.raises(ValueError, match="rate must be a fraction"):
        ResearchDeal.model_validate(raw)
