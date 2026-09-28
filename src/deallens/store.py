"""DuckDB persistence with atomic inserts, evidence ledgers and no silent upserts."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

import duckdb

from .models import walk_facts
from .research import ResearchDeal, Review, load_research, validate_financial_inputs


class Store:
    def __init__(self, path="deallens.duckdb"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(path))
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                deal_id VARCHAR PRIMARY KEY, review_status VARCHAR NOT NULL,
                document JSON NOT NULL, imported_at TIMESTAMP DEFAULT current_timestamp
            );
            CREATE TABLE IF NOT EXISTS sources (
                deal_id VARCHAR REFERENCES deals(deal_id), source_id VARCHAR,
                document JSON NOT NULL, PRIMARY KEY (deal_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS evidence (
                deal_id VARCHAR, evidence_id VARCHAR, source_id VARCHAR, document JSON NOT NULL,
                PRIMARY KEY (deal_id, evidence_id),
                FOREIGN KEY (deal_id, source_id) REFERENCES sources(deal_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS verification_events (
                deal_id VARCHAR PRIMARY KEY REFERENCES deals(deal_id), reviewer VARCHAR NOT NULL,
                verified_at TIMESTAMP NOT NULL, notes VARCHAR NOT NULL,
                reviewed_document_sha256 VARCHAR NOT NULL, acknowledged_review_codes JSON NOT NULL
            );
            CREATE TABLE IF NOT EXISTS field_facts (
                deal_id VARCHAR REFERENCES deals(deal_id), field_path VARCHAR,
                document JSON NOT NULL, PRIMARY KEY (deal_id, field_path)
            );
        """)
        self.connection.execute("ALTER TABLE verification_events ADD COLUMN IF NOT EXISTS verified_document_sha256 VARCHAR")

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def import_file(self, path):
        return self.import_deal(load_research(path))

    def import_deal(self, deal: ResearchDeal):
        # Revalidation also defends against unsafe model_construct/model_copy callers.
        deal = ResearchDeal.model_validate(deal.model_dump())
        validate_financial_inputs(deal)
        if deal.review_status == "VERIFIED":
            raise ValueError("import cannot grant VERIFIED status; import DRAFT/REVIEWED and complete manual verification")
        deal_id = deal.identity.deal_id
        db = self.connection
        db.execute("BEGIN TRANSACTION")
        try:
            db.execute("INSERT INTO deals (deal_id, review_status, document) VALUES (?, ?, ?)",
                       [deal_id, deal.review_status, deal.model_dump_json()])
            for source in deal.sources:
                db.execute("INSERT INTO sources VALUES (?, ?, ?)", [deal_id, source.source_id, source.model_dump_json()])
            for evidence in deal.field_evidence:
                db.execute("INSERT INTO evidence VALUES (?, ?, ?, ?)",
                           [deal_id, evidence.evidence_id, evidence.source_id, evidence.model_dump_json()])
            for path, fact in walk_facts(deal):
                db.execute("INSERT INTO field_facts VALUES (?, ?, ?)", [deal_id, path, fact.model_dump_json()])
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return deal_id

    def show(self, deal_id) -> ResearchDeal:
        row = self.connection.execute("SELECT document FROM deals WHERE deal_id = ?", [deal_id]).fetchone()
        if row is None:
            raise ValueError(f"unknown deal: {deal_id}")
        return ResearchDeal.model_validate_json(row[0])

    def all(self):
        return [ResearchDeal.model_validate_json(row[0]) for row in
                self.connection.execute("SELECT document FROM deals ORDER BY deal_id").fetchall()]


    def verify(self, deal_id, *, reviewer, notes, confirm_manual_review=False, acknowledged_review_codes=()):
        """Explicit human action only; a database transaction records document and attestation."""
        from .qa import qa_deal
        if not confirm_manual_review or not reviewer.strip() or not notes.strip():
            raise ValueError("verification requires explicit manual-review confirmation, named reviewer and notes")
        db = self.connection
        db.execute("BEGIN TRANSACTION")
        try:
            deal = self.show(deal_id)
            if deal.review_status == "VERIFIED":
                raise ValueError("deal is already VERIFIED; its original attestation is preserved")
            report = qa_deal(deal, require_verified=False)
            blockers = [flag.code for flag in report["flags"] if flag.severity in ("ERROR", "BLOCK_PUBLISH")]
            if blockers:
                raise ValueError("verification blocked: " + ", ".join(sorted(set(blockers))))
            review_codes = {flag.code for flag in report["flags"] if flag.severity == "REVIEW"}
            if review_codes - set(acknowledged_review_codes):
                raise ValueError("explicitly acknowledge remaining REVIEW codes: " + ", ".join(sorted(review_codes)))
            timestamp = datetime.now(timezone.utc)
            original = deal.model_dump_json()
            review = Review(notes=deal.review_notes.notes, reviewer=reviewer.strip(),
                            reviewed_at=timestamp.date(), verification_notes=notes.strip())
            verified = ResearchDeal.model_validate(deal.model_dump() | {"review_status": "VERIFIED", "review_notes": review})
            db.execute("UPDATE deals SET review_status = ?, document = ? WHERE deal_id = ?",
                       ["VERIFIED", verified.model_dump_json(), deal_id])
            db.execute("INSERT INTO verification_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                       [deal_id, reviewer.strip(), timestamp, notes.strip(), hashlib.sha256(original.encode()).hexdigest(),
                        json.dumps(sorted(review_codes)), hashlib.sha256(verified.model_dump_json().encode()).hexdigest()])
            db.execute("COMMIT")
            return verified
        except Exception:
            db.execute("ROLLBACK")
            raise
