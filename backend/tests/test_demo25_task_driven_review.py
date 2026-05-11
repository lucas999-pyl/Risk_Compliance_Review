from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"
SAMPLES_ROOT = DATASET_ROOT / "upload_samples"
DEFAULT_REVIEW_TASK = "请基于上传资料执行化工物料准入风险预审。"
ELECTRONICS_REVIEW_TASK = "请判断该供应商清洗剂是否可用于电子零部件清洗工艺，并进入 CN/EU 市场。"


def test_upload_review_is_driven_by_review_task_and_agent_branch_queries(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_sample(client, "incompatible_oxidizer_flammable", review_task=ELECTRONICS_REVIEW_TASK)

    assert payload["case_source"] == "uploaded"
    assert payload["review_task"] == ELECTRONICS_REVIEW_TASK
    assert payload["verdict"] == "不合规"
    assert "expected_verdict" not in payload
    assert "verdict_matched" not in payload

    decomposition = payload["task_decomposition"]
    assert [item["agent"] for item in decomposition] == ["资料完整性", "物料", "工艺", "储运", "法规"]
    assert all(ELECTRONICS_REVIEW_TASK in item["review_task"] for item in decomposition)

    rag_queries = payload["rag_queries"]
    assert set(rag_queries) == {"资料完整性", "物料", "工艺", "储运", "法规"}
    assert all(ELECTRONICS_REVIEW_TASK in query for query in rag_queries.values())
    assert len(set(rag_queries.values())) == len(rag_queries)
    assert payload["retrieval"]["queries"] == list(rag_queries.values())

    branches = payload["agent_branches"]
    assert set(branches) == {"资料完整性", "物料", "工艺", "储运", "法规"}
    for agent_name, branch in branches.items():
        assert branch["task"]
        assert branch["input_summary"]
        assert branch["rag_query"] == rag_queries[agent_name]
        assert branch["evidence_refs"]
        assert branch["rule_refs"]
        assert branch["reasoning_steps"]
        assert branch["verdict"] in {"合规", "复核", "不合规"}
        assert 0 <= branch["confidence"] <= 1

    chief = payload["chief_synthesis"]
    assert chief["final_verdict"] == "不合规"
    assert "incompatibility_oxidizer_flammable" in chief["hard_stop_rules"]
    assert any(item["agent"] in {"工艺", "储运"} for item in chief["adopted_conclusions"])

    workbench = payload["review_workbench"]
    assert workbench["review_task"] == ELECTRONICS_REVIEW_TASK
    assert workbench["task_decomposition"] == decomposition
    assert workbench["agent_branch_summary"]
    assert workbench["chief_review_summary"]["final_verdict"] == "不合规"


def test_upload_review_without_review_task_uses_conservative_default(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_sample(client, "compliant_water_cleaner")

    assert payload["review_task"] == DEFAULT_REVIEW_TASK
    assert payload["task_decomposition"][0]["review_task"] == DEFAULT_REVIEW_TASK
    assert all(DEFAULT_REVIEW_TASK in query for query in payload["rag_queries"].values())


def test_unknown_or_missing_package_is_reviewed_by_chief_synthesis(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/chemical/knowledge/import-demo-pack")

    payload = _upload_sample(client, "unknown_missing_process", review_task=ELECTRONICS_REVIEW_TASK)

    assert payload["verdict"] == "复核"
    assert payload["needs_human"] is True
    chief = payload["chief_synthesis"]
    assert chief["final_verdict"] == "复核"
    review_text = " ".join(chief["review_items"] + chief["synthesis"])
    assert any(keyword in review_text for keyword in ["未知", "缺少", "工艺", "复核"])


def _upload_sample(client: TestClient, sample_id: str, review_task: str | None = None) -> dict:
    files = {
        "sds_file": (f"{sample_id}_sds.txt", (SAMPLES_ROOT / f"{sample_id}_sds.txt").read_bytes(), "text/plain"),
        "formula_file": (f"{sample_id}_formula.txt", (SAMPLES_ROOT / f"{sample_id}_formula.txt").read_bytes(), "text/plain"),
        "process_file": (f"{sample_id}_process.txt", (SAMPLES_ROOT / f"{sample_id}_process.txt").read_bytes(), "text/plain"),
    }
    data = {
        "title": f"供应商资料包审查 {sample_id}",
        "target_markets": "CN,EU,US",
        "top_k": "6",
    }
    if review_task is not None:
        data["review_task"] = review_task
    response = client.post("/chemical/upload-review", data=data, files=files)
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
