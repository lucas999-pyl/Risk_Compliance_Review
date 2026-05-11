from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "golden_dataset"


def test_golden_dataset_manifest_is_complete() -> None:
    manifest_path = DATASET_ROOT / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["dataset_id"] == "chemical_compliance_pre_review_golden_v1"
    assert manifest["data_policy"]["synthetic"] is True
    assert len(manifest["cases"]) >= 6

    case_ids = set()
    for case in manifest["cases"]:
        case_ids.add(case["case_id"])
        assert case["title"]
        assert case["material_type"] in {"mixture", "substance", "article"}
        assert case["target_markets"]
        assert case["intended_use"]
        assert (DATASET_ROOT / case["document_path"]).exists()
        assert case["knowledge_pack"] in {"demo_regulatory_pack", "empty"}
        assert case["expected_findings"]
        for expected in case["expected_findings"]:
            assert expected["jurisdiction"] in {"GLOBAL", "CN", "EU", "US"}
            assert expected["issue_type"]
            assert expected["severity"] in {"info", "low", "medium", "high", "critical", "review"}
            assert isinstance(expected["requires_human_review"], bool)

    assert len(case_ids) == len(manifest["cases"])


def test_demo_knowledge_pack_has_all_jurisdictions() -> None:
    pack_path = DATASET_ROOT / "knowledge" / "demo_regulatory_pack.json"
    assert pack_path.exists()

    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    assert pack["pack_id"] == "demo_regulatory_pack"
    assert pack["synthetic"] is True
    assert {source["jurisdiction"] for source in pack["sources"]} == {"CN", "EU", "US"}
    assert all(source["source_url"].startswith("https://") for source in pack["sources"])
    assert all(source["content"].strip() for source in pack["sources"])


def test_golden_dataset_cases_drive_review_workflow(tmp_path: Path) -> None:
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        client = TestClient(
            create_app(
                Settings(
                    database_path=str(tmp_path / f"{case['case_id']}.db"),
                    storage_dir=str(tmp_path / case["case_id"] / "objects"),
                    enable_llm=False,
                )
            )
        )
        if case["knowledge_pack"] == "demo_regulatory_pack":
            _ingest_demo_pack(client)

        created_case = client.post(
            "/cases",
            json={
                "title": case["title"],
                "material_type": case["material_type"],
                "target_markets": case["target_markets"],
                "intended_use": case["intended_use"],
            },
        )
        assert created_case.status_code == 201
        case_id = created_case.json()["id"]

        document_text = (DATASET_ROOT / case["document_path"]).read_text(encoding="utf-8")
        uploaded = client.post(
            f"/cases/{case_id}/documents",
            data={"document_type": "sds", "source_name": "golden_dataset"},
            files={"file": (Path(case["document_path"]).name, document_text.encode("utf-8"), "text/plain")},
        )
        assert uploaded.status_code == 201

        run = client.post(f"/cases/{case_id}/run-review")
        assert run.status_code == 202

        findings = client.get(f"/cases/{case_id}/findings").json()
        actual = {(finding["jurisdiction"], finding["issue_type"]) for finding in findings}
        expected = {(finding["jurisdiction"], finding["issue_type"]) for finding in case["expected_findings"]}
        assert expected.issubset(actual), case["case_id"]


def _ingest_demo_pack(client: TestClient) -> None:
    pack = json.loads((DATASET_ROOT / "knowledge" / "demo_regulatory_pack.json").read_text(encoding="utf-8"))
    for source in pack["sources"]:
        content = source["content"]
        payload = {key: value for key, value in source.items() if key != "content"}
        created = client.post("/knowledge/sources", json=payload)
        assert created.status_code == 201
        ingested = client.post("/knowledge/ingest", json={"source_id": created.json()["id"], "content": content})
        assert ingested.status_code == 201
