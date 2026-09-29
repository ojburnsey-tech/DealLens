"""The UI must not count provisional research as a verified portfolio sample."""

from pathlib import Path

from deallens.web import build_payload
from deallens.store import Store


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
