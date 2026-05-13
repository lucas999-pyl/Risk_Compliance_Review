from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"
SAMPLES_ROOT = DATASET_ROOT / "upload_samples"


def test_upload_review_accepts_fixed_checks_and_returns_customer_report(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_package(
        client,
        "incompatible_oxidizer_flammable",
        data={
            "review_scenario": "market_access",
            "check_types": "document_completeness,material,storage,regulatory",
            "target_markets": "CN,EU",
        },
    )

    assert payload["review_scenario"] == "market_access"
    assert payload["case_id"].startswith("case_")
    assert payload["check_types"] == [
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "compatibility_risk",
        "storage_transport",
        "regulatory_screening",
    ]
    assert [item["agent"] for item in payload["task_decomposition"]] == ["资料完整性", "物料", "储运", "法规"]

    report = payload["customer_report"]
    assert report["verdict"] == "not_approved"
    assert report["selected_checks"] == [
        {"id": "intake_readiness", "label": "资料完整性与可审性"},
        {"id": "ingredient_identity", "label": "成分识别与 CAS/浓度完整性"},
        {"id": "restricted_substance", "label": "禁限用物质与红线物质筛查"},
        {"id": "compatibility_risk", "label": "物料相容性与危险组合"},
        {"id": "storage_transport", "label": "储存与运输条件核查"},
        {"id": "regulatory_screening", "label": "目标市场法规匹配"},
    ]
    assert report["issue_groups"]
    assert "agent_branches" not in report
    assert "retrieval" not in report
    assert "trace" not in report

    issue = next(
        item
        for group in report["issue_groups"]
        for item in group["items"]
        if item["status"] in {"not_approved", "needs_review"}
    )
    assert {"id", "status", "reason", "rule_id", "rule_text", "user_text", "impact", "recommendation"} <= set(issue)
    assert issue["rule_text"]
    assert issue["user_text"]
    assert issue["recommendation"]

    detail = client.get(f"/chemical/cases/{payload['case_id']}")
    assert detail.status_code == 200
    case_payload = detail.json()
    assert case_payload["case"]["status"] == "not_approved"
    assert case_payload["latest_report"]["customer_report"]["verdict"] == "not_approved"


def test_customer_report_exposes_industrial_structured_contract(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_package(
        client,
        "incompatible_oxidizer_flammable",
        data={
            "review_scenario": "market_access",
            "check_types": "intake_readiness,ingredient_identity,restricted_substance,compatibility_risk,storage_transport,regulatory_screening",
            "target_markets": "CN,EU",
        },
    )

    report = payload["customer_report"]
    assert report["schema_version"] == "customer_report.v1"
    assert report["report_metadata"]["case_id"] == payload["case_id"]
    assert report["report_metadata"]["run_id"] == payload["run_id"]
    assert report["report_metadata"]["generated_at"]
    assert report["report_metadata"]["locale"] == "zh-CN"
    assert report["report_metadata"]["report_type"] == "chemical_compliance_precheck"
    assert report["case_profile"]["title"] == payload["case_title"]
    assert report["case_profile"]["review_scenario"] == report["review_scenario"]
    assert report["case_profile"]["target_markets"] == ["CN", "EU"]
    assert report["case_profile"]["selected_checks"] == report["selected_checks"]
    assert report["executive_summary"]["verdict"] == report["verdict"]
    assert report["executive_summary"]["verdict_label"] == report["verdict_label"]
    assert report["executive_summary"]["issue_count"] == sum(
        len(group["items"]) for group in report["issue_groups"]
    )
    assert {"completed_checks", "limited_checks", "blocked_checks"} <= set(report["review_scope"])
    assert "检索切片明细" in report["evidence_policy"]["customer_report_excludes"]
    assert report["technical_reference"]["admin_evidence_available"] is True

    group = next(group for group in report["issue_groups"] if group["items"])
    assert {"id", "label", "issue_count", "status_counts", "items"} <= set(group)
    assert group["issue_count"] == len(group["items"])
    assert sum(group["status_counts"].values()) == group["issue_count"]

    issue = group["items"][0]
    assert {
        "id",
        "issue_id",
        "status",
        "status_label",
        "severity",
        "category",
        "category_label",
        "reason",
        "rule_id",
        "rule_text",
        "rule",
        "user_text",
        "source",
        "impact",
        "recommendation",
        "requires_human_review",
    } <= set(issue)
    assert issue["issue_id"] == issue["id"]
    assert issue["rule"]["id"] == issue["rule_id"]
    assert issue["rule"]["text"] == issue["rule_text"]
    assert issue["source"]["text"] == issue["user_text"]
    assert issue["category"] == group["id"]
    assert issue["category_label"] == group["label"]

    assert "agent_branches" not in report
    assert "retrieval" not in report
    assert "trace" not in report
    assert "chunks" not in report


def test_customer_report_quotes_uploaded_source_text_for_rule_hits(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_package(
        client,
        "incompatible_oxidizer_flammable",
        data={
            "review_scenario": "market_access",
            "check_types": "intake_readiness,ingredient_identity,restricted_substance,compatibility_risk,storage_transport,regulatory_screening",
            "target_markets": "CN,EU",
        },
    )

    issues = [
        item
        for group in payload["customer_report"]["issue_groups"]
        for item in group["items"]
        if item["rule_id"] == "incompatibility_oxidizer_flammable"
    ]

    assert len(issues) == 1
    issue = issues[0]
    assert "SDS 章节数 16" not in issue["user_text"]
    assert "缺失字段 ['无']" not in issue["user_text"]
    assert "用户资料未提供可直接引用的原文" not in issue["user_text"]
    assert "乙醇 CAS 64-17-5 45%" in issue["user_text"]
    assert "过氧化氢 CAS 7722-84-1 12%" in issue["user_text"]
    assert "同一反应釜" in issue["user_text"] or "同釜混配" in issue["user_text"]
    assert issue["source"]["evidence_refs"] == ["formula_document", "process_document"]


def test_chemical_case_draft_upload_and_run_review_are_persisted(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    created = client.post(
        "/chemical/cases",
        json={
            "title": "供应商 D 新物料预审",
            "review_scenario": "market_access",
            "check_types": ["document_completeness", "material", "regulatory"],
            "target_markets": ["CN", "EU"],
        },
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]

    cases = client.get("/chemical/cases")
    assert cases.status_code == 200
    assert any(item["id"] == case_id and item["status"] == "draft" for item in cases.json()["cases"])

    sds_file = SAMPLES_ROOT / "unknown_missing_process_sds.txt"
    uploaded = client.post(
        f"/chemical/cases/{case_id}/documents",
        files={"documents": (sds_file.name, sds_file.read_bytes(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["document_count"] == 1

    detail = client.get(f"/chemical/cases/{case_id}").json()
    assert detail["case"]["id"] == case_id
    assert detail["document_count"] == 1
    assert detail["latest_report"] is None

    run = client.post(f"/chemical/cases/{case_id}/run-review", data={"top_k": "6"})
    assert run.status_code == 201, run.text
    payload = run.json()
    assert payload["case_id"] == case_id
    assert payload["customer_report"]["verdict"] in {"needs_supplement", "needs_review"}

    detail_after = client.get(f"/chemical/cases/{case_id}").json()
    assert detail_after["case"]["status"] in {"needs_supplement", "needs_review"}
    assert detail_after["latest_report"]["customer_report"]["verdict"] == payload["customer_report"]["verdict"]


def test_chemical_case_list_can_be_cleared_for_demo_reset(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    first = client.post("/chemical/cases", json={"title": "演示 Case 1", "target_markets": ["CN"]})
    second = client.post("/chemical/cases", json={"title": "演示 Case 2", "target_markets": ["EU"]})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    cleared = client.delete("/chemical/cases")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["deleted_cases"] == 2

    cases = client.get("/chemical/cases")
    assert cases.status_code == 200
    assert cases.json()["cases"] == []


def test_upload_review_accepts_single_document_list_and_requests_supplement(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    sds_file = SAMPLES_ROOT / "unknown_missing_process_sds.txt"
    response = client.post(
        "/chemical/upload-review",
        data={
            "title": "单文件 SDS 预审",
            "review_scenario": "market_access",
            "check_types": "document_completeness,material,regulatory",
            "target_markets": "CN,EU,US",
            "top_k": "6",
        },
        files={"documents": (sds_file.name, sds_file.read_bytes(), "text/plain")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["case_source"] == "uploaded"
    assert [item["document_type"] for item in payload["uploaded_documents"]] == ["sds"]
    assert payload["package_precheck"]["overall_status"] == "needs_supplement"
    assert payload["customer_report"]["verdict"] == "needs_supplement"
    assert payload["customer_report"]["verdict_label"] == "需补充资料"
    assert any(group["id"] == "intake_readiness" for group in payload["customer_report"]["issue_groups"])
    assert payload["review_workbench"]["document_quality"]["status"] == "needs_supplement"
    assert payload["review_workbench"]["supplement_actions"]
    assert "合格" not in payload["customer_report"]["summary"]
    assert "sds_sections" not in payload["customer_report"]["summary"]
    assert "component_concentrations" not in payload["customer_report"]["summary"]
    issue_keys = [
        (group["id"], item["rule_id"], item["reason"], item["user_text"])
        for group in payload["customer_report"]["issue_groups"]
        for item in group["items"]
        if item["rule_id"] != "document_completeness_precheck"
    ]
    assert len(issue_keys) == len(set(issue_keys))
    assert all(
        not item["reason"].startswith("命中规则 ")
        for group in payload["customer_report"]["issue_groups"]
        for item in group["items"]
    )
    assert all(
        "_" not in item["reason"] and "_" not in item["recommendation"]
        for group in payload["customer_report"]["issue_groups"]
        for item in group["items"]
    )


def test_upload_review_with_only_formula_and_broad_checks_requires_supplement(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    formula_file = SAMPLES_ROOT / "compliant_water_cleaner_formula.txt"
    response = client.post(
        "/chemical/upload-review",
        data={
            "title": "只上传配方表的准入预审",
            "review_scenario": "market_access",
            "check_types": "intake_readiness,ingredient_identity,restricted_substance,compatibility_risk,sds_key_sections,process_fit,storage_transport,regulatory_screening",
            "target_markets": "CN,EU,US",
            "top_k": "6",
        },
        files={"documents": (formula_file.name, formula_file.read_bytes(), "text/plain")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["package_precheck"]["overall_status"] == "needs_supplement"
    assert {"sds", "process"} <= set(payload["package_precheck"]["missing_documents"])
    assert payload["customer_report"]["verdict"] == "needs_supplement"
    assert payload["customer_report"]["verdict_label"] == "需补充资料"
    assert "暂不能形成准入结论" in payload["customer_report"]["summary"]
    assert "合格" not in payload["customer_report"]["summary"]


def test_upload_review_prechecks_unrelated_package_without_forcing_sds(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    response = client.post(
        "/chemical/upload-review",
        data={
            "title": "客户随手上传的采购说明",
            "review_scenario": "supplier_intake",
            "check_types": "intake_readiness,ingredient_identity,regulatory_screening,process_fit",
            "target_markets": "CN,EU",
            "top_k": "6",
        },
        files={"documents": ("purchase_note.txt", "本文件只是采购邮件摘要，没有 SDS、CAS、配方、浓度或工艺参数。".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    precheck = payload["package_precheck"]
    assert precheck["overall_status"] == "needs_supplement"
    assert precheck["documents"][0]["detected_type"] == "unknown"
    assert precheck["documents"][0]["readability"] == "readable"
    assert {"sds", "formula", "process"} <= set(precheck["missing_documents"])
    assert any(item["id"] == "intake_readiness" for item in precheck["available_checks"])
    assert any(item["id"] == "ingredient_identity" for item in precheck["limited_checks"])
    assert any(item["id"] == "process_fit" for item in precheck["blocked_checks"])
    assert precheck["supplement_actions"]

    report = payload["customer_report"]
    assert report["verdict"] == "needs_supplement"
    assert report["review_scope"]["package_status"] == "needs_supplement"
    assert report["limited_checks"] == precheck["limited_checks"]
    assert all(action in report["supplement_actions"] for action in precheck["supplement_actions"])

    detail = client.get(f"/chemical/cases/{payload['case_id']}").json()
    assert detail["package_precheck"]["overall_status"] == "needs_supplement"
    assert detail["latest_report"]["package_precheck"]["documents"][0]["detected_type"] == "unknown"


def test_upload_review_prechecks_unreadable_pdf_as_supplement_needed(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    response = client.post(
        "/chemical/upload-review",
        data={
            "title": "扫描 PDF 资料包",
            "review_scenario": "market_access",
            "check_types": "intake_readiness,sds_key_sections,ingredient_identity",
            "target_markets": "CN",
        },
        files={"documents": ("scan.pdf", b"%PDF-1.4\n% image only without text\n%%EOF", "application/pdf")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    precheck = payload["package_precheck"]
    assert precheck["overall_status"] == "unreadable"
    assert precheck["documents"][0]["readability"] == "unreadable"
    assert precheck["documents"][0]["recognized_fields"] == []
    assert any(action["field"] == "machine_readable_text" for action in precheck["supplement_actions"])
    assert payload["customer_report"]["verdict"] == "needs_supplement"


def test_review_scenarios_recommend_business_check_types_and_keep_legacy_compatible(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    supplier = client.post(
        "/chemical/cases",
        json={"title": "供应商准入", "review_scenario": "supplier_intake", "target_markets": ["CN"]},
    )
    assert supplier.status_code == 201, supplier.text
    supplier_checks = supplier.json()["check_types"]
    assert supplier_checks == [
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "sds_key_sections",
        "supplier_evidence_consistency",
        "manual_review",
    ]

    legacy = client.post(
        "/chemical/cases",
        json={
            "title": "旧字段兼容",
            "review_scenario": "market_access",
            "check_types": ["document_completeness", "material", "storage", "regulatory"],
            "target_markets": ["CN", "EU"],
        },
    )
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["check_types"] == [
        "intake_readiness",
        "ingredient_identity",
        "restricted_substance",
        "compatibility_risk",
        "storage_transport",
        "regulatory_screening",
    ]


def test_demo_case_catalog_exposes_12_manifest_cases_and_6_new_upload_templates(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.get("/chemical/demo-cases")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["template_count"] == 18
    assert {group["id"] for group in payload["groups"]} >= {"pass", "needs_supplement", "needs_review", "not_approved"}
    assert len([item for item in payload["templates"] if item["source"] == "manifest"]) == 12
    upload_templates = [item for item in payload["templates"] if item["source"] == "upload_sample"]
    assert len(upload_templates) == 6
    assert {
        "supplier_statement_test_conflict",
        "eu_svhc_single_market",
        "cn_hazardous_review",
        "scanned_unreadable_package",
        "storage_transport_supplement",
        "cross_file_cas_concentration_conflict",
    } <= {item["id"] for item in upload_templates}
    for item in payload["templates"]:
        assert {"id", "title", "group", "source", "expected_customer_verdict", "review_task", "target_markets", "check_types", "files"} <= set(item)
        assert item["files"]
        assert all(Path(file["path"]).exists() for file in item["files"])


def test_customer_report_downloads_json_html_and_pdf_from_latest_report(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")
    payload = _upload_package(
        client,
        "incompatible_oxidizer_flammable",
        data={
            "review_scenario": "market_access",
            "check_types": "intake_readiness,ingredient_identity,restricted_substance,compatibility_risk,storage_transport,regulatory_screening",
            "target_markets": "CN,EU",
        },
    )
    case_id = payload["case_id"]

    report_json = client.get(f"/chemical/cases/{case_id}/report.json")
    assert report_json.status_code == 200, report_json.text
    customer_report = report_json.json()
    assert customer_report["schema_version"] == "customer_report.v1"
    assert customer_report["report_metadata"]["case_id"] == case_id
    assert "agent_branches" not in customer_report
    assert "retrieval" not in customer_report
    assert "trace" not in customer_report

    report_html = client.get(f"/chemical/cases/{case_id}/report.html")
    assert report_html.status_code == 200, report_html.text
    assert "text/html" in report_html.headers["content-type"]
    assert "客户合规预审报告" in report_html.text
    assert payload["customer_report"]["verdict_label"] in report_html.text
    assert "问题分组" in report_html.text
    assert "技术边界" in report_html.text
    assert "本结果为 AI 辅助合规预审" in report_html.text
    assert "agent_branches" not in report_html.text
    assert "retrieval" not in report_html.text

    with patch("app.reporting.render_customer_report_pdf", return_value=b"%PDF-1.4\n% test\n%%EOF"):
        report_pdf = client.get(f"/chemical/cases/{case_id}/report.pdf")
    assert report_pdf.status_code == 200, report_pdf.text
    assert report_pdf.headers["content-type"] == "application/pdf"
    assert report_pdf.content.startswith(b"%PDF-")


def test_customer_report_pdf_returns_clear_error_when_renderer_unavailable(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")
    payload = _upload_package(
        client,
        "unknown_missing_process",
        data={
            "review_scenario": "supplier_intake",
            "check_types": "intake_readiness,ingredient_identity,manual_review",
            "target_markets": "CN,EU",
        },
    )

    with patch("app.reporting.render_customer_report_pdf", side_effect=RuntimeError("Playwright browser runtime is not installed")):
        response = client.get(f"/chemical/cases/{payload['case_id']}/report.pdf")

    assert response.status_code == 503
    assert "Playwright" in response.json()["detail"]


def test_customer_report_pdf_uses_system_chrome_fallback_when_playwright_is_missing() -> None:
    from app import reporting

    report = {
        "schema_version": "customer_report.v1",
        "report_metadata": {"case_id": "case_pdf_fallback", "run_id": "run_pdf_fallback", "generated_at": "2026-05-13T00:00:00+00:00"},
        "case_profile": {"title": "PDF fallback case", "target_markets": ["CN"]},
        "verdict": "needs_review",
        "verdict_label": "需人工复核",
        "executive_summary": {"issue_count": 0, "supplement_count": 0, "needs_review_count": 0, "not_approved_count": 0},
        "summary": "用于验证系统 Chrome 兜底生成 PDF。",
        "selected_checks": [],
        "issue_groups": [],
    }

    with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
        with patch("app.reporting._render_customer_report_pdf_with_chrome", return_value=b"%PDF-1.4\n% fallback\n%%EOF", create=True) as chrome_pdf:
            pdf = reporting.render_customer_report_pdf(report)

    assert pdf.startswith(b"%PDF-")
    chrome_pdf.assert_called_once()


def test_static_workbench_exposes_customer_flow_and_keeps_admin_advanced_task() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

    assert "合规预审 Case 工作台" in html
    assert "Case 列表" in html
    assert "客户预审" in html
    assert "Case 流程" in html
    assert "创建 Case" in html
    assert "上传资料包" in html
    assert "审查场景" in html
    assert "推荐检查项" in html
    assert 'id="documentFiles"' in html
    assert "选择资料包" in html
    assert "上传并预检" in html
    assert "资料包预检结果" in html
    assert "禁限用物质与红线物质筛查" in html
    assert "供应商声明/检测报告一致性" in html
    assert "renderPackagePrecheck" in html
    assert "演示 Case 模板" in html
    assert "/chemical/cases" in html
    assert "/chemical/cases/${caseId}/documents" in html
    assert "/chemical/cases/${caseId}/run-review" in html
    assert 'form.append("check_types"' in html
    assert 'form.append("review_scenario"' in html
    assert "customer_report" in html
    assert "客户报告" in html
    assert "管理端" in html
    assert "审查 TopK" in html[html.index("管理端") :]
    assert 'id="reviewTask"' in html
    assert "普通用户端不需要填写" in html
    assert "clearDemoPackageSelection" in html
    assert "clearCustomerPackageSelection" in html


def test_static_workbench_exposes_expanded_demo_case_templates_and_report_downloads() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

    assert "/chemical/demo-cases" in html
    assert "demoCaseTemplates" in html
    assert "renderDemoCaseTemplates" in html
    assert "supplier_statement_test_conflict" in html
    assert "cross_file_cas_concentration_conflict" in html
    assert "报告下载" in html
    assert "downloadReportJson" in html
    assert "downloadReportHtml" in html
    assert "downloadReportPdf" in html
    assert "downloadCaseReportFile" in html
    assert "URL.createObjectURL" in html
    assert "link.download = filename" in html
    assert "window.open(`/chemical/cases/${state.selectedCaseId}/report.${format}`" not in html
    assert "/report.json" in html
    assert "/report.html" in html
    assert "/report.pdf" in html


def test_static_workbench_refines_demo_templates_reset_and_report_copy() -> None:
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

    assert "demo-template-toolbar" in html
    assert "demo-template-counts" in html
    assert "activeGroupCount" in html
    assert "覆盖 ${activeGroupCount} 类场景" in html
    assert "orderedTemplates" in html
    assert "demo-template-grid" in html
    assert "sample-group-title" not in html
    template_static_section = html[html.index("function renderDemoCaseTemplates") : html.index("function clearCustomerPackageSelection")]
    assert "REPORT_VERDICT_LABELS" not in template_static_section
    assert "expected_customer_verdict" not in template_static_section
    assert "可进入下一步" not in template_static_section
    assert "需补充资料" not in template_static_section
    assert "需人工复核" not in template_static_section
    assert "不建议准入" not in template_static_section
    assert "${groups\n            .map" not in template_static_section
    assert "resetCurrentCase" in html
    assert 'id="resetCurrentCase"' in html
    assert "resetCustomerWorkbenchState" in html
    assert "$(\"uploadTitle\").value = \"\";" in html
    assert "$(\"packagePrecheck\").innerHTML" in html
    assert "$(\"customerReport\").innerHTML" in html
    assert "客户结论" not in html[html.index('id="customerWorkbench"') : html.index('id="adminWorkbench"')]
    assert "预审结论" in html


def test_report_html_uses_platform_conclusion_copy_and_pdf_print_layout() -> None:
    from app.reporting import render_customer_report_html

    report = {
        "schema_version": "customer_report.v1",
        "report_metadata": {"case_id": "case_report_copy", "run_id": "run_report_copy", "generated_at": "2026-05-13T00:00:00+00:00"},
        "case_profile": {"title": "报告文案与 PDF 版式验证", "target_markets": ["CN", "EU"]},
        "verdict": "needs_supplement",
        "verdict_label": "需补充资料",
        "executive_summary": {"issue_count": 1, "supplement_count": 1, "needs_review_count": 0, "not_approved_count": 0},
        "summary": "用于验证报告文案和打印版式。",
        "selected_checks": [{"id": "intake_readiness", "label": "资料完整性与可审性"}],
        "issue_groups": [],
    }

    html = render_customer_report_html(report)

    assert "客户结论" not in html
    assert "预审结论" in html
    assert "<span>复核事项</span><strong>0</strong>" in html
    assert "<span>不建议准入</span><strong>0</strong>" in html
    assert "@page" in html
    assert "size: A4" in html
    assert "print-color-adjust: exact" in html
    assert "page-break-inside: avoid" in html
    assert html.rindex("@media print") > html.rindex("@media (max-width: 760px)")


def test_report_pdf_chrome_export_disables_browser_headers() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "reporting.py").read_text(encoding="utf-8")

    assert "--no-pdf-header-footer" in source
    assert "--print-to-pdf-no-header" in source
    assert 'display_header_footer=False' in source


def test_superpowers_brainstorm_artifacts_are_gitignored() -> None:
    gitignore = Path(__file__).resolve().parents[2] / ".gitignore"

    assert ".superpowers/" in gitignore.read_text(encoding="utf-8")


def _upload_package(client: TestClient, sample_id: str, data: dict[str, str]) -> dict:
    files = {
        "sds_file": (f"{sample_id}_sds.txt", (SAMPLES_ROOT / f"{sample_id}_sds.txt").read_bytes(), "text/plain"),
        "formula_file": (f"{sample_id}_formula.txt", (SAMPLES_ROOT / f"{sample_id}_formula.txt").read_bytes(), "text/plain"),
        "process_file": (f"{sample_id}_process.txt", (SAMPLES_ROOT / f"{sample_id}_process.txt").read_bytes(), "text/plain"),
    }
    response = client.post(
        "/chemical/upload-review",
        data={"title": f"客户级资料包审查 {sample_id}", "top_k": "6", **data},
        files=files,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=str(tmp_path / "risk-review.db"),
                storage_dir=str(tmp_path / "objects"),
                chem_rag_vector_store_dir=str(tmp_path / "vector_store"),
                enable_llm=False,
            )
        )
    )
