from datetime import date
from decimal import Decimal as D

import pytest

from deallens.finance import (Adjustment, EVAdjustment, ShareComponent, Synergy, accretion, consideration,
                             enterprise_value, equity_value, leverage, ltm, multiple, premium, synergy_analysis)
from deallens.models import Period
from conftest import fact


def period(start, end, basis):
    return Period(start=date.fromisoformat(start), end=date.fromisoformat(end), basis=basis)


@pytest.mark.parametrize("end,prior_end,current,prior,expected", [
    ("2024-06-30", "2023-06-30", 60, 50, 110),
    ("2024-09-30", "2023-09-30", 90, 80, 110),
    ("2024-06-30", "2023-06-30", -20, -10, 90)])
@pytest.mark.parametrize("metric", ["revenue", "ebitda", "ebit", "net_income"])
def test_ltm_flow_metrics(fy, end, prior_end, current, prior, expected, metric):
    result = ltm(metric, fact(100, period=fy, evidence=("fy",)),
                 fact(current, period=period("2024-01-01", end, "YTD"), evidence=("cy",)),
                 fact(prior, period=period("2023-01-01", prior_end, "YTD"), evidence=("py",)))
    assert result.result == expected
    assert result.period.basis == "LTM"
    assert result.inputs["latest_fy"].evidence == ("fy",)


def test_ltm_missing_comparable(fy):
    result = ltm("ebitda", fact(100, period=fy), fact(60, period=period("2024-01-01", "2024-06-30", "YTD")), None)
    assert result.result is None and result.warnings


@pytest.mark.parametrize("metric", ["cash", "debt", "net_debt", "assets"])
def test_ltm_rejects_snapshots(fy, metric):
    with pytest.raises(ValueError):
        ltm(metric, fact(100, period=fy), fact(60, period=fy), None)


@pytest.mark.parametrize("change", ["length", "definition", "start", "currency", "fy_length"])
def test_ltm_rejects_mismatch(fy, change):
    a = fact(100, period=fy)
    b = fact(60, period=period("2024-01-01", "2024-06-30", "YTD"))
    c = fact(50, period=period("2023-01-01", "2023-06-30", "YTD"))
    if change == "length":
        c = fact(50, period=period("2023-01-01", "2023-09-30", "YTD"))
    if change == "definition":
        c = fact(50, definition="statutory", period=c.period)
    if change == "start":
        b = fact(60, period=period("2024-02-01", "2024-06-30", "YTD"))
    if change == "currency":
        c = fact(50, currency="USD", period=c.period)
    if change == "fy_length":
        a = fact(100, period=period("2023-06-01", "2023-12-31", "FY"))
    with pytest.raises(ValueError):
        ltm("ebitda", a, b, c)


def share(kind, count, *, strike=None, id=None):
    return ShareComponent(component_id=id or kind, kind=kind, shares=fact(count, "shares"),
                          method="treasury_stock" if kind == "options" else "if_converted" if kind == "convertibles" else "gross",
                          exercise_price=None if strike is None else fact(strike, "currency/share"), basis="separate non-overlapping instruments")


def test_equity_full_bridge_and_reported_preserved():
    result = equity_value(fact(10, "currency/share"), [share("ordinary", 100), share("options", 20, strike=5),
                          share("restricted_stock", 3), share("employee_awards", 2), share("convertibles", 5)],
                          share_basis="fully diluted, distinct instruments", reported_equity_value=fact(1190))
    assert result["fully_diluted_shares"] == 120
    assert result["calculated_equity_value"].result == 1200
    assert result["reported_equity_value"].value == 1190
    assert len(result["bridge"]) == 5
    assert result["calculated_equity_value"].warnings


@pytest.mark.parametrize("strike,expected", [(0, 1200), (5, 1100), (10, 1000), (15, 1000)])
def test_options_treasury_stock(strike, expected):
    assert equity_value(fact(10, "currency/share"), [share("ordinary", 100), share("options", 20, strike=strike)],
                        share_basis="diluted")["calculated_equity_value"].result == expected


def test_pence_and_million_shares_normalised():
    shares = share("ordinary", 2).model_copy(update={"shares": fact(2, "shares", scale=1_000_000)})
    result = equity_value(fact(1250, "currency/share", scale="0.01"), [shares], share_basis="ordinary only")
    assert result["calculated_equity_value"].result == 25_000_000


