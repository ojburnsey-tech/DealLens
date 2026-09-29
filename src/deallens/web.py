"""Read-only local HTML workspace for DealLens research.

The public portfolio only uses database records that pass the existing
verification and QA gates. Inbox YAML is visible as research, never promoted
to a portfolio statistic. The server has no write endpoints.
"""

import argparse
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path

from .analytics import accepted_deals, portfolio_summary
from .models import Fact
from .qa import qa_deal
from .research import ResearchDeal, analyse, load_research


FRONTEND = Path(__file__).resolve().parent / "frontend"
PROJECT = Path(__file__).resolve().parents[2]


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


def _deal(deal, *, origin):
    calculations = analyse(deal)
    report = qa_deal(deal)
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
        "review_status": deal.review_status,
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


def build_payload(project=PROJECT, db_path=None):
    """Create one truthful snapshot from validated inbox and store records."""
    project = Path(project)
    db_path = Path(db_path) if db_path else Path(os.environ.get("DEALLENS_DB", project / "deallens.duckdb"))
    stored = []
    if db_path.exists():
        import duckdb
        with duckdb.connect(str(db_path), read_only=True) as connection:
            rows = connection.execute("SELECT document FROM deals ORDER BY deal_id").fetchall()
            stored = [ResearchDeal.model_validate_json(row[0]) for row in rows]

    seen = {deal.identity.deal_id for deal in stored}
    inbox = []
    inbox_paths = set((project / "research" / "inbox").glob("*.yml"))
    inbox_paths.update((project / "research" / "inbox").glob("*.yaml"))
    for path in sorted(inbox_paths):
        deal = load_research(path)
        if deal.identity.deal_id not in seen:
            inbox.append(deal)
            seen.add(deal.identity.deal_id)

    eligible, excluded = accepted_deals(stored)
    records = stored + inbox
    statuses = Counter(deal.review_status for deal in records)
    portfolio = portfolio_summary(stored)
    return {
        "scope": "Local research workspace",
        "database_connected": db_path.exists(),
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
            "ev_cohorts": [{"currency": cohort["currency"], "basis": cohort["basis"],
                            "n": cohort["n"], "sum": _number(cohort["sum"])}
                           for cohort in portfolio["disclosed_ev"]["cohorts"]],
        },
        "deals": [_deal(deal, origin="database") for deal in stored]
                 + [_deal(deal, origin="research/inbox") for deal in inbox],
        "policy": "Only VERIFIED database records that pass QA enter portfolio analytics. Inbox research is provisional.",
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, project, database, **kwargs):
        self.project = project
        self.database = database
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            try:
                body = json.dumps(build_payload(self.project, self.database), separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if self.path in ("/", "/index.html", "/styles.css", "/app.js", "/data.js"):
            return super().do_GET()
        self.send_error(404, "Not found")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the read-only DealLens research workspace")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
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
