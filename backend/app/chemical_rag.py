from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai_clients import AIClientConfig, EmbeddingClient, LLMClient
from app.chemistry import KNOWN_SUBSTANCES, normalize_substance
from app.document_parser import extract_text_from_bytes, parse_document_bytes, parse_document_text
from app.ids import new_id
from app.knowledge import KnowledgeChunk, chunk_text, content_hash, tokenize
from app.models import KnowledgeSourceCreate
from app.settings import Settings
from app.store import SQLiteStore, utc_now
from app.vector_store import SQLiteVectorStore, VectorHit


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"
DEFAULT_REVIEW_TASK = "请基于上传资料执行化工物料准入风险预审。"
QUERY_PRESETS = [
    {
        "id": "sds_completeness",
        "title": "SDS 完整性与补件判断",
        "query": "请检查供应商 SDS 是否具备 16 章节、供应商信息、修订日期、GHS 分类、CAS/浓度、UN 编号，并列出需要补件的字段。",
        "target_markets": ["CN", "EU", "US"],
        "scenario_tags": ["资料完整性", "SDS", "补件"],
    },
    {
        "id": "cn_eu_market_access",
        "title": "CN/EU 市场准入预审",
        "query": "请判断该清洗剂是否可进入中国和欧盟市场，重点筛查危险化学品目录、REACH/SVHC、SDS 完整性和供应商补件要求。",
        "target_markets": ["CN", "EU"],
        "scenario_tags": ["市场准入", "CN", "EU"],
    },
    {
        "id": "oxidizer_flammable_incompatibility",
        "title": "乙醇/过氧化氢禁忌组合",
        "query": "请审查乙醇 CAS 64-17-5 与过氧化氢 CAS 7722-84-1 在同一配方、同釜混配或同储条件下是否构成可燃液体与氧化剂禁忌组合。",
        "target_markets": ["CN", "EU", "US"],
        "scenario_tags": ["禁忌矩阵", "储运", "工艺安全"],
    },
    {
        "id": "unknown_cas_review",
        "title": "未知 CAS / 保密成分复核",
        "query": "请判断未知 CAS、保密成分、缺 CAS 或缺浓度的供应商资料是否可以自动放行，并列出需要供应商补充的声明或证明。",
        "target_markets": ["CN", "EU", "US"],
        "scenario_tags": ["未知物质", "补件", "复核"],
    },
    {
        "id": "svhc_tsca_screening",
        "title": "SVHC / TSCA 初筛",
        "query": "请基于 ECHA Candidate List 和 EPA TSCA Inventory 证据，对上传配方中的 CAS 进行 EU SVHC 与 US TSCA 初筛，并说明证据版本。",
        "target_markets": ["EU", "US"],
        "scenario_tags": ["SVHC", "TSCA", "法规筛查"],
    },
]
NODE_ORDER = [
    "load_task",
    "parse_sds",
    "parse_formula",
    "rag_retrieve",
    "material_agent",
    "process_agent",
    "storage_agent",
    "regulatory_agent",
    "cross_check",
    "chief_review",
    "evaluate",
]
VERDICT_ORDER = {"合规": 0, "复核": 1, "不合规": 2}
FORMULA_COMPONENT_PATTERN = re.compile(
    r"(?m)^\s*(?:[-*]\s*)?(?P<name>.+?)\s+CAS\s+"
    r"(?P<cas>\d{2,7}-\d{2}-\d)\s+"
    r"(?P<concentration>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
PROCESS_FIELD_PATTERN = re.compile(r"(?m)^\s*(?P<key>温度|压力|关键步骤|设备|工艺名称)\s*[:：]\s*(?P<value>.+?)\s*$")
PROCESS_EXTRA_FIELD_PATTERN = re.compile(r"(?m)^\s*(?P<key>储存条件|储存类别|运输信息)\s*[:：]\s*(?P<value>.+?)\s*$")
TEMPERATURE_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:C|℃)", re.IGNORECASE)
DATE_PATTERN = re.compile(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})")
HARD_STOP_RULES = {
    "incompatibility_oxidizer_flammable",
    "incompatibility_hypochlorite_acid",
    "enterprise_redline_benzene",
}
REVIEW_RULES = {
    "sds_missing_sections",
    "process_parameters_missing",
    "formula_components_missing",
    "unknown_substance_review",
    "knowledge_no_match_review",
    "knowledge_pack_missing_review",
    "hazardous_catalog_match",
    "svhc_threshold_match",
    "flammable_storage_missing",
    "oxidizer_high_temperature_process",
    "sds_revision_outdated",
    "transport_un_mismatch",
}
CHECK_TYPE_LABELS = {
    "intake_readiness": "资料完整性与可审性",
    "ingredient_identity": "成分识别与 CAS/浓度完整性",
    "restricted_substance": "禁限用物质与红线物质筛查",
    "compatibility_risk": "物料相容性与危险组合",
    "sds_key_sections": "SDS 关键章节核查",
    "process_fit": "工艺条件适配性",
    "storage_transport": "储存与运输条件核查",
    "regulatory_screening": "目标市场法规匹配",
    "supplier_evidence_consistency": "供应商声明/检测报告一致性",
    "manual_review": "人工复核与补件建议",
}
LEGACY_CHECK_TYPE_MAP = {
    "document_completeness": ["intake_readiness"],
    "material": ["ingredient_identity", "restricted_substance", "compatibility_risk"],
    "process": ["process_fit"],
    "storage": ["storage_transport"],
    "regulatory": ["regulatory_screening"],
}
CHECK_TYPE_AGENTS = {
    "intake_readiness": "资料完整性",
    "ingredient_identity": "物料",
    "restricted_substance": "法规",
    "compatibility_risk": "储运",
    "sds_key_sections": "资料完整性",
    "process_fit": "工艺",
    "storage_transport": "储运",
    "regulatory_screening": "法规",
    "supplier_evidence_consistency": "资料完整性",
    "manual_review": "资料完整性",
}
AGENT_CHECK_TYPES = {agent: check_type for check_type, agent in CHECK_TYPE_AGENTS.items()}
REVIEW_SCENARIO_LABELS = {
    "market_access": "市场准入预审",
    "substitution": "替代物料评估",
    "supplier_intake": "供应商资料准入",
    "process_introduction": "工艺导入风险评估",
    "storage_safety": "储运与现场安全评估",
}
SCENARIO_RECOMMENDED_CHECK_TYPES = {
    "supplier_intake": (
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "sds_key_sections",
        "supplier_evidence_consistency",
        "manual_review",
    ),
    "substitution": (
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "compatibility_risk",
        "process_fit",
        "storage_transport",
        "manual_review",
    ),
    "market_access": (
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "sds_key_sections",
        "process_fit",
        "storage_transport",
        "regulatory_screening",
    ),
    "process_introduction": (
        "intake_readiness",
        "ingredient_identity",
        "compatibility_risk",
        "process_fit",
        "storage_transport",
        "manual_review",
    ),
    "storage_safety": (
        "intake_readiness",
        "ingredient_identity",
        "compatibility_risk",
        "storage_transport",
        "sds_key_sections",
        "manual_review",
    ),
}
DEFAULT_CHECK_TYPES = SCENARIO_RECOMMENDED_CHECK_TYPES["market_access"]
DOCUMENT_TYPE_LABELS = {
    "sds": "SDS 安全技术说明书",
    "formula": "配方/成分表",
    "process": "工艺说明",
    "storage_transport": "储运资料",
    "regulatory_certificate": "法规/供应商声明",
    "test_report": "检测报告",
    "unknown": "未识别资料",
}
CORE_DOCUMENT_TYPES = ("sds", "formula", "process")
CUSTOMER_FIELD_LABELS = {
    "sds_sections": "SDS 16 章节",
    "supplier": "供应商名称",
    "revision_date": "SDS 修订日期",
    "cas_numbers": "成分 CAS 号",
    "component_concentrations": "成分浓度",
    "process_temperature": "工艺温度",
    "process_pressure": "工艺压力",
    "process_steps": "工艺关键步骤",
    "storage_condition": "储存条件",
    "transport_information": "运输信息",
    "supplier_declaration": "供应商声明",
    "test_report": "检测报告",
    "machine_readable_text": "可复制文字版资料",
}
EMPTY_UPLOADED_DOCUMENT: dict[str, Any] = {
    "filename": "",
    "path": "",
    "content": "",
    "content_type": "text/plain",
    "text_source": "missing",
    "parse_status": "needs_manual_review",
    "sha256": "",
}


@dataclass(frozen=True)
class RankedChunk:
    chunk: KnowledgeChunk
    score: float
    rank: int
    vector_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    rerank_reasons: tuple[str, ...] = ()


