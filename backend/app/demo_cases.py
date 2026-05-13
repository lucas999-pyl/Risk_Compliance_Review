from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"
DOCUMENTS_ROOT = DATASET_ROOT / "documents"
UPLOAD_SAMPLES_ROOT = DATASET_ROOT / "upload_samples"

GROUPS = [
    {"id": "pass", "label": "可进入下一步", "description": "资料完整且未命中红线或复核规则。"},
    {"id": "needs_supplement", "label": "需补充资料", "description": "资料包或关键字段不足，不能直接形成准入结论。"},
    {"id": "needs_review", "label": "需人工复核", "description": "存在法规、储运、版本或证据不确定性。"},
    {"id": "not_approved", "label": "不建议准入", "description": "命中禁忌组合或企业硬性红线。"},
]

VERDICT_TO_GROUP = {
    "合规": "pass",
    "复核": "needs_review",
    "不合规": "not_approved",
}

VERDICT_TO_CUSTOMER = {
    "合规": "pass",
    "复核": "needs_review",
    "不合规": "not_approved",
}

SCENARIO_BY_CASE = {
    "chemical_acetone_storage_review": "storage_safety",
    "chemical_hydrogen_peroxide_heated_process": "process_introduction",
    "chemical_confidential_formula_missing_cas": "supplier_intake",
    "chemical_transport_un_mismatch": "storage_safety",
}

CHECKS_BY_GROUP = {
    "pass": ["intake_readiness", "ingredient_identity", "restricted_substance", "sds_key_sections", "process_fit", "storage_transport", "regulatory_screening"],
    "needs_supplement": ["intake_readiness", "ingredient_identity", "sds_key_sections", "process_fit", "manual_review"],
    "needs_review": ["intake_readiness", "ingredient_identity", "restricted_substance", "storage_transport", "regulatory_screening", "manual_review"],
    "not_approved": ["intake_readiness", "ingredient_identity", "restricted_substance", "compatibility_risk", "storage_transport", "regulatory_screening"],
}

