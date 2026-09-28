"""DealLens public dashboard. Run: streamlit run dashboard/app.py."""
from __future__ import annotations

import html
from decimal import Decimal
from typing import cast

import streamlit as st

from deallens.analytics import (Dimension, category_counts, data_quality_summary,
                                metric_summary, observations, portfolio_summary)
from deallens.models import Fact, Result
from deallens.qa import evidence_audit, qa_deal
from deallens.research import ResearchDeal, analyse
from dashboard.data import PublicDataset, load_public_dataset
from dashboard.presentation import compact_number, matching_deals, multiple, observation_for, percent

PAGES = (
    "Overview", "Deal Explorer", "Valuation", "Premiums", "Financing & Leverage",
    "Synergies", "Deal Outcomes", "Deal Detail", "Methodology", "Data Quality & Sources",
)
METRICS = {"EV / EBITDA": "ev_ebitda", "EV / revenue": "ev_revenue",
           "Reported enterprise value": "disclosed_ev", "Offer premium": "premium"}
st.set_page_config(page_title="DealLens | Transaction research", layout="wide",
                   initial_sidebar_state="expanded")


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _style() -> None:
    st.markdown("""<style>
    :root { color-scheme: light; }
    [data-testid="stAppViewContainer"] { background: #f6f7f8; color: #182537; }
    [data-testid="stSidebar"] { background: #111e30; border-right: 1px solid #26384b; }
    [data-testid="stSidebar"] * { color: #e6edf2 !important; }
    [data-testid="stSidebar"] [role="radiogroup"] label { padding: .22rem .45rem; border-radius: 7px; }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #21364c; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #b9c7d2; }
    .block-container { max-width: 1420px; padding: 2.8rem 3.5rem 5rem; }
    h1, h2, h3 { color: #15273b !important; letter-spacing: -.035em; }
    h1 { font-size: 2.25rem !important; font-weight: 680 !important; }
    h2 { font-size: 1.48rem !important; padding-top: .4rem; }
    h3 { font-size: 1.1rem !important; }
    .eyebrow { font-size: .72rem; letter-spacing: .15em; font-weight: 750; color: #52738a;
               text-transform: uppercase; margin-bottom: .7rem; }
    .lead { color: #617183; font-size: 1.04rem; line-height: 1.65; max-width: 850px; }
    .wordmark { font-size: 1.62rem; font-weight: 750; letter-spacing: -.045em;
                color: #f2f6f8; padding: .35rem .4rem 0; }
    .wordmark span { color: #76c4bb; }
    .side-sub { color: #9bb0c0; font-size: .78rem; padding: 0 .4rem 1.8rem; }
    .side-foot { color: #9bb0c0; font-size: .75rem; line-height: 1.6;
                 border-top: 1px solid #344657; padding: 1.2rem .4rem; margin-top: 1.8rem; }
    .hero { border: 1px solid #dce4e9; background: linear-gradient(120deg,#ffffff 10%,#eaf3f2 100%);
            border-radius: 14px; padding: 2.1rem 2.25rem 1.9rem; margin: .3rem 0 1.6rem; }
    .hero-title { color: #14283a; font-size: 2.25rem; font-weight: 720; letter-spacing: -.05em; }
    .hero-copy { color: #5b6e7d; font-size: 1rem; max-width: 740px; margin-top: .55rem; line-height: 1.6; }
    .kpi { background: #fff; border: 1px solid #dce4e9; border-radius: 11px;
           min-height: 125px; padding: 1.25rem 1.35rem; margin-bottom: .7rem; }
    .kpi-label { color: #607383; font-size: .78rem; font-weight: 640; letter-spacing: .01em; }
    .kpi-value { color: #172d3f; font-size: 1.85rem; font-weight: 720; letter-spacing: -.04em;
                 margin-top: .5rem; line-height: 1.12; }
    .kpi-note { color: #7e8d9a; font-size: .73rem; margin-top: .5rem; }
    .quiet-panel { background: #fff; border: 1px solid #dce4e9; border-radius: 11px;
                   padding: 1.45rem 1.6rem; margin: .8rem 0 1.2rem; }
    .quiet-title { color: #183148; font-weight: 700; font-size: 1.05rem; margin-bottom: .55rem; }
    .quiet-copy { color: #627487; font-size: .91rem; line-height: 1.6; }
    .meta { color: #667b89; font-size: .79rem; line-height: 1.5; }
    .rule { height: 1px; background: #dbe3e8; margin: 1.3rem 0 1.7rem; }
    [data-testid="stDataFrame"] { border: 1px solid #dce4e9; border-radius: 10px; }
    [data-testid="stMetric"] { background: #fff; border: 1px solid #dce4e9;
                               border-radius: 10px; padding: 1rem 1.2rem; }
    @media (max-width: 900px) { .block-container { padding: 1.4rem 1rem 3rem; }
                               .hero { padding: 1.35rem; } .hero-title { font-size: 1.8rem; } }
    </style>""", unsafe_allow_html=True)


