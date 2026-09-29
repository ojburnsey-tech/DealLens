"""The UI must not count provisional research as a verified portfolio sample."""

from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer
import json
from decimal import Decimal
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from conftest import fact
from deallens.releases import build_release
from deallens.research import Financials, FinancialSeries, ReferencePrice, ResearchDeal, ResearchProfile, Valuation
from deallens.web import Handler, build_payload, build_public_payload
from deallens.store import Store
from test_research import sourced


PROJECT = Path(__file__).resolve().parents[1]


def test_bundled_draft_is_visible_but_excluded_from_portfolio(tmp_path):
    payload = build_payload(PROJECT, tmp_path / "missing.duckdb")

    assert payload["summary"]["inventory"] == 1
    assert payload["summary"]["draft"] == 1
    assert payload["summary"]["verified"] == 0
    assert payload["portfolio"]["deal_count"] == 0
    assert payload["portfolio"]["ev_cohorts"] == []

    record = payload["deals"][0]
    assert record["id"] == "DL-00001"
    assert record["review_status"] == "DRAFT"
    assert record["qa"]["publishable"] is False
    assert record["values"]["offer"]["sources"]
    assert any(flag["code"] == "MANUAL_VERIFICATION_REQUIRED" for flag in record["qa"]["flags"])


def test_existing_database_record_is_not_duplicated_by_inbox(tmp_path):
    database = tmp_path / "research.duckdb"
    with Store(database) as store:
        store.import_file(PROJECT / "research/inbox/DL-00001.yml")

    payload = build_payload(PROJECT, database)
    assert payload["database_connected"] is True
    assert payload["summary"]["inventory"] == 1
    assert payload["summary"]["verified"] == 0
    assert payload["deals"][0]["origin"] == "database"


def test_forged_verified_database_record_is_rejected(tmp_path, draft):
    database = tmp_path / "research.duckdb"
    with Store(database) as store:
        deal = sourced(draft)
        store.import_deal(deal)
        store.verify(deal.identity.deal_id, reviewer="Synthetic test reviewer",
                     notes="Synthetic verification test only", confirm_manual_review=True)
        store.connection.execute("DELETE FROM verification_events")

    with pytest.raises(ValueError, match="attestation"):
        build_payload(tmp_path, database)


def test_public_snapshot_uses_audited_release_and_not_local_database(tmp_path, draft, fy, monkeypatch):
    deal = sourced(draft)
    deal = ResearchDeal.model_validate(deal.model_dump() | {"profile": ResearchProfile(
        sector="Consumer", transaction_type="scheme", consideration_type="cash",
        field_evidence={key: ["E1"] for key in ("sector", "transaction_type", "consideration_type")},
    ), "transaction_valuation": Valuation(
        reported_enterprise_value=fact(1000, definition="Reported EV", evidence=("E1",)),
    ), "target_financials": Financials(
        ebitda=FinancialSeries(selected=fact(100, definition="Adjusted EBITDA", period=fy, evidence=("E1",))),
        revenue=FinancialSeries(selected=fact(500, definition="Revenue", period=fy, evidence=("E1",))),
    ), "unaffected_price": [ReferencePrice(
        reference_id="close", price=fact(10, "currency/share", evidence=("E1",)),
        reference_date=deal.identity.announcement_date, reference_basis="unaffected_close",
        selection_notes="Synthetic selected close",
    )]})
    database = tmp_path / "research.duckdb"
    with Store(database) as store:
        store.import_deal(deal)
        store.verify(deal.identity.deal_id, reviewer="Synthetic test reviewer",
                     notes="Synthetic verification test only", confirm_manual_review=True)
        monkeypatch.setenv("DEALLENS_DB", str(database))
        unpublished = build_public_payload(tmp_path)
        assert unpublished["portfolio"]["deal_count"] == 0
        build_release(store, tmp_path / "public" / "release", version="test-1")

    live = build_payload(tmp_path, database)
    assert live["portfolio"]["deal_count"] == 1
    assert live["summary"]["verified"] == 1
    published = build_public_payload(tmp_path)
    assert published["portfolio"]["deal_count"] == 1
    assert published["summary"]["verified"] == 1
    assert published["release_version"] == "test-1"
    assert published["deals"][0]["origin"] == "audited release"
    assert Decimal(published["metrics"]["disclosed_ev"]["cohorts"][0]["statistics"]["median"]) == 1000
    assert Decimal(published["metrics"]["ev_ebitda"]["cohorts"][0]["statistics"]["median"]) == 10
    assert Decimal(published["metrics"]["ev_revenue"]["cohorts"][0]["statistics"]["median"]) == 2
    assert published["metrics"]["premium"]["cohorts"][0]["n"] == 1


def test_public_snapshot_rejects_linked_inbox_file(tmp_path):
    inbox = tmp_path / "research" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "linked.yml").symlink_to(PROJECT / "research" / "inbox" / "DL-00001.yml")
    with pytest.raises(ValueError, match="symlink"):
        build_public_payload(tmp_path)


def test_inbox_cannot_claim_verified_status_without_release(tmp_path, draft, monkeypatch):
    inbox = tmp_path / "research" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "record.yml").write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("deallens.web.load_research", lambda _: draft.model_copy(update={"review_status": "VERIFIED"}))
    with pytest.raises(ValueError, match="inbox record cannot claim VERIFIED"):
        build_public_payload(tmp_path)


def test_http_api_uses_live_data_and_restricts_cors(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALLENS_PUBLIC_ORIGIN", "https://ojburnsey-tech.github.io")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, project=PROJECT,
                                                           database=tmp_path / "missing.duckdb"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/") as response:
            assert b'<meta name="deallens-api" content="/api/data">' in response.read()
        with urlopen(base + "/?cache=1") as response:
            assert response.status == 200
            assert b'<meta name="deallens-api" content="/api/data">' in response.read()
        request = Request(base + "/api/data", headers={"Origin": "https://ojburnsey-tech.github.io"})
        with urlopen(request) as response:
            payload = json.load(response)
            assert payload["summary"]["draft"] == 1
            assert response.headers["Access-Control-Allow-Origin"] == "https://ojburnsey-tech.github.io"
            assert response.headers["Cache-Control"] == "no-store"
        with urlopen(base + "/api/data?cache=1") as response:
            assert json.load(response)["summary"]["draft"] == 1
        request = Request(base + "/api/data", headers={"Origin": "https://unrelated.example"})
        with urlopen(request) as response:
            assert response.headers.get("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_api_reports_missing_public_release_without_snapshot_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALLENS_PUBLIC_RELEASE", str(tmp_path / "missing-release"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, project=PROJECT,
                                                           database=tmp_path / "missing.duckdb"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/data")
        assert exc.value.code == 500
        assert json.load(exc.value)["error"] == "Research data could not be loaded."
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