UPLOAD_TEMPLATES = [
    {
        "id": "supplier_statement_test_conflict",
        "title": "供应商声明与检测报告不一致复核",
        "group": "needs_review",
        "expected_customer_verdict": "needs_review",
        "review_scenario": "supplier_intake",
        "target_markets": ["CN", "EU"],
        "check_types": ["intake_readiness", "ingredient_identity", "supplier_evidence_consistency", "manual_review"],
        "risk_tags": ["供应商声明", "检测报告", "证据不一致"],
        "review_task": "请核对供应商声明与检测报告是否一致，重点判断 BPA/SVHC 声明、检测结果和配方资料是否存在冲突。",
        "description": "供应商声明声称不含 BPA，但检测报告提示检出 BPA，需要人工复核证据可靠性。",
        "files": [
            {"type": "sds", "path": UPLOAD_SAMPLES_ROOT / "supplier_statement_test_conflict_sds.txt"},
            {"type": "formula", "path": UPLOAD_SAMPLES_ROOT / "supplier_statement_test_conflict_formula.txt"},
            {"type": "process", "path": UPLOAD_SAMPLES_ROOT / "supplier_statement_test_conflict_process.txt"},
            {"type": "regulatory_certificate", "path": UPLOAD_SAMPLES_ROOT / "supplier_statement_test_conflict_declaration.txt"},
            {"type": "test_report", "path": UPLOAD_SAMPLES_ROOT / "supplier_statement_test_conflict_test_report.txt"},
        ],
    },
    {
        "id": "eu_svhc_single_market",
        "title": "EU 单市场 SVHC 阈值复核",
        "group": "needs_review",
        "expected_customer_verdict": "needs_review",
        "review_scenario": "market_access",
        "target_markets": ["EU"],
        "check_types": ["intake_readiness", "ingredient_identity", "restricted_substance", "regulatory_screening", "manual_review"],
        "risk_tags": ["EU", "SVHC", "阈值复核"],
        "review_task": "请仅面向 EU 市场判断该环氧添加剂是否触发 REACH/SVHC 复核义务。",
        "description": "BPA 浓度达到 SVHC 演示阈值，输出法规复核而非直接否决。",
        "files": [
            {"type": "sds", "path": UPLOAD_SAMPLES_ROOT / "eu_svhc_single_market_sds.txt"},
            {"type": "formula", "path": UPLOAD_SAMPLES_ROOT / "eu_svhc_single_market_formula.txt"},
            {"type": "process", "path": UPLOAD_SAMPLES_ROOT / "eu_svhc_single_market_process.txt"},
        ],
    },
    {
        "id": "cn_hazardous_review",
        "title": "CN 危化目录命中但需用途复核",
        "group": "needs_review",
        "expected_customer_verdict": "needs_review",
        "review_scenario": "market_access",
        "target_markets": ["CN"],
        "check_types": ["intake_readiness", "ingredient_identity", "restricted_substance", "storage_transport", "regulatory_screening"],
        "risk_tags": ["CN", "危化目录", "用途复核"],
        "review_task": "请判断含乙醇清洗剂在中国市场准入时是否因危化目录命中需要法规/EHS 复核。",
        "description": "乙醇命中危化目录演示信号，但不是硬性不准入，需要结合用途、浓度、储运和许可复核。",
        "files": [
            {"type": "sds", "path": UPLOAD_SAMPLES_ROOT / "cn_hazardous_review_sds.txt"},
            {"type": "formula", "path": UPLOAD_SAMPLES_ROOT / "cn_hazardous_review_formula.txt"},
            {"type": "process", "path": UPLOAD_SAMPLES_ROOT / "cn_hazardous_review_process.txt"},
        ],
    },
    {
        "id": "scanned_unreadable_package",
        "title": "扫描 PDF 不可读资料包补件",
        "group": "needs_supplement",
        "expected_customer_verdict": "needs_supplement",
        "review_scenario": "supplier_intake",
        "target_markets": ["CN", "EU", "US"],
        "check_types": ["intake_readiness", "ingredient_identity", "sds_key_sections", "manual_review"],
        "risk_tags": ["扫描 PDF", "不可读", "补件"],
        "review_task": "请判断扫描版资料是否可支撑准入预审，并列出需要供应商补交的机器可读资料。",
        "description": "资料为无文本扫描 PDF，系统只能要求补交可复制文字版资料。",
        "files": [
            {"type": "unknown", "path": UPLOAD_SAMPLES_ROOT / "scanned_unreadable_package.pdf"},
        ],
    },
    {
        "id": "storage_transport_supplement",
        "title": "储运文件单独补充前的可燃液体复核",
        "group": "needs_review",
        "expected_customer_verdict": "needs_review",
        "review_scenario": "storage_safety",
        "target_markets": ["CN", "US"],
        "check_types": ["intake_readiness", "ingredient_identity", "compatibility_risk", "storage_transport", "manual_review"],
        "risk_tags": ["储运资料", "可燃液体", "现场安全"],
        "review_task": "请判断含丙酮清洗剂在缺少完整储运附件时是否需要 EHS 储运复核。",
        "description": "SDS 与工艺信息存在可燃液体信号，但储运附件仍需补充确认。",
        "files": [
            {"type": "sds", "path": UPLOAD_SAMPLES_ROOT / "storage_transport_supplement_sds.txt"},
            {"type": "formula", "path": UPLOAD_SAMPLES_ROOT / "storage_transport_supplement_formula.txt"},
            {"type": "process", "path": UPLOAD_SAMPLES_ROOT / "storage_transport_supplement_process.txt"},
            {"type": "storage_transport", "path": UPLOAD_SAMPLES_ROOT / "storage_transport_supplement_storage.txt"},
        ],
    },
    {
        "id": "cross_file_cas_concentration_conflict",
        "title": "跨文件 CAS/浓度冲突复核",
        "group": "needs_review",
        "expected_customer_verdict": "needs_review",
        "review_scenario": "supplier_intake",
        "target_markets": ["CN", "EU", "US"],
        "check_types": ["intake_readiness", "ingredient_identity", "restricted_substance", "supplier_evidence_consistency", "manual_review"],
        "risk_tags": ["跨文件冲突", "CAS", "浓度"],
        "review_task": "请核对 SDS 与配方表中的 CAS 和浓度是否一致，并识别需要供应商澄清的冲突。",
        "description": "SDS 与配方表对同一物料的 CAS/浓度描述不一致，需要供应商澄清后再放行。",
        "files": [
            {"type": "sds", "path": UPLOAD_SAMPLES_ROOT / "cross_file_cas_concentration_conflict_sds.txt"},
            {"type": "formula", "path": UPLOAD_SAMPLES_ROOT / "cross_file_cas_concentration_conflict_formula.txt"},
            {"type": "process", "path": UPLOAD_SAMPLES_ROOT / "cross_file_cas_concentration_conflict_process.txt"},
        ],
    },
]