def _header(title: str, subtitle: str, eyebrow: str = "TRANSACTION RESEARCH") -> None:
    st.markdown(f'<div class="eyebrow">{_esc(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="lead">{_esc(subtitle)}</div><div class="rule"></div>',
                unsafe_allow_html=True)


def _panel(title: str, copy: str) -> None:
    st.markdown(f'<div class="quiet-panel"><div class="quiet-title">{_esc(title)}</div>'
                f'<div class="quiet-copy">{_esc(copy)}</div></div>', unsafe_allow_html=True)


def _no_data(subject: str = "analysis") -> None:
    _panel("No eligible observations", f"There is no published, QA-qualified data for {subject}. "
           "An unavailable metric is not zero. Once a manually verified transaction is included "
           "in an audited public release, this view will populate automatically.")


def _kpi(label: str, value: str, note: str) -> None:
    st.markdown(f'<div class="kpi"><div class="kpi-label">{_esc(label)}</div>'
                f'<div class="kpi-value">{_esc(value)}</div><div class="kpi-note">{_esc(note)}</div></div>',
                unsafe_allow_html=True)


def _value(result: Result | Fact | None) -> str:
    if result is None:
        return "Unavailable"
    amount = result.amount if isinstance(result, Fact) else result.result
    if amount is None:
        return "Unavailable"
    if result.unit == "fraction":
        return percent(amount)
    if result.unit == "ratio":
        return multiple(amount)
    if result.unit in ("currency", "currency/share"):
        suffix = " / share" if result.unit == "currency/share" else ""
        return compact_number(amount, currency=result.currency) + suffix
    return f"{amount:,.2f} {result.unit}"


def _select(label: str, choices: list, *, key: str):
    return st.selectbox(label, [None, *choices], format_func=lambda x: "All" if x is None else str(x), key=key)


def _unique(deals: tuple[ResearchDeal, ...], extract) -> list:
    return sorted({value for d in deals if (value := extract(d)) is not None})


def _basis_options(deals: tuple[ResearchDeal, ...], metric: str) -> list[str]:
    return sorted({item.basis for deal in deals for item in observations(deal, metric)})


def _open_detail(deal_id: str) -> None:
    st.session_state["focus_deal"] = deal_id
    st.session_state["page"] = "Deal Detail"


def _cohort_selector(deals: tuple[ResearchDeal, ...], metric: str, *, key: str):
    report = metric_summary(deals, metric)
    cohorts = report["cohorts"]
    if not cohorts:
        _no_data(metric.replace("_", " / "))
        return None
    selected = st.selectbox("Comparable metric basis", range(len(cohorts)), key=key,
                            format_func=lambda i: f"{cohorts[i]['currency'] or cohorts[i]['unit']} "
                            f"· n={cohorts[i]['n']} · {cohorts[i]['basis']}")
    return cohorts[selected]


def _distribution(cohort: dict) -> None:
    stats = cohort["statistics"]
    formatter = percent if cohort["unit"] == "fraction" else (
        multiple if cohort["unit"] == "ratio" else
        lambda x: compact_number(x, currency=cohort["currency"]))
    cols = st.columns(4)
    for col, (label, value) in zip(cols, (("25th percentile", stats.q25),
                                         ("Median", stats.median), ("75th percentile", stats.q75),
                                         ("Sample", stats.n)), strict=True):
        col.metric(label, f"n={value}" if label == "Sample" else formatter(value))
    unit_label = (f"percentage of referenced share price (underlying currency {cohort['currency']})"
                  if cohort["unit"] == "fraction" else
                  f"{cohort['unit']} {cohort['currency'] or ''}".strip())
    st.caption(f"Unit: {unit_label} | n={cohort['n']} | Basis: {cohort['basis']}. "
               "Quartiles use linear interpolation; no FX conversion.")
    rows = [{"Deal": item.deal_id, "Value": float(item.value)} for item in cohort["observations"]]
    if len(rows) > 1:
        st.bar_chart(rows, x="Deal", y="Value", color="#287b78", use_container_width=True)
    st.dataframe([{"Deal ID": item.deal_id, "Value": formatter(item.value), "Basis": item.basis}
                  for item in cohort["observations"]], hide_index=True, use_container_width=True)


