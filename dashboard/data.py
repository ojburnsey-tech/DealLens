"""Load only integrity-checked DealLens public releases for the dashboard."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

from deallens.releases import audit_release
from deallens.research import ResearchDeal

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE = REPOSITORY_ROOT / "public" / "release"
RELEASE_ENVIRONMENT_VARIABLE = "DEALLENS_PUBLIC_RELEASE"


@dataclass(frozen=True)
class PublicDataset:
    """A validated public-release snapshot ready for presentation."""

    deals: tuple[ResearchDeal, ...]
    version: str | None
    release_directory: Path | None = None


def _release_location(directory: Path | str | None) -> tuple[Path, bool]:
    if directory is not None:
        return Path(directory).expanduser(), True
    configured = os.environ.get(RELEASE_ENVIRONMENT_VARIABLE)
    if configured:
        return Path(configured).expanduser(), True
    return DEFAULT_RELEASE, False


def load_public_dataset(directory: Path | str | None = None) -> PublicDataset:
    """Load a release after its allowlist, hashes and financial QA pass.

    A repository without a published release intentionally opens as an empty
    dashboard. An explicitly configured missing release is an error so a bad
    deployment cannot be mistaken for a valid empty dataset.
    """

    release, explicitly_configured = _release_location(directory)
    if not release.exists():
        if explicitly_configured:
            raise OSError(f"configured public release does not exist: {release}")
        return PublicDataset((), None)

    audit = audit_release(release)
    deals: list[ResearchDeal] = []
    with (release / "deals.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                public_record = json.loads(row["public_record_json"])
                # Public exports deliberately omit private reviewer identity.
                # Validate the complete public schema without those private
                # fields, then retain the VERIFIED status established by the
                # successful release audit above.
                deal = ResearchDeal.model_validate(public_record | {"review_status": "DRAFT"})
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("malformed public dashboard record") from exc
            if public_record.get("review_status") != "VERIFIED":
                raise ValueError(f"unverified dashboard record: {deal.identity.deal_id}")
            deals.append(deal.model_copy(update={"review_status": "VERIFIED"}))

    ordered = tuple(sorted(deals, key=lambda deal: deal.identity.deal_id))
    if len({deal.identity.deal_id for deal in ordered}) != len(ordered):
        raise ValueError("duplicate deal ID in public dashboard release")
    if len(ordered) != audit["deal_count"]:
        raise ValueError("dashboard record count does not match audited release")
    return PublicDataset(ordered, str(audit["version"]), release)