@pytest.mark.parametrize("price,count", [(None, 100), (10, None)])
def test_missing_equity(price, count):
    assert equity_value(fact(price, "currency/share"), [share("ordinary", count)],
                        share_basis="ordinary")["calculated_equity_value"].result is None


def test_equity_duplicate_and_negative():
    with pytest.raises(ValueError):
        equity_value(fact(10, "currency/share"), [share("ordinary", 1), share("ordinary", 1)], share_basis="x")
    with pytest.raises(ValueError):
        equity_value(fact(-1, "currency/share"), [share("ordinary", 1)], share_basis="x")


def adjustment(kind, amount):
    return EVAdjustment(adjustment_id=kind, kind=kind, amount=fact(amount, as_of=date(2023, 12, 31)),
                        sign=-1 if kind == "non_operating_investments" else 1, basis="explicit inclusion")


def test_ev_bridge_and_reconciliation():
    result = enterprise_value(fact(1000), [adjustment("net_debt", 200), adjustment("preferred_stock", 30),
                              adjustment("minority_interest", 20), adjustment("non_operating_investments", 50)],
                              bridge_basis="ND + preferred + NCI - investments", reported_enterprise_value=fact(1250))
    assert result["calculated_enterprise_value"].result == 1200
    assert result["reported_enterprise_value"].value == 1250
    assert result["reconciliation"]["calculated_minus_reported"] == -50
    assert result["reconciliation"]["relative_difference"] == D("-0.04")


@pytest.mark.parametrize("net_debt,expected", [(-200, 800), (0, 1000), (None, None)])
def test_ev_negative_net_debt_and_missing(net_debt, expected):
    r = enterprise_value(fact(1000), [adjustment("net_debt", net_debt)], bridge_basis="net debt only")
    assert r["calculated_enterprise_value"].result == expected


def test_ev_reported_selected_and_no_fallback():
    r = enterprise_value(fact(1000), [], bridge_basis="debt free cash free", preferred_ev_basis="reported")
    assert r["preferred_enterprise_value"] is None
    assert r["calculated_enterprise_value"].result == 1000


def test_ev_reject_duplicate_and_incorrect_sign():
    with pytest.raises(ValueError):
        enterprise_value(fact(1), [adjustment("net_debt", 1)] * 2, bridge_basis="x")
    with pytest.raises(ValueError):
        EVAdjustment(adjustment_id="x", kind="net_debt", amount=fact(1), sign=-1, basis="x")


@pytest.mark.parametrize("metric", ["ev_revenue", "ev_ebitda", "ev_ebit", "equity_net_income"])
@pytest.mark.parametrize("den,expected", [(100, 10), (0, None), (-100, None), (None, None)])
def test_multiples(fy, metric, den, expected):
    result = multiple(metric, fact(1000, evidence=("ev",)), fact(den, period=fy, evidence=("earnings",)))
    assert result.result == expected
    assert result.period == fy and "FY" in result.basis
    assert result.inputs["numerator"].evidence == ("ev",)
    if expected is None:
        assert result.warnings


def test_multiples_currency_and_period(fy):
    with pytest.raises(ValueError):
        multiple("ev_ebitda", fact(1, currency="USD"), fact(1, period=fy))
    with pytest.raises(ValueError):
        multiple("ev_ebitda", fact(1), fact(1))
    ltm_period = period("2023-07-01", "2024-06-30", "LTM")
    assert "LTM" in multiple("ev_ebitda", fact(10), fact(1, period=ltm_period)).basis


@pytest.mark.parametrize("offer,ref,expected", [(125, 100, ".25"), (80, 100, "-.2"), (100, 100, "0")])
@pytest.mark.parametrize("stage", ["initial", "revised", "final"])
def test_premiums(offer, ref, expected, stage):
    r = premium(fact(offer, "currency/share"), fact(ref, "currency/share"), reference_date=date(2024, 1, 1),
                reference_basis="unaffected_close", offer_stage=stage)
    assert r.result == D(expected) and stage in r.basis