def _overview(data: PublicDataset) -> None:
    st.markdown('<div class="hero"><div class="eyebrow">SOURCE-AUDITABLE M&A RESEARCH</div>'
                '<div class="hero-title">Transactions, with the evidence in view.</div>'
                '<div class="hero-copy">Explore disclosed terms, valuation and deal outcomes. '
                'Every analytical figure comes from a verified public record and retains its source and basis.</div>'
                '</div>', unsafe_allow_html=True)
    summary = portfolio_summary(data.deals)
    ev = summary["disclosed_ev"]["cohorts"]
    aggregate = compact_number(ev[0]["sum"], currency=ev[0]["currency"]) if len(ev) == 1 else "Unavailable"
    ev_note = f"n={ev[0]['n']}; {ev[0]['currency']} only" if len(ev) == 1 else (
        "Multiple currencies or bases; no FX mixing" if ev else "n=0; not reported")
    ebitda = summary["ev_ebitda"]["cohorts"]
    premium = summary["premium"]["cohorts"]
    for labels in (
        (("Deals tracked", str(summary["deal_count"]["value"]), "VERIFIED and QA-publishable"),
         ("Aggregate disclosed EV", aggregate, ev_note),
         ("Median EV / EBITDA", multiple(ebitda[0]["statistics"].median) if len(ebitda) == 1 else "Unavailable",
          f"n={ebitda[0]['n']}; one basis" if len(ebitda) == 1 else "Select a comparable cohort in Valuation"),
         ("Median offer premium", percent(premium[0]["statistics"].median) if len(premium) == 1 else "Unavailable",
          f"n={premium[0]['n']}; one basis" if len(premium) == 1 else "Select a reference basis in Premiums")),
        (("Cross-border share", percent(summary["cross_border_share"]["value"]),
          f"n={summary['cross_border_share']['n']} classified"),
         ("Completion rate", percent(summary["completion_rate"]["value"]),
          f"n={summary['completion_rate']['n']} tracked"),
         ("Median completion time", (f"{summary['completion_days']['statistics'].median:,.0f} days"
                                      if summary["completion_days"]["n"] else "Unavailable"),
          f"n={summary['completion_days']['n']} completed with dates"))):
        cols = st.columns(len(labels), gap="medium")
        for col, (label, value, note) in zip(cols, labels, strict=True):
            with col:
                _kpi(label, value, note)
    st.markdown("### Coverage at a glance")
    if not data.deals:
        _panel("Research foundation ready", "No transactions are published yet. The dashboard is connected "
               "to the public-release audit and will not promote a draft to a verified observation. "
               "The first case study is still subject to source and manual review.")
    else:
        col_a, col_b = st.columns(2)
        for col, dim, title in ((col_a, "sector", "Deals by sector"), (col_b, "status", "Deal outcomes")):
            with col:
                st.markdown(f"#### {title}")
                counts = category_counts(data.deals, cast(Dimension, dim))
                st.bar_chart([{"Category": c["category"], "Deals": c["n"]}
                              for c in counts["categories"]], x="Category", y="Deals", color="#287b78")
                st.caption(f"Unit: deals | n={counts['n']} | VERIFIED and QA-publishable only")
    _panel("Reading this dashboard", "A blank value means the underlying figure was not established or "
           "is analytically unsuitable. Medians use a single disclosed basis; premiums and FY/LTM multiples "
           "are never pooled silently. This is research, not investment advice.")


