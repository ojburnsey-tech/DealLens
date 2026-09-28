"""Pure transaction calculations; no database, network, rounding or inferred dates.

All currency results are in base units; share counts are absolute shares. Rates
are fractions, multiples are ratios. Missing is never coerced to zero. Callers
must explicitly supply zero or an empty adjustment list when that is their basis.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from .models import Fact, Model, Period, Result, Text, walk_facts

D = Decimal


def _value(fact: Fact | None, unit: str, *, nonnegative=False) -> Decimal | None:
    if fact is None:
        return None
    if fact.unit != unit:
        raise ValueError(f"expected {unit}, got {fact.unit}")
    value = fact.amount
    if value is not None and nonnegative and value < 0:
        raise ValueError("negative input is invalid for this component")
    return value


def _currency(*facts: Fact | None) -> str | None:
    currencies = {f.currency for f in facts if f is not None and f.currency is not None}
    if len(currencies) > 1:
        raise ValueError("currency mismatch; supply explicitly converted inputs with FX evidence")
    return next(iter(currencies), None)


def _rate(fact: Fact) -> Decimal | None:
    value = _value(fact, "fraction", nonnegative=True)
    if value is not None and value > 1:
        raise ValueError("rate must be a fraction in [0,1], not percentage points")
    return value


def _annual(fact: Fact, bases=("FY", "LTM")):
    """Annual dates must describe a calendar year or 52/53-week fiscal year."""
    p = fact.period
    if p is None or p.basis not in bases or (p.end-p.start).days + 1 not in (364, 365, 366, 371):
        raise ValueError("annual period required: calendar year or 52/53-week fiscal year")
    if fact.as_of is not None:
        raise ValueError("annual flow cannot also be a balance-sheet snapshot")


def _annual_assumption(fact: Fact, *, earnings: Fact | None = None):
    """A documented zero/unknown needs no invented annual assumption dates."""
    if fact.period is None and fact.amount in (None, D(0)):
        if fact.as_of is not None:
            raise ValueError("earnings assumption cannot be a snapshot")
        return
    if earnings is not None and fact.period == earnings.period:
        _annual(fact)
    elif fact.period is not None and fact.period.basis == "RUN_RATE":
        _annual(fact, ("RUN_RATE",))
    elif fact.classification == "ASSUMPTION":
        _annual(fact, ("FORECAST",))
    else:
        raise ValueError("nonzero synergy or recurring adjustment requires explicit annual RUN_RATE or annual assumption")


def _snapshot(fact: Fact | None):
    if fact is None:
        return
    if fact.period is not None:
        raise ValueError("balance-sheet snapshot cannot have a flow period")
    if fact.amount not in (None, D(0)) and fact.as_of is None:
        raise ValueError("nonzero balance-sheet snapshot requires as_of date")


def _snapshot_alignment(facts, basis: str | None):
    for fact in facts:
        _snapshot(fact)
    dates = sorted({fact.as_of for fact in facts if fact is not None and fact.amount is not None and fact.as_of is not None})
    if len(dates) <= 1:
        return ()
    if not basis or not basis.strip():
        raise ValueError("snapshot dates differ; explicit snapshot_alignment_basis required")
    return ("Qualified snapshot alignment: " + ", ".join(str(d) for d in dates) + "; " + basis,)


def _result(value, unit, formula, basis, inputs, *, warnings=(), period=None, illustrative=False, qualifications=()):
    facts = [fact for _, fact in walk_facts(inputs)]
    currency = _currency(*facts) if unit in ("currency", "currency/share") else None
    inherited_warnings = [w for fact in facts if fact.derivation for w in fact.derivation.warnings]
    inherited_qualifications = [q for fact in facts if fact.derivation for q in fact.derivation.qualifications]
    warnings = list(warnings)
    if value is None and not warnings:
        warnings.append("Missing required inputs; result not calculated.")
    return Result(result=value, unit=unit, currency=currency, formula=formula, basis=basis,
                  inputs=inputs, warnings=tuple(dict.fromkeys(warnings + inherited_warnings)), period=period,
                  illustrative=illustrative, qualifications=tuple(dict.fromkeys(list(qualifications) + inherited_qualifications)))


def derived_fact(result: Result) -> Fact:
    """Retain the exact participating calculation, without unrelated sibling facts."""
    evidence = tuple(dict.fromkeys(e for _, fact in walk_facts(result.inputs) for e in fact.evidence))
    return Fact.model_validate(dict(value=result.result, unit=result.unit, currency=result.currency, definition=result.basis,
                period=result.period, classification="CALCULATED", evidence=evidence, derivation=result))


def ltm(metric: str, latest_fy: Fact, current_ytd: Fact, prior_ytd: Fact | None) -> Result:
    """Reconstruct flow metrics only, with an explicitly comparable annual cycle."""
    if metric not in {"revenue", "ebitda", "ebit", "net_income"}:
        raise ValueError("LTM reconstruction supports income-statement flows, never cash/debt snapshots")
    inputs = dict(latest_fy=latest_fy, current_ytd=current_ytd, prior_ytd=prior_ytd)
    _currency(latest_fy, current_ytd, prior_ytd)
    values = [_value(f, "currency") for f in inputs.values()]
    fy, cy = latest_fy.period, current_ytd.period
    if fy is None or cy is None or fy.basis != "FY" or cy.basis != "YTD":
        raise ValueError("FY and YTD period dates and bases are required")
    _annual(latest_fy, ("FY",))
    if cy.start != fy.end + timedelta(days=1) or cy.end <= fy.end:
        raise ValueError("current YTD must immediately follow latest FY")
    if (cy.end - cy.start).days >= 364:
        raise ValueError("YTD must be less than a full year")
    if latest_fy.definition != current_ytd.definition:
        raise ValueError("financial definitions differ")
    warnings = []
    result_period = None
    if prior_ytd is not None:
        py = prior_ytd.period
        if py is None or py.basis != "YTD" or py.start != fy.start or py.end >= fy.end:
            raise ValueError("prior YTD must begin with and lie within latest FY")
        if prior_ytd.definition != latest_fy.definition:
            raise ValueError("financial definitions differ")
        # Permit one day for leap years only; fiscal week mismatches need manual restatement.
        a, b = (cy.end - cy.start).days, (py.end - py.start).days
        if abs(a - b) > 1:
            raise ValueError("YTD period lengths are not comparable")
        span = (cy.end - py.end).days
        if span not in (364, 365, 366, 371):
            raise ValueError("comparable endpoints must span twelve months")
        if span == 371:
            warnings.append("53-week LTM fiscal period; verify comparability with 52-week/calendar-year figures.")
        if a != b:
            warnings.append("YTD lengths differ by one day; verify leap-year comparability.")
        result_period = Period(start=py.end + timedelta(days=1), end=cy.end, basis="LTM")
    fy_value, cy_value, py_value = values
    value = None if fy_value is None or cy_value is None or py_value is None else fy_value + cy_value - py_value
    if value is None:
        warnings.append("Missing comparable or financial value; LTM unavailable.")
    return _result(value, "currency", "Latest FY + Current YTD - Prior-year comparable YTD",
                   f"LTM {metric}; {latest_fy.definition}", inputs, warnings=warnings, period=result_period)


class ShareComponent(Model):
    component_id: Text
    kind: Literal["ordinary", "options", "restricted_stock", "employee_awards", "convertibles"]
    shares: Fact
    method: Literal["gross", "treasury_stock", "if_converted"]
    exercise_price: Fact | None = None
    basis: Text

    @model_validator(mode="after")
    def compatible(self):
        if self.kind == "options" and self.method != "treasury_stock":
            raise ValueError("options require treasury_stock method and exercise price")
        if self.kind == "convertibles" and self.method != "if_converted":
            raise ValueError("convertibles require if_converted method")
        if self.kind not in ("options", "convertibles") and self.method != "gross":
            raise ValueError("ordinary/restricted/employee shares require gross method")
        if self.method == "treasury_stock" and self.exercise_price is None:
            raise ValueError("treasury stock method requires exercise price")
        if self.method != "treasury_stock" and self.exercise_price is not None:
            raise ValueError("exercise price applies only to treasury stock method")
        _value(self.shares, "shares", nonnegative=True)
        _value(self.exercise_price, "currency/share", nonnegative=True)
        return self


def equity_value(offer_price: Fact, components: list[ShareComponent], *,
                 share_basis: str, reported_equity_value: Fact | None = None) -> dict:
    """Options contribute net incremental shares; convertibles need an EV debt adjustment."""
    if not share_basis.strip():
        raise ValueError("share basis must state scope and non-overlap")
    ids = [c.component_id for c in components]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate share components")
    price = _value(offer_price, "currency/share", nonnegative=True)
    _value(reported_equity_value, "currency", nonnegative=True)
    _currency(offer_price, reported_equity_value)
    bridge, warnings = [], []
    total = D(0) if components else None
    for component in components:
        shares = _value(component.shares, "shares", nonnegative=True)
        incremental = shares
        if component.method == "treasury_stock":
            strike = _value(component.exercise_price, "currency/share", nonnegative=True)
            _currency(offer_price, component.exercise_price)
            if price is None or strike is None or shares is None:
                incremental = None
            elif price == 0:
                incremental = D(0)
            else:
                incremental = shares * max(D(0), D(1) - strike / price)
        if component.kind == "convertibles":
            warnings.append("If-converted shares included: remove the converted liability from EV net debt.")
        bridge.append({"component": component, "incremental_shares": incremental})
        total = None if total is None or incremental is None else total + incremental
    value = None if price is None or total is None else price * total
    calc = _result(value, "currency", "Offer price × fully diluted shares", share_basis,
                   {"offer_price": offer_price, "components": components, "bridge": bridge,
                    "fully_diluted_shares": total}, warnings=warnings)
    return {"reported_equity_value": reported_equity_value, "calculated_equity_value": calc,
            "fully_diluted_shares": total, "bridge": bridge}


class EVAdjustment(Model):
    adjustment_id: Text
    kind: Literal["net_debt", "preferred_stock", "minority_interest", "non_operating_investments", "other"]
    amount: Fact
    sign: Literal[1, -1]
    basis: Text

    @model_validator(mode="after")
    def signs(self):
        if self.kind != "other" and self.sign != (-1 if self.kind == "non_operating_investments" else 1):
            raise ValueError("incorrect sign for EV adjustment kind")
        _value(self.amount, "currency", nonnegative=self.kind not in ("net_debt", "other"))
        if self.kind != "other":
            _snapshot(self.amount)
        return self


def enterprise_value(equity: Fact, adjustments: list[EVAdjustment], *, bridge_basis: str,
                     reported_enterprise_value: Fact | None = None,
                     preferred_ev_basis: Literal["reported", "calculated"] = "calculated",
                     snapshot_alignment_basis: str | None = None) -> dict:
    if preferred_ev_basis not in ("reported", "calculated"):
        raise ValueError("preferred_ev_basis must be reported or calculated")
    if not bridge_basis.strip():
        raise ValueError("explicit EV bridge basis required, including excluded adjustments")
    ids = [a.adjustment_id for a in adjustments]
    kinds = [a.kind for a in adjustments if a.kind != "other"]
    if len(ids) != len(set(ids)) or len(kinds) != len(set(kinds)):
        raise ValueError("duplicate EV adjustment; consolidate explicitly to prevent double counting")
    _currency(equity, reported_enterprise_value, *(a.amount for a in adjustments))
    value = _value(equity, "currency", nonnegative=True)
    reported = _value(reported_enterprise_value, "currency")
    qualifications = _snapshot_alignment([a.amount for a in adjustments if a.kind != "other"], snapshot_alignment_basis)
    bridge = []
    for adjustment in adjustments:
        amount = _value(adjustment.amount, "currency", nonnegative=adjustment.kind not in ("net_debt", "other"))
        signed = None if amount is None else amount * adjustment.sign
        bridge.append({"adjustment": adjustment, "signed_amount": signed})
        value = None if value is None or signed is None else value + signed
    calc = _result(value, "currency", "Equity Value + explicit signed EV adjustments", bridge_basis,
                   {"equity_value": equity, "adjustments": adjustments, "bridge": bridge,
                    "snapshot_alignment_basis": snapshot_alignment_basis}, qualifications=qualifications)
    preferred = reported if preferred_ev_basis == "reported" else value
    difference = None if reported is None or value is None else value - reported
    relative = None if difference is None or reported is None or reported == 0 else difference / abs(reported)
    return {"reported_enterprise_value": reported_enterprise_value, "calculated_enterprise_value": calc,
            "preferred_enterprise_value": preferred, "preferred_ev_basis": preferred_ev_basis,
            "reconciliation": {"calculated_minus_reported": difference, "relative_difference": relative},
            "bridge": bridge}


def multiple(metric: str, numerator: Fact, denominator: Fact) -> Result:
    """Caller must supply the named metric; free-text definitions are not inferred."""
    expected = {"ev_revenue": "revenue", "ev_ebitda": "ebitda", "ev_ebit": "ebit",
                "equity_net_income": "net_income"}
    if metric not in expected:
        raise ValueError("unsupported valuation multiple")
    _currency(numerator, denominator)
    num, den = _value(numerator, "currency"), _value(denominator, "currency")
    if denominator.period is None or denominator.period.basis not in ("FY", "LTM"):
        raise ValueError("valuation denominator must have an explicit FY or LTM financial period")
    _annual(denominator)
    warnings = []
    value = None
    if num is None or den is None:
        warnings.append("Missing numerator or denominator.")
    elif den <= 0:
        warnings.append("Analytically non-meaningful: denominator is zero or negative.")
    elif num < 0:
        warnings.append("Analytically non-meaningful: valuation numerator is negative.")
    else:
        value = num / den
    return _result(value, "ratio", metric.replace("_", " / ", 1),
                   f"{denominator.period.basis}; {denominator.definition}",
                   {"numerator": numerator, "denominator": denominator}, warnings=warnings,
                   period=denominator.period)


def premium(offer_price: Fact, reference_price: Fact, *, reference_date: date | None,
            reference_basis: str | None, offer_stage: Literal["initial", "revised", "final"] = "initial") -> Result:
    if reference_date is None or not reference_basis or not reference_basis.strip():
        raise ValueError("manually selected reference date and basis are required")
    if reference_price.as_of is not None and reference_price.as_of != reference_date:
        raise ValueError("reference price date disagrees with selected date")
    if offer_stage not in ("initial", "revised", "final"):
        raise ValueError("invalid offer stage")
    _currency(offer_price, reference_price)
    offer = _value(offer_price, "currency/share", nonnegative=True)
    ref = _value(reference_price, "currency/share", nonnegative=True)
    if ref == 0:
        raise ValueError("reference price must be greater than zero")
    value = None if offer is None or ref is None else offer / ref - 1
    return _result(value, "fraction", "Offer price / Reference price - 1",
                   f"{offer_stage} offer; {reference_basis}",
                   {"offer_price": offer_price, "reference_price": reference_price,
                    "reference_date": reference_date, "reference_basis": reference_basis})


def consideration(*, cash: Fact, exchange_ratio: Fact, bidder_price: Fact | None,
                  bidder_reference_date: date | None, other: Fact,
                  structure: Literal["fixed", "floating", "collared"], reference_basis: str) -> Result:
    if structure not in ("fixed", "floating", "collared"):
        raise ValueError("unsupported consideration structure")
    c, ratio, o = (_value(cash, "currency/share", nonnegative=True),
                   _value(exchange_ratio, "ratio", nonnegative=True),
                   _value(other, "currency/share", nonnegative=True))
    b = _value(bidder_price, "currency/share", nonnegative=True)
    _currency(cash, bidder_price, other)
    if ratio != 0 and (bidder_reference_date is None or not reference_basis.strip()):
        raise ValueError("share consideration requires an explicit bidder price reference date and basis")
    if bidder_price is not None and bidder_price.as_of not in (None, bidder_reference_date):
        raise ValueError("bidder reference date mismatch")
    if structure != "fixed" and not reference_basis.strip():
        raise ValueError("floating/collared terms require an explicit reference basis")
    share = D(0) if ratio == 0 else None if ratio is None or b is None else ratio * b
    value = None if c is None or share is None or o is None else c + share + o
    warnings = ("Reference scenario only; floating/collared terms are not a fixed entitlement.",) if structure != "fixed" else ()
    return _result(value, "currency/share", "Cash + Exchange ratio × Bidder reference price + Eligible other",
                   reference_basis, {"cash": cash, "exchange_ratio": exchange_ratio, "bidder_price": bidder_price,
                                     "bidder_reference_date": bidder_reference_date, "other": other,
                                     "share_component": share, "structure": structure},
                   warnings=warnings, illustrative=structure != "fixed")


class Synergy(Model):
    synergy_id: Text
    kind: Literal["cost", "revenue", "capex", "financial", "implementation_cost"]
    amount: Fact
    eligible: bool
    realisation_months: int | None = None
    revenue_margin: Fact | None = None
    basis: Text

    @model_validator(mode="after")
    def valid(self):
        if self.realisation_months is not None and self.realisation_months < 0:
            raise ValueError("realisation months cannot be negative")
        if self.revenue_margin is not None and self.kind != "revenue":
            raise ValueError("margin assumption only applies to revenue synergies")
        _value(self.amount, "currency", nonnegative=True)
        if self.revenue_margin is not None:
            _rate(self.revenue_margin)
        if self.eligible and self.kind in ("cost", "revenue"):
            _annual_assumption(self.amount)
        return self


def synergy_analysis(synergies: list[Synergy], ev: Fact, target_ebitda: Fact) -> dict:
    ids = [s.synergy_id for s in synergies]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate synergy ID")
    _currency(ev, target_ebitda, *(s.amount for s in synergies))
    e, t = _value(ev, "currency"), _value(target_ebitda, "currency")
    if target_ebitda.period is None or target_ebitda.period.basis not in ("FY", "LTM"):
        raise ValueError("target EBITDA requires FY/LTM period")
    _annual(target_ebitda)
    cost: Decimal | None = D(0)
    revenue_ebitda: Decimal | None = D(0)
    warnings = ["Illustrative annual run-rate case, not realised earnings; implementation costs excluded from recurring EBITDA."]
    for s in synergies:
        amount = _value(s.amount, "currency", nonnegative=True)
        if s.kind in ("cost", "revenue") and s.eligible:
            _annual_assumption(s.amount)
        if s.kind == "cost" and s.eligible:
            cost = None if amount is None or cost is None else cost + amount
        if s.kind == "revenue" and s.eligible:
            if s.revenue_margin is None:
                warnings.append(f"Revenue synergy {s.synergy_id} not converted into EBITDA: no margin assumption.")
            else:
                margin = _rate(s.revenue_margin)
                revenue_ebitda = None if amount is None or margin is None or revenue_ebitda is None else revenue_ebitda + amount * margin
    inputs = {"synergies": synergies, "ev": ev, "target_ebitda": target_ebitda,
              "eligible_cost_synergies": cost}
    def ratio(numerator, denominator, formula):
        notes = list(warnings)
        value = None
        if numerator is None or denominator is None:
            notes.append("Missing numerator or denominator; ratio unavailable.")
        elif denominator <= 0:
            notes.append("Analytically non-meaningful: denominator is zero or negative.")
        elif numerator < 0:
            notes.append("Analytically non-meaningful: valuation numerator is negative.")
        else:
            value = numerator / denominator
        return _result(value, "ratio", formula, "Illustrative annual run-rate cost synergies", inputs,
                       warnings=notes, period=target_ebitda.period, illustrative=True)
    adjusted = None if cost is None or t is None else t + cost
    return {"eligible_cost_synergies": cost, "explicit_margin_revenue_ebitda": revenue_ebitda,
            "cost_synergy_ev": ratio(cost, e, "Eligible cost synergy / EV"),
            "cost_synergy_ebitda": ratio(cost, t, "Eligible cost synergy / Target EBITDA"),
            "synergy_adjusted_multiple": ratio(e, adjusted, "EV / (Target EBITDA + Eligible Cost Synergies)")}


class Adjustment(Model):
    adjustment_id: Text
    amount: Fact
    basis: Text


def _sum_known(values: list[Decimal | None]) -> Decimal | None:
    """Sum established components; one unknown makes the bridge unavailable."""
    total = D(0)
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _adjustments(items: list[Adjustment]) -> Decimal | None:
    if len({a.adjustment_id for a in items}) != len(items):
        raise ValueError("duplicate adjustment ID")
    values = [_value(a.amount, "currency") for a in items]
    return _sum_known(values)


def _comparable(a: Fact, b: Fact):
    if a.period is None or b.period is None or a.period != b.period:
        raise ValueError("buyer and target earnings require matching financial periods and bases")
    _annual(a)
    _annual(b)
    if a.period.basis not in ("FY", "LTM") or a.definition != b.definition:
        raise ValueError("buyer and target earnings require comparable FY/LTM definitions")


def leverage(*, buyer_net_debt: Fact, target_net_debt: Fact, cash_consideration: Fact,
             fees: Fact, new_equity_proceeds: Fact, disposal_proceeds: Fact,
             buyer_ebitda: Fact, target_ebitda: Fact, eligible_cost_synergy: Fact,
             adjustments: list[Adjustment], basis: str, snapshot_alignment_basis: str | None = None) -> dict:
    """Cash use increases net debt regardless of whether financed from cash or debt.

    Do not add new borrowing again: doing so double counts acquisition funding.
    Adjustments are signed net-debt changes, including explicit refinancing effects.
    """
    inputs = dict(buyer_net_debt=buyer_net_debt, target_net_debt=target_net_debt,
                  cash_consideration=cash_consideration, fees=fees, new_equity_proceeds=new_equity_proceeds,
                  disposal_proceeds=disposal_proceeds, buyer_ebitda=buyer_ebitda,
                  target_ebitda=target_ebitda, eligible_cost_synergy=eligible_cost_synergy,
                  adjustments=adjustments, snapshot_alignment_basis=snapshot_alignment_basis)
    _currency(*(v for v in inputs.values() if isinstance(v, Fact)), *(a.amount for a in adjustments))
    _comparable(buyer_ebitda, target_ebitda)
    _annual_assumption(eligible_cost_synergy)
    qualifications = _snapshot_alignment([buyer_net_debt, target_net_debt], snapshot_alignment_basis)
    if not basis.strip():
        raise ValueError("explicit funding and balance-sheet bridge basis required")
    v = {k: _value(f, "currency", nonnegative=k in ("cash_consideration", "fees", "new_equity_proceeds", "disposal_proceeds", "eligible_cost_synergy"))
         for k, f in inputs.items() if isinstance(f, Fact)}
    adj = _adjustments(adjustments)
    components = {"buyer_net_debt": v["buyer_net_debt"], "target_net_debt": v["target_net_debt"],
                  "cash_consideration": v["cash_consideration"], "fees": v["fees"],
                  "new_equity_proceeds": None if v["new_equity_proceeds"] is None else -v["new_equity_proceeds"],
                  "disposal_proceeds": None if v["disposal_proceeds"] is None else -v["disposal_proceeds"],
                  "transaction_adjustments": adj}
    debt = _sum_known(list(components.values()))
    b, t, s = v["buyer_ebitda"], v["target_ebitda"], v["eligible_cost_synergy"]
    earnings = None if b is None or t is None else b + t
    after = None if earnings is None or s is None else earnings + s
    def out(value, unit, formula, illustrative=False, warnings=()):
        return _result(value, unit, formula, basis, inputs | {"bridge": components},
                       period=buyer_ebitda.period, illustrative=illustrative, warnings=warnings, qualifications=qualifications)
    def ratio(n, d, formula, illustrative=False):
        notes = ()
        if n is None or d is None:
            notes = ("Missing net debt or EBITDA; leverage unavailable.",)
        elif d <= 0:
            notes = ("Analytically non-meaningful: EBITDA denominator is zero or negative.",)
        return out(None if notes else n/d, "ratio", formula, illustrative, notes)
    return {"buyer_standalone_leverage": ratio(v["buyer_net_debt"], b, "Buyer net debt / EBITDA"),
            "pro_forma_net_debt": out(debt, "currency", "Buyer ND + Target ND + Cash + Fees - New equity - Disposals + Adjustments"),
            "pro_forma_ebitda_before_synergy": out(earnings, "currency", "Buyer EBITDA + Target EBITDA"),
            "pro_forma_ebitda_after_synergy": out(after, "currency", "Buyer EBITDA + Target EBITDA + Eligible cost synergies", True),
            "leverage_before_synergy": ratio(debt, earnings, "Pro-forma net debt / EBITDA before synergy"),
            "leverage_after_synergy": ratio(debt, after, "Pro-forma net debt / EBITDA after synergy", True)}


def accretion(*, buyer_net_income: Fact, buyer_diluted_shares: Fact, target_net_income: Fact,
              eligible_pretax_synergies: Fact, tax_rate: Fact, new_debt: Fact,
              incremental_interest_rate: Fact, new_shares_issued: Fact,
              recurring_adjustments: list[Adjustment], basis: str) -> dict:
    """Simplified full-year EPS model. Recurring adjustments are explicitly AFTER TAX.

    Buyer shares must be the diluted weighted-average denominator for standalone
    EPS; new shares represent full-year incremental dilution. Detailed purchase
    accounting is excluded unless supplied as signed after-tax adjustments.
    """
    inputs = dict(buyer_net_income=buyer_net_income, buyer_diluted_shares=buyer_diluted_shares,
                  target_net_income=target_net_income, eligible_pretax_synergies=eligible_pretax_synergies,
                  tax_rate=tax_rate, new_debt=new_debt, incremental_interest_rate=incremental_interest_rate,
                  new_shares_issued=new_shares_issued, recurring_adjustments=recurring_adjustments)
    _currency(*(f for f in inputs.values() if isinstance(f, Fact)), *(a.amount for a in recurring_adjustments))
    _comparable(buyer_net_income, target_net_income)
    _annual_assumption(eligible_pretax_synergies)
    for recurring in recurring_adjustments:
        _annual_assumption(recurring.amount, earnings=buyer_net_income)
    if not basis.strip():
        raise ValueError("explicit full-year earnings, funding and after-tax adjustments basis required")
    ni = _value(buyer_net_income, "currency")
    target = _value(target_net_income, "currency")
    shares = _value(buyer_diluted_shares, "shares", nonnegative=True)
    new_shares = _value(new_shares_issued, "shares", nonnegative=True)
    synergy = _value(eligible_pretax_synergies, "currency", nonnegative=True)
    debt = _value(new_debt, "currency", nonnegative=True)
    tax, rate = _rate(tax_rate), _rate(incremental_interest_rate)
    if shares == 0:
        raise ValueError("buyer diluted shares must be positive")
    adjustment = _adjustments(recurring_adjustments)
    interest = None if debt is None or rate is None else debt * rate
    after_interest = None if interest is None or tax is None else interest * (1-tax)
    after_synergy = None if synergy is None or tax is None else synergy * (1-tax)
    standalone = None if ni is None or shares is None else ni/shares
    pf_shares = None if shares is None or new_shares is None else shares + new_shares
    pf_ni = None if ni is None or target is None or after_interest is None or after_synergy is None or adjustment is None else ni + target - after_interest + after_synergy + adjustment
    pf_eps = None if pf_ni is None or pf_shares is None else pf_ni/pf_shares
    pct = None if standalone is None or standalone <= 0 or pf_eps is None else pf_eps/standalone-1
    warnings = ["SIMPLIFIED full-year illustrative EPS model; excludes detailed purchase-price accounting unless separately supplied as after-tax recurring adjustments.",
                "Assumes tax deductibility of interest and full-year synergies; cash interest foregone, refinancing, amortisation and other effects require explicit adjustments."]
    if standalone is not None and standalone <= 0:
        warnings.append("Accretion/dilution percentage is non-meaningful for non-positive standalone EPS.")
    values = {"buyer_standalone_eps": (standalone, "currency/share", "Buyer net income / Buyer diluted shares"),
              "incremental_interest_expense": (interest, "currency", "New debt × Incremental annual interest rate"),
              "after_tax_interest": (after_interest, "currency", "Incremental interest × (1 - Tax rate)"),
              "after_tax_synergies": (after_synergy, "currency", "Eligible pretax synergies × (1 - Tax rate)"),
              "pro_forma_net_income": (pf_ni, "currency", "Buyer NI + Target NI - After-tax interest + After-tax synergies + After-tax adjustments"),
              "pro_forma_diluted_shares": (pf_shares, "shares", "Buyer diluted shares + New shares"),
              "pro_forma_eps": (pf_eps, "currency/share", "Pro-forma NI / Pro-forma diluted shares"),
              "accretion_dilution": (pct, "fraction", "Pro-forma EPS / Standalone EPS - 1")}
    return {key: _result(v, unit, formula, basis, inputs, warnings=warnings,
                         period=buyer_net_income.period, illustrative=True)
            for key, (v, unit, formula) in values.items()}
