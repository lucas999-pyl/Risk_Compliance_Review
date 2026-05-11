from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from app.chemistry import KNOWN_SUBSTANCES, normalize_substance
from app.document_parser import parse_document_bytes
from app.ids import new_id
from app.knowledge import chunk_text, content_hash, rank_chunks, tokenize
from app.models import (
    CaseCreate,
    ExtractionReviewCreate,
    KnowledgeIngestRequest,
    KnowledgeSourceCreate,
    ReviewDecisionCreate,
)
from app.store import SQLiteStore, utc_now
from app.vector_store import SQLiteVectorStore


class ComplianceReviewService:
    def __init__(self, store: SQLiteStore, vector_store: SQLiteVectorStore | None = None) -> None:
        self.store = store
        self.vector_store = vector_store

    def create_case(self, payload: CaseCreate) -> dict[str, Any]:
        return self.store.create_case(payload)

    async def add_document(
        self,
        *,
        case_id: str,
        upload: UploadFile,
        document_type: str,
        source_name: str | None,
    ) -> dict[str, Any]:
        self._require_case(case_id)
        raw = await upload.read()
        sha = hashlib.sha256(raw).hexdigest()
        storage_path = self.store.storage_dir / f"{sha}_{Path(upload.filename or 'document').name}"
        storage_path.write_bytes(raw)
        parsed = parse_document_bytes(raw, filename=upload.filename, content_type=upload.content_type)
        document = self.store.insert_document(
            case_id=case_id,
            document_type=document_type,
            filename=upload.filename or "document",
            source_name=source_name,
            content_type=upload.content_type,
            sha256=sha,
            storage_path=str(storage_path),
            text_content=raw.decode("utf-8", errors="ignore"),
            metadata=parsed.metadata,
            parse_status=parsed.parse_status,
            extracted_fields=parsed.extracted_fields,
            missing_fields=parsed.missing_fields,
            needs_manual_review=parsed.needs_manual_review,
            text_source=parsed.text_source,
        )
        self.store.insert_sections(document["id"], case_id, parsed.sections)
        components = []
        for component in parsed.components:
            profile = normalize_substance(component.name, component.cas, component.ec)
            components.append(
                {
                    "substance_id": profile.substance_id,
                    "name": profile.name,
                    "cas": profile.cas,
                    "ec": profile.ec or component.ec,
                    "concentration_min": component.concentration_min,
                    "concentration_max": component.concentration_max,
                    "concentration_text": component.concentration_text,
                }
            )
        self.store.insert_components(case_id, document["id"], components)
        return document

    def review_extraction(self, document_id: str, payload: ExtractionReviewCreate) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return self.store.review_extraction(
            document_id=document_id,
            decision=payload.decision,
            reviewer=payload.reviewer,
            comment=payload.comment,
            edited_fields=payload.edited_fields,
        )

    def create_knowledge_source(self, payload: KnowledgeSourceCreate) -> dict[str, Any]:
        return self.store.create_knowledge_source(payload)

    def ingest_knowledge(self, payload: KnowledgeIngestRequest) -> dict[str, Any]:
        source = self.store.get_knowledge_source(payload.source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Knowledge source not found")
        chunks = []
        for index, chunk in enumerate(chunk_text(payload.content)):
            chunks.append(
                {
                    "id": new_id("chunk"),
                    "jurisdiction": source["jurisdiction"],
                    "source_type": source["source_type"],
                    "source_url": source["source_url"],
                    "version": source["version"],
                    "effective_date": source["effective_date"],
                    "chunk_index": index,
                    "content": chunk,
                    "tokens": tokenize(chunk),
                }
            )
        self.store.insert_knowledge_chunks(payload.source_id, content_hash(payload.content), chunks)
        if self.vector_store:
            source_chunks = self.store.get_knowledge_chunks(jurisdiction=source["jurisdiction"])
            self.vector_store.upsert_chunks([chunk for chunk in source_chunks if chunk.source_id == payload.source_id])
        return {"source_id": payload.source_id, "chunk_count": len(chunks)}

    def run_review(self, case_id: str) -> dict[str, Any]:
        case = self._require_case(case_id)
        documents = self.store.get_documents(case_id)
        sections = self.store.get_sections(case_id)
        components = self.store.get_components(case_id)
        agent_run = self.store.start_agent_run(case_id, {"workflow": "supplier_material_intake_demo_v1"})
        findings = []
        findings.extend(self._intake_findings(case, documents, agent_run["id"]))
        findings.extend(self._extraction_validation_findings(case_id, documents, agent_run["id"]))
        findings.extend(self._sds_structure_findings(case_id, documents, sections, agent_run["id"]))
        findings.extend(self._composition_findings(case_id, documents, components, agent_run["id"]))
        for jurisdiction in case["target_markets"]:
            findings.extend(
                self._jurisdiction_findings(
                    case_id=case_id,
                    jurisdiction=jurisdiction,
                    documents=documents,
                    components=components,
                    agent_run_id=agent_run["id"],
                )
            )
        self.store.replace_findings(case_id, findings)
        self.store.complete_agent_run(agent_run["id"])
        return {"agent_run_id": agent_run["id"], "status": "completed", "finding_count": len(findings)}

    def get_findings(self, case_id: str) -> list[dict[str, Any]]:
        self._require_case(case_id)
        return self.store.get_findings(case_id)

    def review_finding(self, finding_id: str, payload: ReviewDecisionCreate) -> dict[str, Any]:
        finding = self.store.get_finding(finding_id)
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        return self.store.review_finding(
            finding_id=finding_id,
            decision=payload.decision,
            reviewer=payload.reviewer,
            comment=payload.comment,
            edited_conclusion=payload.edited_conclusion,
        )

    def build_report(self, case_id: str) -> dict[str, Any]:
        case = self._require_case(case_id)
        documents = self.store.get_documents(case_id)
        components = self.store.get_components(case_id)
        findings = self.store.get_findings(case_id)
        reviewed = [finding for finding in findings if finding["review_status"] != "pending"]
        high_or_above = [finding for finding in findings if finding["severity"] in {"high", "critical"}]
        follow_up_actions = [
            finding["recommended_action"]
            for finding in findings
            if finding["severity"] in {"review", "medium", "high", "critical"} or finding["missing_inputs"]
        ]
        payload = {
            "report_type": "supplier_material_intake_pre_review",
            "generated_at": utc_now(),
            "disclaimer": "本报告为 AI 辅助预审结果，不构成最终法律或合规意见；最终准入结论必须由具备资质的 EHS/合规人员复核确认。",
            "case": case,
            "summary": {
                "finding_count": len(findings),
                "reviewed_findings": len(reviewed),
                "requires_human_review": sum(1 for finding in findings if finding["requires_human_review"]),
                "high_or_critical": len(high_or_above),
            },
            "document_readiness": {
                "documents": [
                    {
                        "id": document["id"],
                        "filename": document["filename"],
                        "document_type": document["document_type"],
                        "parse_status": document["parse_status"],
                        "text_source": document["text_source"],
                        "missing_fields": document["missing_fields"],
                        "needs_manual_review": document["needs_manual_review"],
                        "extracted_fields": document["extracted_fields"],
                    }
                    for document in documents
                ]
            },
            "composition": {"components": components},
            "jurisdiction_risks": {
                jurisdiction: [finding for finding in findings if finding["jurisdiction"] == jurisdiction]
                for jurisdiction in case["target_markets"]
            },
            "evidence_chain": self._build_evidence_chain(documents, findings),
            "supplier_follow_up_actions": list(dict.fromkeys(follow_up_actions)),
            "findings": findings,
            "documents": documents,
        }
        self.store.create_report(case_id, payload)
        return payload

    def _require_case(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    def _intake_findings(self, case: dict[str, Any], documents: list[dict[str, Any]], agent_run_id: str) -> list[dict[str, Any]]:
        evidence_ids = [doc["id"] for doc in documents] or [case["id"]]
        missing = []
        if not documents:
            missing.append("documents")
        if not case.get("intended_use"):
            missing.append("intended_use")
        if not missing:
            return [
                self._finding(
                    case_id=case["id"],
                    agent_run_id=agent_run_id,
                    jurisdiction="GLOBAL",
                    issue_type="intake_complete",
                    severity="info",
                    conclusion="案件已包含供应商资料和预期用途，可进入物料准入预审流程。",
                    evidence_ids=evidence_ids,
                    regulation_refs=["internal:supplier-intake-workflow-v1"],
                    confidence=0.95,
                    recommended_action="继续执行 SDS 结构、成分和目标法域筛查，并由 EHS 人员复核。",
                    requires_human_review=True,
                )
            ]
        return [
            self._finding(
                case_id=case["id"],
                agent_run_id=agent_run_id,
                jurisdiction="GLOBAL",
                issue_type="missing_intake_information",
                severity="review",
                conclusion="案件资料缺少可靠预审所需的基本输入。",
                evidence_ids=evidence_ids,
                regulation_refs=["internal:supplier-intake-workflow-v1"],
                confidence=0.8,
                missing_inputs=missing,
                recommended_action="补齐缺失的立项信息或供应商资料后再执行后续筛查。",
                requires_human_review=True,
            )
        ]

    def _extraction_validation_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        agent_run_id: str,
    ) -> list[dict[str, Any]]:
        findings = []
        for document in documents:
            if document["parse_status"] == "parse_failed":
                findings.append(
                    self._finding(
                        case_id=case_id,
                        agent_run_id=agent_run_id,
                        jurisdiction="GLOBAL",
                        issue_type="document_parse_failed",
                        severity="review",
                        conclusion=f"{document['filename']} 未能提取机器可读文本，可能是扫描件或受保护 PDF。",
                        evidence_ids=[document["id"]],
                        regulation_refs=["internal:document-ingestion-v1"],
                        confidence=0.7,
                        missing_inputs=document["missing_fields"],
                        recommended_action="要求供应商提供可复制文本的 SDS，或由人工录入关键字段后再执行预审。",
                        requires_human_review=True,
                    )
                )
            elif document["missing_fields"]:
                findings.append(
                    self._finding(
                        case_id=case_id,
                        agent_run_id=agent_run_id,
                        jurisdiction="GLOBAL",
                        issue_type="extraction_fields_need_review",
                        severity="review",
                        conclusion=f"{document['filename']} 已解析，但关键字段仍需人工确认：{', '.join(document['missing_fields'])}。",
                        evidence_ids=[document["id"]],
                        regulation_refs=["internal:extraction-validation-v1"],
                        confidence=0.78,
                        missing_inputs=document["missing_fields"],
                        recommended_action="在放行前由 EHS 或采购合规人员校验抽取字段，并向供应商补件。",
                        requires_human_review=True,
                    )
                )
        return findings

    def _sds_structure_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        agent_run_id: str,
    ) -> list[dict[str, Any]]:
        evidence_ids = [doc["id"] for doc in documents] or [case_id]
        present = {section["section_number"] for section in sections}
        missing = [str(number) for number in range(1, 17) if number not in present]
        if not missing:
            return [
                self._finding(
                    case_id=case_id,
                    agent_run_id=agent_run_id,
                    jurisdiction="GLOBAL",
                    issue_type="sds_16_section_structure",
                    severity="info",
                    conclusion="上传资料包含预期的 SDS 16 章节结构。",
                    evidence_ids=evidence_ids,
                    regulation_refs=["GHS/SDS:16-section-structure", "GB/T 16483 metadata check"],
                    confidence=0.9,
                    recommended_action="复核抽取字段，并继续执行目标法域筛查。",
                    requires_human_review=True,
                )
            ]
        return [
            self._finding(
                case_id=case_id,
                agent_run_id=agent_run_id,
                jurisdiction="GLOBAL",
                issue_type="sds_missing_sections",
                severity="medium",
                conclusion=f"SDS 类资料缺少预期章节：{', '.join(missing)}。",
                evidence_ids=evidence_ids,
                regulation_refs=["GHS/SDS:16-section-structure", "GB/T 16483 metadata check"],
                confidence=0.85,
                missing_inputs=[f"sds_section_{number}" for number in missing],
                recommended_action="在最终复核前，要求供应商提供包含 16 章节的完整 SDS。",
                requires_human_review=True,
            )
        ]

    def _composition_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        components: list[dict[str, Any]],
        agent_run_id: str,
    ) -> list[dict[str, Any]]:
        evidence_ids = [doc["id"] for doc in documents] or [case_id]
        if not components:
            return [
                self._finding(
                    case_id=case_id,
                    agent_run_id=agent_run_id,
                    jurisdiction="GLOBAL",
                    issue_type="composition_not_extracted",
                    severity="review",
                    conclusion="提交资料中未抽取到带 CAS 号和浓度的成分条目。",
                    evidence_ids=evidence_ids,
                    regulation_refs=["internal:composition-normalization-v1"],
                    confidence=0.7,
                    missing_inputs=["cas_numbers", "component_concentrations"],
                    recommended_action="要求供应商提供包含 CAS/EC 标识和浓度范围的成分表。",
                    requires_human_review=True,
                )
            ]
        substance_ids = [component["substance_id"] for component in components]
        return [
            self._finding(
                case_id=case_id,
                agent_run_id=agent_run_id,
                jurisdiction="GLOBAL",
                issue_type="composition_extracted",
                severity="info",
                conclusion=f"已抽取 {len(components)} 个带 CAS 号和浓度的成分，可用于法规筛查。",
                evidence_ids=evidence_ids,
                regulation_refs=["internal:composition-normalization-v1"],
                substance_ids=substance_ids,
                confidence=0.88,
                recommended_action="如涉及保密成分或浓度区间，应向供应商进一步确认披露充分性。",
                requires_human_review=True,
            )
        ]

    def _jurisdiction_findings(
        self,
        *,
        case_id: str,
        jurisdiction: str,
        documents: list[dict[str, Any]],
        components: list[dict[str, Any]],
        agent_run_id: str,
    ) -> list[dict[str, Any]]:
        evidence_ids = [doc["id"] for doc in documents] or [case_id]
        if not components:
            return [
                self._finding(
                    case_id=case_id,
                    agent_run_id=agent_run_id,
                    jurisdiction=jurisdiction,
                    issue_type="insufficient_regulatory_evidence",
                    severity="review",
                    conclusion=f"未抽取到带 CAS 号和浓度的成分，系统无法形成 {jurisdiction} 法域的来源支撑型预审结论。",
                    evidence_ids=evidence_ids,
                    regulation_refs=[f"{jurisdiction}:composition-required"],
                    confidence=0.0,
                    missing_inputs=["cas_numbers", "component_concentrations"],
                    recommended_action="在进行法域筛查前，要求供应商披露包含 CAS 标识和浓度范围的成分信息。",
                    requires_human_review=True,
                )
            ]
        query = " ".join([*(component["cas"] for component in components), *(component["name"] for component in components)])
        chunks = rank_chunks(query, self.store.get_knowledge_chunks(jurisdiction=jurisdiction), top_k=5)
        if not chunks:
            return [
                self._finding(
                    case_id=case_id,
                    agent_run_id=agent_run_id,
                    jurisdiction=jurisdiction,
                    issue_type="insufficient_regulatory_evidence",
                    severity="review",
                    conclusion=f"未检索到与该材料成分匹配的 {jurisdiction} 法规知识片段，系统不能自动形成合规预审结论。",
                    evidence_ids=evidence_ids,
                    regulation_refs=[f"{jurisdiction}:knowledge-base-required"],
                    confidence=0.0,
                    missing_inputs=[f"{jurisdiction}_regulatory_source"],
                    recommended_action="导入官方或客户授权的法规来源后，再使用该法域筛查结果。",
                    requires_human_review=True,
                )
            ]
        if jurisdiction == "CN":
            return self._china_findings(case_id, documents, components, agent_run_id, chunks)
        if jurisdiction == "EU":
            return self._eu_findings(case_id, documents, components, agent_run_id, chunks)
        if jurisdiction == "US":
            return self._us_findings(case_id, documents, components, agent_run_id, chunks)
        return []

    def _china_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        components: list[dict[str, Any]],
        agent_run_id: str,
        chunks: list[Any],
    ) -> list[dict[str, Any]]:
        findings = []
        for component in components:
            profile = KNOWN_SUBSTANCES.get(component["cas"])
            if profile and profile.china_hazardous_demo:
                evidence = self._document_ids(documents) + [chunk.id for chunk in chunks if component["cas"].lower() in chunk.tokens]
                findings.append(
                    self._finding(
                        case_id=case_id,
                        agent_run_id=agent_run_id,
                        jurisdiction="CN",
                        issue_type="regulated_substance_match",
                        severity="high",
                        conclusion=f"{profile.name}（{profile.cas}）命中已加载的中国危险化学品演示筛查数据。",
                        evidence_ids=evidence or self._document_ids(documents),
                        regulation_refs=self._refs(chunks),
                        substance_ids=[profile.substance_id],
                        confidence=0.82,
                        recommended_action="由 EHS 复核中国危险化学品目录适用性以及 SDS/标签义务。",
                        requires_human_review=True,
                    )
                )
        return findings or [
            self._source_backed_no_match(case_id, agent_run_id, "CN", documents, chunks, "regulated_substance_match")
        ]

    def _eu_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        components: list[dict[str, Any]],
        agent_run_id: str,
        chunks: list[Any],
    ) -> list[dict[str, Any]]:
        for component in components:
            profile = KNOWN_SUBSTANCES.get(component["cas"])
            if profile and profile.svhc_demo and (component.get("concentration_max") or 0) >= 0.1:
                return [
                    self._finding(
                        case_id=case_id,
                        agent_run_id=agent_run_id,
                        jurisdiction="EU",
                        issue_type="svhc_threshold_match",
                        severity="high",
                        conclusion=f"{profile.name}（{profile.cas}）命中已加载的欧盟 SVHC 演示筛查数据，且浓度达到或超过 0.1% w/w。",
                        evidence_ids=self._document_ids(documents) + [chunk.id for chunk in chunks],
                        regulation_refs=self._refs(chunks),
                        substance_ids=[profile.substance_id],
                        confidence=0.8,
                        recommended_action="由具备资质的复核人员确认 REACH 候选清单状态、浓度依据以及物品/混合物义务。",
                        requires_human_review=True,
                    )
                ]
        return [
            self._finding(
                case_id=case_id,
                agent_run_id=agent_run_id,
                jurisdiction="EU",
                issue_type="source_backed_no_svhc_demo_match",
                severity="info",
                conclusion="已加载的欧盟演示知识源未对抽取的 CAS 清单产生 SVHC 阈值命中。",
                evidence_ids=self._document_ids(documents) + [chunk.id for chunk in chunks],
                regulation_refs=self._refs(chunks),
                substance_ids=[component["substance_id"] for component in components],
                confidence=0.62,
                recommended_action="仅作为预审信号；批准前应更新候选清单来源并由人员复核确认。",
                requires_human_review=True,
            )
        ]

    def _us_findings(
        self,
        case_id: str,
        documents: list[dict[str, Any]],
        components: list[dict[str, Any]],
        agent_run_id: str,
        chunks: list[Any],
    ) -> list[dict[str, Any]]:
        findings = []
        for component in components:
            profile = KNOWN_SUBSTANCES.get(component["cas"])
            if profile and profile.tsca_active_demo:
                evidence = self._document_ids(documents) + [chunk.id for chunk in chunks if component["cas"].lower() in chunk.tokens]
                findings.append(
                    self._finding(
                        case_id=case_id,
                        agent_run_id=agent_run_id,
                        jurisdiction="US",
                        issue_type="tsca_inventory_match",
                        severity="medium",
                        conclusion=f"{profile.name}（{profile.cas}）命中已加载的美国 TSCA active 演示清单摘录。",
                        evidence_ids=evidence or self._document_ids(documents),
                        regulation_refs=self._refs(chunks),
                        substance_ids=[profile.substance_id],
                        confidence=0.82,
                        recommended_action="通过授权来源确认 TSCA 清单状态以及 OSHA HCS 下的 SDS/标签义务。",
                        requires_human_review=True,
                    )
                )
        return findings or [self._source_backed_no_match(case_id, agent_run_id, "US", documents, chunks, "tsca_inventory_match")]

    def _source_backed_no_match(
        self,
        case_id: str,
        agent_run_id: str,
        jurisdiction: str,
        documents: list[dict[str, Any]],
        chunks: list[Any],
        issue_type: str,
    ) -> dict[str, Any]:
        return self._finding(
            case_id=case_id,
            agent_run_id=agent_run_id,
            jurisdiction=jurisdiction,
            issue_type=f"source_backed_no_{issue_type}",
            severity="info",
            conclusion=f"已加载的 {jurisdiction} 知识源未对 {issue_type} 产生确定性命中。",
            evidence_ids=self._document_ids(documents) + [chunk.id for chunk in chunks],
            regulation_refs=self._refs(chunks),
            confidence=0.6,
            recommended_action="在依赖该未命中信号前，应由复核人员确认来源时效性和适用性。",
            requires_human_review=True,
        )

    def _finding(
        self,
        *,
        case_id: str,
        agent_run_id: str,
        jurisdiction: str,
        issue_type: str,
        severity: str,
        conclusion: str,
        evidence_ids: list[str],
        regulation_refs: list[str],
        confidence: float,
        recommended_action: str,
        requires_human_review: bool,
        missing_inputs: list[str] | None = None,
        substance_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": new_id("finding"),
            "case_id": case_id,
            "agent_run_id": agent_run_id,
            "jurisdiction": jurisdiction,
            "issue_type": issue_type,
            "severity": severity,
            "conclusion": conclusion,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "regulation_refs": list(dict.fromkeys(regulation_refs)),
            "substance_ids": substance_ids or [],
            "confidence": confidence,
            "missing_inputs": missing_inputs or [],
            "recommended_action": recommended_action,
            "requires_human_review": requires_human_review,
            "review_status": "pending",
            "reviewer": None,
            "reviewed_at": None,
            "created_at": utc_now(),
        }

    def _build_evidence_chain(self, documents: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "document_evidence": [
                {"id": document["id"], "filename": document["filename"], "sha256": document["sha256"]}
                for document in documents
            ],
            "regulatory_references": sorted({ref for finding in findings for ref in finding["regulation_refs"]}),
        }

    def _document_ids(self, documents: list[dict[str, Any]]) -> list[str]:
        return [document["id"] for document in documents]

    def _refs(self, chunks: list[Any]) -> list[str]:
        return [f"{chunk.jurisdiction}:{chunk.source_type}:{chunk.version}:{chunk.source_url}" for chunk in chunks]