@pytest.mark.parametrize("ref,when,basis", [(0, date(2024, 1, 1), "close"), (100, None, "close"), (100, date(2024, 1, 1), "")])
def test_premium_requires_reference(ref, when, basis):
    with pytest.raises(ValueError):
        premium(fact(125, "currency/share"), fact(ref, "currency/share"), reference_date=when, reference_basis=basis)


@pytest.mark.parametrize("cash,ratio,other,expected", [(10, 0, 0, 10), (0, 2, 0, 40), (10, 2, 5, 55)])
def test_consideration_mix(cash, ratio, other, expected):
    result = consideration(cash=fact(cash, "currency/share"), exchange_ratio=fact(ratio, "ratio"),
                           bidder_price=None if ratio == 0 else fact(20, "currency/share"),
                           bidder_reference_date=None if ratio == 0 else date(2024, 1, 1),
                           other=fact(other, "currency/share"), structure="fixed", reference_basis="explicit reference")
    assert result.result == expected


@pytest.mark.parametrize("structure", ["floating", "collared"])
def test_floating_consideration_requires_basis(structure):
    kwargs = dict(cash=fact(10, "currency/share"), exchange_ratio=fact(2, "ratio"), bidder_price=fact(20, "currency/share"),
                  bidder_reference_date=date(2024, 1, 1), other=fact(0, "currency/share"), structure=structure)
    with pytest.raises(ValueError):
        consideration(**kwargs, reference_basis="")
    result = consideration(**kwargs, reference_basis="ratio at stated collar reference scenario")
    assert result.illustrative and result.warnings


def synergy(kind, amount, margin=None):
    return Synergy(synergy_id=kind, kind=kind, amount=fact(amount, period=period("2025-01-01", "2025-12-31", "RUN_RATE")),
                   eligible=True, realisation_months=36, revenue_margin=None if margin is None else fact(margin, "fraction"), basis="annual savings")


def test_synergy_taxonomy(fy):
    r = synergy_analysis([synergy("cost", 20), synergy("revenue", 100), synergy("capex", 10),
                          synergy("financial", 5), synergy("implementation_cost", 30)], fact(1200), fact(100, period=fy))
    assert r["eligible_cost_synergies"] == 20
    assert r["explicit_margin_revenue_ebitda"] == 0
    assert r["synergy_adjusted_multiple"].result == 10
    assert r["cost_synergy_ebitda"].result == D(".2")
    assert r["synergy_adjusted_multiple"].illustrative
    assert "no margin" in " ".join(r["synergy_adjusted_multiple"].warnings)


def test_revenue_margin_only_when_explicit(fy):
    r = synergy_analysis([synergy("revenue", 100, ".3")], fact(1000), fact(100, period=fy))
    assert r["explicit_margin_revenue_ebitda"] == 30
    assert r["synergy_adjusted_multiple"].result == 10  # only eligible cost synergies


@pytest.mark.parametrize("ebitda", [0, -10, None])
def test_synergy_nonmeaningful_denominator(fy, ebitda):
    r = synergy_analysis([synergy("cost", 0)], fact(1000), fact(ebitda, period=fy))
    assert r["cost_synergy_ebitda"].result is None
    assert r["synergy_adjusted_multiple"].result is None


def leverage_inputs(fy):
    return dict(buyer_net_debt=fact(300, as_of=fy.end), target_net_debt=fact(50, as_of=fy.end), cash_consideration=fact(100), fees=fact(10),
                new_equity_proceeds=fact(0), disposal_proceeds=fact(0), buyer_ebitda=fact(100, period=fy),
                target_ebitda=fact(50, period=fy), eligible_cost_synergy=fact(10, period=period("2025-01-01", "2025-12-31", "RUN_RATE")), adjustments=[],
                basis="same currency and snapshot date; full-year annual run-rate; all cash uses included once")


@pytest.mark.parametrize("changes,debt", [({}, 460), ({"cash_consideration": 50}, 410),
                        ({"target_net_debt": -50}, 360), ({"new_equity_proceeds": 100}, 360),
                        ({"disposal_proceeds": 20}, 440), ({"fees": None}, None)])
