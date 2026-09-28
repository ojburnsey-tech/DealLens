from datetime import date

import pytest

from conftest import fact
from deallens.cli import main
from deallens.finance import EVAdjustment
from deallens.qa import evidence_audit, qa_deal, qa_summary
from deallens.research import FinancialSeries, Financials, ReferencePrice, Valuation
from deallens.store import Store
from test_finance import synergy
from test_research import sourced


def codes(report):
    return {f.code for f in report["flags"]}


@pytest.mark.parametrize("price,code", [(31, "PREMIUM_ABOVE_200_PERCENT"), (7, "PREMIUM_BELOW_MINUS_20_PERCENT"),
                                       (30, None), (8, None)])
def test_premium_thresholds(draft, price, code):
    deal = sourced(draft)
    offer = deal.offer_terms[0].model_copy(update={"price": fact(price, "currency/share", evidence=("E1",))})
    ref = ReferencePrice(reference_id="close", price=fact(10, "currency/share", evidence=("E1",)),
                         reference_date=date(2024, 6, 1), reference_basis="unaffected_close", selection_notes="selected manually")
    report = qa_deal(deal.model_copy(update={"offer_terms": [offer], "unaffected_price": [ref]}))
    if code:
        assert code in codes(report)
        assert next(f for f in report["flags"] if f.code == code).severity == "REVIEW"
    else:
        assert not any(c.startswith("PREMIUM_") for c in codes(report))


@pytest.mark.parametrize("metric,value,code", [("ebitda", 51, "EV_EBITDA_HIGH"), ("revenue", 31, "EV_REVENUE_HIGH")])
def test_multiple_flags(draft, fy, metric, value, code):
    deal = sourced(draft).model_copy(update={"transaction_valuation": Valuation(reported_enterprise_value=fact(value)),
                 "target_financials": Financials(**{metric: FinancialSeries(selected=fact(1, period=fy))})})
    assert code in codes(qa_deal(deal))


def test_synergy_and_ev_reconciliation(draft, fy):
    deal = sourced(draft).model_copy(update={"transaction_valuation": Valuation(reported_enterprise_value=fact(1000),
                equity_for_ev=fact(1200), ev_bridge_basis="debt-free cash-free"),
                "target_financials": Financials(ebitda=FinancialSeries(selected=fact(50, period=fy))),
                "synergies": [synergy("cost", 60)]})
    assert {"SYNERGY_ABOVE_TARGET_EBITDA", "EV_RECONCILIATION"} <= codes(qa_deal(deal))


def test_chronology_and_provenance_block(draft):
    deal = sourced(draft).model_copy(update={"identity": draft.identity.model_copy(update={"completion_date": date(2020, 1, 1)})})
    report = qa_deal(deal)
    assert not report["publishable"]
    assert "COMPLETION_BEFORE_ANNOUNCEMENT" in codes(report)
    assert "MANUAL_VERIFICATION_REQUIRED" in codes(report)
    assert evidence_audit(deal)["missing_evidence"] == []
    assert evidence_audit(deal)["fields"][0]["references"][0]["source"].publication_date == date(2024, 7, 1)


def test_bad_schema_qa_error(draft):
    raw = draft.model_copy(update={"selected_offer_id": "missing"})
    assert "SCHEMA_OR_FINANCE" in codes(qa_deal(raw))


def test_qualified_results_block(draft, fy):
    val = Valuation(equity_for_ev=fact(1000), preferred_ev_basis="calculated", ev_bridge_basis="debt and preferred",
                    snapshot_alignment_basis="different source dates; unadjusted",
                    ev_adjustments=[EVAdjustment(adjustment_id="nd", kind="net_debt", amount=fact(100, as_of=date(2020, 1, 1)), sign=1, basis="net debt"),
                                    EVAdjustment(adjustment_id="p", kind="preferred_stock", amount=fact(10, as_of=fy.end), sign=1, basis="preferred")])
    deal = sourced(draft).model_copy(update={"transaction_valuation": val})
    assert "MATERIAL_QUALIFICATION" in codes(qa_deal(deal))


def test_manual_verification_auditable_and_explicit(draft):
    deal = sourced(draft)
    with Store(":memory:") as store:
        store.import_deal(deal)
        with pytest.raises(ValueError):
            store.verify("DL-00001", reviewer="Human", notes="Reviewed")
        verified = store.verify("DL-00001", reviewer="Human", notes="Checked primary sources and calculation sheet", confirm_manual_review=True)
        assert verified.review_status == "VERIFIED"
        assert qa_deal(verified)["publishable"]
        assert store.connection.execute("SELECT count(*) FROM verification_events").fetchone()[0] == 1
        with pytest.raises(ValueError, match="already VERIFIED"):
            store.verify("DL-00001", reviewer="Human", notes="Again", confirm_manual_review=True)


def test_verification_blocks_missing_sources_and_rolls_back(draft):
    with Store(":memory:") as store:
        store.import_deal(draft)
        with pytest.raises(ValueError, match="blocked"):
            store.verify("DL-00001", reviewer="Human", notes="Reviewed", confirm_manual_review=True)
        assert store.show("DL-00001").review_status == "DRAFT"
        assert store.connection.execute("SELECT count(*) FROM verification_events").fetchone()[0] == 0


def test_review_flags_need_explicit_acknowledgement(draft):
    deal = sourced(draft)
    price = deal.offer_terms[0].price.model_copy(update={"ambiguity": "rounded quote"})
    deal = deal.model_copy(update={"offer_terms": [deal.offer_terms[0].model_copy(update={"price": price})]})
    with Store(":memory:") as store:
        store.import_deal(deal)
        with pytest.raises(ValueError, match="acknowledge"):
            store.verify("DL-00001", reviewer="Human", notes="Reviewed", confirm_manual_review=True)
        verified = store.verify("DL-00001", reviewer="Human", notes="Rounding acceptable for cited precision", confirm_manual_review=True,
                                acknowledged_review_codes=["SOURCE_AMBIGUITY"])
        assert verified.review_status == "VERIFIED"


def test_qa_cli_commands(tmp_path, draft, capsys):
    path = tmp_path / "qa.duckdb"
    with Store(path) as store:
        store.import_deal(sourced(draft))
    for command in (["qa", "deal", "DL-00001"], ["qa", "all"], ["qa", "report"]):
        assert main(["--db", str(path), *command]) == 2
    assert main(["--db", str(path), "evidence", "audit", "DL-00001"]) == 0
    assert main(["--db", str(path), "deal", "export", "DL-00001", "--output", str(tmp_path / "export.yml")]) == 0


def test_summary(draft):
    summary = qa_summary([qa_deal(draft)])
    assert summary["deals"] == 1 and summary["publishable_deals"] == 0
    assert summary["severity_counts"]["BLOCK_PUBLISH"] >= 1