def _explorer(data: PublicDataset) -> None:
    _header("Deal Explorer", "Screen published transactions. Filters narrow candidates; they do not decide comparability.")
    if not data.deals:
        _no_data("deal screening")
        return
    a, b, c, fourth = st.columns(4)
    with a:
        sector = _select("Sector", _unique(data.deals, lambda x: x.profile.sector), key="ex_sector")
        buyer_type = _select("Buyer type", _unique(data.deals, lambda x: x.profile.buyer_type), key="ex_buyer")
    with b:
        country = _select("Target country", _unique(data.deals, lambda x: x.target.country), key="ex_country")
        status = _select("Status", _unique(data.deals, lambda x: x.identity.transaction_status), key="ex_status")
    with c:
        year = _select("Announcement year", _unique(data.deals, lambda x: x.identity.announcement_date.year), key="ex_year")
        consideration = _select("Consideration", _unique(data.deals, lambda x: x.profile.consideration_type), key="ex_consideration")
    with fourth:
        from deallens.analytics import dimension_value
        border = _select("Border", _unique(data.deals, lambda x: dimension_value(x, "cross_border")), key="ex_border")
        currency = _select("Reported EV currency", _unique(data.deals, lambda x: (
            x.transaction_valuation.reported_enterprise_value.currency
            if x.transaction_valuation.reported_enterprise_value else None)), key="ex_currency")
    with st.expander("Valuation and premium ranges", expanded=False):
        st.caption("Range filters use base currency units. Choose an exact basis before filtering a multiple or premium.")
        a, b = st.columns(2)
        with a:
            min_ev = st.number_input("Minimum reported EV", min_value=0.0, value=None, key="ex_min_ev")
            max_ev = st.number_input("Maximum reported EV", min_value=0.0, value=None, key="ex_max_ev")
            bases = _basis_options(data.deals, "ev_ebitda")
            mult_basis = _select("EV / EBITDA basis", bases, key="ex_mult_basis")
            min_mult = st.number_input("Minimum EV / EBITDA (x)", min_value=0.0, value=None, key="ex_min_mult")
            max_mult = st.number_input("Maximum EV / EBITDA (x)", min_value=0.0, value=None, key="ex_max_mult")
        with b:
            premium_bases = _basis_options(data.deals, "premium")
            premium_basis = _select("Premium reference basis", premium_bases, key="ex_premium_basis")
            min_premium = st.number_input("Minimum premium (%)", value=None, key="ex_min_prem")
            max_premium = st.number_input("Maximum premium (%)", value=None, key="ex_max_prem")
        if ((min_mult is not None or max_mult is not None) and mult_basis is None) or (
                (min_premium is not None or max_premium is not None) and premium_basis is None) or (
                (min_ev is not None or max_ev is not None) and currency is None):
            st.warning("Choose the corresponding exact basis or EV currency to apply a numerical range.")
            return
        if any(lo is not None and hi is not None and lo > hi for lo, hi in (
                (min_ev, max_ev), (min_mult, max_mult), (min_premium, max_premium))):
            st.warning("A minimum cannot exceed its maximum.")
            return
    deals = matching_deals(data.deals, sector=sector, country=country, year=year,
                           buyer_type=buyer_type, status=status, consideration=consideration,
                           border=border, ev_currency=currency,
                           minimum_ev=Decimal(str(min_ev)) if min_ev is not None else None,
                           maximum_ev=Decimal(str(max_ev)) if max_ev is not None else None,
                           minimum_multiple=Decimal(str(min_mult)) if min_mult is not None else None,
                           maximum_multiple=Decimal(str(max_mult)) if max_mult is not None else None,
                           multiple_basis=mult_basis,
                           minimum_premium=Decimal(str(min_premium / 100)) if min_premium is not None else None,
                           maximum_premium=Decimal(str(max_premium / 100)) if max_premium is not None else None,
                           premium_basis=premium_basis)
    st.subheader(f"{len(deals)} matching transactions")
    if not deals:
        _panel("No matches", "Adjust the filters. A missing EV, multiple or premium does not pass a numerical range.")
        return
    rows = []
    for d in deals:
        ev = observation_for(d, "disclosed_ev")
        rows.append({"ID": d.identity.deal_id, "Target": d.target.name, "Bidder": d.bidder.name,
                     "Announced": d.identity.announcement_date.isoformat(), "Sector": d.profile.sector or "Unavailable",
                     "Target country": d.target.country, "Status": d.identity.transaction_status,
                     "Consideration": d.profile.consideration_type or "Unavailable",
                     "Reported EV": compact_number(ev.value, currency=ev.currency) if ev else "Unavailable"})
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption(f"Sample: {len(deals)} of {len(data.deals)} published deals. Reported EV only; no FX conversion.")
    selected = st.selectbox("Select a transaction to inspect", deals, format_func=lambda d: (
        f"{d.identity.deal_id} · {d.target.name}"), key="ex_selected")
    st.button("Open deal detail", type="primary", on_click=_open_detail,
              args=(selected.identity.deal_id,))