def test_acquisition_leverage(fy, changes, debt):
    inputs = leverage_inputs(fy)
    inputs.update({k: fact(v, as_of=fy.end if k.endswith("net_debt") else None) for k, v in changes.items()})
    r = leverage(**inputs)
    assert r["buyer_standalone_leverage"].result == 3
    assert r["pro_forma_net_debt"].result == debt
    assert r["pro_forma_ebitda_before_synergy"].result == 150
    assert r["pro_forma_ebitda_after_synergy"].result == 160
    assert r["leverage_after_synergy"].result == (None if debt is None else D(debt)/160)
    assert r["leverage_after_synergy"].illustrative


def test_leverage_missing_ebitda(fy):
    inputs = leverage_inputs(fy) | {"target_ebitda": fact(None, period=fy)}
    r = leverage(**inputs)
    assert r["pro_forma_net_debt"].result == 460
    assert r["leverage_before_synergy"].result is None


def test_leverage_adjustment_and_net_cash(fy):
    r = leverage(**(leverage_inputs(fy) | {"buyer_net_debt": fact(-1000, as_of=fy.end),
                 "adjustments": [Adjustment(adjustment_id="disposal", amount=fact(-20), basis="additional signed adjustment")]}))
    assert r["pro_forma_net_debt"].result == -860
    assert r["leverage_before_synergy"].result < 0  # net cash is meaningful


def eps_inputs(fy):
    return dict(buyer_net_income=fact(100, period=fy), buyer_diluted_shares=fact(50, "shares"),
                target_net_income=fact(20, period=fy), eligible_pretax_synergies=fact(10, period=period("2025-01-01", "2025-12-31", "RUN_RATE")), tax_rate=fact(".25", "fraction"),
                new_debt=fact(100), incremental_interest_rate=fact(".1", "fraction"), new_shares_issued=fact(10, "shares"),
                recurring_adjustments=[], basis="annual full-year, adjustments after tax")


def test_simplified_eps_full_bridge(fy):
    r = accretion(**eps_inputs(fy))
    assert r["buyer_standalone_eps"].result == 2
    assert r["incremental_interest_expense"].result == 10
    assert r["after_tax_interest"].result == D("7.5")
    assert r["after_tax_synergies"].result == D("7.5")
    assert r["pro_forma_net_income"].result == 120
    assert r["pro_forma_diluted_shares"].result == 60
    assert r["pro_forma_eps"].result == 2
    assert r["accretion_dilution"].result == 0
    assert all(v.illustrative and "SIMPLIFIED" in v.warnings[0] for v in r.values())


@pytest.mark.parametrize("ni", [0, -100, None])
def test_eps_nonpositive_or_missing_base(fy, ni):
    r = accretion(**(eps_inputs(fy) | {"buyer_net_income": fact(ni, period=fy)}))
    assert r["accretion_dilution"].result is None


@pytest.mark.parametrize("rate", [25, -1, "1.01"])
def test_eps_percentage_errors(fy, rate):
    with pytest.raises(ValueError):
        accretion(**(eps_inputs(fy) | {"tax_rate": fact(rate, "fraction")}))


def test_eps_zero_shares_and_period_mismatch(fy):
    with pytest.raises(ValueError):
        accretion(**(eps_inputs(fy) | {"buyer_diluted_shares": fact(0, "shares")}))
    with pytest.raises(ValueError):
        accretion(**(eps_inputs(fy) | {"target_net_income": fact(20, period=period("2022-01-01", "2022-12-31", "FY"))}))


def test_eps_after_tax_adjustment_and_dilution(fy):
    r = accretion(**(eps_inputs(fy) | {"recurring_adjustments": [Adjustment(adjustment_id="ppa", amount=fact(-12, period=fy), basis="after-tax amortisation")]}))
    assert r["pro_forma_net_income"].result == 108
    assert r["accretion_dilution"].result == D("-.1")


def test_decimal_precision_and_evidence(fy):
    r = multiple("ev_revenue", fact("0.3", evidence=("source1",)), fact("0.1", period=fy))
    assert r.result == 3
    assert r.inputs["numerator"].evidence == ("source1",)


@pytest.mark.parametrize("value", ["NaN", "Infinity", True])
def test_nonfinite_and_boolean_rejected(value):
    from deallens.models import Fact
    with pytest.raises(ValueError):
        Fact(value=value, unit="currency", currency="GBP", definition="test")
