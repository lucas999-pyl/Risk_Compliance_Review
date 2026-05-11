from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


Jurisdiction = Literal["CN", "EU", "US", "GLOBAL"]
Severity = Literal["info", "low", "medium", "high", "critical", "review"]
ReviewDecision = Literal["approved", "edited", "rejected"]


class CaseCreate(BaseModel):
    title: str = Field(min_length=1)
    material_type: str = Field(default="mixture")
    target_markets: list[Jurisdiction] = Field(default_factory=lambda: ["CN", "EU", "US"])
    intended_use: str | None = None


class CaseRecord(CaseCreate):
    id: str
    status: str
    created_at: datetime


class DocumentRecord(BaseModel):
    id: str
    case_id: str
    document_type: str
    filename: str
    source_name: str | None = None
    content_type: str | None = None
    sha256: str
    storage_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parse_status: str = "needs_manual_review"
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_manual_review: bool = True
    text_source: str = "text"
    created_at: datetime


class KnowledgeSourceCreate(BaseModel):
    title: str
    jurisdiction: Jurisdiction
    source_type: str
    source_url: HttpUrl | str
    version: str
    effective_date: str
    license_note: str
    source_origin: str = "unknown"
    quality_tier: str = "unspecified"
    retrieved_at: str = ""
    document_role: str = "general"


class KnowledgeSourceRecord(KnowledgeSourceCreate):
    id: str
    content_hash: str | None = None
    created_at: datetime


class KnowledgeIngestRequest(BaseModel):
    source_id: str
    content: str = Field(min_length=1)


class KnowledgeIngestResponse(BaseModel):
    source_id: str
    chunk_count: int


class TechnologyRunCreate(BaseModel):
    case_id: str
    top_k: int = Field(default=4, ge=1, le=20)


class ChemicalRunCreate(BaseModel):
    case_id: str
    top_k: int = Field(default=4, ge=1, le=20)


class ChemicalKnowledgeSearchCreate(BaseModel):
    query: str = Field(min_length=1)
    target_markets: list[Jurisdiction] = Field(default_factory=lambda: ["CN", "EU", "US"])
    top_k: int = Field(default=5, ge=1, le=20)


class FindingRecord(BaseModel):
    id: str
    case_id: str
    agent_run_id: str
    jurisdiction: Jurisdiction
    issue_type: str
    severity: Severity
    conclusion: str
    evidence_ids: list[str]
    regulation_refs: list[str]
    substance_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    missing_inputs: list[str] = Field(default_factory=list)
    recommended_action: str
    requires_human_review: bool = True
    review_status: str = "pending"
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class ReviewDecisionCreate(BaseModel):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1)
    comment: str | None = None
    edited_conclusion: str | None = None


class ReviewDecisionRecord(ReviewDecisionCreate):
    id: str
    finding_id: str
    audit_log_id: str
    created_at: datetime


class ExtractionReviewCreate(BaseModel):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1)
    comment: str | None = None
    edited_fields: dict[str, Any] = Field(default_factory=dict)


class ExtractionReviewRecord(ExtractionReviewCreate):
    id: str
    document_id: str
    audit_log_id: str
    created_at: datetime


class RunReviewResponse(BaseModel):
    agent_run_id: str
    status: str
    finding_count: int