def _valuation(data: PublicDataset) -> None:
    _header("Valuation", "Compare only observations with the same currency, financial period and earnings definition.")
    if not data.deals:
        _no_data("valuation")
        return
    metric = st.selectbox("Metric", ["EV / EBITDA", "EV / revenue", "Reported enterprise value"], key="valuation_metric")
    cohort = _cohort_selector(data.deals, METRICS[metric], key="valuation_basis")
    if cohort:
        _distribution(cohort)
        if metric == "Reported enterprise value":
            st.caption("The aggregate is shown only within this exact currency and EV definition: "
                       f"{compact_number(cohort['sum'], currency=cohort['currency'])} (n={cohort['n']}).")
    st.markdown("### Precedent selection")
    _panel("Analyst judgement remains essential", "The distribution above is descriptive, not an automatic "
           "valuation recommendation. Screen for business model, scale, geography, deal timing, financial "
           "definitions and control terms before selecting precedents.")
    from deallens.precedents import selected_statistics
    ids = st.multiselect("Manually select precedent IDs", [d.identity.deal_id for d in data.deals])
    notes = st.text_input("Selection rationale", placeholder="Why these deals are comparable")
    if ids and notes.strip():
        selected = selected_statistics(list(data.deals), ids, selection_notes=notes)
        st.caption(f"Selected sample: n={selected['n']}. Statistics remain separated by exact basis.")
        for title, key in (("EV / revenue", "ev_revenue"), ("EV / EBITDA", "ev_ebitda"),
                           ("Premium", "premium")):
            report = selected["statistics"][key]
            st.write(f"{title}: {len(report['cohorts'])} comparable cohort(s)")
            for item in report["cohorts"]:
                st.caption(f"n={item['n']} | {item['basis']} | median " + (
                    percent(item["statistics"].median) if item["unit"] == "fraction" else
                    multiple(item["statistics"].median)))
    elif ids:
        st.info("Add a selection rationale to inspect the selected precedents.")


def _premiums(data: PublicDataset) -> None:
    _header("Takeover Premiums", "Offer premium is tied to a selected offer and an explicit unaffected-price reference.")
    if not data.deals:
        _no_data("takeover premiums")
        return
    cohort = _cohort_selector(data.deals, "premium", key="premium_basis")
    if cohort:
        _distribution(cohort)
    st.caption("A 1M VWAP, 3M VWAP and unaffected closing price are different reference bases. "
               "Revised offers are not silently combined with initial offers.")


def _financing(data: PublicDataset) -> None:
    _header("Financing & Leverage", "Disclosed funding is separated from illustrative pro-forma leverage.")
    if not data.deals:
        _no_data("financing and leverage")
        return
    records = []
    for d in data.deals:
        terms = d.financing
        calc = analyse(d).get("leverage", {})
        records.append({"Deal": d.identity.deal_id, "Bidder / target": f"{d.bidder.name} / {d.target.name}",
                        "Committed facility": _value(terms.committed_facility), "New debt": _value(terms.new_debt),
                        "Cash consideration": _value(terms.cash_consideration),
                        "Net debt / EBITDA before synergy": _value(calc.get("leverage_before_synergy")),
                        "After synergy, illustrative": _value(calc.get("leverage_after_synergy"))})
    st.dataframe(records, hide_index=True, use_container_width=True)
    st.caption(f"n={len(data.deals)} published deals. Unavailable is not zero; raw amounts use their own currency.")
    for label, key in (("Before synergy", "leverage_before_synergy"),
                       ("After synergy, illustrative", "leverage_after_synergy")):
        st.subheader(label)
        cohort = _cohort_selector(data.deals, key, key=f"fin_{key}")
        if cohort:
            _distribution(cohort)
    st.info("Pro-forma leverage is modelled only where matched earnings periods and explicit funding inputs exist.")


def _synergies(data: PublicDataset) -> None:
    _header("Synergies", "Keep stated run-rate opportunities separate from eligible model inputs and realised results.")
    if not data.deals:
        _no_data("synergy analysis")
        return
    records = []
    for d in data.deals:
        result = analyse(d).get("synergies", {})
        selected_ebitda = d.target_financials.ebitda.selected
        records.append({"Deal": d.identity.deal_id, "Disclosed synergy items": len(d.synergies),
                        "Eligible cost synergies": compact_number(result.get("eligible_cost_synergies"),
                                                                   currency=selected_ebitda.currency if selected_ebitda else None)
                        if result.get("eligible_cost_synergies") is not None else "Unavailable",
                        "Cost synergy / EV": _value(result.get("cost_synergy_ev")),
                        "Synergy-adjusted EV / EBITDA": _value(result.get("synergy_adjusted_multiple"))})
    st.dataframe(records, hide_index=True, use_container_width=True)
    st.caption(f"n={len(data.deals)} published deals. Modelled figures are illustrative, not realised savings.")
    cohort = _cohort_selector(data.deals, "cost_synergy_ev", key="synergy_basis")
    if cohort:
        _distribution(cohort)


