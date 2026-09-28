from datetime import date

import duckdb
import pytest
import yaml

from conftest import fact
from deallens.cli import main
from deallens.models import Evidence, Source
from deallens.research import Offer, ResearchDeal, Review, jsonable, load_research, template
from deallens.store import Store


@pytest.mark.parametrize("text", ["[", "[]", "null", "a: 1\na: 2", "!!python/object/apply:os.system ['false']", "a: &x [*x]", "---\na: 1\n---\nb: 2"])
def test_malformed_yaml(tmp_path, text):
    path = tmp_path / "bad.yml"
    path.write_text(text)
    with pytest.raises((ValueError, yaml.YAMLError)):
        load_research(path)


def test_missing_identity_rejected(tmp_path):
    path = tmp_path / "missing.yml"
    path.write_text("review_status: DRAFT\n")
    with pytest.raises(ValueError):
        load_research(path)


def test_template_valid_missing_financials(tmp_path):
    path = tmp_path / "deal.yml"
    path.write_text(template())
    deal = load_research(path)
    assert deal.target_financials.cash is None
    assert deal.review_status == "DRAFT"


def sourced(draft):
    source = Source(source_id="S1", title="Announcement", url="https://example.com/announcement",
                    publication_date=date(2024, 7, 1), source_type="ANNOUNCEMENT")
    evidence = Evidence(evidence_id="E1", source_id="S1", section="Terms", reported_unit="GBP/share", note="Offer price")
    return ResearchDeal.model_validate(draft.model_dump() | {"sources": [source], "field_evidence": [evidence],
            "offer_terms": [Offer(offer_id="offer", stage="initial", date=date(2024, 7, 1),
                                  price=fact("12.123456789123456789", "currency/share", evidence=("E1",)), basis="cash")],
            "selected_offer_id": "offer"})


def test_successful_import_retains_precision_and_evidence(tmp_path, draft):
    path = tmp_path / "research.yml"
    deal = sourced(draft)
    path.write_text(yaml.safe_dump(jsonable(deal)))
    with Store(tmp_path / "data.duckdb") as store:
        assert store.import_file(path) == "DL-00001"
        assert store.show("DL-00001") == deal
        assert store.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
        assert store.connection.execute("SELECT count(*) FROM field_facts").fetchone()[0] == 1


def test_duplicate_id_no_partial_inserts(draft):
    with Store(":memory:") as store:
        store.import_deal(draft)
        with pytest.raises(duckdb.Error):
            store.import_deal(sourced(draft))
        assert len(store.all()) == 1
        assert store.connection.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


def test_mid_transaction_failure_rolls_back(draft):
    with Store(":memory:") as store:
        # Force an actual database failure after the deal row and source row insert.
        store.connection.execute("DROP TABLE field_facts")
        with pytest.raises(duckdb.Error):
            store.import_deal(sourced(draft))
        for table in ("deals", "sources", "evidence"):
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_unknown_evidence_rejected(draft):
    raw = sourced(draft).model_dump()
    raw["field_evidence"][0]["source_id"] = "missing"
    with pytest.raises(ValueError):
        ResearchDeal.model_validate(raw)


def test_import_never_verifies(draft):
    verified = draft.model_copy(update={"review_status": "VERIFIED", "review_notes": Review(reviewer="Human", reviewed_at=date(2024, 7, 2), verification_notes="Checked originals")})
    with Store(":memory:") as store:
        with pytest.raises(ValueError, match="cannot grant VERIFIED"):
            store.import_deal(verified)
        assert store.all() == []


def test_reviewed_requires_reviewer(draft):
    with pytest.raises(ValueError):
        ResearchDeal.model_validate(draft.model_dump() | {"review_status": "REVIEWED"})
    reviewed = draft.model_copy(update={"review_status": "REVIEWED", "review_notes": Review(reviewer="Human", reviewed_at=date(2024, 7, 2))})
    with Store(":memory:") as store:
        store.import_deal(reviewed)
        assert store.show("DL-00001").review_status == "REVIEWED"


def test_cli_template_validate_import_show(tmp_path, capsys):
    path, db = tmp_path / "draft.yml", tmp_path / "data.duckdb"
    assert main(["deal", "template", "--output", str(path)]) == 0
    assert main(["deal", "validate", str(path)]) == 0
    assert main(["--db", str(db), "deal", "import", str(path)]) == 0
    assert main(["--db", str(db), "deal", "show", "DL-00000"]) == 0
    assert main(["--db", str(db), "deal", "import", str(path)]) == 1
    assert main(["deal", "template", "--output", str(path)]) == 1
