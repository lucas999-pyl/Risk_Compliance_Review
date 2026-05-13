from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.chemical_rag import ChemicalRagRunner
from app.factory import create_app
from app.settings import Settings
from app.store import SQLiteStore


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"


MAIN_RETAINED_CASES = {
    "chemical_supplier_statement_test_conflict": "supplier_evidence_conflict",
    "chemical_eu_svhc_single_market": "svhc_threshold_match",
    "chemical_cn_hazardous_review": "hazardous_catalog_match",
    "chemical_scanned_unreadable_package": "sds_missing_sections",
    "chemical_storage_transport_supplement": "flammable_storage_missing",
    "chemical_cross_file_cas_concentration_conflict": "cross_file_identity_conflict",
}


FEATURE_COATING_CASES = {
    "coatings_demo_case_pass",
    "coatings_demo_case_needs_review",
    "coatings_demo_case_not_approved",
    "coatings_demo_case_needs_supplement",
}


def test_feature_shell_and_pdf_routes_are_primary(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    shell = client.get("/")
    legacy = client.get("/legacy")

    assert shell.status_code == 200
    assert 'id="route-outlet"' in shell.text
    assert "/static/js/shell.js" in shell.text
    assert "/static/css/shell.css" in shell.text
    assert "customerWorkbench" not in shell.text
    assert legacy.status_code == 200
    assert "customerWorkbench" in legacy.text

    missing_pdf = client.get("/api/cases/case_missing/report.pdf")
    assert missing_pdf.status_code == 404


def test_wizard_exposes_all_dataset_case_templates_and_autoruns_after_scope() -> None:
    steps_js = (Path(__file__).resolve().parents[1] / "app" / "static" / "pages" / "wizard" / "steps.js").read_text(
        encoding="utf-8"
    )
    api_js = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "api.js").read_text(encoding="utf-8")

    assert "caseTemplates" in api_js
    assert "loadCaseTemplates" in steps_js
    assert "data-template-id" in steps_js
    assert "selectedTemplateId" in steps_js
    assert "uploadTemplateDocuments" in steps_js
    assert "autoRunFromStep4" in steps_js
    assert "kickoff()" in steps_js
    assert 'id="wz-run"' not in steps_js[steps_js.index("export async function renderStep5") :]
    assert "?{escapeHtml(" not in steps_js
    assert "`r`n" not in steps_js


def test_dataset_case_templates_endpoint_lists_feature_and_main_cases(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.get("/chemical/case-templates")

    assert response.status_code == 200, response.text
    payload = response.json()
    templates = payload["templates"]
    template_ids = {item["case_id"] for item in templates}
    assert payload["count"] == len(templates)
    assert len(templates) >= 18
    assert FEATURE_COATING_CASES <= template_ids
    assert set(MAIN_RETAINED_CASES) <= template_ids
    assert all(item["document_count"] >= 3 for item in templates)
    assert all(item["target_markets"] for item in templates)


def test_case_template_can_create_case_with_documents(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    created = client.post("/chemical/cases/from-template/coatings_demo_case_needs_supplement")

    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["template_id"] == "coatings_demo_case_needs_supplement"
    assert payload["case"]["id"].startswith("case_")
    assert payload["document_count"] == 3
    assert payload["package_precheck"]["overall_status"] in {"ready", "needs_supplement", "partial"}
    detail = client.get(f"/chemical/cases/{payload['case']['id']}").json()
    assert detail["document_count"] == 3
    assert detail["case"]["title"]


def test_single_chemical_case_can_be_deleted_with_related_rows(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    first = client.post("/chemical/cases", json={"title": "删除目标", "target_markets": ["CN"]}).json()
    second = client.post("/chemical/cases", json={"title": "保留目标", "target_markets": ["EU"]}).json()

    deleted = client.delete(f"/chemical/cases/{first['id']}")

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_cases"] == 1
    assert client.get(f"/chemical/cases/{first['id']}").status_code == 404
    assert client.get(f"/chemical/cases/{second['id']}").status_code == 200


def test_case_board_exposes_single_case_delete_action() -> None:
    board_js = (Path(__file__).resolve().parents[1] / "app" / "static" / "pages" / "case-board" / "index.js").read_text(
        encoding="utf-8"
    )
    board_css = (Path(__file__).resolve().parents[1] / "app" / "static" / "pages" / "case-board" / "case-board.css").read_text(
        encoding="utf-8"
    )

    assert 'data-action="delete-case"' in board_js
    assert "api.cases.deleteOne" in board_js
    assert "confirm(" in board_js
    assert ".cb-delete" in board_css


def test_report_pdf_falls_back_when_playwright_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(tmp_path)
    created = client.post("/chemical/cases", json={"title": "PDF 降级 Case", "target_markets": ["CN"]}).json()
    store = client.app.state.service.store
    store.create_report(
        created["id"],
        {
            "customer_report": {
                "schema_version": "customer_report.v1",
                "verdict": "pass",
                "summary": "本次预审未发现需要客户立即处理的问题。",
                "issue_groups": [],
                "report_metadata": {"generated_at": "2026-05-13T00:00:00Z"},
            },
            "generated_at": "2026-05-13T00:00:00Z",
        },
    )
    store.update_case_review_state(
        case_id=created["id"],
        status="pass",
        latest_verdict="pass",
        latest_report_id=None,
    )

    async def unavailable(*args, **kwargs):  # noqa: ANN002, ANN003
        from app.pdf_render import PDFRendererUnavailable

        raise PDFRendererUnavailable("chromium 未安装")

    monkeypatch.setattr("app.pdf_render.render_case_report_pdf", unavailable)

    response = client.get(f"/api/cases/{created['id']}/report.pdf")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content


def test_dataset_combines_feature_coatings_and_main_retained_cases() -> None:
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in manifest["cases"]}

    assert FEATURE_COATING_CASES <= set(cases)
    assert set(MAIN_RETAINED_CASES) <= set(cases)

    for case_id, expected_rule in MAIN_RETAINED_CASES.items():
        case = cases[case_id]
        assert expected_rule in case["expected_rules"]
        assert case["expected_verdict"] == "\u590d\u6838"
        assert (DATASET_ROOT / case["sds_path"]).exists()
        assert (DATASET_ROOT / case["formula_path"]).exists()
        assert (DATASET_ROOT / case["process_path"]).exists()


def test_customer_user_text_prefers_rule_keywords_in_uploaded_source(tmp_path: Path) -> None:
    store = SQLiteStore(str(tmp_path / "risk-review.db"), str(tmp_path / "objects"))
    runner = ChemicalRagRunner(store, Settings(database_path=str(tmp_path / "risk-review.db")))

    text = runner._customer_user_text(
        ["formula_document"],
        [{"ref": "formula_document", "type": "\u8d44\u6599", "snippet": "SDS \u7ae0\u8282\u6570 16\uff1b\u7f3a\u5931\u5b57\u6bb5 ['\u65e0']\u3002"}],
        rule_meta={"expected_user_quote_keywords": ["VOC", "350"]},
        source_documents=[
            {
                "type": "\u914d\u65b9\u8868",
                "content": "\u4ea7\u54c1\u8bf4\u660e\nVOC \u68c0\u6d4b\u503c 350 g/L\uff0c\u9ad8\u4e8e\u4f01\u4e1a\u9650\u503c\u3002\n\u5176\u4ed6\u4fe1\u606f",
            }
        ],
    )

    assert "VOC" in text
    assert "350 g/L" in text
    assert "SDS \u7ae0\u8282\u6570" not in text


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
