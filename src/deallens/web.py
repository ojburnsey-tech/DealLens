"""Read-only local HTML workspace for DealLens research.

The public portfolio only uses database records that pass the existing
verification and QA gates. Inbox YAML is visible as research, never promoted
to a portfolio statistic. The server has no write endpoints.
"""

import argparse
import csv
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .analytics import _metric_summary_accepted, _portfolio_summary_accepted, accepted_deals, portfolio_summary
from .models import Fact
from .qa import qa_deal
from .releases import audit_release, public_url, safe_text
from .research import ResearchDeal, analyse, load_research


FRONTEND = Path(__file__).resolve().parent / "frontend"
PROJECT = Path.cwd()


def _number(value):
    return None if value is None else str(value)


def _fact(fact: Fact | None):
    if fact is None or fact.amount is None:
        return None
    return {
        "amount": _number(fact.amount),
        "currency": fact.currency,
        "unit": fact.unit,
        "definition": fact.definition,
        "classification": fact.classification,
        "evidence": list(fact.evidence),
        "period": fact.period.basis if fact.period else None,
    }


def _result(result):
    if result is None or result.result is None:
        return None
    return {
        "value": _number(result.result),
        "unit": result.unit,
        "currency": result.currency,
        "basis": result.basis,
        "warnings": list(result.warnings),
        "qualifications": list(result.qualifications),
    }


def _metric_report(deals, metric):
    report = _metric_summary_accepted(deals, [], metric)
    return {
        "eligible_n": report["eligible_deals"],
        "missing_n": len(report["missing_or_nonmeaningful_deals"]),
        "cohorts": [{
            "unit": cohort["unit"],
            "currency": cohort["currency"],
            "basis": cohort["basis"],
            "n": cohort["n"],
            "sum": _number(cohort["sum"]),
            "statistics": {key: _number(getattr(cohort["statistics"], key))
                           for key in ("minimum", "q25", "median", "mean", "q75", "maximum")},
            "observations": [{"deal_id": item.deal_id, "value": _number(item.value)}
                             for item in cohort["observations"]],
        } for cohort in report["cohorts"]],
    }


def _deal(deal, *, origin, audited_release=False):
    calculations = analyse(deal)
    report = qa_deal(deal, require_verified=not audited_release)
    offer = next((o for o in deal.offer_terms if o.offer_id == deal.selected_offer_id), None)
    sources = {source.source_id: source for source in deal.sources}
    evidence = {item.evidence_id: item for item in deal.field_evidence}

    def sourced(fact):
        result = _fact(fact)
        if result:
            result["sources"] = sorted({
                evidence[key].source_id for key in result["evidence"] if key in evidence
                and evidence[key].source_id in sources
            })
        return result

    values = {
        "offer": sourced(offer.price if offer else None),
        "equity": sourced(deal.transaction_valuation.reported_equity_value),
        "enterprise": sourced(deal.transaction_valuation.reported_enterprise_value),
        "ev_ebitda": _result(calculations.get("ev_ebitda")),
        "premium": next((_result(item) for item in calculations.get("premiums", {}).values()
                         if item.result is not None), None),
    }
    return {
        "id": deal.identity.deal_id,
        "name": deal.identity.name,
        "bidder": deal.bidder.name,
        "target": deal.target.name,
        "target_country": deal.target.country,
        "announcement_date": deal.identity.announcement_date.isoformat(),
        "completion_date": deal.identity.completion_date.isoformat() if deal.identity.completion_date else None,
        "transaction_status": deal.identity.transaction_status,
        "review_status": "VERIFIED" if audited_release else deal.review_status,
        "origin": origin,
        "sector": deal.profile.sector,
        "values": values,
        "selected_offer": {"id": offer.offer_id, "date": offer.date.isoformat(), "basis": offer.basis} if offer else None,
        "sources": [{"id": source.source_id, "title": source.title, "url": str(source.url),
                     "date": source.publication_date.isoformat(), "type": source.source_type}
                    for source in deal.sources],
        "evidence_count": len(deal.field_evidence),
        "qa": {"publishable": report["publishable"],
               "flags": [{"severity": flag.severity, "code": flag.code, "message": flag.message}
                         for flag in report["flags"] if flag.severity != "INFO"]},
    }