UPLOAD_TEMPLATE_IDS = {f"chemical_{item['id']}" for item in UPLOAD_TEMPLATES}


def demo_case_catalog(dataset_root: Path = DATASET_ROOT) -> dict[str, Any]:
    manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    templates = [_manifest_template(case, dataset_root) for case in manifest["cases"] if case["case_id"] not in UPLOAD_TEMPLATE_IDS]
    templates.extend(_upload_template(item) for item in UPLOAD_TEMPLATES)
    return {
        "template_count": len(templates),
        "groups": GROUPS,
        "templates": templates,
    }


def _manifest_template(case: dict[str, Any], dataset_root: Path) -> dict[str, Any]:
    group = VERDICT_TO_GROUP.get(case["expected_verdict"], "needs_review")
    check_types = CHECKS_BY_GROUP[group]
    scenario = SCENARIO_BY_CASE.get(case["case_id"], "market_access")
    return {
        "id": case["case_id"],
        "title": case["title"],
        "group": group,
        "source": "manifest",
        "expected_customer_verdict": VERDICT_TO_CUSTOMER.get(case["expected_verdict"], "needs_review"),
        "expected_verdict": case["expected_verdict"],
        "review_scenario": scenario,
        "target_markets": case.get("target_markets", ["CN", "EU", "US"]),
        "check_types": check_types,
        "risk_tags": case.get("scenario_tags", []),
        "review_task": f"请基于演示 Case《{case['title']}》执行化工物料准入预审，并输出客户可读的补件、复核或不建议准入事项。",
        "description": "来自内置回归评测集，适合演示规则/RAG/Agent 预审闭环。",
        "files": [
            _file_item("sds", dataset_root / case["sds_path"]),
            _file_item("formula", dataset_root / case["formula_path"]),
            _file_item("process", dataset_root / case["process_path"]),
        ],
    }


def _upload_template(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in item.items() if key != "files"},
        "source": "upload_sample",
        "expected_verdict": _customer_to_legacy(item["expected_customer_verdict"]),
        "files": [_file_item(file["type"], Path(file["path"])) for file in item["files"]],
    }


def _file_item(file_type: str, path: Path) -> dict[str, str]:
    return {
        "type": file_type,
        "name": path.name,
        "path": str(path),
        "url": f"/data_samples/chemical_rag_dataset/upload_samples/{path.name}" if path.parent == UPLOAD_SAMPLES_ROOT else f"/data_samples/chemical_rag_dataset/documents/{path.name}",
    }


def _customer_to_legacy(verdict: str) -> str:
    return {
        "pass": "合规",
        "needs_review": "复核",
        "needs_supplement": "复核",
        "not_approved": "不合规",
    }.get(verdict, "复核")
