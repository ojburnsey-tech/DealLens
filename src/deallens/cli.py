"""Small JSON-first command line interface; failures return non-zero exit codes."""
import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
import yaml

from .research import analyse, jsonable, load_research, template
from .store import Store


def _print(value):
    print(json.dumps(jsonable(value), indent=2, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="deallens")
    parser.add_argument("--db", default=os.environ.get("DEALLENS_DB", "deallens.duckdb"))
    groups = parser.add_subparsers(dest="group", required=True)
    deal = groups.add_parser("deal").add_subparsers(dest="command", required=True)
    create = deal.add_parser("template")
    create.add_argument("--output", type=Path)
    for command in ("validate", "import"):
        deal.add_parser(command).add_argument("file", type=Path)
    for command in ("show", "calculate"):
        deal.add_parser(command).add_argument("deal_id")
    verify = deal.add_parser("verify")
    verify.add_argument("deal_id")
    verify.add_argument("--reviewer", required=True)
    verify.add_argument("--notes-file", type=Path, required=True)
    verify.add_argument("--confirm-manual-review", action="store_true")
    verify.add_argument("--acknowledge-review", action="append", default=[])
    export = deal.add_parser("export")
    export.add_argument("deal_id")
    export.add_argument("--output", type=Path, required=True)
    evidence = groups.add_parser("evidence").add_subparsers(dest="command", required=True)
    evidence.add_parser("audit").add_argument("deal_id")
    qa = groups.add_parser("qa").add_subparsers(dest="command", required=True)
    qa.add_parser("deal").add_argument("deal_id")
    qa.add_parser("all")
    qa.add_parser("report")
    ch = groups.add_parser("companies-house").add_subparsers(dest="command", required=True)
    ch.add_parser("search").add_argument("query")
    for command in ("profile", "filings"):
        ch.add_parser(command).add_argument("company_number")
    for command_parser in ch.choices.values():
        command_parser.add_argument("--start-index", type=int, default=0)
        command_parser.add_argument("--items-per-page", type=int, default=100)
    release = groups.add_parser("release").add_subparsers(dest="command", required=True)
    release_build = release.add_parser("build")
    release_build.add_argument("version")
    release_build.add_argument("--output", type=Path)
    release.add_parser("audit").add_argument("directory", type=Path)
    report = groups.add_parser("report").add_subparsers(dest="command", required=True)
    report_build = report.add_parser("build")
    report_build.add_argument("deal_id")
    report_build.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.group == "release" and args.command == "audit":
            from .releases import audit_release
            _print(audit_release(args.directory))
            return 0
        if args.group == "companies-house":
            from .companies_house import CompaniesHouse, CompaniesHouseError
            try:
                with CompaniesHouse() as client:
                    if args.command == "profile":
                        result = client.profile(args.company_number)
                    else:
                        result = getattr(client, args.command)(args.query if args.command == "search" else args.company_number,
                                                              start_index=args.start_index, items_per_page=args.items_per_page)
                    _print(result)
            except CompaniesHouseError as exc:
                raise ValueError(str(exc)) from exc
            return 0
        if args.group == "deal" and args.command == "template":
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Never clobber someone's in-progress research.
                with args.output.open("x", encoding="utf-8") as handle:
                    handle.write(template())
            else:
                print(template(), end="")
            return 0
        if args.group == "deal" and args.command == "validate":
            result = load_research(args.file)
            _print({"valid": True, "deal_id": result.identity.deal_id, "review_status": result.review_status})
            return 0
        with Store(args.db) as store:
            if args.group == "release":
                from .releases import build_release
                _print(build_release(store, args.output or Path("releases") / args.version, version=args.version))
            elif args.group == "report":
                from .reports import build_report
                output = args.output or Path("reports") / f"{args.deal_id}.pdf"
                _print({"report": str(build_report(store.show(args.deal_id), output))})
            elif args.group == "deal":
                if args.command == "import":
                    _print({"imported": store.import_file(args.file)})
                elif args.command == "verify":
                    _print(store.verify(args.deal_id, reviewer=args.reviewer,
                                        notes=args.notes_file.read_text(encoding="utf-8"),
                                        confirm_manual_review=args.confirm_manual_review,
                                        acknowledged_review_codes=args.acknowledge_review))
                elif args.command == "export":
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    with args.output.open("x", encoding="utf-8") as handle:
                        yaml.safe_dump(jsonable(store.show(args.deal_id)), handle, sort_keys=False)
                else:
                    record = store.show(args.deal_id)
                    _print(record if args.command == "show" else analyse(record))
            elif args.group == "evidence":
                from .qa import evidence_audit
                result = evidence_audit(store.show(args.deal_id))
                _print(result)
                return 2 if result["missing_evidence"] else 0
            else:
                from .qa import qa_deal, qa_summary
                reports = [qa_deal(store.show(args.deal_id))] if args.command == "deal" else [qa_deal(d) for d in store.all()]
                _print(reports[0] if args.command == "deal" else qa_summary(reports) if args.command == "report" else reports)
                return 2 if any(not r["publishable"] for r in reports) else 0
        return 0
    except (ValueError, OSError, yaml.YAMLError, duckdb.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