def _outcomes(data: PublicDataset) -> None:
    _header("Deal Outcomes", "Track announced, completed, lapsed and withdrawn transactions without treating pending as failed.")
    if not data.deals:
        _no_data("deal outcomes")
        return
    report = category_counts(data.deals, "status")
    st.bar_chart([{"Outcome": item["category"], "Deals": item["n"]}
                  for item in report["categories"]], x="Outcome", y="Deals", color="#287b78")
    st.dataframe([{"Outcome": item["category"], "Deals": item["n"],
                   "Share of sample": percent(Decimal(item["n"]) / report["n"])}
                  for item in report["categories"]], hide_index=True, use_container_width=True)
    summary = portfolio_summary(data.deals)
    st.caption(f"Unit: deals | n={report['n']} | Status recorded in verified public records.")
    a, b = st.columns(2)
    a.metric("Completion rate", percent(summary["completion_rate"]["value"]))
    days = summary["completion_days"]
    b.metric("Median announcement-to-completion", f"{days['statistics'].median:,.0f} days"
             if days["n"] else "Unavailable")
    st.caption(f"Completion rate n={summary['completion_rate']['n']}; timing n={days['n']} "
               "completed deals with both dates. This is a tracked-sample outcome, not a probability forecast.")


def _fact_table(deal: ResearchDeal) -> list[dict]:
    audit = evidence_audit(deal)
    return [{"Field": item["field"], "Value": _value(item["fact"]),
             "Reported / calculated": item["fact"].classification,
             "Definition": item["fact"].definition,
             "Evidence IDs": ", ".join(item["fact"].evidence),
             "Source": "; ".join(f"{r['source'].title} ({r['source'].publication_date}) · "
                                   f"{r['evidence'].section}" for r in item["references"])}
            for item in audit["fields"]]


