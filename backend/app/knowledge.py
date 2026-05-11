from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    source_id: str
    jurisdiction: str
    source_type: str
    source_url: str
    version: str
    effective_date: str
    content: str
    tokens: list[str]
    source_origin: str = "unknown"
    quality_tier: str = "unspecified"
    retrieved_at: str = ""
    document_role: str = "general"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def chunk_text(content: str, max_words: int = 140) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for paragraph in paragraphs or [content.strip()]:
        words = paragraph.split()
        if len(current) + len(words) > max_words and current:
            chunks.append(" ".join(current))
            current = []
        current.extend(words)
    if current:
        chunks.append(" ".join(current))
    return chunks


def rank_chunks(query: str, chunks: Iterable[KnowledgeChunk], top_k: int = 5) -> list[KnowledgeChunk]:
    query_tokens = set(tokenize(query))
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        chunk_tokens = set(chunk.tokens)
        exact_cas_bonus = sum(3 for token in query_tokens if "-" in token and token in chunk_tokens)
        overlap = len(query_tokens & chunk_tokens)
        if overlap or exact_cas_bonus:
            scored.append((overlap + exact_cas_bonus, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
