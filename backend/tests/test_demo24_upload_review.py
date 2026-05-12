from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"
SAMPLES_ROOT = DATASET_ROOT / "upload_samples"


def test_upload_review_runs_real_uploaded_documents_through_rag_stack(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_sample(client, "incompatible_oxidizer_flammable")

    assert payload["case_source"] == "uploaded"
    assert payload["case_id"].startswith("case_")
    assert payload["verdict"] == "不合规"
    assert payload["needs_human"] is False
    assert "evaluation" not in payload
    assert all("expected_verdict" not in node["output"] for node in payload["trace"]["nodes"])
    assert {item["document_type"] for item in payload["uploaded_documents"]} == {"sds", "formula", "process"}
    assert {item["document_type"] for item in payload["parsed_documents"]} == {"sds", "formula", "process"}
    assert payload["review_workbench"]["source_documents"]
    assert payload["retrieval"]["chunks"]
    assert set(payload["sub_agent_results"]) == {"物料", "工艺", "储运", "法规"}
    assert any(hit["rule_id"] == "incompatibility_oxidizer_flammable" for hit in payload["rule_hits"])
    assert any("CAS exact match" in " ".join(chunk["rerank_reasons"]) for chunk in payload["retrieval"]["chunks"])


def test_upload_review_unknown_or_missing_inputs_stays_in_review(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_sample(client, "unknown_missing_process")

    assert payload["case_source"] == "uploaded"
    assert payload["verdict"] == "复核"
    assert payload["needs_human"] is True
    assert any(
        item["status"] == "missing" and item["field"] in {"process_temperature", "process_pressure", "process_steps"}
        for item in payload["review_workbench"]["extracted_checklist"]
    )
    assert any(hit["rule_id"] in {"unknown_substance_review", "process_parameters_missing"} for hit in payload["rule_hits"])


def test_knowledge_chunks_and_free_query_search_make_vector_store_auditable(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    imported = client.post("/chemical/knowledge/import-demo-pack")
    assert imported.status_code == 201

    chunks = client.get("/chemical/knowledge/chunks")
    assert chunks.status_code == 200
    chunk_payload = chunks.json()
    assert chunk_payload["source_count"] >= 1
    assert chunk_payload["chunk_count"] == chunk_payload["vector_count"]
    first = chunk_payload["chunks"][0]
    assert {"chunk_id", "source_title", "jurisdiction", "version", "effective_date", "source_url", "tokens", "content", "vector_status"} <= set(first)
    assert first["vector_status"] == "indexed"

    search = client.post(
        "/chemical/knowledge/search",
        json={"query": "CAS 64-17-5 过氧化氢 氧化剂 可燃液体 禁忌", "target_markets": ["CN", "EU", "US"], "top_k": 5},
    )
    assert search.status_code == 200
    retrieval = search.json()["retrieval"]
    assert retrieval["strategy"] == "hybrid_vector_keyword_rerank"
    assert retrieval["chunks"]
    assert any("CAS exact match" in " ".join(chunk["rerank_reasons"]) for chunk in retrieval["chunks"])


def _upload_sample(client: TestClient, sample_id: str) -> dict:
    files = {
        "sds_file": (f"{sample_id}_sds.txt", (SAMPLES_ROOT / f"{sample_id}_sds.txt").read_bytes(), "text/plain"),
        "formula_file": (f"{sample_id}_formula.txt", (SAMPLES_ROOT / f"{sample_id}_formula.txt").read_bytes(), "text/plain"),
        "process_file": (f"{sample_id}_process.txt", (SAMPLES_ROOT / f"{sample_id}_process.txt").read_bytes(), "text/plain"),
    }
    response = client.post(
        "/chemical/upload-review",
        data={"title": f"上传样张审查 {sample_id}", "target_markets": "CN,EU,US", "top_k": "6"},
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
