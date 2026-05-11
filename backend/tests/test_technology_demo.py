from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "golden_dataset"


def test_technology_trace_run_exposes_graph_rag_and_rule_steps(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_demo_pack(client)

    response = client.post("/technology/runs", json={"case_id": "chemical_compliant_formula", "top_k": 4})

    assert response.status_code == 201
    trace = response.json()
    assert trace["run_id"].startswith("chemrun_")
    assert trace["case_id"] == "chemical_compliant_formula"
    assert trace["verdict"] == "合规"
    assert set(trace["sub_agent_results"]) == {"物料", "工艺", "储运", "法规"}
    assert trace["graph"]["engine"] in {"langgraph", "deterministic_state_graph"}
    assert [node["node_id"] for node in trace["trace"]["nodes"]] == [
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
    assert trace["retrieval"]["mode"] == "local_vector"
    assert trace["retrieval"]["queries"]
    assert trace["retrieval"]["chunks"]
    assert all("score" in chunk and "source_url" in chunk for chunk in trace["retrieval"]["chunks"])
    assert trace["rule_hits"]
    assert all("rule_id" in hit and "evidence_ids" in hit for hit in trace["rule_hits"])
    assert trace["evidences"]
    assert trace["evaluation"]["case_id"] == "chemical_compliant_formula"
    assert trace["evaluation"]["verdict_matched"] is True
    assert 0.0 <= trace["evaluation"]["evidence_coverage"] <= 1.0
    assert trace["replay"]["checkpoint_count"] == len(trace["trace"]["nodes"])


def test_technology_evaluation_summarizes_golden_dataset(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_demo_pack(client)

    response = client.get("/technology/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_id"] == "chemical_rag_golden_v1"
    assert payload["case_count"] >= 4
    assert payload["metrics"]["verdict_match_rate"] >= 0.75
    assert payload["metrics"]["average_evidence_coverage"] > 0
    assert payload["cases"]
    assert all("retrieved_chunk_count" in case for case in payload["cases"])
    assert all("verdict_matched" in case for case in payload["cases"])


def test_static_workbench_contains_technology_demo_tabs(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "化工合规 RAG 工具" in response.text
    assert "三值判定" in response.text
    assert "物料 Agent" in response.text
    assert "流程回放" in response.text
    assert "评测看板" in response.text
    assert "/chemical/upload-review" in response.text
    assert "/chemical/knowledge/search" in response.text
    assert "鍖栧" not in response.text


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


def _ingest_demo_pack(client: TestClient) -> None:
    pack = json.loads((Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset" / "knowledge" / "chemical_rules_pack.json").read_text(encoding="utf-8"))
    for source in pack["sources"]:
        content = source["content"]
        created = client.post("/knowledge/sources", json={key: value for key, value in source.items() if key != "content"})
        assert created.status_code == 201, created.text
        ingested = client.post("/knowledge/ingest", json={"source_id": created.json()["id"], "content": content})
        assert ingested.status_code == 201, ingested.text
