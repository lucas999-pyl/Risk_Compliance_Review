from __future__ import annotations

import importlib.util
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.chemistry import KNOWN_SUBSTANCES, normalize_substance
from app.document_parser import parse_document_text
from app.ids import new_id
from app.knowledge import KnowledgeChunk, tokenize
from app.store import SQLiteStore, utc_now


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "golden_dataset"


@dataclass(frozen=True)
class RankedChunk:
    chunk: KnowledgeChunk
    score: float
    rank: int


class TechnologyDemoRunner:
    def __init__(self, store: SQLiteStore, dataset_root: Path = DATASET_ROOT) -> None:
        self.store = store
        self.dataset_root = dataset_root

    def run_trace(self, case_id: str, top_k: int = 4) -> dict[str, Any]:
        manifest = self._load_manifest()
        case = self._case_from_manifest(manifest, case_id)
        document_text = (self.dataset_root / case["document_path"]).read_text(encoding="utf-8")
        parsed = parse_document_text(document_text)
        components = [
            {
                "substance_id": normalize_substance(component.name, component.cas, component.ec).substance_id,
                "name": normalize_substance(component.name, component.cas, component.ec).name,
                "cas": component.cas,
                "ec": component.ec,
                "concentration_min": component.concentration_min,
                "concentration_max": component.concentration_max,
                "concentration_text": component.concentration_text,
            }
            for component in parsed.components
        ]
        query = self._build_query(case, components)
        retrieved = self._retrieve(query, case["target_markets"], top_k)
        rule_hits = self._rule_hits(case, parsed, components, retrieved)
        findings = self._findings(case, parsed, components, retrieved, rule_hits)
        evaluation = self._evaluate_case(case, findings, retrieved)
        nodes = self._nodes(case, parsed, components, query, retrieved, rule_hits, findings, evaluation)
        return {
            "run_id": new_id("techrun"),
            "case_id": case["case_id"],
            "generated_at": utc_now(),
            "graph": {
                "name": "risk_compliance_technical_demo_v1",
                "engine": "langgraph" if self._langgraph_available() else "deterministic_state_graph",
                "langgraph_available": self._langgraph_available(),
                "checkpoint_strategy": "node_state_snapshots",
            },
            "nodes": nodes,
            "retrieval": {
                "mode": "local_vector",
                "queries": [query],
                "chunks": [self._chunk_payload(item) for item in retrieved],
            },
            "rule_hits": rule_hits,
            "findings": findings,
            "evaluation": evaluation,
            "replay": {
                "checkpoint_count": len(nodes),
                "checkpoints": [
                    {
                        "node_id": node["node_id"],
                        "status": node["status"],
                        "output_keys": sorted(node["output"].keys()),
                    }
                    for node in nodes
                ],
            },
        }

    def evaluate_dataset(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        case_results = []
        for case in manifest["cases"]:
            trace = self.run_trace(case["case_id"])
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "title": case["title"],
                    "scenario_tags": case.get("scenario_tags", []),
                    "retrieved_chunk_count": len(trace["retrieval"]["chunks"]),
                    "rule_hit_count": len(trace["rule_hits"]),
                    "finding_count": len(trace["findings"]),
                    "expected_finding_count": len(case["expected_findings"]),
                    "matched_expected_findings": trace["evaluation"]["matched_expected_findings"],
                    "finding_match_rate": trace["evaluation"]["finding_match_rate"],
                    "evidence_coverage": trace["evaluation"]["evidence_coverage"],
                }
            )
        return {
            "dataset_id": manifest["dataset_id"],
            "version": manifest["version"],
            "case_count": len(case_results),
            "generated_at": utc_now(),
            "metrics": {
                "average_finding_match_rate": _average(item["finding_match_rate"] for item in case_results),
                "average_evidence_coverage": _average(item["evidence_coverage"] for item in case_results),
                "average_rule_hits": _average(item["rule_hit_count"] for item in case_results),
                "average_retrieved_chunks": _average(item["retrieved_chunk_count"] for item in case_results),
            },
            "cases": case_results,
        }

    def _load_manifest(self) -> dict[str, Any]:
        return json.loads((self.dataset_root / "manifest.json").read_text(encoding="utf-8"))

    def _case_from_manifest(self, manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
        for case in manifest["cases"]:
            if case["case_id"] == case_id:
                return case
        raise KeyError(case_id)

    def _build_query(self, case: dict[str, Any], components: list[dict[str, Any]]) -> str:
        terms = [case["title"], case["material_type"], case["intended_use"]]
        terms.extend(component["cas"] for component in components)
        terms.extend(component["name"] for component in components)
        return " ".join(str(term) for term in terms if term)

    def _retrieve(self, query: str, jurisdictions: list[str], top_k: int) -> list[RankedChunk]:
        candidates = [
            chunk
            for jurisdiction in jurisdictions
            for chunk in self.store.get_knowledge_chunks(jurisdiction=jurisdiction)
        ]
        query_vector = _vectorize(query)
        scored = []
        for chunk in candidates:
            score = _cosine(query_vector, Counter(chunk.tokens))
            cas_bonus = sum(0.35 for token in query_vector if "-" in token and token in chunk.tokens)
            final_score = score + cas_bonus
            if final_score > 0:
                scored.append((final_score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RankedChunk(chunk=chunk, score=round(score, 4), rank=index + 1)
            for index, (score, chunk) in enumerate(scored[:top_k])
        ]

    def _rule_hits(
        self,
        case: dict[str, Any],
        parsed: Any,
        components: list[dict[str, Any]],
        retrieved: list[RankedChunk],
    ) -> list[dict[str, Any]]:
        hits = []
        section_numbers = {section.number for section in parsed.sections}
        if section_numbers == set(range(1, 17)):
            hits.append(self._rule_hit("sds_16_section_structure", "GLOBAL", ["document"], 0.9))
        elif section_numbers:
            hits.append(self._rule_hit("sds_missing_sections", "GLOBAL", ["document"], 0.85))
        if components:
            hits.append(self._rule_hit("composition_extracted", "GLOBAL", ["document"], 0.88))
        else:
            hits.append(self._rule_hit("composition_not_extracted", "GLOBAL", ["document"], 0.72))

        retrieved_ids = [item.chunk.id for item in retrieved]
        for jurisdiction in case["target_markets"]:
            jurisdiction_chunks = [item for item in retrieved if item.chunk.jurisdiction == jurisdiction]
            if not components or not jurisdiction_chunks:
                hits.append(self._rule_hit("insufficient_regulatory_evidence", jurisdiction, retrieved_ids or ["document"], 0.0))
                continue
            if jurisdiction == "CN":
                for component in components:
                    profile = KNOWN_SUBSTANCES.get(component["cas"])
                    if profile and profile.china_hazardous_demo:
                        hits.append(self._rule_hit("regulated_substance_match", "CN", retrieved_ids, 0.82, [profile.substance_id]))
            if jurisdiction == "EU":
                svhc_hit = False
                for component in components:
                    profile = KNOWN_SUBSTANCES.get(component["cas"])
                    if profile and profile.svhc_demo and (component.get("concentration_max") or 0) >= 0.1:
                        hits.append(self._rule_hit("svhc_threshold_match", "EU", retrieved_ids, 0.8, [profile.substance_id]))
                        svhc_hit = True
                if not svhc_hit:
                    hits.append(self._rule_hit("source_backed_no_svhc_demo_match", "EU", retrieved_ids, 0.62))
            if jurisdiction == "US":
                for component in components:
                    profile = KNOWN_SUBSTANCES.get(component["cas"])
                    if profile and profile.tsca_active_demo:
                        hits.append(self._rule_hit("tsca_inventory_match", "US", retrieved_ids, 0.82, [profile.substance_id]))
        return _dedupe_hits(hits)

    def _findings(
        self,
        case: dict[str, Any],
        parsed: Any,
        components: list[dict[str, Any]],
        retrieved: list[RankedChunk],
        rule_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs = [self._ref(item.chunk) for item in retrieved]
        retrieved_ids = [item.chunk.id for item in retrieved]
        findings = []
        for hit in rule_hits:
            evidence_ids = ["document"] + [evidence for evidence in hit["evidence_ids"] if evidence != "document"]
            if hit["jurisdiction"] == "GLOBAL":
                regulation_refs = ["internal:technical-demo-rule-engine-v1"]
            elif refs:
                regulation_refs = refs
            else:
                regulation_refs = [f"{hit['jurisdiction']}:knowledge-base-required"]
            findings.append(
                {
                    "jurisdiction": hit["jurisdiction"],
                    "issue_type": hit["rule_id"],
                    "severity": self._severity(hit["rule_id"]),
                    "conclusion": self._conclusion(hit["rule_id"], hit["jurisdiction"]),
                    "evidence_ids": list(dict.fromkeys(evidence_ids or retrieved_ids or ["document"])),
                    "regulation_refs": list(dict.fromkeys(regulation_refs)),
                    "substance_ids": hit.get("substance_ids", []),
                    "confidence": hit["confidence"],
                    "requires_human_review": True,
                }
            )
        return findings

    def _evaluate_case(
        self,
        case: dict[str, Any],
        findings: list[dict[str, Any]],
        retrieved: list[RankedChunk],
    ) -> dict[str, Any]:
        actual = {(finding["jurisdiction"], finding["issue_type"]) for finding in findings}
        expected = {(finding["jurisdiction"], finding["issue_type"]) for finding in case["expected_findings"]}
        matched = actual & expected
        evidence_backed = [
            finding
            for finding in findings
            if finding["evidence_ids"] and finding["regulation_refs"]
        ]
        return {
            "case_id": case["case_id"],
            "matched_expected_findings": len(matched),
            "expected_finding_count": len(expected),
            "actual_finding_count": len(actual),
            "finding_match_rate": round(len(matched) / len(expected), 4) if expected else 1.0,
            "evidence_coverage": round(len(evidence_backed) / len(findings), 4) if findings else 0.0,
            "retrieved_chunk_count": len(retrieved),
            "missing_expected_findings": [
                {"jurisdiction": jurisdiction, "issue_type": issue_type}
                for jurisdiction, issue_type in sorted(expected - actual)
            ],
        }

    def _nodes(
        self,
        case: dict[str, Any],
        parsed: Any,
        components: list[dict[str, Any]],
        query: str,
        retrieved: list[RankedChunk],
        rule_hits: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        evaluation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            self._node("load_case", {"case_id": case["case_id"]}, {"title": case["title"], "target_markets": case["target_markets"]}),
            self._node("parse_document", {"document_path": case["document_path"]}, {"section_count": len(parsed.sections), "component_count": len(components), "cas_numbers": parsed.metadata["cas_numbers"]}),
            self._node("vector_retrieve", {"query": query}, {"retrieved_chunk_count": len(retrieved), "top_scores": [item.score for item in retrieved]}),
            self._node("rule_engine", {"component_count": len(components)}, {"rule_hit_count": len(rule_hits), "rule_ids": [hit["rule_id"] for hit in rule_hits]}),
            self._node("synthesize_findings", {"rule_hit_count": len(rule_hits)}, {"finding_count": len(findings), "issue_types": [finding["issue_type"] for finding in findings]}),
            self._node("evaluate", {"expected_count": len(case["expected_findings"])}, evaluation),
        ]

    def _node(self, node_id: str, inputs: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "label": node_id.replace("_", " ").title(),
            "status": "completed",
            "started_at": utc_now(),
            "completed_at": utc_now(),
            "input": inputs,
            "output": output,
        }

    def _rule_hit(
        self,
        rule_id: str,
        jurisdiction: str,
        evidence_ids: list[str],
        confidence: float,
        substance_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "jurisdiction": jurisdiction,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "confidence": confidence,
            "substance_ids": substance_ids or [],
        }

    def _chunk_payload(self, item: RankedChunk) -> dict[str, Any]:
        chunk = item.chunk
        return {
            "rank": item.rank,
            "id": chunk.id,
            "source_id": chunk.source_id,
            "jurisdiction": chunk.jurisdiction,
            "source_type": chunk.source_type,
            "source_url": chunk.source_url,
            "version": chunk.version,
            "effective_date": chunk.effective_date,
            "score": item.score,
            "content": chunk.content,
        }

    def _ref(self, chunk: KnowledgeChunk) -> str:
        return f"{chunk.jurisdiction}:{chunk.source_type}:{chunk.version}:{chunk.source_url}"

    def _severity(self, rule_id: str) -> str:
        if rule_id in {"regulated_substance_match", "svhc_threshold_match"}:
            return "high"
        if rule_id in {"sds_missing_sections", "tsca_inventory_match"}:
            return "medium"
        if rule_id in {"composition_not_extracted", "insufficient_regulatory_evidence"}:
            return "review"
        return "info"

    def _conclusion(self, rule_id: str, jurisdiction: str) -> str:
        labels = {
            "sds_16_section_structure": "SDS 16-section structure detected.",
            "sds_missing_sections": "SDS section gaps detected.",
            "composition_extracted": "CAS composition was extracted for technical review.",
            "composition_not_extracted": "No CAS composition was extracted.",
            "regulated_substance_match": "Regulated substance rule matched for CN.",
            "source_backed_no_svhc_demo_match": "EU retrieval evidence produced no SVHC demo threshold match.",
            "svhc_threshold_match": "EU SVHC demo threshold rule matched.",
            "tsca_inventory_match": "US TSCA active inventory demo rule matched.",
            "insufficient_regulatory_evidence": f"Insufficient source-backed evidence for {jurisdiction}.",
        }
        return labels.get(rule_id, rule_id)

    def _langgraph_available(self) -> bool:
        return importlib.util.find_spec("langgraph") is not None


def _vectorize(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    dot = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for hit in hits:
        key = (hit["jurisdiction"], hit["rule_id"])
        if key not in unique:
            unique[key] = hit
    return list(unique.values())


def _average(values: Any) -> float:
    numbers = list(values)
    return round(sum(numbers) / len(numbers), 4) if numbers else 0.0
