from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai_clients import EmbeddingClient, cosine
from app.knowledge import KnowledgeChunk, tokenize
from app.store import utc_now


@dataclass(frozen=True)
class VectorHit:
    chunk: KnowledgeChunk
    vector_score: float
    keyword_score: float
    rerank_score: float
    rerank_reasons: list[str]


class SQLiteVectorStore:
    EMBEDDING_BATCH_SIZE = 10

    def __init__(self, index_path: str | Path, embedding_client: EmbeddingClient) -> None:
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_client = embedding_client
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    version TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        if not chunks:
            return 0
        existing = self._fresh_ids(chunks)
        pending = [chunk for chunk in chunks if chunk.id not in existing]
        if not pending:
            return 0
        embeddings = []
        for start in range(0, len(pending), self.EMBEDDING_BATCH_SIZE):
            batch = pending[start : start + self.EMBEDDING_BATCH_SIZE]
            embeddings.extend(self.embedding_client.embed_texts([chunk.content for chunk in batch]))
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO vectors
                (chunk_id, source_id, jurisdiction, source_type, source_url, version, effective_date,
                 content, tokens, embedding, embedding_provider, embedding_model, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.source_id,
                        chunk.jurisdiction,
                        chunk.source_type,
                        chunk.source_url,
                        chunk.version,
                        chunk.effective_date,
                        chunk.content,
                        json.dumps(chunk.tokens),
                        json.dumps(embedding),
                        self.embedding_client.last_provider,
                        self.embedding_client.config.embedding_model,
                        utc_now(),
                    )
                    for chunk, embedding in zip(pending, embeddings)
                ],
            )
        return len(pending)

    def sync_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        expected_ids = {chunk.id for chunk in chunks}
        with self.connect() as connection:
            if expected_ids:
                placeholders = ",".join("?" for _ in expected_ids)
                cursor = connection.execute(
                    f"DELETE FROM vectors WHERE chunk_id NOT IN ({placeholders})",
                    tuple(expected_ids),
                )
            else:
                cursor = connection.execute("DELETE FROM vectors")
            pruned = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        self.upsert_chunks(chunks)
        return pruned

    def clear(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM vectors")
            return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

    def search(self, query: str, *, jurisdictions: set[str], top_k: int = 8) -> list[VectorHit]:
        rows = self._rows(jurisdictions)
        if not rows:
            return []
        query_vector = self.embedding_client.embed_texts([query])[0]
        query_tokens = set(tokenize(query))
        query_cas = {token for token in query_tokens if "-" in token}
        hits = []
        for row in rows:
            chunk_tokens = set(json.loads(row["tokens"]))
            vector_score = cosine(query_vector, json.loads(row["embedding"]))
            keyword_overlap = len(query_tokens & chunk_tokens)
            keyword_score = keyword_overlap / max(len(query_tokens), 1)
            rerank_score = vector_score * 0.58 + keyword_score * 0.22
            reasons = []
            cas_hits = sorted(query_cas & chunk_tokens)
            if cas_hits:
                rerank_score += 0.45 + 0.08 * len(cas_hits)
                reasons.append(f"CAS exact match: {', '.join(cas_hits)}")
            if row["jurisdiction"] in jurisdictions:
                rerank_score += 0.12
                reasons.append(f"jurisdiction match: {row['jurisdiction']}")
            for keyword in ["incompatibility", "oxidizer", "flammable", "unknown", "storage", "svhc", "tsca", "sds"]:
                if keyword in query_tokens and keyword in chunk_tokens:
                    rerank_score += 0.05
                    reasons.append(f"keyword match: {keyword}")
            hits.append(
                VectorHit(
                    chunk=self._chunk_from_row(row),
                    vector_score=round(vector_score, 4),
                    keyword_score=round(keyword_score, 4),
                    rerank_score=round(rerank_score, 4),
                    rerank_reasons=reasons or ["semantic vector similarity"],
                )
            )
        hits.sort(key=lambda item: item.rerank_score, reverse=True)
        return hits[:top_k]

    def stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS vector_count,
                       COUNT(DISTINCT source_id) AS source_count,
                       MAX(embedding_provider) AS embedding_provider,
                       MAX(embedding_model) AS embedding_model
                FROM vectors
                """
            ).fetchone()
        return {
            "store_type": "sqlite_vector_store",
            "index_path": str(self.index_path),
            "vector_count": int(row["vector_count"] or 0),
            "source_count": int(row["source_count"] or 0),
            "embedding_provider": row["embedding_provider"] or self.embedding_client.last_provider,
            "embedding_model": row["embedding_model"] or self.embedding_client.config.embedding_model,
        }

    def _fresh_ids(self, chunks: list[KnowledgeChunk]) -> set[str]:
        remote_configured = (
            self.embedding_client.config.embedding_provider in {"auto", "qwen", "openai_compatible"}
            and bool(self.embedding_client.config.base_url)
            and bool(self.embedding_client.config.api_key)
        )
        current_content = {chunk.id: chunk.content for chunk in chunks}
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, content, embedding_provider, embedding_model
                FROM vectors
                """
            ).fetchall()
        fresh_ids = set()
        expected_model = self.embedding_client.config.embedding_model
        for row in rows:
            if current_content.get(row["chunk_id"]) != row["content"]:
                continue
            if row["embedding_model"] != expected_model:
                continue
            if remote_configured and row["embedding_provider"] != "openai_compatible":
                continue
            fresh_ids.add(row["chunk_id"])
        return fresh_ids

    def _rows(self, jurisdictions: set[str]) -> list[sqlite3.Row]:
        if not jurisdictions:
            with self.connect() as connection:
                return connection.execute("SELECT * FROM vectors").fetchall()
        placeholders = ",".join("?" for _ in jurisdictions)
        with self.connect() as connection:
            return connection.execute(f"SELECT * FROM vectors WHERE jurisdiction IN ({placeholders})", tuple(jurisdictions)).fetchall()

    def _chunk_from_row(self, row: sqlite3.Row) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=row["chunk_id"],
            source_id=row["source_id"],
            jurisdiction=row["jurisdiction"],
            source_type=row["source_type"],
            source_url=row["source_url"],
            version=row["version"],
            effective_date=row["effective_date"],
            content=row["content"],
            tokens=json.loads(row["tokens"]),
        )