def _assemble_payload(project, stored, *, origin, database_connected, scope, audited_release=False,
                      release_version=None):
    """Combine validated records while keeping provisional research out of statistics."""
    project = Path(project)
    seen = {deal.identity.deal_id for deal in stored}
    inbox = []
    inbox_directory = project / "research" / "inbox"
    if audited_release and inbox_directory.is_symlink():
        raise ValueError("public research inbox cannot be a symlink")
    inbox_paths = set(inbox_directory.glob("*.yml"))
    inbox_paths.update(inbox_directory.glob("*.yaml"))
    for path in sorted(inbox_paths):
        if audited_release and path.is_symlink():
            raise ValueError(f"public research file cannot be a symlink: {path.name}")
        deal = load_research(path)
        if deal.review_status == "VERIFIED":
            raise ValueError(f"inbox record cannot claim VERIFIED status: {deal.identity.deal_id}")
        if deal.identity.deal_id not in seen:
            inbox.append(deal)
            seen.add(deal.identity.deal_id)

    if audited_release:
        if any(not qa_deal(deal, require_verified=False)["publishable"] for deal in stored):
            raise ValueError("audited release record fails current QA")
        eligible, excluded = stored, []
        portfolio = _portfolio_summary_accepted(stored, [])
    else:
        eligible, excluded = accepted_deals(stored)
        portfolio = portfolio_summary(stored)
    records = stored + inbox
    statuses = Counter(deal.review_status for deal in inbox)
    statuses.update("VERIFIED" if audited_release else deal.review_status for deal in stored)
    metrics = {metric: _metric_report(eligible, metric) for metric in (
        "disclosed_ev", "ev_ebitda", "ev_revenue", "premium", "cost_synergy_ev",
        "synergy_adjusted_multiple", "buyer_standalone_leverage", "leverage_before_synergy",
        "leverage_after_synergy",
    )}
    outcome_statuses = Counter(deal.identity.transaction_status for deal in eligible)
    return {
        "scope": scope,
        "database_connected": database_connected,
        "release_version": release_version,
        "summary": {
            "inventory": len(records),
            "verified": len(eligible),
            "verified_status": statuses["VERIFIED"],
            "draft": statuses["DRAFT"],
            "reviewed": statuses["REVIEWED"],
            "excluded": len(excluded),
        },
        "portfolio": {
            "deal_count": portfolio["deal_count"]["value"],
            "completion_rate": _number(portfolio["completion_rate"]["value"]),
            "completion_n": portfolio["completion_rate"]["n"],
            "completion_days_median": _number(portfolio["completion_days"]["statistics"].median),
            "completion_days_n": portfolio["completion_days"]["n"],
            "status_counts": [{"status": status, "n": count} for status, count in sorted(outcome_statuses.items())],
            "ev_cohorts": [{"currency": cohort["currency"], "basis": cohort["basis"],
                            "n": cohort["n"], "sum": _number(cohort["sum"])}
                           for cohort in portfolio["disclosed_ev"]["cohorts"]],
        },
        "metrics": metrics,
        "deals": [_deal(deal, origin=origin, audited_release=audited_release) for deal in stored]
                 + [_deal(deal, origin="research/inbox") for deal in inbox],
        "policy": "Only attested VERIFIED records that pass QA enter portfolio analytics. Inbox research is provisional.",
    }


def build_payload(project=PROJECT, db_path=None):
    """Read local DuckDB research, requiring its attestation for VERIFIED records."""
    project = Path(project)
    db_path = Path(db_path) if db_path else Path(os.environ.get("DEALLENS_DB", project / "deallens.duckdb"))
    stored = []
    if db_path.exists():
        import duckdb
        with duckdb.connect(str(db_path), read_only=True) as connection:
            rows = connection.execute("SELECT deal_id, document FROM deals ORDER BY deal_id").fetchall()
            for deal_id, document in rows:
                deal = ResearchDeal.model_validate_json(document)
                if deal.identity.deal_id != deal_id:
                    raise ValueError(f"database ID mismatch: {deal_id}")
                if deal.review_status == "VERIFIED":
                    event = connection.execute(
                        "SELECT verified_document_sha256 FROM verification_events WHERE deal_id = ?", [deal_id]
                    ).fetchone()
                    digest = hashlib.sha256(deal.model_dump_json().encode()).hexdigest()
                    if event is None or event[0] != digest:
                        raise ValueError(f"missing or mismatched document attestation: {deal_id}")
                stored.append(deal)
    return _assemble_payload(project, stored, origin="database", database_connected=db_path.exists(),
                             scope="Local research workspace")


def build_public_payload(project=PROJECT, release_directory=None):
    """Build the public snapshot only from inbox YAML and an audited release."""
    project = Path(project)
    release = Path(release_directory) if release_directory else project / "public" / "release"
    stored = []
    release_version = None
    if release.exists():
        release_version = str(audit_release(release)["version"])
        with (release / "deals.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                public = json.loads(row["public_record_json"])
                deal = ResearchDeal.model_validate(public | {"review_status": "DRAFT"})
                stored.append(deal)
    elif release_directory is not None:
        raise FileNotFoundError(f"configured public release does not exist: {release}")
    payload = _assemble_payload(project, stored, origin="audited release", database_connected=False,
                                scope="Published research snapshot", audited_release=True,
                                release_version=release_version)
    for deal in payload["deals"]:
        for source in deal["sources"]:
            public_url(source["url"])
    safe_text(json.dumps(payload, ensure_ascii=False))
    return payload


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, project, database, **kwargs):
        self.project = project
        self.database = database
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def do_GET(self):
        request_path = urlsplit(self.path).path
        if request_path == "/api/data":
            try:
                release = os.environ.get("DEALLENS_PUBLIC_RELEASE")
                payload = (build_public_payload(self.project, release) if release
                           else build_payload(self.project, self.database))
                body = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._send_cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.log_error("data request failed: %s", exc)
                body = json.dumps({"error": "Research data could not be loaded."}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._send_cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if request_path in ("/", "/index.html", "/styles.css", "/app.js", "/data.js"):
            return super().do_GET()
        self.send_error(404, "Not found")

    def _send_cors(self):
        allowed = os.environ.get("DEALLENS_PUBLIC_ORIGIN")
        if allowed and self.headers.get("Origin") == allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the read-only DealLens research workspace")
    parser.add_argument("--host", default=os.environ.get("DEALLENS_HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args(argv)
    if not FRONTEND.exists():
        parser.error(f"frontend missing: {FRONTEND}")

    from functools import partial
    with ThreadingHTTPServer((args.host, args.port), partial(Handler, project=args.project,
                                                             database=args.db)) as server:
        print(f"DealLens at http://{args.host}:{server.server_port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
