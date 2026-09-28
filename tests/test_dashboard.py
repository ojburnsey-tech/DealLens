from decimal import Decimal
from pathlib import Path

import pytest

from dashboard import data
from dashboard.data import load_public_dataset
from dashboard.presentation import compact_number, matching_deals, multiple, percent
from deallens.releases import build_release
from deallens.research import ResearchDeal, ResearchProfile
from deallens.store import Store
from test_research import sourced


def public_deal(draft) -> ResearchDeal:
    deal = sourced(draft)
    return ResearchDeal.model_validate(
        deal.model_dump()
        | {
            "profile": ResearchProfile(
                sector="Consumer",
                transaction_type="scheme",
                consideration_type="cash",
                field_evidence={
                    key: ["E1"] for key in ("sector", "transaction_type", "consideration_type")
                },
            )
        }
    )


def test_missing_default_release_opens_empty_dashboard(tmp_path, monkeypatch):
    monkeypatch.delenv(data.RELEASE_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(data, "DEFAULT_RELEASE", tmp_path / "not-published")
    assert load_public_dataset() == data.PublicDataset((), None)


def test_explicit_missing_release_is_an_error(tmp_path):
    with pytest.raises(OSError, match="does not exist"):
        load_public_dataset(tmp_path / "missing")


def test_audited_release_loads_for_dashboard(tmp_path, draft):
    deal = public_deal(draft)
    release = tmp_path / "release"
    with Store(":memory:") as store:
        store.import_deal(deal)
        store.verify(
            deal.identity.deal_id,
            reviewer="Synthetic dashboard test",
            notes="Synthetic verification test only",
            confirm_manual_review=True,
        )
        build_release(store, release, version="dashboard-test")

    loaded = load_public_dataset(release)
    assert loaded.version == "dashboard-test"
    assert loaded.release_directory == release
    assert [item.identity.deal_id for item in loaded.deals] == ["DL-00001"]
    assert matching_deals(loaded.deals, sector="Consumer") == loaded.deals
    assert matching_deals(loaded.deals, sector="Technology") == ()


def test_public_number_formatters_are_explicit():
    assert compact_number(Decimal("1234000000"), currency="GBP") == "GBP 1.2bn"
    assert compact_number(None, currency="GBP") == "Unavailable"
    assert percent(Decimal("0.125")) == "12.5%"
    assert multiple(Decimal("8.25")) == "8.2x"


def test_root_streamlit_app_starts():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert app.radio[0].value == "Overview"