def _detail(data: PublicDataset) -> None:
    _header("Deal Detail", "Reported terms, calculations, QA and source trail for one published transaction.")
    if not data.deals:
        _no_data("transaction detail")
        return
    lookup = {d.identity.deal_id: d for d in data.deals}
    focus = st.session_state.get("focus_deal")
    index = list(lookup).index(focus) if focus in lookup else 0
    deal_id = st.selectbox("Transaction", list(lookup), index=index, key="detail_selection",
                           format_func=lambda x: f"{x} · {lookup[x].bidder.name} / {lookup[x].target.name}")
    deal = lookup[deal_id]
    st.session_state["focus_deal"] = deal_id
    st.subheader(deal.identity.name)
    st.caption(f"{deal.identity.deal_id} | {deal.identity.announcement_date} | "
               f"{deal.identity.transaction_status} | Public release {data.version}")
    a, b, c, d = st.columns(4)
    for col, label, val in ((a, "Bidder", deal.bidder.name), (b, "Target", deal.target.name),
                            (c, "Sector", deal.profile.sector or "Unavailable"),
                            (d, "Consideration", deal.profile.consideration_type or "Unavailable")):
        col.metric(label, val)
    offer = next((x for x in deal.offer_terms if x.offer_id == deal.selected_offer_id), None)
    calc = analyse(deal)
    st.markdown("### Transaction snapshot")
    a, b, c, d = st.columns(4)
    a.metric("Selected offer", _value(offer.price) if offer else "Unavailable")
    b.metric("Reported equity value", _value(deal.transaction_valuation.reported_equity_value))
    c.metric("Reported enterprise value", _value(deal.transaction_valuation.reported_enterprise_value))
    d.metric("EV / EBITDA", _value(calc.get("ev_ebitda")))
    if offer:
        st.caption(f"Selected {offer.stage} offer dated {offer.date}. Basis: {offer.basis}")
    else:
        st.caption("No selected offer was established.")
    st.markdown("### Offer chronology")
    chronology = [{"Date": deal.identity.announcement_date.isoformat(), "Event": "Formal announcement",
                   "Terms": "Transaction announced"}]
    chronology.extend({"Date": item.date.isoformat(), "Event": f"{item.stage.title()} offer",
                       "Terms": f"{_value(item.price)} · {item.basis}"}
                      for item in deal.offer_terms)
    if deal.identity.completion_date:
        chronology.append({"Date": deal.identity.completion_date.isoformat(), "Event": "Completion",
                           "Terms": "Transaction completed"})
    st.dataframe(sorted(chronology, key=lambda event: event["Date"]),
                 hide_index=True, use_container_width=True)
    st.markdown("### Valuation and premium")
    rows = []
    for label, key in (("Calculated equity value", "equity"), ("Calculated enterprise value", "ev"),
                       ("EV / revenue", "ev_revenue"), ("EV / EBITDA", "ev_ebitda"),
                       ("EV / EBIT", "ev_ebit")):
        value = calc.get(key)
        if key == "equity":
            value = value.get("calculated_equity_value") if value else None
        elif key == "ev":
            value = value.get("calculated_enterprise_value") if value else None
        rows.append({"Metric": label, "Value": _value(value),
                     "Basis": value.basis if isinstance(value, Result) else "Unavailable",
                     "Warnings": "; ".join((*value.warnings, *value.qualifications)) if isinstance(value, Result) else ""})
    for ref in deal.unaffected_price:
        prem = calc.get("premiums", {}).get(ref.reference_id)
        rows.append({"Metric": f"Premium to {ref.reference_basis} ({ref.reference_date})",
                     "Value": _value(prem), "Basis": prem.basis if prem else "Unavailable",
                     "Warnings": "; ".join((*prem.warnings, *prem.qualifications)) if prem else ""})
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.markdown("### Target financials")
    financial_rows = []
    for name in ("revenue", "ebitda", "ebit", "net_income"):
        selected = getattr(deal.target_financials, name).selected
        financial_rows.append({"Metric": name.replace("_", " ").title(), "Selected amount": _value(selected),
                               "Period": (f"{selected.period.basis}: {selected.period.start} to {selected.period.end}"
                                          if selected and selected.period else "Unavailable"),
                               "Definition": selected.definition if selected else "Unavailable"})
    st.dataframe(financial_rows, hide_index=True, use_container_width=True)
    st.markdown("### Financing, synergies and leverage")
    if deal.financing.description and deal.financing.evidence:
        st.write(deal.financing.description)
        st.caption("Financing description evidence: " + ", ".join(deal.financing.evidence))
    else:
        st.caption("Financing narrative unavailable or not tied to a field-level evidence reference.")
    details = []
    for label, value in (("Committed facility", deal.financing.committed_facility),
                         ("New debt", deal.financing.new_debt),
                         ("Cash consideration", deal.financing.cash_consideration),
                         ("Leverage before synergy", calc.get("leverage", {}).get("leverage_before_synergy")),
                         ("Leverage after synergy, illustrative", calc.get("leverage", {}).get("leverage_after_synergy")),
                         ("Synergy-adjusted multiple, illustrative", calc.get("synergies", {}).get("synergy_adjusted_multiple"))):
        details.append({"Metric": label, "Value": _value(value),
                        "Status": value.classification if isinstance(value, Fact) else
                        "CALCULATED" if isinstance(value, Result) else "Unavailable"})
    st.dataframe(details, hide_index=True, use_container_width=True)
    st.markdown("### Source documents")
    for source in deal.sources:
        st.markdown(f"[{source.title}]({source.url})  ")
        st.caption(f"{source.source_type} | Published {source.publication_date} | Source ID {source.source_id}")
    st.markdown("### Field-level evidence")
    st.dataframe(_fact_table(deal), hide_index=True, use_container_width=True)
    st.markdown("### QA and limitations")
    report = qa_deal(deal)
    st.caption("QA-publishable after public release audit. This does not constitute an independent source audit "
               "or an investment recommendation.")
    flagged = [f for f in report["flags"] if f.severity != "INFO"]
    if flagged:
        st.dataframe([{"Severity": f.severity, "Code": f.code, "Field": f.field, "Issue": f.message}
                      for f in flagged], hide_index=True, use_container_width=True)
    else:
        st.success("No non-informational QA flags in this published record.")