class ChemicalRagRunner:
    def __init__(
        self,
        store: SQLiteStore,
        settings: Settings | None = None,
        vector_store: SQLiteVectorStore | None = None,
        dataset_root: Path = DATASET_ROOT,
    ) -> None:
        self.store = store
        self.settings = settings or Settings()
        self.dataset_root = dataset_root
        self.ai_config = AIClientConfig(
            base_url=self.settings.openai_compatible_base_url,
            api_key=self.settings.openai_compatible_api_key,
            embedding_provider=self.settings.chem_rag_embedding_provider if self.settings.enable_llm else "hash",
            embedding_model=self.settings.chem_rag_embedding_model,
            embedding_dimensions=self.settings.chem_rag_embedding_dimensions,
            llm_provider=self.settings.chem_rag_llm_provider if self.settings.enable_llm else "disabled",
            llm_model=self.settings.chem_rag_llm_model,
            timeout_seconds=self.settings.chem_rag_request_timeout_seconds,
        )
        self.embedding_client = vector_store.embedding_client if vector_store else EmbeddingClient(self.ai_config)
        self.vector_store = vector_store or SQLiteVectorStore(
            Path(self.settings.chem_rag_vector_store_dir) / "vectors.sqlite3",
            self.embedding_client,
        )
        self.llm_client = LLMClient(self.ai_config)
        self._knowledge_lock = threading.RLock()

    def run_trace(self, case_id: str, top_k: int = 4, use_llm: bool = True) -> dict[str, Any]:
        manifest = self._load_manifest()
        case = self._case_from_manifest(manifest, case_id)
        documents = {
            "sds": {
                "filename": Path(case["sds_path"]).name,
                "path": case["sds_path"],
                "content": self._read_case_file(case["sds_path"]),
                "content_type": "text/plain",
                "text_source": "dataset",
            },
            "formula": {
                "filename": Path(case["formula_path"]).name,
                "path": case["formula_path"],
                "content": self._read_case_file(case["formula_path"]),
                "content_type": "text/plain",
                "text_source": "dataset",
            },
            "process": {
                "filename": Path(case.get("process_path") or "process.txt").name,
                "path": case.get("process_path", ""),
                "content": self._read_case_file(case.get("process_path")),
                "content_type": "text/plain",
                "text_source": "dataset",
            },
        }
        return self.run_from_documents(
            case=case,
            documents=documents,
            top_k=top_k,
            use_llm=use_llm,
            case_source="dataset",
            include_evaluation=True,
            allow_demo_fallback_retrieval=True,
        )

    def run_uploaded_documents(
        self,
        *,
        title: str,
        case_id: str | None = None,
        review_task: str | None = None,
        review_scenario: str = "market_access",
        check_types: list[str] | None = None,
        target_markets: list[str],
        top_k: int,
        sds: dict[str, Any],
        formula: dict[str, Any],
        process: dict[str, Any],
        package_precheck: dict[str, Any] | None = None,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        case_id = case_id or new_id("upload")
        normalized_scenario = self._normalize_review_scenario(review_scenario)
        normalized_checks = self._normalize_check_types(check_types, normalized_scenario)
        package_precheck = package_precheck or self.build_package_precheck(
            [
                {**sds, "document_type": "sds"},
                {**formula, "document_type": "formula"},
                {**process, "document_type": "process"},
            ],
            review_scenario=normalized_scenario,
            check_types=normalized_checks,
        )
        case = {
            "case_id": case_id,
            "title": title,
            "review_task": (review_task or DEFAULT_REVIEW_TASK).strip() or DEFAULT_REVIEW_TASK,
            "review_scenario": normalized_scenario,
            "check_types": normalized_checks,
            "package_precheck": package_precheck,
            "scenario_tags": ["现场上传", "非预设案例"],
            "target_markets": target_markets,
            "sds_path": sds["filename"],
            "formula_path": formula["filename"],
            "process_path": process["filename"],
            "expected_review": None,
        }
        trace = self.run_from_documents(
            case=case,
            documents={"sds": sds, "formula": formula, "process": process},
            top_k=top_k,
            use_llm=use_llm,
            case_source="uploaded",
            include_evaluation=False,
            allow_demo_fallback_retrieval=False,
        )
        trace["uploaded_documents"] = [
            self._uploaded_document_payload("sds", sds),
            self._uploaded_document_payload("formula", formula),
            self._uploaded_document_payload("process", process),
        ]
        trace["parsed_documents"] = [
            self._parsed_document_payload("sds", sds),
            self._parsed_document_payload("formula", formula),
            self._parsed_document_payload("process", process),
        ]
        trace["package_precheck"] = package_precheck
        trace["customer_report"] = trace["review_workbench"]["customer_report"]
        return trace

    def run_uploaded_document_package(
        self,
        *,
        title: str,
        case_id: str | None = None,
        review_task: str | None = None,
        review_scenario: str = "market_access",
        check_types: list[str] | None = None,
        target_markets: list[str],
        top_k: int,
        documents: list[dict[str, Any]],
        use_llm: bool = True,
    ) -> dict[str, Any]:
        package = self._classify_uploaded_package(documents)
        normalized_scenario = self._normalize_review_scenario(review_scenario)
        normalized_checks = self._normalize_check_types(check_types, normalized_scenario)
        package_precheck = self.build_package_precheck(
            package["original_documents"],
            review_scenario=normalized_scenario,
            check_types=normalized_checks,
        )
        trace = self.run_uploaded_documents(
            title=title,
            case_id=case_id,
            review_task=review_task,
            review_scenario=normalized_scenario,
            check_types=normalized_checks,
            target_markets=target_markets,
            top_k=top_k,
            sds=package["sds"],
            formula=package["formula"],
            process=package["process"],
            package_precheck=package_precheck,
            use_llm=use_llm,
        )
        trace["uploaded_documents"] = [
            self._uploaded_document_payload(item["document_type"], item)
            for item in package["original_documents"]
        ]
        trace["parsed_documents"] = [
            self._parsed_document_payload(item["document_type"], item)
            for item in package["original_documents"]
        ]
        trace["document_classification"] = {
            item["filename"]: item["document_type"]
            for item in package["original_documents"]
            if item.get("filename")
        }
        trace["_classified_documents"] = package["original_documents"]
        return trace

    def uploaded_document_from_bytes(
        self,
        *,
        filename: str,
        content_type: str | None,
        raw: bytes,
    ) -> dict[str, Any]:
        text, text_source = extract_text_from_bytes(raw, filename=filename, content_type=content_type)
        parsed = parse_document_bytes(raw, filename=filename, content_type=content_type)
        return {
            "filename": filename,
            "path": filename,
            "content": text,
            "content_type": content_type,
            "text_source": text_source,
            "parse_status": parsed.parse_status,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "parsed_document": parsed,
        }

    def run_from_documents(
        self,
        *,
        case: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        top_k: int = 4,
        use_llm: bool = True,
        case_source: str,
        include_evaluation: bool,
        allow_demo_fallback_retrieval: bool = False,
    ) -> dict[str, Any]:
        sds_text = documents["sds"]["content"]
        formula_text = documents["formula"]["content"]
        process_text = documents["process"]["content"]
        parsed_sds = parse_document_text(sds_text)
        if documents["sds"].get("parsed_document") is not None:
            parsed_sds = documents["sds"]["parsed_document"]
        formula = self._parse_formula(formula_text)
        process = self._parse_process(process_text)
        components = formula["components"] or self._components_from_sds(parsed_sds)
        knowledge_pack = self._knowledge_pack_payload()
        review_task = str(case.get("review_task") or DEFAULT_REVIEW_TASK).strip() or DEFAULT_REVIEW_TASK
        case["review_task"] = review_task
        case["review_scenario"] = self._normalize_review_scenario(str(case.get("review_scenario") or "market_access"))
        case["check_types"] = self._normalize_check_types(case.get("check_types"), case["review_scenario"])
        query = self._build_query(case, components, process)
        task_decomposition = self._decompose_review_task(review_task, case, parsed_sds, formula, components, process)
        rag_queries = self._build_rag_queries(task_decomposition, case, components, process)
        self._ensure_vector_index()
        retrieval_by_agent = {
            agent_name: self._retrieve(
                agent_query,
                case["target_markets"],
                top_k,
                allow_demo_fallback=allow_demo_fallback_retrieval,
            )
            for agent_name, agent_query in rag_queries.items()
        }
        retrieved = self._merge_retrievals(retrieval_by_agent)

        base_hits = self._base_rule_hits(case, parsed_sds, formula, components, process, retrieved)
        completeness_agent_result = self._with_llm(
            "资料完整性",
            self._completeness_agent(parsed_sds, formula, process, components),
            retrieval_by_agent.get("资料完整性", retrieved),
            enabled=use_llm,
        )
        base_agent_results = {
            "物料": self._material_agent(components),
            "工艺": self._process_agent(components, process),
            "储运": self._storage_agent(components, formula, parsed_sds, process),
            "法规": self._regulatory_agent(case, components, retrieval_by_agent.get("法规", retrieved), parsed_sds),
        }
        sub_agent_results = self._with_llm_concurrently(
            base_agent_results,
            retrieved,
            retrieval_by_agent=retrieval_by_agent,
            enabled=use_llm,
        )
        agent_hits = self._rule_hits_from_agents(sub_agent_results)
        rule_hits = self._dedupe_rule_hits([*base_hits, *agent_hits])
        cross_check = self._cross_check(sub_agent_results, rule_hits)
        chief = self._chief_review(parsed_sds, process, components, sub_agent_results, rule_hits)
        if knowledge_pack["status"] == "missing" and case_source == "uploaded":
            rule_hits = self._dedupe_rule_hits([*rule_hits, self._rule_hit("knowledge_pack_missing_review", "GLOBAL", ["knowledge_base"], 0.99)])
            chief = {
                "verdict": "复核",
                "reasons": ["知识库未加载，不能形成证据充分的预审结论。请先上传官方知识库源文档。"],
                "needs_human": True,
            }
        chief = {
            **chief,
            "source": "rules_first_llm_assisted",
            "llm_used": False,
            "llm_model": self.ai_config.llm_model,
        }
        agent_branches = self._build_agent_branches(
            task_decomposition=task_decomposition,
            rag_queries=rag_queries,
            retrieval_by_agent=retrieval_by_agent,
            agent_results={"资料完整性": completeness_agent_result, **sub_agent_results},
            parsed_sds=parsed_sds,
            formula=formula,
            process=process,
            components=components,
        )
        chief_synthesis = self._chief_synthesis(chief, agent_branches, rule_hits, review_task)
        evidences = self._build_evidences(case, parsed_sds, formula, process, retrieved, rule_hits, case_source=case_source)
        evaluation = self._evaluate_case(case, chief, evidences, retrieved) if include_evaluation else None
        run_id = new_id("chemrun")
        generated_at = utc_now()
        review_workbench = self._build_review_workbench(
            case=case,
            sds_text=sds_text,
            formula_text=formula_text,
            process_text=process_text,
            parsed_sds=parsed_sds,
            formula=formula,
            process=process,
            components=components,
            chief=chief,
            rule_hits=rule_hits,
            evidences=evidences,
            documents=documents,
            review_task=review_task,
            task_decomposition=task_decomposition,
            agent_branches=agent_branches,
            chief_synthesis=chief_synthesis,
            knowledge_pack=knowledge_pack,
            run_id=run_id,
            generated_at=generated_at,
        )
        nodes = self._nodes(
            case=case,
            parsed_sds=parsed_sds,
            formula=formula,
            process=process,
            query=query,
            retrieved=retrieved,
            task_decomposition=task_decomposition,
            rag_queries=rag_queries,
            agent_branches=agent_branches,
            chief_synthesis=chief_synthesis,
            sub_agent_results=sub_agent_results,
            rule_hits=rule_hits,
            cross_check=cross_check,
            chief=chief,
            evaluation=evaluation,
            include_evaluation=include_evaluation,
        )
        findings = self._compat_findings(case, chief, rule_hits, evidences)

        payload = {
            "run_id": run_id,
            "case_id": case["case_id"],
            "case_title": case["title"],
            "case_source": case_source,
            "review_task": review_task,
            "review_scenario": case["review_scenario"],
            "check_types": case["check_types"],
            "knowledge_pack": knowledge_pack,
            "generated_at": generated_at,
            "graph": {
                "name": "chemical_compliance_rag_v1",
                "engine": "langgraph" if self._langgraph_available() else "deterministic_state_graph",
                "langgraph_available": self._langgraph_available(),
                "checkpoint_strategy": "node_state_snapshots",
            },
            "agent_orchestration": {
                "mode": "langgraph" if self._langgraph_available() else "deterministic_state_graph",
                "llm_provider": self.llm_client.last_provider,
                "llm_model": self.ai_config.llm_model,
                "rules_first": True,
            },
            "verdict": chief["verdict"],
            "reasons": chief["reasons"],
            "chief_review": chief,
            "evidences": evidences,
            "sub_agent_results": sub_agent_results,
            "task_decomposition": task_decomposition,
            "rag_queries": rag_queries,
            "agent_branches": agent_branches,
            "chief_synthesis": chief_synthesis,
            "cross_check_score": cross_check["score"],
            "needs_human": chief["needs_human"],
            "trace": {"nodes": nodes},
            "nodes": nodes,
            "retrieval": {
                "mode": "local_vector",
                "strategy": "hybrid_vector_keyword_rerank",
                "vector_store": {"type": "sqlite_vector_store", **self.vector_store.stats()},
                "embedding": {
                    "provider": self.embedding_client.last_provider,
                    "model": self.ai_config.embedding_model,
                    "fallback_error": self.embedding_client.last_error,
                },
                "rerank": {"mode": "rules", "features": ["vector_score", "keyword_score", "cas_exact", "jurisdiction", "domain_keyword"]},
                "queries": list(rag_queries.values()),
                "by_query": {
                    agent_name: {
                        "query": rag_queries[agent_name],
                        "chunks": [self._chunk_payload(item) for item in retrieval_by_agent.get(agent_name, [])],
                    }
                    for agent_name in rag_queries
                },
                "chunks": [self._chunk_payload(item) for item in retrieved],
            },
            "rule_hits": rule_hits,
            "package_precheck": case.get("package_precheck"),
            "findings": findings,
            "review_workbench": review_workbench,
            "customer_report": review_workbench["customer_report"],
            "technical_trace": {
                "task_decomposition": task_decomposition,
                "rag_queries": rag_queries,
                "agent_branches": agent_branches,
                "chief_synthesis": chief_synthesis,
                "retrieval": {
                    "queries": list(rag_queries.values()),
                    "chunk_count": len(retrieved),
                },
                "trace_node_count": len(nodes),
            },
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
        if evaluation is not None:
            payload["evaluation"] = evaluation
        return payload

    def evaluate_dataset(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        case_results = []
        for case in manifest["cases"]:
            trace = self.run_trace(case["case_id"], use_llm=False)
            evaluation = trace["evaluation"]
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "title": case["title"],
                    "scenario_tags": case.get("scenario_tags", []),
                    "expected_verdict": case["expected_verdict"],
                    "actual_verdict": trace["verdict"],
                    "verdict_matched": evaluation["verdict_matched"],
                    "expected_review": case["expected_review"],
                    "needs_human": trace["needs_human"],
                    "retrieved_chunk_count": len(trace["retrieval"]["chunks"]),
                    "rule_hit_count": len(trace["rule_hits"]),
                    "evidence_coverage": evaluation["evidence_coverage"],
                    "cross_check_score": trace["cross_check_score"],
                }
            )
        expected_review_cases = [item for item in case_results if item["expected_review"]]
        review_recall = (
            sum(1 for item in expected_review_cases if item["needs_human"]) / len(expected_review_cases)
            if expected_review_cases
            else 1.0
        )
        evidence_coverage = _average(item["evidence_coverage"] for item in case_results)
        return {
            "dataset_id": manifest["dataset_id"],
            "version": manifest["version"],
            "case_count": len(case_results),
            "generated_at": utc_now(),
            "metrics": {
                "verdict_match_rate": _average(1.0 if item["verdict_matched"] else 0.0 for item in case_results),
                "evidence_coverage": evidence_coverage,
                "average_evidence_coverage": evidence_coverage,
                "review_recall": round(review_recall, 4),
                "average_cross_check_score": _average(item["cross_check_score"] for item in case_results),
                "average_rule_hits": _average(item["rule_hit_count"] for item in case_results),
                "average_retrieved_chunks": _average(item["retrieved_chunk_count"] for item in case_results),
            },
            "cases": case_results,
        }

    def vector_store_status(self) -> dict[str, Any]:
        self._ensure_vector_index()
        stats = self.vector_store.stats()
        return {
            **stats,
            "chunk_count": len(self.store.get_knowledge_chunks()),
            "embedding_provider": stats["embedding_provider"] or self.embedding_client.last_provider,
            "embedding_model": stats["embedding_model"] or self.ai_config.embedding_model,
            "llm_provider": self.llm_client.last_provider,
            "llm_model": self.ai_config.llm_model,
        }

    def knowledge_status(self) -> dict[str, Any]:
        with self._knowledge_lock:
            chunks = self.store.get_knowledge_chunks()
            sources = self.store.get_knowledge_sources()
            self.vector_store.sync_chunks(chunks)
            stats = self.vector_store.stats()
            chunk_counts = self.store.knowledge_source_chunk_counts()
            source_payload = [
                {
                    **source,
                    "chunk_count": chunk_counts.get(source["id"], 0),
                }
                for source in sources
            ]
            return {
                "pack_id": self._load_rules_pack()["pack_id"],
                "pack_version": self._load_rules_pack()["version"],
                "metadata_source": self._knowledge_metadata_source(sources, chunks),
                "knowledge_base": {
                    "source_count": len(sources),
                    "chunk_count": len(chunks),
                },
                "vector_store": stats,
                "embedding": {
                    "provider": stats["embedding_provider"],
                    "model": stats["embedding_model"],
                    "last_error": self.embedding_client.last_error,
                },
                "sources": source_payload,
            }

    def knowledge_chunks(self) -> dict[str, Any]:
        with self._knowledge_lock:
            chunks = self.store.get_knowledge_chunks()
            sources = self.store.get_knowledge_sources()
            metadata_source = self._knowledge_metadata_source(sources, chunks)
            self.vector_store.sync_chunks(chunks)
            stats = self.vector_store.stats()
            source_by_id = {source["id"]: source for source in sources}
            indexed_ids = self._indexed_chunk_ids()
            return {
                "pack_id": self._load_rules_pack()["pack_id"],
                "pack_version": self._load_rules_pack()["version"],
                "metadata_source": metadata_source,
                "source_count": len({chunk.source_id for chunk in chunks}),
                "chunk_count": len(chunks),
                "vector_count": stats["vector_count"],
                "embedding": {
                    "provider": stats["embedding_provider"],
                    "model": stats["embedding_model"],
                    "last_error": self.embedding_client.last_error,
                },
                "chunks": [
                    {
                        "chunk_id": chunk.id,
                        "source_id": chunk.source_id,
                        "source_title": source_by_id.get(chunk.source_id, {}).get("title", chunk.source_id),
                        "jurisdiction": chunk.jurisdiction,
                        "source_type": chunk.source_type,
                        "source_url": chunk.source_url,
                        "version": chunk.version,
                        "effective_date": chunk.effective_date,
                        "source_origin": chunk.source_origin,
                        "quality_tier": chunk.quality_tier,
                        "retrieved_at": chunk.retrieved_at,
                        "document_role": chunk.document_role,
                        "tokens": chunk.tokens,
                        "content": chunk.content,
                        "vector_status": "indexed" if chunk.id in indexed_ids else "missing",
                    }
                    for chunk in chunks
                ],
            }

    def search_knowledge(self, query: str, target_markets: list[str], top_k: int = 5) -> dict[str, Any]:
        markets = target_markets or ["CN", "EU", "US"]
        chunks = self.store.get_knowledge_chunks()
        if not chunks:
            self.vector_store.sync_chunks([])
            stats = self.vector_store.stats()
            return {
                "query": query,
                "target_markets": markets,
                "requires_knowledge_upload": True,
                "retrieval": {
                    "mode": "local_vector",
                    "strategy": "hybrid_vector_keyword_rerank",
                    "vector_store": {"type": "sqlite_vector_store", **stats},
                    "embedding": {
                        "provider": self.embedding_client.last_provider,
                        "model": self.ai_config.embedding_model,
                        "fallback_error": self.embedding_client.last_error,
                    },
                    "rerank": {"mode": "rules", "features": ["vector_score", "keyword_score", "cas_exact", "jurisdiction", "domain_keyword"]},
                    "chunks": [],
                    "message": "知识库未加载，请先上传 manifest_file 和 source_files。",
                },
            }
        self._ensure_vector_index()
        retrieved = self._retrieve(query, markets, top_k)
        stats = self.vector_store.stats()
        return {
            "query": query,
            "target_markets": markets,
            "retrieval": {
                "mode": "local_vector",
                "strategy": "hybrid_vector_keyword_rerank",
                "vector_store": {"type": "sqlite_vector_store", **stats},
                "embedding": {
                    "provider": self.embedding_client.last_provider,
                    "model": self.ai_config.embedding_model,
                    "fallback_error": self.embedding_client.last_error,
                },
                "rerank": {"mode": "rules", "features": ["vector_score", "keyword_score", "cas_exact", "jurisdiction", "domain_keyword"]},
                "chunks": [self._chunk_payload(item) for item in retrieved],
            },
            "requires_knowledge_upload": False,
        }

    def query_presets(self) -> dict[str, Any]:
        return {"presets": QUERY_PRESETS}

    def import_demo_pack(self) -> dict[str, Any]:
        with self._knowledge_lock:
            pack = self._load_rules_pack()
            source_payloads = []
            total_chunks = 0
            self.store.delete_knowledge()
            self.vector_store.clear()
            for source in pack["sources"]:
                content = source["content"]
                created = self.store.create_knowledge_source(
                    KnowledgeSourceCreate(**{key: value for key, value in source.items() if key != "content"})
                )
                chunks = []
                for index, chunk in enumerate(chunk_text(content)):
                    chunks.append(
                        {
                            "id": new_id("chunk"),
                            "jurisdiction": created["jurisdiction"],
                            "source_type": created["source_type"],
                            "source_url": created["source_url"],
                            "version": created["version"],
                            "effective_date": created["effective_date"],
                            "source_origin": created.get("source_origin", "demo"),
                            "quality_tier": created.get("quality_tier", "demo"),
                            "retrieved_at": created.get("retrieved_at", ""),
                            "document_role": created.get("document_role", "demo_rule"),
                            "chunk_index": index,
                            "content": chunk,
                            "tokens": tokenize(chunk),
                        }
                    )
                self.store.insert_knowledge_chunks(created["id"], content_hash(content), chunks)
                total_chunks += len(chunks)
                source_payloads.append({**created, "chunk_count": len(chunks)})
            all_chunks = self.store.get_knowledge_chunks()
            self.vector_store.sync_chunks(all_chunks)
            stats = self.vector_store.stats()
            return {
                "pack_id": pack["pack_id"],
                "pack_version": pack["version"],
                "source_count": len(source_payloads),
                "chunk_count": total_chunks,
                "vector_count": stats["vector_count"],
                "embedding_provider": stats["embedding_provider"],
                "embedding_model": stats["embedding_model"],
                "sources": source_payloads,
            }

    def upload_knowledge_pack(self, manifest: dict[str, Any], source_texts: dict[str, str]) -> dict[str, Any]:
        with self._knowledge_lock:
            warnings: list[str] = []
            source_payloads = []
            total_chunks = 0
            self.store.delete_knowledge()
            self.vector_store.clear()
            for source in manifest.get("sources", []):
                filename = source.get("filename")
                content = source_texts.get(filename or "", "")
                if not filename or not content.strip():
                    warnings.append(f"source file missing or empty: {filename}")
                    continue
                created = self.store.create_knowledge_source(
                    KnowledgeSourceCreate(
                        title=source["title"],
                        jurisdiction=source["jurisdiction"],
                        source_type=source["source_type"],
                        source_url=source["source_url"],
                        version=source["version"],
                        effective_date=source["effective_date"],
                        license_note=source["license_note"],
                        source_origin=source.get("source_origin", "unknown"),
                        quality_tier=source.get("quality_tier", "unspecified"),
                        retrieved_at=source.get("retrieved_at", manifest.get("retrieved_at", "")),
                        document_role=source.get("document_role", "general"),
                    )
                )
                chunks = [
                    {
                        "id": new_id("chunk"),
                        "jurisdiction": created["jurisdiction"],
                        "source_type": created["source_type"],
                        "source_url": created["source_url"],
                        "version": created["version"],
                        "effective_date": created["effective_date"],
                        "source_origin": created["source_origin"],
                        "quality_tier": created["quality_tier"],
                        "retrieved_at": created["retrieved_at"],
                        "document_role": created["document_role"],
                        "chunk_index": index,
                        "content": chunk,
                        "tokens": tokenize(chunk),
                    }
                    for index, chunk in enumerate(chunk_text(content))
                ]
                self.store.insert_knowledge_chunks(created["id"], content_hash(content), chunks)
                total_chunks += len(chunks)
                source_payloads.append({**created, "chunk_count": len(chunks)})
            all_chunks = self.store.get_knowledge_chunks()
            self.vector_store.sync_chunks(all_chunks)
            stats = self.vector_store.stats()
            return {
                "pack_id": manifest.get("pack_id", "uploaded_knowledge_pack"),
                "pack_version": manifest.get("version", "uploaded"),
                "source_count": len(source_payloads),
                "chunk_count": total_chunks,
                "vector_count": stats["vector_count"],
                "embedding": {
                    "provider": stats["embedding_provider"] or self.embedding_client.last_provider,
                    "model": stats["embedding_model"] or self.ai_config.embedding_model,
                    "fallback_error": self.embedding_client.last_error,
                },
                "sources": source_payloads,
                "validation_warnings": warnings,
            }

    def clear_knowledge(self) -> dict[str, Any]:
        with self._knowledge_lock:
            deleted = self.store.delete_knowledge()
            deleted_vectors = self.vector_store.clear()
            stats = self.vector_store.stats()
            return {
                **deleted,
                "deleted_vectors": deleted_vectors,
                "metadata_source": "empty_customer_knowledge_base",
            }

    def retrieval_preview(self, case_id: str, top_k: int = 5) -> dict[str, Any]:
        manifest = self._load_manifest()
        case = self._case_from_manifest(manifest, case_id)
        sds_text = self._read_case_file(case["sds_path"])
        formula_text = self._read_case_file(case["formula_path"])
        process_text = self._read_case_file(case.get("process_path"))
        parsed_sds = parse_document_text(sds_text)
        formula = self._parse_formula(formula_text)
        process = self._parse_process(process_text)
        components = formula["components"] or self._components_from_sds(parsed_sds)
        query = self._build_query(case, components, process)
        self._ensure_vector_index()
        retrieved = self._retrieve(query, case["target_markets"], top_k)
        stats = self.vector_store.stats()
        return {
            "case_id": case_id,
            "case_title": case["title"],
            "query": query,
            "target_markets": case["target_markets"],
            "components": components,
            "process_fields": process["fields"],
            "retrieval": {
                "strategy": "hybrid_vector_keyword_rerank",
                "vector_store": {"type": "sqlite_vector_store", **stats},
                "embedding": {
                    "provider": self.embedding_client.last_provider,
                    "model": self.ai_config.embedding_model,
                    "fallback_error": self.embedding_client.last_error,
                },
                "rerank": {"mode": "rules", "features": ["vector_score", "keyword_score", "cas_exact", "jurisdiction", "domain_keyword"]},
                "chunks": [self._chunk_payload(item) for item in retrieved],
            },
        }

    def _load_manifest(self) -> dict[str, Any]:
        return json.loads((self.dataset_root / "manifest.json").read_text(encoding="utf-8"))

    def _load_rules_pack(self) -> dict[str, Any]:
        return json.loads((self.dataset_root / "knowledge" / "chemical_rules_pack.json").read_text(encoding="utf-8"))

    def _pack_sources_for_chunks(self) -> list[dict[str, Any]]:
        sources = []
        for index, source in enumerate(self._load_rules_pack()["sources"]):
            sources.append(
                {
                    "id": f"pack_source_{index}",
                    "title": source["title"],
                    "jurisdiction": source["jurisdiction"],
                    "source_type": source["source_type"],
                    "source_url": source["source_url"],
                    "version": source["version"],
                    "effective_date": source["effective_date"],
                    "license_note": source["license_note"],
                    "content_hash": content_hash(source["content"]),
                    "created_at": "2026-05-01T00:00:00Z",
                }
            )
        return sources

    def _indexed_chunk_ids(self) -> set[str]:
        with self.vector_store.connect() as connection:
            rows = connection.execute("SELECT chunk_id FROM vectors").fetchall()
        return {row["chunk_id"] for row in rows}

    def _case_from_manifest(self, manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
        for case in manifest["cases"]:
            if case["case_id"] == case_id:
                return case
        raise KeyError(case_id)

    def _normalize_review_scenario(self, review_scenario: str | None) -> str:
        value = (review_scenario or "market_access").strip()
        return value if value in REVIEW_SCENARIO_LABELS else "market_access"

    def _default_check_types_for_scenario(self, review_scenario: str | None) -> list[str]:
        scenario = self._normalize_review_scenario(review_scenario)
        return list(SCENARIO_RECOMMENDED_CHECK_TYPES.get(scenario, DEFAULT_CHECK_TYPES))

    def _normalize_check_types(self, check_types: object | None, review_scenario: str | None = None) -> list[str]:
        if check_types is None:
            return self._default_check_types_for_scenario(review_scenario)
        if isinstance(check_types, str):
            raw_items = re.split(r"[,，;\s]+", check_types)
        else:
            raw_items = [str(item) for item in check_types if str(item).strip()]
        normalized = []
        for item in raw_items:
            value = item.strip()
            mapped_values = LEGACY_CHECK_TYPE_MAP.get(value, [value])
            for mapped in mapped_values:
                if mapped in CHECK_TYPE_LABELS and mapped not in normalized:
                    normalized.append(mapped)
        return normalized or self._default_check_types_for_scenario(review_scenario)

    def _classify_uploaded_package(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        slots = {
            "sds": self._missing_document("sds"),
            "formula": self._missing_document("formula"),
            "process": self._missing_document("process"),
        }
        original_documents = []
        for document in documents:
            document_type = self._classify_uploaded_document(document)
            typed_document = {**document, "document_type": document_type}
            original_documents.append(typed_document)
            if document_type in slots and slots[document_type].get("text_source") == "missing":
                slots[document_type] = typed_document
        return {**slots, "original_documents": original_documents}

    def _missing_document(self, document_type: str) -> dict[str, Any]:
        return {**EMPTY_UPLOADED_DOCUMENT, "filename": f"missing_{document_type}.txt", "path": f"missing_{document_type}.txt", "document_type": document_type}

    def _classify_uploaded_document(self, document: dict[str, Any]) -> str:
        filename = document.get("filename", "").lower()
        text = document.get("content", "")
        parsed = document.get("parsed_document")
        lowered_text = text.lower()
        if document.get("text_source") == "pdf_unreadable":
            return "unknown"
        if filename.endswith("_sds.txt") or filename.endswith("-sds.txt") or "sds" in filename or "安全技术说明书" in text or "safety data sheet" in lowered_text:
            return "sds"
        if filename.endswith("_formula.txt") or filename.endswith("-formula.txt") or "formula" in filename or "配方" in filename or "成分表" in text or "ingredient" in lowered_text:
            return "formula"
        if filename.endswith("_process.txt") or filename.endswith("-process.txt") or "process" in filename or "工艺" in filename:
            return "process"
        if any(keyword in filename for keyword in ["storage", "transport", "shipping"]) or any(keyword in text for keyword in ["储存条件", "运输信息", "储运"]):
            return "storage_transport"
        if any(keyword in filename for keyword in ["certificate", "declaration", "compliance", "声明", "合规"]) or any(keyword in text for keyword in ["符合性声明", "供应商声明", "REACH", "RoHS", "TSCA"]):
            return "regulatory_certificate"
        if any(keyword in filename for keyword in ["report", "test", "检测", "测试"]) or any(keyword in text for keyword in ["检测报告", "测试报告", "检验报告"]):
            return "test_report"
        if "formula" in filename or "配方" in filename or self._parse_formula(text)["component_count"] > 0:
            return "formula"
        if "process" in filename or "工艺" in filename or self._parse_process(text)["fields"]:
            return "process"
        if parsed is not None and len(parsed.sections) >= 4:
            return "sds"
        return "unknown"

    def build_package_precheck(
        self,
        documents: list[dict[str, Any]],
        *,
        review_scenario: str = "market_access",
        check_types: list[str] | None = None,
    ) -> dict[str, Any]:
        selected_checks = self._normalize_check_types(check_types, review_scenario)
        typed_documents = [
            document if document.get("document_type") else {**document, "document_type": self._classify_uploaded_document(document)}
            for document in documents
            if document.get("text_source") != "missing"
        ]
        document_items = [self._precheck_document_item(document) for document in typed_documents]
        coverage_types = {item["detected_type"] for item in document_items}
        recognized_types = {item["detected_type"] for item in document_items if item["detected_type"] != "unknown"}
        missing_documents = [doc_type for doc_type in CORE_DOCUMENT_TYPES if doc_type not in recognized_types]
        supplement_actions = self._package_supplement_actions(document_items, missing_documents, selected_checks)
        coverage = self._check_coverage(coverage_types, selected_checks)
        if document_items and all(item["readability"] == "unreadable" for item in document_items):
            overall_status = "unreadable"
        elif not document_items or "sds" not in recognized_types or "formula" not in recognized_types:
            overall_status = "needs_supplement"
        elif missing_documents or coverage["limited_checks"] or coverage["blocked_checks"]:
            overall_status = "partial"
        else:
            overall_status = "ready"
        return {
            "overall_status": overall_status,
            "review_scenario": {
                "id": self._normalize_review_scenario(review_scenario),
                "label": REVIEW_SCENARIO_LABELS[self._normalize_review_scenario(review_scenario)],
            },
            "selected_checks": [{"id": item, "label": CHECK_TYPE_LABELS[item]} for item in selected_checks],
            "documents": document_items,
            "recognized_documents": [
                {
                    "type": doc_type,
                    "label": DOCUMENT_TYPE_LABELS.get(doc_type, doc_type),
                    "count": sum(1 for item in document_items if item["detected_type"] == doc_type),
                }
                for doc_type in sorted(recognized_types)
            ],
            "missing_documents": missing_documents,
            "available_checks": coverage["available_checks"],
            "limited_checks": coverage["limited_checks"],
            "blocked_checks": coverage["blocked_checks"],
            "supplement_actions": supplement_actions,
            "user_message": self._package_precheck_message(overall_status, recognized_types, missing_documents),
        }

    def _precheck_document_item(self, document: dict[str, Any]) -> dict[str, Any]:
        document_type = document.get("document_type") or self._classify_uploaded_document(document)
        text = document.get("content", "")
        parsed = document.get("parsed_document")
        if parsed is None:
            parsed = parse_document_text(text)
        readability = self._document_readability(document, parsed)
        recognized_fields = self._recognized_precheck_fields(document_type, text, parsed)
        missing_fields = self._missing_precheck_fields(document_type, recognized_fields, readability)
        confidence = self._document_type_confidence(document_type, recognized_fields, readability)
        return {
            "filename": document.get("filename", "document"),
            "detected_type": document_type,
            "detected_type_label": DOCUMENT_TYPE_LABELS.get(document_type, document_type),
            "readability": readability,
            "confidence": confidence,
            "recognized_fields": recognized_fields,
            "missing_fields": missing_fields,
            "user_message": self._document_precheck_message(document_type, readability, recognized_fields, missing_fields),
        }

    def _document_readability(self, document: dict[str, Any], parsed: Any) -> str:
        if document.get("text_source") == "pdf_unreadable" or getattr(parsed, "text_source", "") == "pdf_unreadable":
            return "unreadable"
        text_length = len(str(document.get("content") or "").strip())
        if text_length < 20:
            return "partially_readable"
        if getattr(parsed, "parse_status", "parsed") == "parse_failed":
            return "unreadable"
        return "readable"

    def _recognized_precheck_fields(self, document_type: str, text: str, parsed: Any) -> list[str]:
        fields: list[str] = []
        extracted = getattr(parsed, "extracted_fields", {}) or {}
        metadata = getattr(parsed, "metadata", {}) or {}
        if extracted.get("supplier"):
            fields.append("supplier")
        if extracted.get("revision_date"):
            fields.append("revision_date")
        if metadata.get("sds_section_numbers"):
            fields.append("sds_sections")
        if metadata.get("cas_numbers"):
            fields.append("cas_numbers")
        if getattr(parsed, "components", []):
            fields.append("component_concentrations")
        formula = self._parse_formula(text)
        if formula["component_count"] > 0 and "cas_numbers" not in fields:
            fields.append("cas_numbers")
        if formula["component_count"] > 0 and "component_concentrations" not in fields:
            fields.append("component_concentrations")
        process = self._parse_process(text)
        process_field_map = {
            "温度": "process_temperature",
            "压力": "process_pressure",
            "关键步骤": "process_steps",
            "储存条件": "storage_condition",
            "储存类别": "storage_condition",
            "运输信息": "transport_information",
        }
        for key, field in process_field_map.items():
            if process["fields"].get(key) and field not in fields:
                fields.append(field)
        if any(keyword in text for keyword in ["符合性声明", "供应商声明", "REACH", "RoHS", "TSCA"]) and "supplier_declaration" not in fields:
            fields.append("supplier_declaration")
        if any(keyword in text for keyword in ["检测报告", "测试报告", "检验报告"]) and "test_report" not in fields:
            fields.append("test_report")
        if document_type == "sds" and "sds_sections" not in fields and len(getattr(parsed, "sections", [])) >= 4:
            fields.append("sds_sections")
        return fields

    def _missing_precheck_fields(self, document_type: str, recognized_fields: list[str], readability: str) -> list[str]:
        if readability == "unreadable":
            return ["machine_readable_text"]
        required = {
            "sds": ["sds_sections", "supplier", "revision_date", "cas_numbers"],
            "formula": ["cas_numbers", "component_concentrations"],
            "process": ["process_temperature", "process_pressure", "process_steps"],
            "storage_transport": ["storage_condition", "transport_information"],
            "regulatory_certificate": ["supplier_declaration"],
            "test_report": ["test_report"],
            "unknown": [],
        }
        return [field for field in required.get(document_type, []) if field not in recognized_fields]

    def _document_type_confidence(self, document_type: str, recognized_fields: list[str], readability: str) -> str:
        if readability == "unreadable" or document_type == "unknown":
            return "low"
        if len(recognized_fields) >= 3:
            return "high"
        return "medium"

    def _document_precheck_message(
        self,
        document_type: str,
        readability: str,
        recognized_fields: list[str],
        missing_fields: list[str],
    ) -> str:
        if readability == "unreadable":
            return "文件无法抽取机器可读文本，请补充可复制文字版 PDF、Word 转文本或原始文本资料。"
        if document_type == "unknown":
            return "系统未能判断该文件属于 SDS、配方、工艺、储运、声明或检测报告，已作为参考资料保留。"
        if missing_fields:
            return f"已识别为{DOCUMENT_TYPE_LABELS.get(document_type, document_type)}，但仍缺少：{'、'.join(self._customer_field_label(item) for item in missing_fields)}。"
        return f"已识别为{DOCUMENT_TYPE_LABELS.get(document_type, document_type)}，可支撑相关预审。"

    def _check_coverage(self, recognized_types: set[str], selected_checks: list[str]) -> dict[str, list[dict[str, str]]]:
        required_by_check = {
            "intake_readiness": set(),
            "ingredient_identity": {"sds", "formula"},
            "restricted_substance": {"sds", "formula"},
            "compatibility_risk": {"formula"},
            "sds_key_sections": {"sds"},
            "process_fit": {"process"},
            "storage_transport": {"sds", "storage_transport"},
            "regulatory_screening": {"sds", "formula"},
            "supplier_evidence_consistency": {"regulatory_certificate", "test_report"},
            "manual_review": set(),
        }
        fallback_by_check = {
            "ingredient_identity": {"unknown", "sds", "formula"},
            "restricted_substance": {"unknown", "sds", "formula"},
            "regulatory_screening": {"unknown", "sds", "formula"},
            "storage_transport": {"sds", "process"},
            "supplier_evidence_consistency": {"sds", "formula", "regulatory_certificate", "test_report"},
        }
        available: list[dict[str, str]] = []
        limited: list[dict[str, str]] = []
        blocked: list[dict[str, str]] = []
        for check_id in selected_checks:
            required = required_by_check.get(check_id, set())
            fallback = fallback_by_check.get(check_id, required)
            item = {"id": check_id, "label": CHECK_TYPE_LABELS[check_id]}
            if not required or required.issubset(recognized_types):
                available.append({**item, "reason": "资料可支撑该检查项。"})
            elif fallback & recognized_types:
                missing = sorted(required - recognized_types)
                limited.append({**item, "reason": f"缺少 {'、'.join(DOCUMENT_TYPE_LABELS.get(doc_type, doc_type) for doc_type in missing)}，结果只能作为初筛或复核依据。"})
            else:
                missing = sorted(required - recognized_types)
                blocked.append({**item, "reason": f"缺少 {'、'.join(DOCUMENT_TYPE_LABELS.get(doc_type, doc_type) for doc_type in missing)}，当前不能形成可靠判断。"})
        return {"available_checks": available, "limited_checks": limited, "blocked_checks": blocked}

    def _package_supplement_actions(
        self,
        document_items: list[dict[str, Any]],
        missing_documents: list[str],
        selected_checks: list[str],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for item in document_items:
            if item["readability"] == "unreadable":
                actions.append(
                    {
                        "field": "machine_readable_text",
                        "action": f"补充 {item['filename']} 的可复制文字版或原始电子文档",
                        "reason": "当前文件无法抽取文本，系统不能识别资料类型和关键字段。",
                        "required_before_release": True,
                    }
                )
        for doc_type in missing_documents:
            actions.append(
                {
                    "field": f"missing_{doc_type}",
                    "action": f"补充{DOCUMENT_TYPE_LABELS[doc_type]}",
                    "reason": "缺少该资料会影响所选检查项的可靠性。",
                    "required_before_release": doc_type in {"sds", "formula"},
                }
            )
        for item in document_items:
            for field in item.get("missing_fields", []):
                if field == "machine_readable_text":
                    continue
                actions.append(
                    {
                        "field": field,
                        "action": f"补充或确认 {item['filename']} 中的 {self._customer_field_label(field)}",
                        "reason": "关键字段缺失会导致相关检查项只能复核或补件。",
                        "required_before_release": field in {"cas_numbers", "component_concentrations", "sds_sections"},
                    }
                )
        return list({(item["field"], item["action"]): item for item in actions}.values())[:10]

    def _package_precheck_message(self, overall_status: str, recognized_types: set[str], missing_documents: list[str]) -> str:
        if overall_status == "unreadable":
            return "资料包中的文件无法抽取机器可读文本，请先补充可读版本。"
        recognized = "、".join(DOCUMENT_TYPE_LABELS.get(item, item) for item in sorted(recognized_types)) or "未识别到核心资料"
        if overall_status == "ready":
            return f"系统已识别 {recognized}，资料包可支撑所选预审。"
        missing = "、".join(DOCUMENT_TYPE_LABELS.get(item, item) for item in missing_documents) or "部分关键字段"
        return f"系统已识别 {recognized}，但仍缺少 {missing}；可继续初筛，最终结论需补件或复核。"

    def _read_case_file(self, relative_path: str | None) -> str:
        if not relative_path:
            return ""
        return (self.dataset_root / relative_path).read_text(encoding="utf-8")

    def _ensure_vector_index(self) -> None:
        chunks = self.store.get_knowledge_chunks()
        self.vector_store.sync_chunks(chunks)

    def _parse_formula(self, text: str) -> dict[str, Any]:
        components = []
        for match in FORMULA_COMPONENT_PATTERN.finditer(text):
            raw_name = match.group("name").strip(" -")
            cas = match.group("cas")
            concentration = float(match.group("concentration"))
            profile = normalize_substance(raw_name, cas)
            components.append(
                {
                    "substance_id": profile.substance_id,
                    "name": profile.name,
                    "raw_name": raw_name,
                    "cas": cas,
                    "ec": profile.ec,
                    "concentration_min": concentration,
                    "concentration_max": concentration,
                    "concentration_text": f"{match.group('concentration')}%",
                    "known": cas in KNOWN_SUBSTANCES,
                    "tags": sorted(profile.tags),
                }
            )
        unresolved_component_lines = [
            line.strip(" -")
            for line in text.splitlines()
            if self._looks_like_unresolved_formula_component(line)
        ]
        missing_fields = []
        if not components:
            missing_fields.append("formula_components")
        if unresolved_component_lines:
            missing_fields.append("formula_component_cas")
        return {
            "component_count": len(components),
            "components": components,
            "missing_fields": missing_fields,
            "unresolved_component_lines": unresolved_component_lines,
            "text": text,
        }

    def _parse_process(self, text: str) -> dict[str, Any]:
        fields = {match.group("key"): match.group("value").strip() for match in PROCESS_FIELD_PATTERN.finditer(text)}
        for match in PROCESS_EXTRA_FIELD_PATTERN.finditer(text):
            fields[match.group("key")] = match.group("value").strip()
        missing = []
        for key in ["温度", "压力", "关键步骤"]:
            value = fields.get(key, "")
            if not value or "未提供" in value:
                missing.append(key)
        temperatures = [float(match.group("value")) for match in TEMPERATURE_PATTERN.finditer(text)]
        return {
            "fields": fields,
            "missing_fields": missing,
            "text": text,
            "temperature_c": max(temperatures) if temperatures else None,
            "is_complete": not missing,
        }

    def _components_from_sds(self, parsed_sds: Any) -> list[dict[str, Any]]:
        components = []
        for component in parsed_sds.components:
            profile = normalize_substance(component.name, component.cas, component.ec)
            components.append(
                {
                    "substance_id": profile.substance_id,
                    "name": profile.name,
                    "raw_name": component.name,
                    "cas": component.cas,
                    "ec": profile.ec or component.ec,
                    "concentration_min": component.concentration_min,
                    "concentration_max": component.concentration_max,
                    "concentration_text": component.concentration_text,
                    "known": component.cas in KNOWN_SUBSTANCES,
                    "tags": sorted(profile.tags),
                }
            )
        return components

    def _build_query(self, case: dict[str, Any], components: list[dict[str, Any]], process: dict[str, Any]) -> str:
        terms = [
            case["title"],
            case.get("review_task", DEFAULT_REVIEW_TASK),
            REVIEW_SCENARIO_LABELS.get(case.get("review_scenario", ""), ""),
            " ".join(CHECK_TYPE_LABELS.get(item, item) for item in case.get("check_types", DEFAULT_CHECK_TYPES)),
            "SDS formula process storage compatibility chemical compliance RAG",
            "incompatibility oxidizer flammable hypochlorite acid benzene unknown substance review TSCA SVHC hazardous catalog storage transport UN revision",
            " ".join(case["target_markets"]),
            " ".join(process["fields"].values()),
        ]
        for component in components:
            terms.extend([component["cas"], component["name"], component.get("raw_name", "")])
            terms.extend(component.get("tags", []))
        return " ".join(str(term) for term in terms if term)

    def _decompose_review_task(
        self,
        review_task: str,
        case: dict[str, Any],
        parsed_sds: Any,
        formula: dict[str, Any],
        components: list[dict[str, Any]],
        process: dict[str, Any],
    ) -> list[dict[str, Any]]:
        component_summary = self._component_summary(components)
        target_markets = "、".join(case.get("target_markets", []))
        missing_sds = "、".join(parsed_sds.missing_fields) if parsed_sds.missing_fields else "无"
        missing_process = "、".join(process.get("missing_fields", [])) if process.get("missing_fields") else "无"
        tasks = [
            {
                "agent": "资料完整性",
                "task_id": "document_completeness",
                "review_task": review_task,
                "objective": "核对 SDS、配方表、工艺说明是否足以支撑合规预审。",
                "inputs": f"SDS 缺失字段：{missing_sds}；工艺缺失字段：{missing_process}；配方成分数：{formula['component_count']}。",
            },
            {
                "agent": "物料",
                "task_id": "material_identification",
                "review_task": review_task,
                "objective": "识别物质 CAS、浓度、危害标签和企业红线信号。",
                "inputs": component_summary,
            },
            {
                "agent": "工艺",
                "task_id": "process_applicability",
                "review_task": review_task,
                "objective": "结合用户任务判断温度、压力、混配步骤与目标用途是否存在工艺安全风险。",
                "inputs": self._process_summary(process),
            },
            {
                "agent": "储运",
                "task_id": "storage_transport_compatibility",
                "review_task": review_task,
                "objective": "判断配方内物质、储存条件和运输信息是否存在兼容性冲突。",
                "inputs": f"{component_summary}；储存条件：{self._storage_value(process, formula)}。",
            },
            {
                "agent": "法规",
                "task_id": "regulatory_screening",
                "review_task": review_task,
                "objective": "面向目标市场执行危化品、SVHC、TSCA/HCS 和内部规则的 RAG 初筛。",
                "inputs": f"目标市场：{target_markets}；{component_summary}。",
            },
        ]
        selected_agents = {CHECK_TYPE_AGENTS[item] for item in self._normalize_check_types(case.get("check_types"), case.get("review_scenario"))}
        return [task for task in tasks if task["agent"] in selected_agents]

    def _build_rag_queries(
        self,
        task_decomposition: list[dict[str, Any]],
        case: dict[str, Any],
        components: list[dict[str, Any]],
        process: dict[str, Any],
    ) -> dict[str, str]:
        base_terms = [
            case["title"],
            " ".join(case.get("target_markets", [])),
            self._component_query_terms(components),
        ]
        agent_terms = {
            "资料完整性": "SDS 16 sections revision date supplier CAS concentration process temperature pressure missing fields document completeness",
            "物料": "CAS EC substance identity hazard tags unknown substance benzene SVHC hazardous catalog",
            "工艺": "process temperature pressure mixing cleaning electronics oxidizer high temperature incompatible operation",
            "储运": "storage transport UN number compatibility oxidizer flammable acid hypochlorite segregation",
            "法规": "CN EU US REACH SVHC TSCA OSHA HCS hazardous chemicals catalog market access",
        }
        queries = {}
        for task in task_decomposition:
            agent = task["agent"]
            terms = [
                task["review_task"],
                task["objective"],
                task["inputs"],
                agent_terms[agent],
                " ".join(base_terms),
                " ".join(process.get("fields", {}).values()),
            ]
            queries[agent] = " ".join(str(term) for term in terms if term)
        return queries

    def _merge_retrievals(self, retrieval_by_agent: dict[str, list[RankedChunk]]) -> list[RankedChunk]:
        unique: dict[str, RankedChunk] = {}
        for items in retrieval_by_agent.values():
            for item in items:
                existing = unique.get(item.chunk.id)
                if existing is None or item.score > existing.score:
                    unique[item.chunk.id] = item
        ranked = sorted(unique.values(), key=lambda item: item.score, reverse=True)
        return [
            RankedChunk(
                chunk=item.chunk,
                score=item.score,
                rank=index + 1,
                vector_score=item.vector_score,
                keyword_score=item.keyword_score,
                rerank_score=item.rerank_score,
                rerank_reasons=item.rerank_reasons,
            )
            for index, item in enumerate(ranked)
        ]

    def _component_summary(self, components: list[dict[str, Any]]) -> str:
        if not components:
            return "未抽取到配方成分。"
        return "；".join(
            f"{component['name']} CAS {component['cas']} {component.get('concentration_text') or ''} tags={','.join(component.get('tags', [])) or '无'}"
            for component in components
        )

    def _component_query_terms(self, components: list[dict[str, Any]]) -> str:
        terms: list[str] = []
        for component in components:
            terms.extend([component.get("cas", ""), component.get("name", ""), component.get("raw_name", "")])
            terms.extend(component.get("tags", []))
        return " ".join(term for term in terms if term)

    def _process_summary(self, process: dict[str, Any]) -> str:
        fields = process.get("fields", {})
        if not fields:
            return "未解析到工艺字段。"
        return "；".join(f"{key}：{value}" for key, value in fields.items())

    def _retrieve(
        self,
        query: str,
        jurisdictions: list[str],
        top_k: int,
        *,
        allow_demo_fallback: bool = False,
    ) -> list[RankedChunk]:
        allowed = set(jurisdictions) | {"GLOBAL"}
        vector_hits = self.vector_store.search(query, jurisdictions=allowed, top_k=max(top_k, 12))
        if vector_hits:
            return [
                RankedChunk(
                    chunk=hit.chunk,
                    score=hit.rerank_score,
                    rank=index + 1,
                    vector_score=hit.vector_score,
                    keyword_score=hit.keyword_score,
                    rerank_score=hit.rerank_score,
                    rerank_reasons=tuple(hit.rerank_reasons),
                )
                for index, hit in enumerate(vector_hits[:top_k])
            ]

        candidates = [chunk for chunk in self.store.get_knowledge_chunks() if chunk.jurisdiction in allowed]
        if not candidates and allow_demo_fallback:
            candidates = self._pack_chunks(allowed)
        candidates = self._dedupe_chunks(candidates)
        if not candidates:
            return []
        query_vector = _vectorize(query)
        scored = []
        for chunk in candidates:
            chunk_vector = Counter(chunk.tokens)
            score = _cosine(query_vector, chunk_vector)
            cas_bonus = sum(0.4 for token in query_vector if "-" in token and token in chunk.tokens)
            keyword_bonus = sum(
                0.12
                for token in query_vector
                if token in {"incompatibility", "oxidizer", "flammable", "unknown", "process", "storage", "tsca", "svhc", "sds"}
                and token in chunk.tokens
            )
            final_score = score + cas_bonus + keyword_bonus
            if final_score > 0:
                scored.append((final_score, chunk))
        if not scored:
            scored = [(0.01, chunk) for chunk in candidates]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RankedChunk(
                chunk=chunk,
                score=round(score, 4),
                rank=index + 1,
                vector_score=round(score, 4),
                keyword_score=round(score, 4),
                rerank_score=round(score, 4),
                rerank_reasons=("fallback lexical score",),
            )
            for index, (score, chunk) in enumerate(scored[:top_k])
        ]

    def _pack_chunks(self, allowed: set[str]) -> list[KnowledgeChunk]:
        chunks = []
        for index, source in enumerate(self._load_rules_pack()["sources"]):
            if source["jurisdiction"] not in allowed:
                continue
            chunks.append(
                KnowledgeChunk(
                    id=f"pack_chunk_{index}",
                    source_id=f"pack_source_{index}",
                    jurisdiction=source["jurisdiction"],
                    source_type=source["source_type"],
                    source_url=source["source_url"],
                    version=source["version"],
                    effective_date=source["effective_date"],
                    content=source["content"],
                    tokens=tokenize(source["content"]),
                    source_origin=source.get("source_origin", "demo"),
                    quality_tier=source.get("quality_tier", "demo"),
                    retrieved_at=source.get("retrieved_at", ""),
                    document_role=source.get("document_role", "demo_rule"),
                )
            )
        return chunks

    def _dedupe_chunks(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
        unique: dict[tuple[str, str, str, str], KnowledgeChunk] = {}
        for chunk in chunks:
            key = (chunk.jurisdiction, chunk.source_type, chunk.version, chunk.content)
            unique.setdefault(key, chunk)
        return list(unique.values())

    def _knowledge_metadata_source(self, sources: list[dict[str, Any]], chunks: list[KnowledgeChunk]) -> str:
        if not chunks:
            return "empty_customer_knowledge_base"
        if any(source.get("source_origin") == "official" for source in sources):
            return "uploaded_knowledge_pack"
        return "sqlite_knowledge_base"

    def _knowledge_pack_payload(self) -> dict[str, Any]:
        chunks = self.store.get_knowledge_chunks()
        sources = self.store.get_knowledge_sources()
        official_count = sum(1 for source in sources if source.get("source_origin") == "official")
        return {
            "status": "loaded" if chunks else "missing",
            "metadata_source": self._knowledge_metadata_source(sources, chunks),
            "source_count": len(sources),
            "official_source_count": official_count,
            "chunk_count": len(chunks),
            "requires_upload": not bool(chunks),
        }

    def _base_rule_hits(
        self,
        case: dict[str, Any],
        parsed_sds: Any,
        formula: dict[str, Any],
        components: list[dict[str, Any]],
        process: dict[str, Any],
        retrieved: list[RankedChunk],
    ) -> list[dict[str, Any]]:
        hits = []
        section_numbers = set(parsed_sds.metadata["sds_section_numbers"])
        if section_numbers == set(range(1, 17)):
            hits.append(self._rule_hit("sds_complete", "GLOBAL", ["sds_document"], 0.92))
        else:
            hits.append(self._rule_hit("sds_missing_sections", "GLOBAL", ["sds_document"], 0.86))
        if formula.get("missing_fields"):
            hits.append(self._rule_hit("formula_components_missing", "GLOBAL", ["formula_document"], 0.82))
        elif components and all(component["known"] for component in components):
            hits.append(self._rule_hit("formula_components_known", "GLOBAL", ["formula_document"], 0.9))
        elif components:
            hits.append(self._rule_hit("unknown_substance_review", "GLOBAL", ["formula_document"], 0.74))
        else:
            hits.append(self._rule_hit("formula_components_missing", "GLOBAL", ["formula_document"], 0.72))
        if process["is_complete"]:
            hits.append(self._rule_hit("process_parameters_present", "GLOBAL", ["process_document"], 0.88))
        else:
            hits.append(self._rule_hit("process_parameters_missing", "GLOBAL", ["process_document"], 0.85))
        if self._has_incompatible_pair(components):
            hits.append(self._rule_hit("incompatibility_oxidizer_flammable", "GLOBAL", ["formula_document", "process_document"], 0.82))
        if self._has_hypochlorite_acid_pair(components):
            hits.append(self._rule_hit("incompatibility_hypochlorite_acid", "GLOBAL", ["formula_document", "process_document"], 0.88))
        if self._has_enterprise_redline(components):
            hits.append(self._rule_hit("enterprise_redline_benzene", "GLOBAL", ["formula_document"], 0.92))
        if self._has_flammable_storage_gap(components, process):
            hits.append(self._rule_hit("flammable_storage_missing", "GLOBAL", ["sds_document", "process_document"], 0.79))
        if self._has_oxidizer_high_temp_process(components, process):
            hits.append(self._rule_hit("oxidizer_high_temperature_process", "GLOBAL", ["sds_document", "process_document"], 0.8))
        if self._is_sds_revision_outdated(parsed_sds):
            hits.append(self._rule_hit("sds_revision_outdated", "GLOBAL", ["sds_document"], 0.82))
        if self._has_transport_un_mismatch(parsed_sds, components, process):
            hits.append(self._rule_hit("transport_un_mismatch", "GLOBAL", ["sds_document", "process_document"], 0.78))
        if not retrieved:
            hits.append(self._rule_hit("knowledge_no_match_review", "GLOBAL", ["knowledge_base"], 0.0))
        return hits

    def _material_agent(self, components: list[dict[str, Any]]) -> dict[str, Any]:
        if not components:
            return self._agent_result("复核", ["formula_components_missing"], ["配方表未抽取到 CAS 和浓度，不能自动放行。"], 0.45)
        unknown = [component for component in components if not component["known"]]
        if unknown:
            cas_list = ", ".join(component["cas"] for component in unknown)
            return self._agent_result("复核", ["unknown_substance_review"], [f"未知物质 CAS {cas_list} 未进入 demo 化学主数据，需人工确认。"], 0.5)
        redline = [component for component in components if "enterprise_redline_demo" in component.get("tags", [])]
        if redline:
            names = "、".join(f"{component['name']}({component['cas']})" for component in redline)
            return self._agent_result("不合规", ["enterprise_redline_benzene"], [f"{names} 命中企业内部准入红线，当前 Demo 判定不合规。"], 0.92)
        hazardous = [component for component in components if "china_hazardous_demo" in component.get("tags", [])]
        if hazardous:
            names = "、".join(f"{component['name']}({component['cas']})" for component in hazardous)
            return self._agent_result("复核", ["hazardous_catalog_match"], [f"{names} 存在危化品目录演示命中信号，需结合用途和储运要求复核。"], 0.72)
        return self._agent_result("合规", ["formula_components_known"], ["配方成分均可识别，未命中物质主数据红线。"], 0.92)

    def _process_agent(self, components: list[dict[str, Any]], process: dict[str, Any]) -> dict[str, Any]:
        if not process["is_complete"]:
            missing = "、".join(process["missing_fields"])
            return self._agent_result("复核", ["process_parameters_missing"], [f"缺少关键工艺参数：{missing}。"], 0.48)
        if self._has_hypochlorite_acid_pair(components) and self._process_indicates_mixing(process):
            return self._agent_result(
                "不合规",
                ["incompatibility_hypochlorite_acid"],
                ["工艺步骤显示次氯酸钠与盐酸同槽或同釜混合，命中酸化次氯酸盐禁忌规则。"],
                0.88,
            )
        if self._has_incompatible_pair(components) and self._process_indicates_mixing(process):
            return self._agent_result(
                "不合规",
                ["incompatibility_oxidizer_flammable"],
                ["工艺步骤显示可燃液体与氧化剂同釜混配，命中禁忌组合规则。"],
                0.82,
            )
        if self._has_oxidizer_high_temp_process(components, process):
            return self._agent_result(
                "复核",
                ["oxidizer_high_temperature_process"],
                ["工艺温度或步骤显示氧化剂存在高温操作，需工艺安全人员确认分解和防护措施。"],
                0.8,
            )
        return self._agent_result("合规", ["process_parameters_present"], ["关键工艺温度、压力和步骤已披露。"], 0.86)

    def _storage_agent(
        self,
        components: list[dict[str, Any]],
        formula: dict[str, Any],
        parsed_sds: Any,
        process: dict[str, Any],
    ) -> dict[str, Any]:
        if self._has_hypochlorite_acid_pair(components):
            return self._agent_result(
                "不合规",
                ["incompatibility_hypochlorite_acid"],
                ["次氯酸盐与酸类不允许按同一储存或使用单元处理，可能释放氯气。"],
                0.88,
            )
        if self._has_incompatible_pair(components):
            return self._agent_result(
                "不合规",
                ["incompatibility_oxidizer_flammable"],
                ["乙醇等可燃液体与过氧化氢等氧化剂不允许按同一兼容储存单元处理。"],
                0.84,
            )
        if any(not component["known"] for component in components):
            return self._agent_result("复核", ["unknown_substance_review"], ["存在未知 CAS，储存兼容性不能自动判定。"], 0.5)
        if self._has_flammable_storage_gap(components, process):
            return self._agent_result(
                "复核",
                ["flammable_storage_missing"],
                ["可燃液体资料未给出明确储存条件、防火隔离、通风或防爆要求。"],
                0.79,
            )
        if self._has_transport_un_mismatch(parsed_sds, components, process):
            return self._agent_result(
                "复核",
                ["transport_un_mismatch"],
                ["运输 UN 编号与可燃液体物料类型不一致，需储运或法规人员复核。"],
                0.78,
            )
        return self._agent_result("合规", ["storage_compatible"], ["未发现配方成分之间的演示禁忌储存组合。"], 0.9)

    def _regulatory_agent(
        self,
        case: dict[str, Any],
        components: list[dict[str, Any]],
        retrieved: list[RankedChunk],
        parsed_sds: Any,
    ) -> dict[str, Any]:
        if any(not component["known"] for component in components):
            return self._agent_result("复核", ["knowledge_no_match_review"], ["未知 CAS 或知识库无命中，不能形成法规自动放行结论。"], 0.44)
        if not retrieved:
            return self._agent_result("复核", ["knowledge_no_match_review"], ["未检索到版本化法规/规则证据。"], 0.4)
        if self._is_sds_revision_outdated(parsed_sds):
            return self._agent_result("复核", ["sds_revision_outdated"], ["SDS 修订日期过旧，需供应商补充有效版本后再判定。"], 0.82)
        if self._has_enterprise_redline(components):
            return self._agent_result("不合规", ["enterprise_redline_benzene"], ["物料命中企业内部红线规则，当前准入预审不放行。"], 0.9)
        svhc = [
            component
            for component in components
            if "svhc_demo" in component.get("tags", []) and (component.get("concentration_max") or 0) >= 0.1
        ]
        if svhc:
            names = "、".join(f"{component['name']}({component['cas']})" for component in svhc)
            return self._agent_result("复核", ["svhc_threshold_match"], [f"{names} 命中 REACH/SVHC 演示阈值，需法规人员复核。"], 0.78)
        hazardous = [component for component in components if "china_hazardous_demo" in component.get("tags", [])]
        if hazardous:
            return self._agent_result("复核", ["hazardous_catalog_match", "tsca_inventory_match"], ["存在危化品/TSCA 演示命中信号，需确认适用义务。"], 0.72)
        return self._agent_result("合规", ["source_backed_no_restricted_demo_match"], ["RAG 已召回版本化证据，未命中禁限用或清单红线演示规则。"], 0.84)

    def _completeness_agent(
        self,
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
        missing = list(parsed_sds.missing_fields)
        if formula.get("missing_fields") or not components:
            missing.extend(formula.get("missing_fields") or ["formula_components"])
        missing.extend([f"工艺{field}" for field in process.get("missing_fields", [])])
        if missing:
            return self._agent_result("复核", ["process_parameters_missing"], [f"资料缺口需复核：{'、'.join(missing)}。"], 0.52)
        return self._agent_result("合规", ["sds_complete", "process_parameters_present"], ["SDS、配方表和工艺关键字段已满足预审输入要求。"], 0.88)

    def _agent_result(self, verdict: str, hit_rules: list[str], reasons: list[str], confidence: float) -> dict[str, Any]:
        return {
            "verdict": verdict,
            "hit_rules": hit_rules,
            "reasons": reasons,
            "evidence_ids": [f"rule:{rule_id}" for rule_id in hit_rules],
            "confidence": round(confidence, 4),
        }

    def _with_llm(self, agent_name: str, result: dict[str, Any], retrieved: list[RankedChunk], *, enabled: bool = True) -> dict[str, Any]:
        if enabled:
            llm = self.llm_client.summarize_agent(
                agent_name=agent_name,
                verdict=result["verdict"],
                reasons=result["reasons"],
                evidence_snippets=[item.chunk.content[:220] for item in retrieved],
            )
        else:
            llm = {
                "llm_used": False,
                "llm_reasoning": "评测模式跳过 LLM 调用，本节点使用规则与检索证据生成确定性解释。",
                "llm_error": None,
            }
        return {
            **result,
            **llm,
            "llm_model": self.ai_config.llm_model,
            "llm_provider": self.llm_client.last_provider,
            "agent_type": "llm_assisted_rule_agent",
        }

    def _with_llm_concurrently(
        self,
        agent_results: dict[str, dict[str, Any]],
        retrieved: list[RankedChunk],
        *,
        retrieval_by_agent: dict[str, list[RankedChunk]] | None = None,
        enabled: bool = True,
    ) -> dict[str, dict[str, Any]]:
        if not enabled or len(agent_results) <= 1:
            return {
                agent_name: self._with_llm(agent_name, result, (retrieval_by_agent or {}).get(agent_name, retrieved), enabled=enabled)
                for agent_name, result in agent_results.items()
            }
        with ThreadPoolExecutor(max_workers=len(agent_results)) as executor:
            futures = {
                agent_name: executor.submit(
                    self._with_llm,
                    agent_name,
                    result,
                    (retrieval_by_agent or {}).get(agent_name, retrieved),
                    enabled=enabled,
                )
                for agent_name, result in agent_results.items()
            }
            return {agent_name: futures[agent_name].result() for agent_name in agent_results}

    def _build_agent_branches(
        self,
        *,
        task_decomposition: list[dict[str, Any]],
        rag_queries: dict[str, str],
        retrieval_by_agent: dict[str, list[RankedChunk]],
        agent_results: dict[str, dict[str, Any]],
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        task_by_agent = {task["agent"]: task for task in task_decomposition}
        summaries = {
            "资料完整性": f"SDS 章节 {len(parsed_sds.sections)}/16；配方成分 {formula['component_count']} 个；工艺缺失 {process.get('missing_fields', []) or ['无']}。",
            "物料": self._component_summary(components),
            "工艺": self._process_summary(process),
            "储运": f"储存条件：{self._storage_value(process, formula)}；UN 编号：{'、'.join(parsed_sds.metadata.get('un_numbers', [])) or '未提供/不适用'}。",
            "法规": f"目标市场法规初筛；CAS：{', '.join(component['cas'] for component in components) or '未抽取'}。",
        }
        branches = {}
        for agent_name, task in task_by_agent.items():
            result = agent_results[agent_name]
            retrieved = retrieval_by_agent.get(agent_name, [])
            evidence_refs = self._branch_evidence_refs(result, retrieved)
            branches[agent_name] = {
                "task": task["objective"],
                "task_id": task["task_id"],
                "input_summary": summaries.get(agent_name, task["inputs"]),
                "rag_query": rag_queries[agent_name],
                "retrieved_chunk_ids": [item.chunk.id for item in retrieved],
                "evidence_refs": evidence_refs,
                "rule_refs": result["hit_rules"],
                "reasoning_steps": self._branch_reasoning_steps(agent_name, result, retrieved),
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "llm_used": result.get("llm_used", False),
                "llm_reasoning": result.get("llm_reasoning", ""),
            }
        return branches

    def _branch_evidence_refs(self, result: dict[str, Any], retrieved: list[RankedChunk]) -> list[str]:
        refs = list(result.get("evidence_ids", []))
        refs.extend(
            f"{item.chunk.jurisdiction}:{item.chunk.source_type}:{item.chunk.version}:{item.chunk.id}"
            for item in retrieved[:3]
        )
        return list(dict.fromkeys(refs))

    def _branch_reasoning_steps(self, agent_name: str, result: dict[str, Any], retrieved: list[RankedChunk]) -> list[str]:
        steps = [
            f"{agent_name} Agent 接收独立审查子任务并生成专属 RAG query。",
            f"从本地向量库召回 {len(retrieved)} 条候选知识 Chunk，并按规则 rerank。",
        ]
        if result["hit_rules"]:
            steps.append(f"规则优先命中：{'、'.join(result['hit_rules'])}。")
        steps.extend(result["reasons"])
        steps.append(f"输出三值判定：{result['verdict']}，置信度 {result['confidence']}。")
        return steps

    def _chief_synthesis(
        self,
        chief: dict[str, Any],
        agent_branches: dict[str, dict[str, Any]],
        rule_hits: list[dict[str, Any]],
        review_task: str,
    ) -> dict[str, Any]:
        hard_stop_rules = sorted({hit["rule_id"] for hit in rule_hits if hit["rule_id"] in HARD_STOP_RULES})
        review_rules = sorted({hit["rule_id"] for hit in rule_hits if hit["rule_id"] in REVIEW_RULES})
        adopted = [
            {
                "agent": agent_name,
                "verdict": branch["verdict"],
                "confidence": branch["confidence"],
                "rule_refs": branch["rule_refs"],
            }
            for agent_name, branch in agent_branches.items()
            if branch["verdict"] == chief["verdict"] or branch["rule_refs"]
        ]
        review_items = []
        for agent_name, branch in agent_branches.items():
            if branch["verdict"] == "复核":
                review_items.append(f"{agent_name}：{'；'.join(branch['reasoning_steps'][-2:])}")
        for hit in rule_hits:
            if hit["rule_id"] == "knowledge_pack_missing_review":
                review_items.append("知识库未加载：请先上传官方知识库源文档后再形成证据充分的预审结论。")
        synthesis = [
            f"主审任务：{review_task}",
            "主审按规则优先原则汇总各 Agent 分支，硬性规则不由 LLM 覆盖。",
            *chief["reasons"],
        ]
        if hard_stop_rules:
            synthesis.append(f"硬性拦截规则优先：{'、'.join(hard_stop_rules)}。")
        if review_rules and not hard_stop_rules:
            synthesis.append(f"需复核规则：{'、'.join(review_rules)}。")
        return {
            "review_task": review_task,
            "final_verdict": chief["verdict"],
            "needs_human": chief["needs_human"],
            "adopted_conclusions": adopted,
            "review_items": review_items,
            "hard_stop_rules": hard_stop_rules,
            "review_rules": review_rules,
            "synthesis": synthesis,
            "rules_first": True,
        }

    def _rule_hits_from_agents(self, sub_agent_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        hits = []
        for agent_name, result in sub_agent_results.items():
            for rule_id in result["hit_rules"]:
                hits.append(
                    self._rule_hit(
                        rule_id,
                        self._jurisdiction_for_rule(rule_id),
                        result["evidence_ids"],
                        result["confidence"],
                        agent=agent_name,
                    )
                )
        return hits

    def _cross_check(self, sub_agent_results: dict[str, dict[str, Any]], rule_hits: list[dict[str, Any]]) -> dict[str, Any]:
        verdicts = {agent: result["verdict"] for agent, result in sub_agent_results.items()}
        distinct = set(verdicts.values())
        hard_stop_rules = [hit["rule_id"] for hit in rule_hits if hit["rule_id"] in HARD_STOP_RULES]
        has_hard_stop = bool(hard_stop_rules)
        has_review = "复核" in distinct
        if len(distinct) == 1 and "合规" in distinct:
            score = 0.92
        elif has_hard_stop and not has_review:
            score = 0.84
        elif has_hard_stop:
            score = 0.76
        elif has_review:
            score = 0.56
        else:
            score = 0.7
        return {
            "score": score,
            "agent_verdicts": verdicts,
            "conflicts": sorted(distinct) if len(distinct) > 1 else [],
            "hard_stop_rules": hard_stop_rules,
        }

    def _chief_review(
        self,
        parsed_sds: Any,
        process: dict[str, Any],
        components: list[dict[str, Any]],
        sub_agent_results: dict[str, dict[str, Any]],
        rule_hits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        reasons = []
        has_formula_missing = any(hit["rule_id"] == "formula_components_missing" for hit in rule_hits)
        missing = list(parsed_sds.missing_fields) + [f"工艺{field}" for field in process["missing_fields"]]
        if has_formula_missing and "formula_components" not in missing:
            missing.append("formula_components")
        unknown = [component for component in components if not component["known"]]
        hard_stop_rules = [hit["rule_id"] for hit in rule_hits if hit["rule_id"] in HARD_STOP_RULES]
        review_rules = [hit["rule_id"] for hit in rule_hits if hit["rule_id"] in REVIEW_RULES]
        if missing:
            reasons.append(f"缺少关键资料或字段：{'、'.join(missing)}。")
        if unknown:
            reasons.append(f"未知物质或知识库无命中：{', '.join(component['cas'] for component in unknown)}。")
        if hard_stop_rules and not missing and not unknown:
            reasons.append(f"命中禁忌/硬性拦截规则：{'、'.join(sorted(set(hard_stop_rules)))}。")
            return {"verdict": "不合规", "reasons": reasons, "needs_human": False}
        if review_rules and not missing and not unknown:
            reasons.append(f"命中复核规则：{'、'.join(sorted(set(review_rules)))}。")
        if missing or unknown or review_rules or any(result["verdict"] == "复核" for result in sub_agent_results.values()):
            if not reasons:
                reasons.append("子 Agent 存在复核结论，主审保守输出复核。")
            return {"verdict": "复核", "reasons": reasons, "needs_human": True}
        reasons.append("SDS 16 章节、CAS/浓度、工艺温压和规则证据完整，未命中禁忌组合或禁限用演示规则。")
        return {"verdict": "合规", "reasons": reasons, "needs_human": False}

    def _build_evidences(
        self,
        case: dict[str, Any],
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        retrieved: list[RankedChunk],
        rule_hits: list[dict[str, Any]],
        *,
        case_source: str = "dataset",
    ) -> list[dict[str, Any]]:
        source_prefix = "uploaded" if case_source == "uploaded" else "dataset"
        evidence_version = "upload-session" if case_source == "uploaded" else "dataset-2026-05-demo"
        effective_date = utc_now()[:10] if case_source == "uploaded" else "2026-05-01"
        evidences = [
            {
                "type": "资料",
                "ref": f"{source_prefix}:{case['sds_path']}",
                "snippet": f"SDS 章节数 {len(parsed_sds.sections)}；缺失字段 {parsed_sds.missing_fields or ['无']}。",
                "version": evidence_version,
                "effective_date": effective_date,
                "source_url": f"{source_prefix}://chemical_rag/{case['sds_path']}",
            },
            {
                "type": "资料",
                "ref": f"{source_prefix}:{case['formula_path']}",
                "snippet": f"配方表抽取成分 {formula['component_count']} 个。",
                "version": evidence_version,
                "effective_date": effective_date,
                "source_url": f"{source_prefix}://chemical_rag/{case['formula_path']}",
            },
            {
                "type": "资料",
                "ref": f"{source_prefix}:{case.get('process_path', 'process')}",
                "snippet": f"工艺字段：{process['fields']}；缺失：{process['missing_fields'] or ['无']}。",
                "version": evidence_version,
                "effective_date": effective_date,
                "source_url": f"{source_prefix}://chemical_rag/{case.get('process_path', 'process')}",
            },
        ]
        for hit in rule_hits:
            source = self._source_for_rule(hit["rule_id"])
            evidences.append(self._evidence_from_source(hit["rule_id"], source, evidence_type="规则"))
        for item in retrieved:
            chunk = item.chunk
            evidences.append(
                {
                    "type": "规则" if chunk.source_type.startswith("internal") else "法规",
                    "ref": f"{chunk.jurisdiction}:{chunk.source_type}:{chunk.version}:{chunk.id}",
                    "snippet": chunk.content[:180],
                    "version": chunk.version,
                    "effective_date": chunk.effective_date,
                    "source_url": chunk.source_url,
                }
            )
        return self._dedupe_evidences(evidences)

    def _evidence_from_source(self, rule_id: str, source: dict[str, Any], evidence_type: str) -> dict[str, Any]:
        return {
            "type": evidence_type,
            "ref": f"rule:{rule_id}:{source['version']}",
            "snippet": self._snippet_for_rule(rule_id, source["content"]),
            "version": source["version"],
            "effective_date": source["effective_date"],
            "source_url": source["source_url"],
        }

    def _source_for_rule(self, rule_id: str) -> dict[str, Any]:
        pack = self._load_rules_pack()
        preferred = {
            "incompatibility_oxidizer_flammable": "企业物质禁忌矩阵演示规则",
            "incompatibility_hypochlorite_acid": "企业物质禁忌矩阵演示规则",
            "storage_compatible": "企业物质禁忌矩阵演示规则",
            "sds_complete": "企业内部化工准入红线演示规则",
            "sds_missing_sections": "企业内部化工准入红线演示规则",
            "process_parameters_present": "企业内部化工准入红线演示规则",
            "process_parameters_missing": "企业内部化工准入红线演示规则",
            "formula_components_known": "企业内部化工准入红线演示规则",
            "formula_components_missing": "企业内部化工准入红线演示规则",
            "unknown_substance_review": "企业内部化工准入红线演示规则",
            "knowledge_no_match_review": "企业内部化工准入红线演示规则",
            "knowledge_pack_missing_review": "企业内部化工准入红线演示规则",
            "sds_revision_outdated": "企业内部化工准入红线演示规则",
            "enterprise_redline_benzene": "企业内部化工准入红线演示规则",
            "flammable_storage_missing": "企业储运兼容性演示规则",
            "transport_un_mismatch": "企业储运兼容性演示规则",
            "oxidizer_high_temperature_process": "企业氧化剂工艺安全演示规则",
            "hazardous_catalog_match": "中国危险化学品目录演示摘录",
            "svhc_threshold_match": "ECHA REACH/SVHC 演示摘录",
            "tsca_inventory_match": "EPA TSCA 与 OSHA HCS 演示摘录",
            "source_backed_no_restricted_demo_match": "EPA TSCA 与 OSHA HCS 演示摘录",
        }
        title = preferred.get(rule_id)
        for source in pack["sources"]:
            if source["title"] == title:
                return source
        return pack["sources"][0]

    def _snippet_for_rule(self, rule_id: str, content: str) -> str:
        position = content.find(rule_id)
        if position < 0:
            return content[:180]
        start = max(0, position - 40)
        end = min(len(content), position + 180)
        return content[start:end]

    def _evaluate_case(
        self,
        case: dict[str, Any],
        chief: dict[str, Any],
        evidences: list[dict[str, Any]],
        retrieved: list[RankedChunk],
    ) -> dict[str, Any]:
        evidence_backed = [
            evidence
            for evidence in evidences
            if evidence.get("version") and evidence.get("effective_date") and evidence.get("ref")
        ]
        return {
            "case_id": case["case_id"],
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": chief["verdict"],
            "verdict_matched": chief["verdict"] == case["expected_verdict"],
            "expected_review": case["expected_review"],
            "needs_human_matched": chief["needs_human"] == case["expected_review"],
            "evidence_coverage": round(len(evidence_backed) / len(evidences), 4) if evidences else 0.0,
            "retrieved_chunk_count": len(retrieved),
        }

    def _build_review_workbench(
        self,
        *,
        case: dict[str, Any],
        sds_text: str,
        formula_text: str,
        process_text: str,
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        components: list[dict[str, Any]],
        chief: dict[str, Any],
        rule_hits: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]] | None = None,
        review_task: str | None = None,
        task_decomposition: list[dict[str, Any]] | None = None,
        agent_branches: dict[str, dict[str, Any]] | None = None,
        chief_synthesis: dict[str, Any] | None = None,
        knowledge_pack: dict[str, Any] | None = None,
        run_id: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        documents = documents or {}
        review_task = review_task or case.get("review_task") or DEFAULT_REVIEW_TASK
        task_decomposition = task_decomposition or []
        agent_branches = agent_branches or {}
        chief_synthesis = chief_synthesis or {}
        source_documents = [
            {
                "type": "SDS",
                "title": "安全技术说明书",
                "path": case["sds_path"],
                "filename": documents.get("sds", {}).get("filename", Path(case["sds_path"]).name),
                "content": sds_text,
                "text_source": documents.get("sds", {}).get("text_source", "text"),
            },
            {
                "type": "配方表",
                "title": "供应商配方表",
                "path": case["formula_path"],
                "filename": documents.get("formula", {}).get("filename", Path(case["formula_path"]).name),
                "content": formula_text,
                "text_source": documents.get("formula", {}).get("text_source", "text"),
            },
            {
                "type": "工艺资料",
                "title": "工艺参数资料",
                "path": case.get("process_path", ""),
                "filename": documents.get("process", {}).get("filename", Path(case.get("process_path", "process.txt")).name),
                "content": process_text,
                "text_source": documents.get("process", {}).get("text_source", "text"),
            },
        ]
        checklist = self._review_checklist(parsed_sds, formula, process, components)
        document_quality = self._document_quality(checklist)
        risk_items = self._review_risk_items(chief, rule_hits, evidences)
        evidence_chain = [
            {
                "ref": evidence["ref"],
                "type": evidence["type"],
                "snippet": evidence["snippet"],
                "version": evidence["version"],
                "effective_date": evidence["effective_date"],
                "source_url": evidence.get("source_url"),
            }
            for evidence in evidences
        ]
        report_summary = self._review_report_summary(case, chief, checklist, risk_items, evidence_chain)
        supplement_actions = self._supplement_actions(document_quality)
        package_precheck = case.get("package_precheck")
        customer_report = self._build_customer_report(
            case=case,
            chief=chief,
            document_quality=document_quality,
            supplement_actions=supplement_actions,
            risk_items=risk_items,
            evidence_chain=evidence_chain,
            package_precheck=package_precheck,
            run_id=run_id,
            generated_at=generated_at,
        )
        return {
            "review_task": review_task,
            "review_scenario": case.get("review_scenario", "market_access"),
            "check_types": self._normalize_check_types(case.get("check_types"), case.get("review_scenario")),
            "knowledge_pack": knowledge_pack or {},
            "task_decomposition": task_decomposition,
            "agent_branch_summary": [
                {
                    "agent": agent_name,
                    "task": branch["task"],
                    "verdict": branch["verdict"],
                    "confidence": branch["confidence"],
                    "rule_refs": branch["rule_refs"],
                    "evidence_refs": branch["evidence_refs"],
                }
                for agent_name, branch in agent_branches.items()
            ],
            "chief_review_summary": chief_synthesis,
            "source_documents": source_documents,
            "package_precheck": package_precheck,
            "extracted_checklist": checklist,
            "document_quality": document_quality,
            "supplement_actions": supplement_actions,
            "risk_items": risk_items,
            "evidence_chain": evidence_chain,
            "report_summary": report_summary,
            "customer_report": customer_report,
        }

    def _document_quality(self, checklist: list[dict[str, Any]]) -> dict[str, Any]:
        missing = [item for item in checklist if item["status"] == "missing"]
        blocking_fields = {
            "sds_sections",
            "supplier",
            "revision_date",
            "cas_numbers",
            "component_concentrations",
            "process_temperature",
            "process_pressure",
            "process_steps",
            "storage_condition",
        }
        blocking = [
            {
                "field": item["field"],
                "label": item["label"],
                "source": item["source"],
                "evidence": str(item["value"]),
                "impact": self._gap_impact(item["field"]),
                "requires_human_review": True,
            }
            for item in missing
            if item["field"] in blocking_fields
        ]
        score = max(0, round(100 - len(blocking) * 12 - (len(missing) - len(blocking)) * 4))
        return {
            "score": score,
            "status": "needs_supplement" if blocking else "usable_for_pre_review",
            "blocking_gaps": blocking,
            "field_check_count": len(checklist),
            "missing_count": len(missing),
        }

    def _supplement_actions(self, document_quality: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "field": gap["field"],
                "action": f"补充或确认：{gap['label']}",
                "owner": "供应商/EHS/法规复核人",
                "reason": gap["impact"],
                "required_before_release": True,
            }
            for gap in document_quality.get("blocking_gaps", [])
        ]

    def _gap_impact(self, field: str) -> str:
        impacts = {
            "sds_sections": "SDS 结构不完整，无法支撑后续危害、储运和法规证据链。",
            "supplier": "供应商身份缺失，无法建立准入责任边界。",
            "revision_date": "SDS 版本有效性不明，法规和危害信息可能过期。",
            "cas_numbers": "CAS 缺失，无法完成物质主数据、法规清单和禁忌矩阵匹配。",
            "component_concentrations": "浓度缺失，无法判断 SVHC 阈值、危害分类和混配风险。",
            "process_temperature": "工艺温度缺失，无法判断氧化剂分解、高温和挥发风险。",
            "process_pressure": "工艺压力缺失，无法判断工艺安全边界。",
            "process_steps": "关键步骤缺失，无法确认是否同釜混配、同槽使用或存在禁忌操作。",
            "storage_condition": "储存条件缺失，无法判断禁忌物隔离、防火、防爆和通风要求。",
        }
        return impacts.get(field, "资料字段缺失，需人工确认后再形成最终意见。")

    def _customer_field_label(self, field: str) -> str:
        if field.startswith("missing_"):
            doc_type = field.removeprefix("missing_")
            return DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)
        return CUSTOMER_FIELD_LABELS.get(field, field.replace("_", " "))

    def _customer_action_text(self, action: dict[str, Any]) -> str:
        field = self._customer_field_label(str(action.get("field", "")))
        text = str(action.get("action", "")).strip()
        if text.startswith("补充或确认"):
            return f"请供应商补充或确认：{field}"
        if text.startswith("补充"):
            return text
        return text or f"请补充或确认：{field}"

    def _build_customer_report(
        self,
        *,
        case: dict[str, Any],
        chief: dict[str, Any],
        document_quality: dict[str, Any],
        supplement_actions: list[dict[str, Any]],
        risk_items: list[dict[str, Any]],
        evidence_chain: list[dict[str, Any]],
        package_precheck: dict[str, Any] | None = None,
        run_id: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        check_types = self._normalize_check_types(case.get("check_types"), case.get("review_scenario"))
        package_supplement_actions = package_precheck.get("supplement_actions", []) if package_precheck else []
        combined_supplement_actions = self._dedupe_supplement_actions([*package_supplement_actions, *supplement_actions])
        customer_verdict = self._customer_verdict(chief["verdict"], document_quality, package_precheck)
        grouped: dict[str, list[dict[str, Any]]] = {check_type: [] for check_type in check_types}
        seen: set[tuple[str, str, str]] = set()
        counter = 1
        if "intake_readiness" in grouped:
            for gap in document_quality.get("blocking_gaps", []):
                key = ("intake_readiness", "document_completeness_precheck", gap["field"])
                if key in seen:
                    continue
                seen.add(key)
                action = next((item for item in combined_supplement_actions if item["field"] == gap["field"]), None)
                grouped["intake_readiness"].append(
                    {
                        "id": f"I-{counter:03d}",
                        "issue_id": f"I-{counter:03d}",
                        "status": "needs_supplement",
                        "status_label": self._customer_status_label("needs_supplement"),
                        "severity": "blocking",
                        "category": "intake_readiness",
                        "category_label": CHECK_TYPE_LABELS["intake_readiness"],
                        "reason": f"{gap['label']}缺失或无法确认。",
                        "rule_id": "document_completeness_precheck",
                        "rule_text": f"资料预检要求提供可支撑审查的{gap['label']}，否则不能直接形成准入结论。",
                        "rule": {
                            "id": "document_completeness_precheck",
                            "text": f"资料预检要求提供可支撑审查的{gap['label']}，否则不能直接形成准入结论。",
                            "source": "资料完整性预检",
                        },
                        "user_text": gap.get("evidence") or "用户资料未提供该字段。",
                        "source": {
                            "type": "uploaded_package",
                            "text": gap.get("evidence") or "用户资料未提供该字段。",
                            "document_type": gap.get("source", "资料包"),
                        },
                        "impact": gap["impact"],
                        "recommendation": self._customer_action_text(action) if action else f"请供应商补充或确认：{gap['label']}",
                        "requires_human_review": True,
                    }
                )
                counter += 1
        if package_precheck and "intake_readiness" in grouped:
            for action in package_precheck.get("supplement_actions", []):
                key = ("intake_readiness", "package_precheck", action["field"])
                if key in seen:
                    continue
                seen.add(key)
                grouped["intake_readiness"].append(
                    {
                        "id": f"I-{counter:03d}",
                        "issue_id": f"I-{counter:03d}",
                        "status": "needs_supplement",
                        "status_label": self._customer_status_label("needs_supplement"),
                        "severity": "blocking",
                        "category": "intake_readiness",
                        "category_label": CHECK_TYPE_LABELS["intake_readiness"],
                        "reason": self._customer_action_text(action),
                        "rule_id": "package_precheck",
                        "rule_text": "资料包预检要求先确认文件可读、资料类型清楚，并补齐支撑所选检查项的关键资料。",
                        "rule": {
                            "id": "package_precheck",
                            "text": "资料包预检要求先确认文件可读、资料类型清楚，并补齐支撑所选检查项的关键资料。",
                            "source": "资料包预检",
                        },
                        "user_text": action.get("reason", "资料包预检识别到资料缺口。"),
                        "source": {
                            "type": "package_precheck",
                            "text": action.get("reason", "资料包预检识别到资料缺口。"),
                            "document_type": action.get("field", "资料包"),
                        },
                        "impact": action.get("reason", "该缺口会影响审查可靠性。"),
                        "recommendation": self._customer_action_text(action),
                        "requires_human_review": True,
                    }
                )
                counter += 1
        for item in risk_items:
            if item["verdict"] == "合规":
                continue
            check_type = self._check_type_for_risk_item(item)
            if check_type not in grouped:
                continue
            rule_id = item["rule_refs"][0] if item.get("rule_refs") else "manual_review"
            if self._is_positive_rule(rule_id):
                continue
            user_text = self._customer_user_text(item.get("evidence_refs", []), evidence_chain)
            key = (check_type, rule_id, user_text)
            if key in seen:
                continue
            seen.add(key)
            issue_id = f"I-{counter:03d}"
            status = self._customer_issue_status(item["verdict"])
            rule_text = self._customer_rule_text(rule_id)
            user_text = self._customer_user_text(item.get("evidence_refs", []), evidence_chain)
            check_label = CHECK_TYPE_LABELS[check_type]
            grouped[check_type].append(
                {
                    "id": issue_id,
                    "issue_id": issue_id,
                    "status": status,
                    "status_label": self._customer_status_label(status),
                    "severity": item.get("severity", self._severity_for_verdict(item["verdict"])),
                    "category": check_type,
                    "category_label": check_label,
                    "reason": self._customer_issue_reason(rule_id, item["reason"]),
                    "rule_id": rule_id,
                    "rule_text": rule_text,
                    "rule": {
                        "id": rule_id,
                        "text": rule_text,
                        "source": "法规/企业规则知识库" if rule_id != "manual_review" else "人工复核策略",
                    },
                    "user_text": user_text,
                    "source": {
                        "type": "uploaded_document",
                        "text": user_text,
                        "evidence_refs": item.get("evidence_refs", []),
                    },
                    "impact": self._customer_issue_impact(item["verdict"], rule_id),
                    "recommendation": item["recommended_action"],
                    "requires_human_review": bool(item.get("requires_human_review", status != "not_approved")),
                }
            )
            counter += 1
        issue_groups = [
            {
                "id": check_type,
                "label": CHECK_TYPE_LABELS[check_type],
                "issue_count": len(grouped[check_type]),
                "status_counts": self._customer_status_counts(grouped[check_type]),
                "items": grouped[check_type],
            }
            for check_type in check_types
            if grouped.get(check_type)
        ]
        review_scope = self._customer_review_scope(package_precheck, check_types)
        selected_checks = [{"id": item, "label": CHECK_TYPE_LABELS[item]} for item in check_types]
        verdict_label = {
            "pass": "可进入下一步",
            "needs_review": "需人工复核",
            "not_approved": "不建议准入",
            "needs_supplement": "需补充资料",
        }[customer_verdict]
        summary = self._customer_summary(case, chief, customer_verdict, issue_groups)
        issue_count = sum(len(group["items"]) for group in issue_groups)
        supplement_count = sum(
            1
            for group in issue_groups
            for item in group["items"]
            if item.get("status") == "needs_supplement"
        )
        return {
            "schema_version": "customer_report.v1",
            "report_metadata": {
                "report_type": "chemical_compliance_precheck",
                "case_id": case["case_id"],
                "run_id": run_id,
                "generated_at": generated_at,
                "locale": "zh-CN",
            },
            "case_profile": {
                "case_id": case["case_id"],
                "title": case["title"],
                "review_scenario": {
                    "id": case.get("review_scenario", "market_access"),
                    "label": REVIEW_SCENARIO_LABELS.get(case.get("review_scenario", "market_access"), "市场准入预审"),
                },
                "target_markets": case.get("target_markets", []),
                "selected_checks": selected_checks,
            },
            "verdict": customer_verdict,
            "verdict_label": verdict_label,
            "executive_summary": {
                "verdict": customer_verdict,
                "verdict_label": verdict_label,
                "summary": summary,
                "issue_count": issue_count,
                "supplement_count": supplement_count,
                "not_approved_count": sum(
                    1 for group in issue_groups for item in group["items"] if item.get("status") == "not_approved"
                ),
                "needs_review_count": sum(
                    1 for group in issue_groups for item in group["items"] if item.get("status") == "needs_review"
                ),
            },
            "summary": summary,
            "review_scenario": {
                "id": case.get("review_scenario", "market_access"),
                "label": REVIEW_SCENARIO_LABELS.get(case.get("review_scenario", "market_access"), "市场准入预审"),
            },
            "selected_checks": selected_checks,
            "review_scope": review_scope,
            "limited_checks": package_precheck.get("limited_checks", []) if package_precheck else [],
            "blocked_checks": package_precheck.get("blocked_checks", []) if package_precheck else [],
            "supplement_actions": combined_supplement_actions,
            "customer_supplement_actions": [self._customer_action_text(item) for item in combined_supplement_actions],
            "issue_groups": issue_groups,
            "compliant_summary": "未展开合规项；客户报告仅列示不合格、复核和补件事项。",
            "next_actions": self._customer_next_actions(customer_verdict, combined_supplement_actions),
            "evidence_policy": {
                "customer_report_includes": ["规则编号", "规则原文", "用户资料原文/识别结果", "影响说明", "整改或补件建议"],
                "customer_report_excludes": ["RAG chunks", "rerank 分数", "agent 分支原始输出", "trace 节点 JSON"],
                "admin_evidence_location": "technical_trace / retrieval / agent_branches",
            },
            "limitations": self._customer_limitations(package_precheck, customer_verdict),
            "technical_reference": {
                "admin_trace_available": True,
                "trace_fields": ["technical_trace", "retrieval", "agent_branches", "trace"],
                "run_id": run_id,
            },
            "disclaimer": "本结果为 AI 辅助合规预审，不替代最终法规、法律或 EHS 审批意见。",
        }

    def _dedupe_supplement_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for action in actions:
            deduped.setdefault((str(action.get("field", "")), str(action.get("action", ""))), action)
        return list(deduped.values())

    def _customer_review_scope(self, package_precheck: dict[str, Any] | None, check_types: list[str]) -> dict[str, Any]:
        if not package_precheck:
            return {
                "package_status": "not_prechecked",
                "message": "本次审查未返回独立资料包预检结果。",
                "selected_checks": [{"id": item, "label": CHECK_TYPE_LABELS[item]} for item in check_types],
                "available_checks": [],
                "limited_checks": [],
                "blocked_checks": [],
                "completed_checks": [],
            }
        return {
            "package_status": package_precheck.get("overall_status"),
            "message": package_precheck.get("user_message"),
            "selected_checks": package_precheck.get("selected_checks", []),
            "available_checks": package_precheck.get("available_checks", []),
            "completed_checks": package_precheck.get("available_checks", []),
            "limited_checks": package_precheck.get("limited_checks", []),
            "blocked_checks": package_precheck.get("blocked_checks", []),
            "recognized_documents": package_precheck.get("recognized_documents", []),
            "missing_documents": package_precheck.get("missing_documents", []),
        }

    def _customer_verdict(self, chief_verdict: str, document_quality: dict[str, Any], package_precheck: dict[str, Any] | None = None) -> str:
        if package_precheck and package_precheck.get("overall_status") in {"needs_supplement", "unreadable"}:
            return "needs_supplement"
        if document_quality.get("status") == "needs_supplement":
            return "needs_supplement"
        if chief_verdict == "不合规":
            return "not_approved"
        if chief_verdict == "复核":
            return "needs_review"
        return "pass"

    def _customer_issue_status(self, verdict: str) -> str:
        return {"不合规": "not_approved", "复核": "needs_review"}.get(verdict, "needs_review")

    def _customer_status_label(self, status: str) -> str:
        return {
            "pass": "可进入下一步",
            "needs_review": "需人工复核",
            "not_approved": "不建议准入",
            "needs_supplement": "需补充资料",
        }.get(status, "需人工复核")

    def _customer_status_counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            status = str(item.get("status", "needs_review"))
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _customer_limitations(self, package_precheck: dict[str, Any] | None, verdict: str) -> list[str]:
        limitations: list[str] = ["本报告为预审结论，仍需按企业内部 EHS、法规和采购流程完成最终审批。"]
        if not package_precheck:
            limitations.append("本次响应未包含独立资料包预检结果，审查范围需由管理端复核确认。")
            return limitations
        if package_precheck.get("overall_status") in {"needs_supplement", "unreadable"}:
            limitations.append("资料包尚不能完整支撑所选审查范围，结论优先用于补件和复核安排。")
        limited = package_precheck.get("limited_checks", [])
        blocked = package_precheck.get("blocked_checks", [])
        if limited:
            labels = "、".join(item["label"] for item in limited[:4])
            limitations.append(f"以下检查受资料缺口影响，只能作为初筛或复核依据：{labels}。")
        if blocked:
            labels = "、".join(item["label"] for item in blocked[:4])
            limitations.append(f"以下检查当前不能形成可靠判断：{labels}。")
        if verdict == "pass":
            limitations.append("未发现不合格或复核事项不等同于最终法规放行。")
        return limitations

    def _is_positive_rule(self, rule_id: str) -> bool:
        return rule_id in {
            "sds_complete",
            "formula_components_known",
            "process_parameters_present",
            "storage_compatible",
            "source_backed_no_restricted_demo_match",
        }

    def _customer_summary(
        self,
        case: dict[str, Any],
        chief: dict[str, Any],
        customer_verdict: str,
        issue_groups: list[dict[str, Any]],
    ) -> str:
        issue_count = sum(len(group["items"]) for group in issue_groups)
        markets = "、".join(case.get("target_markets", [])) or "未指定"
        if customer_verdict == "pass":
            return f"{case['title']}面向{markets}的预审未发现需要客户立即处理的不合格或复核事项。"
        if customer_verdict == "needs_supplement":
            supplement_count = sum(1 for group in issue_groups for item in group["items"] if item.get("status") == "needs_supplement")
            return f"{case['title']}面向{markets}的预审暂不能形成准入结论。系统识别到 {supplement_count or issue_count} 项关键资料缺口，请先补充资料后再重新预审。"
        label = {"needs_supplement": "补充资料", "needs_review": "人工复核", "not_approved": "不建议准入"}[customer_verdict]
        reason = "；".join(chief.get("reasons", [])[:2])
        return f"{case['title']}面向{markets}的预审结论为{label}，共发现 {issue_count} 项需处理事项。{reason}"

    def _customer_next_actions(self, verdict: str, supplement_actions: list[dict[str, Any]]) -> list[str]:
        if supplement_actions:
            return [self._customer_action_text(item) for item in supplement_actions[:6]]
        if verdict == "not_approved":
            return ["暂停当前物料准入，要求供应商调整配方、工艺或储运方案后重新提交。"]
        if verdict == "needs_review":
            return ["提交 EHS/法规负责人复核，并补充必要的供应商声明或测试依据。"]
        return ["进入企业内部准入审批或小范围试用流程。"]

    def _check_type_for_risk_item(self, item: dict[str, Any]) -> str:
        rule_id = item["rule_refs"][0] if item.get("rule_refs") else ""
        if rule_id.startswith("sds_") or rule_id in {"formula_components_missing", "process_parameters_missing", "knowledge_pack_missing_review"}:
            return "sds_key_sections" if rule_id.startswith("sds_") else "intake_readiness"
        if rule_id in {"incompatibility_oxidizer_flammable", "incompatibility_hypochlorite_acid", "flammable_storage_missing", "transport_un_mismatch"}:
            return "compatibility_risk" if rule_id.startswith("incompatibility_") else "storage_transport"
        if rule_id in {"oxidizer_high_temperature_process", "process_parameters_present"}:
            return "process_fit"
        if rule_id in {"hazardous_catalog_match", "svhc_threshold_match", "tsca_inventory_match", "knowledge_no_match_review"}:
            return "regulatory_screening"
        if rule_id in {"unknown_substance_review", "enterprise_redline_benzene"}:
            return "restricted_substance"
        return "ingredient_identity"

    def _customer_rule_text(self, rule_id: str) -> str:
        if rule_id == "manual_review":
            return "系统未能形成自动放行结论时，应进入人工复核。"
        source = self._source_for_rule(rule_id)
        return self._snippet_for_rule(rule_id, source["content"])

    def _customer_issue_reason(self, rule_id: str, fallback: str) -> str:
        reasons = {
            "sds_complete": "SDS 结构可读取，但仍需结合配方、工艺和所选市场完成审查。",
            "sds_missing_sections": "SDS 章节不完整，资料不能支撑完整合规预审。",
            "formula_components_missing": "配方或 SDS 未提供足够的成分、CAS 或浓度信息。",
            "process_parameters_missing": "工艺温度、压力或关键步骤信息不足。",
            "unknown_substance_review": "存在未知 CAS 或未进入物质主数据的成分。",
            "knowledge_no_match_review": "知识库未能为部分物质或法规方向提供充分命中证据。",
            "knowledge_pack_missing_review": "知识库未加载，不能形成证据充分的预审结论。",
            "incompatibility_oxidizer_flammable": "资料显示可燃液体与氧化剂存在同配方、同使用或同储风险。",
            "incompatibility_hypochlorite_acid": "资料显示次氯酸盐与酸类存在禁忌组合风险。",
            "enterprise_redline_benzene": "资料中包含企业准入红线物质。",
            "flammable_storage_missing": "含可燃组分但储存隔离、防火或通风条件不足。",
            "oxidizer_high_temperature_process": "氧化剂涉及高温或不明确工艺条件，需要工艺安全复核。",
            "transport_un_mismatch": "运输信息与物质风险不一致或不足。",
            "hazardous_catalog_match": "物质存在危化品目录命中信号，需要结合法规和用途复核。",
            "svhc_threshold_match": "物质存在 SVHC 阈值相关风险，需要补充 REACH/SVHC 证明。",
            "tsca_inventory_match": "物质涉及 TSCA 清单核验，需要确认美国市场状态。",
        }
        return reasons.get(rule_id, fallback.removeprefix(f"命中规则 {rule_id}："))

    def _customer_user_text(self, evidence_refs: list[str], evidence_chain: list[dict[str, Any]]) -> str:
        refs = set(evidence_refs)
        for evidence in evidence_chain:
            if evidence["ref"] in refs and evidence["type"] == "资料":
                return evidence["snippet"]
        for evidence in evidence_chain:
            if evidence["ref"] in refs:
                return evidence["snippet"]
        return evidence_chain[0]["snippet"] if evidence_chain else "用户资料未提供可直接引用的原文。"

    def _customer_issue_impact(self, verdict: str, rule_id: str) -> str:
        if verdict == "不合规":
            return "该事项触发硬性拦截或企业红线，当前资料不支持直接准入。"
        if rule_id in {"sds_missing_sections", "formula_components_missing", "process_parameters_missing", "knowledge_pack_missing_review"}:
            return "资料基础不足，系统不能形成证据充分的自动放行意见。"
        return "该事项存在不确定性，需要 EHS/法规人员结合业务场景确认。"

    def _review_checklist(
        self,
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        section_count = len(parsed_sds.sections)
        section_complete = set(parsed_sds.metadata["sds_section_numbers"]) == set(range(1, 17))
        cas_values = [component["cas"] for component in components]
        concentration_values = [component["concentration_text"] for component in components]
        return [
            self._check_item("sds_sections", "SDS 16 章节", f"{section_count}/16", section_complete, "SDS"),
            self._check_item("supplier", "供应商", parsed_sds.extracted_fields.get("supplier") or "未提供", bool(parsed_sds.extracted_fields.get("supplier")), "SDS"),
            self._check_item("revision_date", "SDS 修订日期", parsed_sds.extracted_fields.get("revision_date") or "未提供", "revision_date" not in parsed_sds.missing_fields, "SDS"),
            self._check_item("cas_numbers", "CAS 识别", "、".join(cas_values) if cas_values else "未抽取", bool(cas_values), "配方表/SDS"),
            self._check_item("component_concentrations", "成分浓度", "、".join(concentration_values) if concentration_values else "未抽取", bool(concentration_values) and not formula.get("missing_fields"), "配方表"),
            self._check_item("process_temperature", "工艺温度", process["fields"].get("温度", "未提供"), "温度" not in process["missing_fields"], "工艺资料"),
            self._check_item("process_pressure", "工艺压力", process["fields"].get("压力", "未提供"), "压力" not in process["missing_fields"], "工艺资料"),
            self._check_item("process_steps", "工艺关键步骤", process["fields"].get("关键步骤", "未提供"), "关键步骤" not in process["missing_fields"], "工艺资料"),
            self._check_item("un_numbers", "UN 编号", "、".join(parsed_sds.metadata.get("un_numbers", [])) or "未提供/不适用", True, "SDS"),
            self._check_item("storage_condition", "储存条件", self._storage_value(process, formula), self._storage_value(process, formula) != "未提供", "SDS/配方/工艺"),
        ]

    def _check_item(self, field: str, label: str, value: object, is_present: bool, source: str) -> dict[str, Any]:
        return {
            "field": field,
            "label": label,
            "value": value,
            "status": "present" if is_present else "missing",
            "source": source,
        }

    def _storage_value(self, process: dict[str, Any], formula: dict[str, Any]) -> str:
        value = process["fields"].get("储存条件") or process["fields"].get("储存类别")
        if value:
            return value
        for line in formula.get("text", "").splitlines():
            if line.strip().startswith("储存类别"):
                return line.split("：", 1)[-1].strip() if "：" in line else line.strip()
        return "未提供"

    def _review_risk_items(
        self,
        chief: dict[str, Any],
        rule_hits: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rule_hits:
            return [
                {
                    "verdict": chief["verdict"],
                    "severity": self._severity_for_verdict(chief["verdict"]),
                    "reason": "未命中明确规则，但仍需人工最终确认。",
                    "evidence_refs": [evidence["ref"] for evidence in evidences[:3]],
                    "rule_refs": [],
                    "recommended_action": self._recommended_action(chief["verdict"]),
                    "requires_human_review": True,
                }
            ]
        items = []
        for hit in rule_hits:
            source = self._source_for_rule(hit["rule_id"])
            rule_evidence = self._evidence_from_source(hit["rule_id"], source, evidence_type="规则")
            verdict = self._verdict_for_rule(hit["rule_id"], chief["verdict"])
            items.append(
                {
                    "verdict": verdict,
                    "severity": self._severity_for_verdict(verdict),
                    "reason": self._risk_reason(hit["rule_id"], rule_evidence["snippet"]),
                    "evidence_refs": hit["evidence_ids"] or [evidence["ref"] for evidence in evidences[:3]],
                    "rule_refs": [hit["rule_id"]],
                    "recommended_action": self._recommended_action(verdict),
                    "requires_human_review": verdict != "不合规",
                }
            )
        return items

    def _verdict_for_rule(self, rule_id: str, fallback: str) -> str:
        if rule_id in HARD_STOP_RULES:
            return "不合规"
        if rule_id in REVIEW_RULES:
            return "复核"
        return fallback if fallback != "合规" else "合规"

    def _severity_for_verdict(self, verdict: str) -> str:
        return {"合规": "info", "复核": "review", "不合规": "high"}[verdict]

    def _risk_reason(self, rule_id: str, snippet: str) -> str:
        labels = {
            "sds_complete": "SDS 结构完整，作为资料完整性正向证据。",
            "formula_components_known": "配方成分可识别，CAS 与浓度已进入审查。",
            "process_parameters_present": "工艺温度、压力和关键步骤已披露。",
            "storage_compatible": "未发现当前配方成分之间的演示禁忌储存组合。",
            "source_backed_no_restricted_demo_match": "RAG 已召回版本化证据，未命中禁限用演示规则。",
            "knowledge_pack_missing_review": "知识库未加载，不能形成证据充分的预审结论。",
        }
        if rule_id in labels:
            return labels[rule_id]
        return f"命中规则 {rule_id}：{snippet}"

    def _review_report_summary(
        self,
        case: dict[str, Any],
        chief: dict[str, Any],
        checklist: list[dict[str, Any]],
        risk_items: list[dict[str, Any]],
        evidence_chain: list[dict[str, Any]],
    ) -> dict[str, Any]:
        missing = [item["label"] for item in checklist if item["status"] == "missing"]
        major = [item["reason"] for item in risk_items if item["severity"] in {"high", "review"}]
        if not major:
            major = ["未命中红线或禁限用演示规则，但仍需人工最终确认。"]
        supplement = [f"补充或确认：{label}" for label in missing]
        return {
            "case_summary": f"{case['title']}；目标市场：{'、'.join(case['target_markets'])}；系统预审结论：{chief['verdict']}。",
            "material_completeness": "资料完整" if not missing else f"存在资料缺口：{'、'.join(missing)}。",
            "major_risks": major[:6],
            "evidence_sources": [item["source_url"] or item["ref"] for item in evidence_chain[:8]],
            "supplement_requests": supplement,
            "human_review_status": "无需系统强制复核，但仍需人工最终确认。" if not chief["needs_human"] else "需要 EHS/法规人员复核后形成最终意见。",
            "disclaimer": "本结果为 AI 辅助预审，不构成最终法规、法律或 EHS 合规意见。",
        }

    def _nodes(
        self,
        *,
        case: dict[str, Any],
        parsed_sds: Any,
        formula: dict[str, Any],
        process: dict[str, Any],
        query: str,
        retrieved: list[RankedChunk],
        task_decomposition: list[dict[str, Any]] | None = None,
        rag_queries: dict[str, str] | None = None,
        agent_branches: dict[str, dict[str, Any]] | None = None,
        chief_synthesis: dict[str, Any] | None = None,
        sub_agent_results: dict[str, dict[str, Any]],
        rule_hits: list[dict[str, Any]],
        cross_check: dict[str, Any],
        chief: dict[str, Any],
        evaluation: dict[str, Any] | None,
        include_evaluation: bool = True,
    ) -> list[dict[str, Any]]:
        task_decomposition = task_decomposition or []
        rag_queries = rag_queries or {"总查询": query}
        agent_branches = agent_branches or {}
        chief_synthesis = chief_synthesis or chief
        outputs = {
            "load_task": {
                "title": case["title"],
                "target_markets": case["target_markets"],
                "review_task": case.get("review_task", DEFAULT_REVIEW_TASK),
                "task_decomposition": task_decomposition,
            },
            "parse_sds": {
                "parse_status": parsed_sds.parse_status,
                "section_count": len(parsed_sds.sections),
                "missing_fields": parsed_sds.missing_fields,
                "cas_numbers": parsed_sds.metadata["cas_numbers"],
            },
            "parse_formula": {
                "component_count": formula["component_count"],
                "missing_fields": formula.get("missing_fields", []),
                "unresolved_component_lines": formula.get("unresolved_component_lines", []),
                "components": [
                    {"name": item["name"], "cas": item["cas"], "concentration_text": item["concentration_text"], "known": item["known"]}
                    for item in formula["components"]
                ],
            },
            "rag_retrieve": {
                "query": query,
                "rag_queries": rag_queries,
                "retrieved_chunk_count": len(retrieved),
                "top_scores": [item.score for item in retrieved],
            },
            "material_agent": agent_branches.get("物料", sub_agent_results["物料"]),
            "process_agent": agent_branches.get("工艺", sub_agent_results["工艺"]),
            "storage_agent": agent_branches.get("储运", sub_agent_results["储运"]),
            "regulatory_agent": agent_branches.get("法规", sub_agent_results["法规"]),
            "cross_check": cross_check,
            "chief_review": {"chief_review": chief, "chief_synthesis": chief_synthesis},
        }
        if include_evaluation:
            outputs["load_task"]["expected_verdict"] = case["expected_verdict"]
            outputs["evaluate"] = evaluation or {}
        inputs = {
            "load_task": {"case_id": case["case_id"]},
            "parse_sds": {"sds_path": case["sds_path"]},
            "parse_formula": {"formula_path": case["formula_path"]},
            "rag_retrieve": {"top_k_query": query, "agent_query_count": len(rag_queries)},
            "material_agent": {"component_count": formula["component_count"]},
            "process_agent": {"process_fields": process["fields"]},
            "storage_agent": {"component_count": formula["component_count"]},
            "regulatory_agent": {"target_markets": case["target_markets"], "retrieved_chunk_count": len(retrieved)},
            "cross_check": {"sub_agent_verdicts": {name: result["verdict"] for name, result in sub_agent_results.items()}},
            "chief_review": {"rule_hit_count": len(rule_hits), "cross_check_score": cross_check["score"]},
        }
        node_order = NODE_ORDER if include_evaluation else [node_id for node_id in NODE_ORDER if node_id != "evaluate"]
        if include_evaluation:
            inputs["evaluate"] = {"expected_verdict": case["expected_verdict"]}
        return [self._node(node_id, inputs[node_id], outputs[node_id]) for node_id in node_order]

    def _node(self, node_id: str, inputs: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "label": self._node_label(node_id),
            "status": "completed",
            "started_at": utc_now(),
            "completed_at": utc_now(),
            "input": inputs,
            "output": output,
        }

    def _node_label(self, node_id: str) -> str:
        labels = {
            "load_task": "加载任务",
            "parse_sds": "解析 SDS",
            "parse_formula": "解析配方表",
            "rag_retrieve": "RAG 检索",
            "material_agent": "物料 Agent",
            "process_agent": "工艺 Agent",
            "storage_agent": "储运 Agent",
            "regulatory_agent": "法规 Agent",
            "cross_check": "交叉质检",
            "chief_review": "主审判定",
            "evaluate": "评测",
        }
        return labels[node_id]

    def _compat_findings(
        self,
        case: dict[str, Any],
        chief: dict[str, Any],
        rule_hits: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        severity = {"合规": "info", "复核": "review", "不合规": "high"}[chief["verdict"]]
        return [
            {
                "jurisdiction": "GLOBAL",
                "issue_type": "chemical_verdict",
                "severity": severity,
                "conclusion": "；".join(chief["reasons"]),
                "evidence_ids": [evidence["ref"] for evidence in evidences[:6]],
                "regulation_refs": [evidence["source_url"] for evidence in evidences if evidence.get("source_url")][:6],
                "substance_ids": [],
                "confidence": max((hit["confidence"] for hit in rule_hits), default=0.6),
                "requires_human_review": chief["needs_human"],
                "recommended_action": self._recommended_action(chief["verdict"]),
                "missing_inputs": [],
            }
        ]

    def _recommended_action(self, verdict: str) -> str:
        if verdict == "合规":
            return "可进入业务复核或小范围试运行放行流程。"
        if verdict == "不合规":
            return "停止当前配方准入，调整配方或储运方案后重新预审。"
        return "补齐资料或由 EHS/法规人员确认后再形成最终意见。"

    def _rule_hit(
        self,
        rule_id: str,
        jurisdiction: str,
        evidence_ids: list[str],
        confidence: float,
        *,
        agent: str | None = None,
    ) -> dict[str, Any]:
        source = self._source_for_rule(rule_id)
        return {
            "rule_id": rule_id,
            "jurisdiction": jurisdiction,
            "agent": agent,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "confidence": round(confidence, 4),
            "version": source["version"],
            "effective_date": source["effective_date"],
            "source_url": source["source_url"],
        }

    def _jurisdiction_for_rule(self, rule_id: str) -> str:
        if rule_id in {"hazardous_catalog_match"}:
            return "CN"
        if rule_id in {"svhc_threshold_match"}:
            return "EU"
        if rule_id in {"tsca_inventory_match"}:
            return "US"
        return "GLOBAL"

    def _dedupe_rule_hits(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = {}
        for hit in hits:
            key = (hit["jurisdiction"], hit["rule_id"], hit.get("agent"))
            unique.setdefault(key, hit)
        return list(unique.values())

    def _dedupe_evidences(self, evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique = {}
        for evidence in evidences:
            unique.setdefault((evidence["type"], evidence["ref"]), evidence)
        return list(unique.values())

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
            "vector_score": item.vector_score,
            "keyword_score": item.keyword_score,
            "rerank_score": item.rerank_score,
            "rerank_reasons": list(item.rerank_reasons),
            "content": chunk.content,
        }

    def _uploaded_document_payload(self, document_type: str, document: dict[str, Any]) -> dict[str, Any]:
        return {
            "document_type": document_type,
            "filename": document["filename"],
            "content_type": document.get("content_type"),
            "sha256": document.get("sha256"),
            "text_source": document.get("text_source"),
            "char_count": len(document.get("content", "")),
        }

    def _parsed_document_payload(self, document_type: str, document: dict[str, Any]) -> dict[str, Any]:
        parsed = document.get("parsed_document")
        if parsed is None:
            parsed = parse_document_text(document.get("content", ""))
        return {
            "document_type": document_type,
            "filename": document["filename"],
            "parse_status": parsed.parse_status,
            "text_source": parsed.text_source,
            "missing_fields": parsed.missing_fields,
            "needs_manual_review": parsed.needs_manual_review,
            "extracted_fields": parsed.extracted_fields,
            "section_count": len(parsed.sections),
            "component_count": len(parsed.components),
        }

    def _has_incompatible_pair(self, components: list[dict[str, Any]]) -> bool:
        has_flammable = any("flammable_demo" in component.get("tags", []) for component in components)
        has_oxidizer = any("oxidizer_demo" in component.get("tags", []) for component in components)
        return has_flammable and has_oxidizer

    def _looks_like_unresolved_formula_component(self, line: str) -> bool:
        clean = line.strip()
        if not clean or not clean.startswith(("-", "*")):
            return False
        if "CAS" in clean:
            return False
        has_concentration = bool(re.search(r"\d+(?:\.\d+)?\s*%", clean))
        return has_concentration and any(keyword in clean for keyword in ["保密", "未披露", "未提供", "组分", "component"])

    def _has_hypochlorite_acid_pair(self, components: list[dict[str, Any]]) -> bool:
        has_hypochlorite = any("hypochlorite_demo" in component.get("tags", []) for component in components)
        has_acid = any("acid_demo" in component.get("tags", []) for component in components)
        return has_hypochlorite and has_acid

    def _has_enterprise_redline(self, components: list[dict[str, Any]]) -> bool:
        return any("enterprise_redline_demo" in component.get("tags", []) for component in components)

    def _has_flammable_storage_gap(self, components: list[dict[str, Any]], process: dict[str, Any]) -> bool:
        has_flammable = any("flammable_demo" in component.get("tags", []) for component in components)
        if not has_flammable:
            return False
        text = " ".join([process.get("text", ""), *process.get("fields", {}).values()])
        return "储存条件：未提供" in text or "储存类别：未提供" in text or "现场储存条件未提供" in text

    def _has_oxidizer_high_temp_process(self, components: list[dict[str, Any]], process: dict[str, Any]) -> bool:
        has_oxidizer = any("oxidizer_demo" in component.get("tags", []) for component in components)
        if not has_oxidizer:
            return False
        temp = process.get("temperature_c")
        text = " ".join([process.get("text", ""), *process.get("fields", {}).values()])
        return (temp is not None and temp >= 60) or any(keyword in text for keyword in ["加热", "高温", "热源", "夹套"])

    def _has_transport_un_mismatch(self, parsed_sds: Any, components: list[dict[str, Any]], process: dict[str, Any]) -> bool:
        un_numbers = set(parsed_sds.metadata.get("un_numbers", []))
        text = process.get("text", "")
        if "UN 3082" not in text and "3082" not in un_numbers:
            return False
        has_flammable = any("flammable_demo" in component.get("tags", []) for component in components)
        has_ethanol_or_acetone = any(component["cas"] in {"64-17-5", "67-64-1"} for component in components)
        return has_flammable and has_ethanol_or_acetone

    def _is_sds_revision_outdated(self, parsed_sds: Any) -> bool:
        revision = parsed_sds.extracted_fields.get("revision_date")
        if not revision:
            return False
        match = DATE_PATTERN.search(str(revision))
        if not match:
            return True
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        return (year, month, day) < (2023, 1, 1)

    def _process_indicates_mixing(self, process: dict[str, Any]) -> bool:
        text = " ".join(process["fields"].values())
        return any(keyword in text for keyword in ["混配", "混合", "搅拌", "同一"])

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


def _average(values: Any) -> float:
    numbers = list(values)
    return round(sum(numbers) / len(numbers), 4) if numbers else 0.0
