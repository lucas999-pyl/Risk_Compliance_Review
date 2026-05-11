from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.factory import create_app
from app.settings import Settings


OFFICIAL_PACK_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_knowledge_sources" / "official_pack_2026_05"
SAMPLES_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset" / "upload_samples"


def test_official_knowledge_pack_sources_are_auditable() -> None:
    manifest = json.loads((OFFICIAL_PACK_ROOT / "manifest.json").read_text(encoding="utf-8"))

    official_sources = [source for source in manifest["sources"] if source["source_origin"] == "official"]
    internal_sources = [source for source in manifest["sources"] if source["source_origin"] == "internal"]

    assert len(official_sources) >= 4
    assert len(internal_sources) >= 1
    assert {source["jurisdiction"] for source in official_sources} >= {"CN", "EU", "US"}
    for source in manifest["sources"]:
        assert source["source_url"]
        assert source["version"]
        assert source["effective_date"]
        assert source["retrieved_at"]
        assert source["quality_tier"] in {"official", "internal_controlled"}
        assert (OFFICIAL_PACK_ROOT / source["filename"]).read_text(encoding="utf-8").strip()


def test_official_knowledge_pack_zip_is_available_for_manual_upload() -> None:
    archive_path = OFFICIAL_PACK_ROOT.parent / "official_pack_2026_05.zip"
    manifest = json.loads((OFFICIAL_PACK_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert archive_path.exists()
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())

    assert "manifest.json" in names
    assert {source["filename"] for source in manifest["sources"]} <= names



def test_empty_customer_knowledge_base_does_not_expose_fallback_chunks_or_vectors(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.delete("/chemical/knowledge")

    status = client.get("/chemical/knowledge/status").json()
    chunks = client.get("/chemical/knowledge/chunks").json()
    search = client.post(
        "/chemical/knowledge/search",
        json={"query": "?? ???? ??", "target_markets": ["CN", "EU", "US"], "top_k": 5},
    ).json()

    assert status["metadata_source"] == "empty_customer_knowledge_base"
    assert "fallback_pack" not in status
    assert "fallback_vector_count" not in client.delete("/chemical/knowledge").json()
    assert status["knowledge_base"] == {"source_count": 0, "chunk_count": 0}
    assert status["vector_store"]["vector_count"] == 0
    assert chunks["metadata_source"] == "empty_customer_knowledge_base"
    assert chunks["source_count"] == 0
    assert chunks["chunk_count"] == 0
    assert chunks["vector_count"] == 0
    assert chunks["chunks"] == []
    assert search["retrieval"]["chunks"] == []
    assert search["retrieval"]["vector_store"]["vector_count"] == 0
    assert search["requires_knowledge_upload"] is True


def test_empty_customer_knowledge_base_prunes_stale_vectors_before_reporting(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    runner = client.app.state.chemical_runner
    runner.vector_store.upsert_chunks(runner._pack_chunks({"GLOBAL", "CN", "EU", "US"}))

    stale_stats = runner.vector_store.stats()
    assert stale_stats["vector_count"] >= 7

    status = client.get("/chemical/knowledge/status").json()
    chunks = client.get("/chemical/knowledge/chunks").json()

    assert status["knowledge_base"] == {"source_count": 0, "chunk_count": 0}
    assert status["vector_store"]["vector_count"] == 0
    assert status["metadata_source"] == "empty_customer_knowledge_base"
    assert chunks["chunk_count"] == 0
    assert chunks["vector_count"] == 0
    assert chunks["chunks"] == []


def test_upload_official_knowledge_pack_builds_auditable_vector_store(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    uploaded = _upload_official_pack(client)

    assert uploaded["pack_id"] == "official_chemical_compliance_pack_2026_05"
    assert uploaded["source_count"] >= 5
    assert uploaded["chunk_count"] == uploaded["vector_count"]
    assert uploaded["validation_warnings"] == []
    assert uploaded["embedding"]["provider"]
    assert any(source["source_origin"] == "official" for source in uploaded["sources"])

    chunks = client.get("/chemical/knowledge/chunks").json()
    first = chunks["chunks"][0]
    assert {"source_origin", "quality_tier", "retrieved_at", "document_role"} <= set(first)
    assert chunks["metadata_source"] == "uploaded_knowledge_pack"

    search = client.post(
        "/chemical/knowledge/search",
        json={"query": "OSHA SDS 16 sections Appendix D supplier revision date", "target_markets": ["US"], "top_k": 5},
    )
    assert search.status_code == 200
    contents = " ".join(chunk["content"] for chunk in search.json()["retrieval"]["chunks"])
    assert "OSHA" in contents
    assert "SDS" in contents


def test_upload_review_without_loaded_knowledge_pack_is_conservative_review(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    payload = _upload_sample(client, "incompatible_oxidizer_flammable")

    assert payload["verdict"] == "复核"
    assert payload["needs_human"] is True
    assert payload["knowledge_pack"]["status"] == "missing"
    assert any("知识库未加载" in reason for reason in payload["reasons"])
    assert any("知识库未加载" in item for item in payload["chief_synthesis"]["review_items"])


def test_upload_review_with_official_pack_returns_document_quality_and_supplement_actions(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _upload_official_pack(client)

    payload = _upload_sample(client, "unknown_missing_process")

    quality = payload["review_workbench"]["document_quality"]
    assert quality["score"] < 100
    assert quality["blocking_gaps"]
    assert any(gap["field"] in {"process_temperature", "process_pressure", "process_steps"} for gap in quality["blocking_gaps"])
    assert payload["review_workbench"]["supplement_actions"]
    assert any("补充" in action["action"] for action in payload["review_workbench"]["supplement_actions"])
    assert any("工艺" in item for item in payload["chief_synthesis"]["review_items"])
    assert payload["review_workbench"]["precheck"]["mode"] == "deterministic_function"
    assert payload["review_workbench"]["precheck"]["agent_removed"] is True
    assert any(section["dimension"] == "资料完整性" for section in payload["review_workbench"]["structured_report"]["sections"])


def test_query_presets_are_business_ready(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    response = client.get("/chemical/query-presets")

    assert response.status_code == 200
    presets = response.json()["presets"]
    assert len(presets) >= 5
    assert {"sds_completeness", "cn_eu_market_access", "oxidizer_flammable_incompatibility", "unknown_cas_review", "svhc_tsca_screening"} <= {
        item["id"] for item in presets
    }
    assert all(item["query"] and item["target_markets"] for item in presets)



def test_official_knowledge_source_downloads_are_attachment_and_pack_zip(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    single = client.get("/chemical/knowledge/source-files/manifest.json")

    assert single.status_code == 200
    assert "attachment" in single.headers["content-disposition"]
    assert single.json()["pack_id"] == "official_chemical_compliance_pack_2026_05"

    bundle = client.get("/chemical/knowledge/source-pack.zip")

    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert "attachment" in bundle.headers["content-disposition"]
    assert len(bundle.content) > 1000

def _upload_official_pack(client: TestClient) -> dict:
    manifest = json.loads((OFFICIAL_PACK_ROOT / "manifest.json").read_text(encoding="utf-8"))
    files = [
        ("manifest_file", ("manifest.json", (OFFICIAL_PACK_ROOT / "manifest.json").read_bytes(), "application/json")),
    ]
    for source in manifest["sources"]:
        path = OFFICIAL_PACK_ROOT / source["filename"]
        files.append(("source_files", (path.name, path.read_bytes(), "text/markdown")))
    response = client.post("/chemical/knowledge/upload-pack", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def _upload_sample(client: TestClient, sample_id: str) -> dict:
    files = {
        "sds_file": (f"{sample_id}_sds.txt", (SAMPLES_ROOT / f"{sample_id}_sds.txt").read_bytes(), "text/plain"),
        "formula_file": (f"{sample_id}_formula.txt", (SAMPLES_ROOT / f"{sample_id}_formula.txt").read_bytes(), "text/plain"),
        "process_file": (f"{sample_id}_process.txt", (SAMPLES_ROOT / f"{sample_id}_process.txt").read_bytes(), "text/plain"),
    }
    response = client.post(
        "/chemical/upload-review",
        data={
            "title": f"供应商资料包审查 {sample_id}",
            "review_task": "请判断该供应商资料是否满足化工物料准入预审要求。",
            "target_markets": "CN,EU,US",
            "top_k": "5",
        },
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