def _methodology(data: PublicDataset) -> None:
    _header("Methodology", "Definitions, sample controls and limitations behind each displayed number.")
    st.markdown("""
### Inclusion standard

Only records in an audited public release enter the dashboard. Release construction requires a recorded
manual verification event tied to the exact document and passing QA. The dashboard re-audits the complete
release before display. Neither a draft nor a database import alone can become a published observation.

### Valuation basis

- Equity value is the selected offer price multiplied by the specified share components when those inputs exist.
- Enterprise value uses an explicit equity-to-EV bridge, or a separately disclosed reported EV. These are labelled
  distinctly and never silently substituted.
- EV / revenue and EV / EBITDA use the selected target financial metric and its explicit FY or LTM period.
- Premium compares the selected offer price with one stated unaffected share-price reference and date.
- Pro-forma leverage and synergy-adjusted metrics are illustrative, not forecasts of realised outcomes.

### Statistical controls

Missing is never zero. Ratios with non-positive or incompatible denominators are excluded. Currency, earnings
definition, financial period, offer stage and premium reference basis remain visible and are never silently pooled.
Medians and quartiles describe the available sample, not a population estimate. No currency conversion is inferred.

### Source standard

The detail view exposes source title, publication date, document section and the evidence IDs supporting
numerical observations. Reported, calculated and assumed inputs have different classifications. Released
source URLs are checked for public access shape; the source documents themselves are not redistributed.
""")
    st.caption(f"Displayed release: {data.version or 'none'} | {len(data.deals)} eligible deals. "
               "This is research and education, not investment advice.")


def _quality(data: PublicDataset) -> None:
    _header("Data Quality & Sources", "See what is present, what is missing and how each published fact is traced.")
    report = data_quality_summary(data.deals)
    a, b, c = st.columns(3)
    a.metric("Published records", report["inventory_n"])
    b.metric("QA-eligible records", report["eligible_n"])
    c.metric("Release version", data.version or "Unavailable")
    st.caption("This inventory covers the public release only. Private drafts and reviewer identities are not exported.")
    if not data.deals:
        _no_data("field coverage and sources")
        return
    st.markdown("### Metric availability")
    st.dataframe([{"Metric": name.replace("_", " / "), "Available": item["n"],
                   "Eligible": item["eligible_n"], "Missing / non-meaningful": item["missing_n"]}
                  for name, item in report["availability"].items()], hide_index=True, use_container_width=True)
    st.markdown("### Evidence coverage")
    summary = []
    for d in data.deals:
        audit = evidence_audit(d)
        qa = qa_deal(d)
        summary.append({"Deal": d.identity.deal_id, "Sources": len(d.sources),
                        "Numerical fields": audit["populated_numerical_fields"],
                        "Fields missing evidence": len(audit["missing_evidence"]),
                        "Unknown fields": len(audit["unknown_fields"]),
                        "QA review flags": sum(f.severity == "REVIEW" for f in qa["flags"])})
    st.dataframe(summary, hide_index=True, use_container_width=True)
    selected = st.selectbox("Inspect source ledger", data.deals,
                            format_func=lambda d: f"{d.identity.deal_id} · {d.target.name}")
    for source in selected.sources:
        st.markdown(f"[{source.title}]({source.url})")
        st.caption(f"{source.source_type} | {source.publication_date} | {source.source_id}")
    st.dataframe(_fact_table(selected), hide_index=True, use_container_width=True)


def main() -> None:
    _style()
    try:
        data = load_public_dataset()
    except (OSError, ValueError) as exc:
        st.error("The published dataset failed its integrity or financial QA check. "
                 "The dashboard will not display untrusted figures.")
        st.caption(f"Administrator detail: {type(exc).__name__}. Run `deallens release audit` "
                   "against the configured release and correct the source package.")
        st.stop()
    with st.sidebar:
        st.markdown('<div class="wordmark">Deal<span>Lens</span></div>'
                    '<div class="side-sub">M&A research · public sources</div>', unsafe_allow_html=True)
        page = st.radio("Navigate", PAGES, key="page", label_visibility="collapsed")
        st.markdown(f'<div class="side-foot">PUBLIC RESEARCH<br>Release: {_esc(data.version or "Not published")}<br>'
                    f'{len(data.deals)} eligible deals<br><br>Not investment advice.</div>', unsafe_allow_html=True)
    pages = {"Overview": _overview, "Deal Explorer": _explorer, "Valuation": _valuation,
             "Premiums": _premiums, "Financing & Leverage": _financing, "Synergies": _synergies,
             "Deal Outcomes": _outcomes, "Deal Detail": _detail, "Methodology": _methodology,
             "Data Quality & Sources": _quality}
    pages[page](data)
    st.markdown('<div class="rule"></div><div class="meta">DealLens · Source-backed transaction research · '
                'Values are displayed only where the underlying basis is established.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
