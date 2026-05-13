from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"


def test_chemical_rag_dataset_contract() -> None:
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))
    rules = json.loads((DATASET_ROOT / "knowledge" / "chemical_rules_pack.json").read_text(encoding="utf-8"))

    assert manifest["dataset_id"] == "chemical_rag_golden_v1"
    assert len(manifest["cases"]) >= 12
    assert {case["expected_verdict"] for case in manifest["cases"]} >= {"合规", "复核", "不合规"}
    for case in manifest["cases"]:
        assert (DATASET_ROOT / case["sds_path"]).exists()
        assert (DATASET_ROOT / case["formula_path"]).exists()
        assert case["expected_verdict"] in {"合规", "复核", "不合规"}
        assert case["expected_review"] is (case["expected_verdict"] == "复核")

    assert rules["pack_id"] == "chemical_rules_pack"
    assert rules["synthetic"] is True
    for source in rules["sources"]:
        assert source["version"]
        assert source["effective_date"]
        assert source["source_url"]
        assert source["content"].strip()


def test_chemical_run_returns_verdict_schema_and_agent_nodes(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/chemical/runs", json={"case_id": "chemical_compliant_formula", "top_k": 4})

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["run_id"].startswith("chemrun_")
    assert payload["case_id"] == "chemical_compliant_formula"
    assert payload["verdict"] == "合规"
    assert payload["needs_human"] is False
    assert payload["reasons"]
    assert payload["evidences"]
    assert all({"type", "ref", "snippet", "version", "effective_date"} <= set(item) for item in payload["evidences"])
    assert set(payload["sub_agent_results"]) == {"物料", "工艺", "储运", "法规"}
    assert 0.0 <= payload["cross_check_score"] <= 1.0
    assert [node["node_id"] for node in payload["trace"]["nodes"]] == [
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
    assert payload["retrieval"]["chunks"]
    assert payload["rule_hits"]
    assert payload["evaluation"]["expected_verdict"] == "合规"
    assert payload["evaluation"]["verdict_matched"] is True


def test_chemical_run_returns_business_review_workbench(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/chemical/runs", json={"case_id": "chemical_incompatible_formula", "top_k": 6})

    assert response.status_code == 201, response.text
    workbench = response.json()["review_workbench"]
    assert {
        "source_documents",
        "extracted_checklist",
        "task_decomposition",
        "agent_branch_summary",
        "chief_review_summary",
        "risk_items",
        "evidence_chain",
        "report_summary",
    } <= set(workbench)
    assert workbench["task_decomposition"]
    assert workbench["agent_branch_summary"]
    assert workbench["chief_review_summary"]["final_verdict"] == response.json()["verdict"]
    assert {document["type"] for document in workbench["source_documents"]} == {"SDS", "配方表", "工艺资料"}
    assert all(document["content"].strip() for document in workbench["source_documents"])
    assert all({"field", "label", "value", "status", "source"} <= set(item) for item in workbench["extracted_checklist"])
    assert workbench["risk_items"]
    assert all(
        {"verdict", "severity", "reason", "evidence_refs", "rule_refs", "recommended_action", "requires_human_review"}
        <= set(item)
        for item in workbench["risk_items"]
    )
    assert any("incompatibility_oxidizer_flammable" in item["rule_refs"] for item in workbench["risk_items"])
    report = workbench["report_summary"]
    assert {"case_summary", "material_completeness", "major_risks", "evidence_sources", "supplement_requests", "human_review_status", "disclaimer"} <= set(report)
    assert "AI 辅助预审" in report["disclaimer"]


def test_review_workbench_marks_missing_inputs_and_compliant_summary(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    missing = client.post("/chemical/runs", json={"case_id": "chemical_missing_sds_or_process", "top_k": 4}).json()
    missing_checklist = missing["review_workbench"]["extracted_checklist"]
    assert any(item["status"] == "missing" and "SDS" in item["label"] for item in missing_checklist)
    assert any(item["status"] == "missing" and "工艺" in item["label"] for item in missing_checklist)
    assert missing["review_workbench"]["report_summary"]["supplement_requests"]

    compliant = client.post("/chemical/runs", json={"case_id": "chemical_compliant_formula", "top_k": 4}).json()
    summary = compliant["review_workbench"]["report_summary"]
    assert "未命中红线" in " ".join(summary["major_risks"])
    assert "人工最终确认" in summary["human_review_status"]


def test_chemical_incompatible_formula_is_non_compliant(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/chemical/runs", json={"case_id": "chemical_incompatible_formula", "top_k": 6})

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["verdict"] == "不合规"
    assert payload["needs_human"] is False
    assert any("禁忌" in reason for reason in payload["reasons"])
    assert any(hit["rule_id"] == "incompatibility_oxidizer_flammable" for hit in payload["rule_hits"])
    assert any(item["type"] == "规则" and item["version"] for item in payload["evidences"])


def test_chemical_review_cases_do_not_get_forced_to_binary_verdict(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    missing = client.post("/chemical/runs", json={"case_id": "chemical_missing_sds_or_process", "top_k": 4}).json()
    unknown = client.post("/chemical/runs", json={"case_id": "chemical_unknown_substance", "top_k": 4}).json()

    assert missing["verdict"] == "复核"
    assert missing["needs_human"] is True
    assert any("缺" in reason for reason in missing["reasons"])
    assert unknown["verdict"] == "复核"
    assert unknown["needs_human"] is True
    assert any("未知" in reason or "知识库无命中" in reason for reason in unknown["reasons"])


def test_expanded_chemical_cases_cover_distinct_risk_scenarios(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    expected = {
        "chemical_bpa_svhc_review": ("复核", "svhc_threshold_match"),
        "chemical_acetone_storage_review": ("复核", "flammable_storage_missing"),
        "chemical_hypochlorite_acid_incompatible": ("不合规", "incompatibility_hypochlorite_acid"),
        "chemical_hydrogen_peroxide_heated_process": ("复核", "oxidizer_high_temperature_process"),
        "chemical_confidential_formula_missing_cas": ("复核", "formula_components_missing"),
        "chemical_outdated_sds_revision": ("复核", "sds_revision_outdated"),
        "chemical_transport_un_mismatch": ("复核", "transport_un_mismatch"),
        "chemical_internal_redline_benzene": ("不合规", "enterprise_redline_benzene"),
    }

    for case_id, (verdict, rule_id) in expected.items():
        payload = client.post("/chemical/runs", json={"case_id": case_id, "top_k": 6}).json()
        assert payload["verdict"] == verdict, case_id
        assert payload["evaluation"]["verdict_matched"] is True, case_id
        assert any(hit["rule_id"] == rule_id for hit in payload["rule_hits"]), case_id
        assert payload["retrieval"]["chunks"], case_id


def test_new_realistic_demo_cases_cover_upload_template_scenarios(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    expected = {
        "chemical_supplier_statement_test_conflict": ("复核", "supplier_evidence_conflict"),
        "chemical_eu_svhc_single_market": ("复核", "svhc_threshold_match"),
        "chemical_cn_hazardous_review": ("复核", "hazardous_catalog_match"),
        "chemical_scanned_unreadable_package": ("复核", "sds_missing_sections"),
        "chemical_storage_transport_supplement": ("复核", "flammable_storage_missing"),
        "chemical_cross_file_cas_concentration_conflict": ("复核", "cross_file_identity_conflict"),
    }

    for case_id, (verdict, rule_id) in expected.items():
        payload = client.post("/chemical/runs", json={"case_id": case_id, "top_k": 6}).json()
        assert payload["verdict"] == verdict, case_id
        assert payload["evaluation"]["verdict_matched"] is True, case_id
        assert any(hit["rule_id"] == rule_id for hit in payload["rule_hits"]), case_id


def test_chemical_evaluation_summarizes_verdict_quality(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.get("/chemical/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_id"] == "chemical_rag_golden_v1"
    assert payload["case_count"] >= 4
    assert payload["metrics"]["verdict_match_rate"] >= 0.75
    assert payload["metrics"]["evidence_coverage"] > 0
    assert payload["metrics"]["review_recall"] >= 1.0
    assert 0.0 <= payload["metrics"]["average_cross_check_score"] <= 1.0
    assert all("verdict_matched" in case for case in payload["cases"])


def test_technology_alias_routes_use_chemical_runner(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/technology/runs", json={"case_id": "chemical_compliant_formula", "top_k": 4})

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["case_id"] == "chemical_compliant_formula"
    assert payload["verdict"] == "合规"
    assert set(payload["sub_agent_results"]) == {"物料", "工艺", "储运", "法规"}


def _make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=str(tmp_path / "risk-review.db"),
                storage_dir=str(tmp_path / "objects"),
                enable_llm=False,
            )
        )
    )


def _ingest_rules(client: TestClient) -> None:
    pack = json.loads((DATASET_ROOT / "knowledge" / "chemical_rules_pack.json").read_text(encoding="utf-8"))
    for source in pack["sources"]:
        content = source["content"]
        payload = {key: value for key, value in source.items() if key != "content"}
        created = client.post("/knowledge/sources", json=payload)
        assert created.status_code == 201, created.text
        ingested = client.post("/knowledge/ingest", json={"source_id": created.json()["id"], "content": content})
        assert ingested.status_code == 201, ingested.text
