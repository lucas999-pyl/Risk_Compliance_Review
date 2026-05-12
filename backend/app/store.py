from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ids import new_id
from app.knowledge import KnowledgeChunk
from app.models import CaseCreate, KnowledgeSourceCreate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class SQLiteStore:
    def __init__(self, database_path: str, storage_dir: str) -> None:
        self.database_path = Path(database_path)
        self.storage_dir = Path(storage_dir)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    material_type TEXT NOT NULL,
                    target_markets TEXT NOT NULL,
                    intended_use TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    source_name TEXT,
                    content_type TEXT,
                    sha256 TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS extraction_reviews (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    comment TEXT,
                    edited_fields TEXT NOT NULL,
                    audit_log_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS extracted_sections (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    section_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_components (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    substance_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    cas TEXT NOT NULL,
                    ec TEXT,
                    concentration_min REAL,
                    concentration_max REAL,
                    concentration_text TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS regulatory_sources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    version TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    license_note TEXT NOT NULL,
                    source_origin TEXT NOT NULL DEFAULT 'unknown',
                    quality_tier TEXT NOT NULL DEFAULT 'unspecified',
                    retrieved_at TEXT NOT NULL DEFAULT '',
                    document_role TEXT NOT NULL DEFAULT 'general',
                    content_hash TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    version TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    source_origin TEXT NOT NULL DEFAULT 'unknown',
                    quality_tier TEXT NOT NULL DEFAULT 'unspecified',
                    retrieved_at TEXT NOT NULL DEFAULT '',
                    document_role TEXT NOT NULL DEFAULT 'general',
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    agent_run_id TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    evidence_ids TEXT NOT NULL,
                    regulation_refs TEXT NOT NULL,
                    substance_ids TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    missing_inputs TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    requires_human_review INTEGER NOT NULL,
                    review_status TEXT NOT NULL,
                    reviewer TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_decisions (
                    id TEXT PRIMARY KEY,
                    finding_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    comment TEXT,
                    edited_conclusion TEXT,
                    audit_log_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "documents", "parse_status", "TEXT NOT NULL DEFAULT 'needs_manual_review'")
            self._ensure_column(connection, "documents", "extracted_fields", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "documents", "missing_fields", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "documents", "needs_manual_review", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "documents", "text_source", "TEXT NOT NULL DEFAULT 'text'")
            self._ensure_column(connection, "regulatory_sources", "source_origin", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(connection, "regulatory_sources", "quality_tier", "TEXT NOT NULL DEFAULT 'unspecified'")
            self._ensure_column(connection, "regulatory_sources", "retrieved_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "regulatory_sources", "document_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(connection, "knowledge_chunks", "source_origin", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(connection, "knowledge_chunks", "quality_tier", "TEXT NOT NULL DEFAULT 'unspecified'")
            self._ensure_column(connection, "knowledge_chunks", "retrieved_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "knowledge_chunks", "document_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(connection, "cases", "review_scenario", "TEXT NOT NULL DEFAULT 'market_access'")
            self._ensure_column(connection, "cases", "check_types", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "cases", "latest_verdict", "TEXT")
            self._ensure_column(connection, "cases", "latest_report_id", "TEXT")

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_case(self, payload: CaseCreate) -> dict[str, Any]:
        row = {
            "id": new_id("case"),
            "title": payload.title,
            "material_type": payload.material_type,
            "target_markets": payload.target_markets,
            "intended_use": payload.intended_use,
            "status": "draft",
            "review_scenario": getattr(payload, "review_scenario", "market_access"),
            "check_types": getattr(payload, "check_types", []),
            "latest_verdict": None,
            "latest_report_id": None,
            "created_at": utc_now(),
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cases
                (id, title, material_type, target_markets, intended_use, status, review_scenario, check_types, latest_verdict, latest_report_id, created_at)
                VALUES
                (:id, :title, :material_type, :target_markets, :intended_use, :status, :review_scenario, :check_types, :latest_verdict, :latest_report_id, :created_at)
                """,
                {**row, "target_markets": json.dumps(row["target_markets"]), "check_types": json.dumps(row["check_types"])},
            )
        return row

    def list_cases(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*,
                       COUNT(d.id) AS document_count,
                       MAX(r.created_at) AS latest_report_created_at
                FROM cases c
                LEFT JOIN documents d ON d.case_id = c.id
                LEFT JOIN reports r ON r.id = c.latest_report_id
                GROUP BY c.id
                ORDER BY c.created_at DESC
                """
            ).fetchall()
        return [self._case_summary_from_row(row) for row in rows]

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return self._case_from_row(row) if row else None

    def delete_cases(self) -> dict[str, int]:
        with self._lock, self.connect() as connection:
            case_count = connection.execute("SELECT COUNT(*) AS count FROM cases").fetchone()["count"]
            document_count = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            report_count = connection.execute("SELECT COUNT(*) AS count FROM reports").fetchone()["count"]
            connection.execute("DELETE FROM review_decisions")
            connection.execute("DELETE FROM audit_logs")
            connection.execute("DELETE FROM findings")
            connection.execute("DELETE FROM agent_runs")
            connection.execute("DELETE FROM material_components")
            connection.execute("DELETE FROM extracted_sections")
            connection.execute("DELETE FROM extraction_reviews")
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM reports")
            connection.execute("DELETE FROM cases")
        return {
            "deleted_cases": int(case_count or 0),
            "deleted_documents": int(document_count or 0),
            "deleted_reports": int(report_count or 0),
        }

    def update_case_review_state(
        self,
        *,
        case_id: str,
        status: str,
        latest_verdict: str | None,
        latest_report_id: str | None,
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                UPDATE cases
                SET status = ?, latest_verdict = ?, latest_report_id = COALESCE(?, latest_report_id)
                WHERE id = ?
                """,
                (status, latest_verdict, latest_report_id, case_id),
            )

    def insert_document(
        self,
        *,
        case_id: str,
        document_type: str,
        filename: str,
        source_name: str | None,
        content_type: str | None,
        sha256: str,
        storage_path: str,
        text_content: str,
        metadata: dict[str, Any],
        parse_status: str = "needs_manual_review",
        extracted_fields: dict[str, Any] | None = None,
        missing_fields: list[str] | None = None,
        needs_manual_review: bool = True,
        text_source: str = "text",
    ) -> dict[str, Any]:
        row = {
            "id": new_id("doc"),
            "case_id": case_id,
            "document_type": document_type,
            "filename": filename,
            "source_name": source_name,
            "content_type": content_type,
            "sha256": sha256,
            "storage_path": storage_path,
            "text_content": text_content,
            "metadata": metadata,
            "parse_status": parse_status,
            "extracted_fields": extracted_fields or {},
            "missing_fields": missing_fields or [],
            "needs_manual_review": needs_manual_review,
            "text_source": text_source,
            "created_at": utc_now(),
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO documents
                (id, case_id, document_type, filename, source_name, content_type, sha256, storage_path, text_content,
                 metadata, parse_status, extracted_fields, missing_fields, needs_manual_review, text_source, created_at)
                VALUES (:id, :case_id, :document_type, :filename, :source_name, :content_type, :sha256, :storage_path, :text_content,
                 :metadata, :parse_status, :extracted_fields, :missing_fields, :needs_manual_review, :text_source, :created_at)
                """,
                {
                    **row,
                    "metadata": json.dumps(metadata),
                    "extracted_fields": json.dumps(row["extracted_fields"]),
                    "missing_fields": json.dumps(row["missing_fields"]),
                    "needs_manual_review": 1 if row["needs_manual_review"] else 0,
                },
            )
        return row

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._document_from_row(row) if row else None

    def review_extraction(
        self,
        *,
        document_id: str,
        decision: str,
        reviewer: str,
        comment: str | None,
        edited_fields: dict[str, Any],
    ) -> dict[str, Any]:
        review_id = new_id("extract_review")
        audit_id = new_id("audit")
        created_at = utc_now()
        with self._lock, self.connect() as connection:
            document = connection.execute("SELECT extracted_fields FROM documents WHERE id = ?", (document_id,)).fetchone()
            if not document:
                raise KeyError(document_id)
            current_fields = loads(document["extracted_fields"], {})
            merged_fields = {**current_fields, **edited_fields}
            connection.execute(
                """
                UPDATE documents
                SET extracted_fields = ?, needs_manual_review = ?
                WHERE id = ?
                """,
                (json.dumps(merged_fields), 0 if decision == "approved" else 1, document_id),
            )
            connection.execute(
                """
                INSERT INTO extraction_reviews
                (id, document_id, decision, reviewer, comment, edited_fields, audit_log_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (review_id, document_id, decision, reviewer, comment, json.dumps(edited_fields), audit_id, created_at),
            )
            connection.execute(
                """
                INSERT INTO audit_logs (id, actor, action, target_type, target_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    reviewer,
                    "review_extraction",
                    "document",
                    document_id,
                    json.dumps({"decision": decision, "comment": comment, "edited_fields": edited_fields}),
                    created_at,
                ),
            )
        return {
            "id": review_id,
            "document_id": document_id,
            "decision": decision,
            "reviewer": reviewer,
            "comment": comment,
            "edited_fields": edited_fields,
            "audit_log_id": audit_id,
            "created_at": created_at,
        }

    def insert_sections(self, document_id: str, case_id: str, sections: list[Any]) -> None:
        with self._lock, self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO extracted_sections (id, document_id, case_id, section_number, title, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (new_id("sec"), document_id, case_id, section.number, section.title, section.content, utc_now())
                    for section in sections
                ],
            )

    def insert_components(self, case_id: str, document_id: str, components: list[dict[str, Any]]) -> None:
        with self._lock, self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO material_components
                (id, case_id, document_id, substance_id, name, cas, ec, concentration_min, concentration_max, concentration_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        new_id("cmp"),
                        case_id,
                        document_id,
                        component["substance_id"],
                        component["name"],
                        component["cas"],
                        component.get("ec"),
                        component.get("concentration_min"),
                        component.get("concentration_max"),
                        component.get("concentration_text"),
                        utc_now(),
                    )
                    for component in components
                ],
            )

    def get_documents(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY created_at", (case_id,)).fetchall()
        return [self._document_from_row(row) for row in rows]

    def get_sections(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM extracted_sections WHERE case_id = ? ORDER BY section_number",
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_components(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM material_components WHERE case_id = ? ORDER BY created_at",
                (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_knowledge_source(self, payload: KnowledgeSourceCreate) -> dict[str, Any]:
        row = {
            "id": new_id("src"),
            "title": payload.title,
            "jurisdiction": payload.jurisdiction,
            "source_type": payload.source_type,
            "source_url": str(payload.source_url),
            "version": payload.version,
            "effective_date": payload.effective_date,
            "license_note": payload.license_note,
            "source_origin": payload.source_origin,
            "quality_tier": payload.quality_tier,
            "retrieved_at": payload.retrieved_at,
            "document_role": payload.document_role,
            "content_hash": None,
            "created_at": utc_now(),
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO regulatory_sources
                (id, title, jurisdiction, source_type, source_url, version, effective_date, license_note,
                 source_origin, quality_tier, retrieved_at, document_role, content_hash, created_at)
                VALUES (:id, :title, :jurisdiction, :source_type, :source_url, :version, :effective_date, :license_note,
                 :source_origin, :quality_tier, :retrieved_at, :document_role, :content_hash, :created_at)
                """,
                row,
            )
        return row

    def get_knowledge_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM regulatory_sources WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None

    def insert_knowledge_chunks(self, source_id: str, content_hash: str, chunks: list[dict[str, Any]]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE regulatory_sources SET content_hash = ? WHERE id = ?",
                (content_hash, source_id),
            )
            connection.executemany(
                """
                INSERT INTO knowledge_chunks
                (id, source_id, jurisdiction, source_type, source_url, version, effective_date,
                 source_origin, quality_tier, retrieved_at, document_role, chunk_index, content, tokens, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk["id"],
                        source_id,
                        chunk["jurisdiction"],
                        chunk["source_type"],
                        chunk["source_url"],
                        chunk["version"],
                        chunk["effective_date"],
                        chunk.get("source_origin", "unknown"),
                        chunk.get("quality_tier", "unspecified"),
                        chunk.get("retrieved_at", ""),
                        chunk.get("document_role", "general"),
                        chunk["chunk_index"],
                        chunk["content"],
                        json.dumps(chunk["tokens"]),
                        utc_now(),
                    )
                    for chunk in chunks
                ],
            )

    def delete_knowledge(self) -> dict[str, int]:
        with self._lock, self.connect() as connection:
            chunk_count = connection.execute("SELECT COUNT(*) AS count FROM knowledge_chunks").fetchone()["count"]
            source_count = connection.execute("SELECT COUNT(*) AS count FROM regulatory_sources").fetchone()["count"]
            connection.execute("DELETE FROM knowledge_chunks")
            connection.execute("DELETE FROM regulatory_sources")
        return {"deleted_sources": int(source_count or 0), "deleted_chunks": int(chunk_count or 0)}

    def get_knowledge_sources(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM regulatory_sources ORDER BY created_at, title").fetchall()
        return [dict(row) for row in rows]

    def knowledge_source_chunk_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_id, COUNT(*) AS chunk_count
                FROM knowledge_chunks
                GROUP BY source_id
                """
            ).fetchall()
        return {row["source_id"]: int(row["chunk_count"]) for row in rows}

    def get_knowledge_chunks(self, jurisdiction: str | None = None) -> list[KnowledgeChunk]:
        query = "SELECT * FROM knowledge_chunks"
        params: tuple[Any, ...] = ()
        if jurisdiction:
            query += " WHERE jurisdiction = ?"
            params = (jurisdiction,)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            KnowledgeChunk(
                id=row["id"],
                source_id=row["source_id"],
                jurisdiction=row["jurisdiction"],
                source_type=row["source_type"],
                source_url=row["source_url"],
                version=row["version"],
                effective_date=row["effective_date"],
                content=row["content"],
                tokens=loads(row["tokens"], []),
                source_origin=row["source_origin"],
                quality_tier=row["quality_tier"],
                retrieved_at=row["retrieved_at"],
                document_role=row["document_role"],
            )
            for row in rows
        ]

    def start_agent_run(self, case_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": new_id("run"),
            "case_id": case_id,
            "status": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "metadata": metadata,
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (id, case_id, status, started_at, completed_at, metadata)
                VALUES (:id, :case_id, :status, :started_at, :completed_at, :metadata)
                """,
                {**row, "metadata": json.dumps(metadata)},
            )
        return row

    def complete_agent_run(self, agent_run_id: str, status: str = "completed") -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status, utc_now(), agent_run_id),
            )

    def replace_findings(self, case_id: str, findings: list[dict[str, Any]]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM findings WHERE case_id = ?", (case_id,))
            connection.executemany(
                """
                INSERT INTO findings
                (id, case_id, agent_run_id, jurisdiction, issue_type, severity, conclusion, evidence_ids,
                 regulation_refs, substance_ids, confidence, missing_inputs, recommended_action,
                 requires_human_review, review_status, reviewer, reviewed_at, created_at)
                VALUES
                (:id, :case_id, :agent_run_id, :jurisdiction, :issue_type, :severity, :conclusion, :evidence_ids,
                 :regulation_refs, :substance_ids, :confidence, :missing_inputs, :recommended_action,
                 :requires_human_review, :review_status, :reviewer, :reviewed_at, :created_at)
                """,
                [
                    {
                        **finding,
                        "evidence_ids": json.dumps(finding["evidence_ids"]),
                        "regulation_refs": json.dumps(finding["regulation_refs"]),
                        "substance_ids": json.dumps(finding.get("substance_ids", [])),
                        "missing_inputs": json.dumps(finding.get("missing_inputs", [])),
                        "requires_human_review": 1 if finding.get("requires_human_review", True) else 0,
                        "review_status": finding.get("review_status", "pending"),
                        "reviewer": finding.get("reviewer"),
                        "reviewed_at": finding.get("reviewed_at"),
                    }
                    for finding in findings
                ],
            )

    def get_findings(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM findings WHERE case_id = ? ORDER BY created_at", (case_id,)).fetchall()
        return [self._finding_from_row(row) for row in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
        return self._finding_from_row(row) if row else None

    def review_finding(
        self,
        *,
        finding_id: str,
        decision: str,
        reviewer: str,
        comment: str | None,
        edited_conclusion: str | None,
    ) -> dict[str, Any]:
        decision_id = new_id("review")
        audit_id = new_id("audit")
        created_at = utc_now()
        new_status = decision
        with self._lock, self.connect() as connection:
            if edited_conclusion:
                connection.execute(
                    """
                    UPDATE findings
                    SET review_status = ?, reviewer = ?, reviewed_at = ?, conclusion = ?
                    WHERE id = ?
                    """,
                    (new_status, reviewer, created_at, edited_conclusion, finding_id),
                )
            else:
                connection.execute(
                    "UPDATE findings SET review_status = ?, reviewer = ?, reviewed_at = ? WHERE id = ?",
                    (new_status, reviewer, created_at, finding_id),
                )
            connection.execute(
                """
                INSERT INTO review_decisions
                (id, finding_id, decision, reviewer, comment, edited_conclusion, audit_log_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (decision_id, finding_id, decision, reviewer, comment, edited_conclusion, audit_id, created_at),
            )
            connection.execute(
                """
                INSERT INTO audit_logs (id, actor, action, target_type, target_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    reviewer,
                    "review_finding",
                    "finding",
                    finding_id,
                    json.dumps({"decision": decision, "comment": comment, "edited_conclusion": edited_conclusion}),
                    created_at,
                ),
            )
        return {
            "id": decision_id,
            "finding_id": finding_id,
            "decision": decision,
            "reviewer": reviewer,
            "comment": comment,
            "edited_conclusion": edited_conclusion,
            "audit_log_id": audit_id,
            "created_at": created_at,
        }

    def create_report(self, case_id: str, payload: dict[str, Any], report_format: str = "json") -> dict[str, Any]:
        row = {
            "id": new_id("report"),
            "case_id": case_id,
            "format": report_format,
            "payload_json": json.dumps(payload),
            "created_at": utc_now(),
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO reports (id, case_id, format, payload_json, created_at) VALUES (:id, :case_id, :format, :payload_json, :created_at)",
                row,
            )
        return {**row, "payload": payload}

    def latest_report(self, case_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM reports
                WHERE case_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = loads(data["payload_json"], {})
        data.pop("payload_json", None)
        return data

    def _case_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["target_markets"] = loads(data["target_markets"], [])
        data["check_types"] = loads(data.get("check_types"), [])
        return data

    def _case_summary_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = self._case_from_row(row)
        data["document_count"] = int(data.get("document_count") or 0)
        data["latest_report_created_at"] = data.get("latest_report_created_at")
        return data

    def _document_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = loads(data["metadata"], {})
        data["extracted_fields"] = loads(data.get("extracted_fields"), {})
        data["missing_fields"] = loads(data.get("missing_fields"), [])
        data["needs_manual_review"] = bool(data.get("needs_manual_review", True))
        data.pop("text_content", None)
        return data

    def _finding_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["evidence_ids"] = loads(data["evidence_ids"], [])
        data["regulation_refs"] = loads(data["regulation_refs"], [])
        data["substance_ids"] = loads(data["substance_ids"], [])
        data["missing_inputs"] = loads(data["missing_inputs"], [])
        data["requires_human_review"] = bool(data["requires_human_review"])
        return data
