from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai_clients import AIClientConfig, LLMClient
from app.factory import create_app
from app.knowledge import KnowledgeChunk
from app.settings import Settings
from app.vector_store import SQLiteVectorStore


DATASET_ROOT = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset"


def test_demo_pack_import_status_clear_and_retrieval_preview_make_rag_visible(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    initial = client.get("/chemical/knowledge/status")
    assert initial.status_code == 200
    assert initial.json()["metadata_source"] == "empty_customer_knowledge_base"
    assert initial.json()["knowledge_base"]["source_count"] == 0
    assert initial.json()["vector_store"]["vector_count"] == 0

    imported = client.post("/chemical/knowledge/import-demo-pack")
    assert imported.status_code == 201, imported.text
    import_payload = imported.json()
    assert import_payload["pack_id"] == "chemical_rules_pack"
    assert import_payload["source_count"] >= 5
    assert import_payload["chunk_count"] >= 5
    assert import_payload["vector_count"] == import_payload["chunk_count"]
    assert import_payload["sources"][0]["title"]
    assert import_payload["sources"][0]["chunk_count"] >= 1

    status = client.get("/chemical/knowledge/status").json()
    assert status["metadata_source"] == "sqlite_knowledge_base"
    assert status["knowledge_base"]["source_count"] == import_payload["source_count"]
    assert status["vector_store"]["vector_count"] == import_payload["chunk_count"]
    assert status["sources"]
    assert status["sources"][0]["source_url"]

    preview = client.post(
        "/chemical/retrieval-preview",
        json={"case_id": "chemical_incompatible_formula", "top_k": 5},
    )
    assert preview.status_code == 200, preview.text
    preview_payload = preview.json()
    assert preview_payload["query"]
    assert preview_payload["retrieval"]["strategy"] == "hybrid_vector_keyword_rerank"
    assert preview_payload["retrieval"]["chunks"]
    first = preview_payload["retrieval"]["chunks"][0]
    assert "vector_score" in first
    assert "keyword_score" in first
    assert "rerank_score" in first
    assert first["rerank_reasons"]

    cleared = client.delete("/chemical/knowledge")
    assert cleared.status_code == 200
    assert cleared.json()["deleted_sources"] == import_payload["source_count"]
    after_clear = client.get("/chemical/knowledge/status").json()
    assert after_clear["knowledge_base"]["source_count"] == 0
    assert after_clear["vector_store"]["vector_count"] == 0


def test_knowledge_status_syncs_vectors_to_current_sqlite_chunks(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    runner = client.app.state.chemical_runner
    runner.vector_store.clear()

    status = client.get("/chemical/knowledge/status").json()

    assert status["metadata_source"] == "sqlite_knowledge_base"
    assert status["knowledge_base"]["chunk_count"] > 0
    assert status["vector_store"]["vector_count"] == status["knowledge_base"]["chunk_count"]


def test_import_demo_pack_reports_pruned_final_vector_count(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    runner = client.app.state.chemical_runner
    runner.vector_store.upsert_chunks(runner._pack_chunks({"GLOBAL", "CN", "EU", "US"}))

    payload = client.post("/chemical/knowledge/import-demo-pack").json()

    assert payload["chunk_count"] >= 7
    assert payload["vector_count"] == payload["chunk_count"]


def test_knowledge_ingest_builds_persistent_vector_index(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.get("/chemical/vector-store")

    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] >= 5
    assert payload["vector_count"] >= 5
    assert payload["embedding_provider"] in {"hash", "openai_compatible"}
    assert payload["embedding_model"]
    assert payload["store_type"] == "sqlite_vector_store"


def test_chemical_run_uses_hybrid_vector_retrieval_and_rerank(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/chemical/runs", json={"case_id": "chemical_incompatible_formula", "top_k": 5})

    assert response.status_code == 201, response.text
    payload = response.json()
    retrieval = payload["retrieval"]
    assert retrieval["strategy"] == "hybrid_vector_keyword_rerank"
    assert retrieval["vector_store"]["type"] == "sqlite_vector_store"
    assert retrieval["embedding"]["model"]
    assert retrieval["rerank"]["mode"] == "rules"
    assert retrieval["chunks"]
    assert all("vector_score" in chunk for chunk in retrieval["chunks"])
    assert all("keyword_score" in chunk for chunk in retrieval["chunks"])
    assert all("rerank_score" in chunk for chunk in retrieval["chunks"])
    assert any("CAS" in " ".join(chunk["rerank_reasons"]) for chunk in retrieval["chunks"])


def test_agent_outputs_expose_llm_collaboration_metadata_without_overriding_rules(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)

    response = client.post("/chemical/runs", json={"case_id": "chemical_missing_sds_or_process", "top_k": 4})

    assert response.status_code == 201
    payload = response.json()
    assert payload["verdict"] == "复核"
    assert payload["agent_orchestration"]["mode"] in {"deterministic_state_graph", "langgraph"}
    assert payload["agent_orchestration"]["llm_model"]
    assert payload["agent_orchestration"]["llm_provider"] in {"disabled", "openai_compatible"}
    for result in payload["sub_agent_results"].values():
        assert "llm_used" in result
        assert "llm_reasoning" in result
        assert result["verdict"] in {"合规", "复核", "不合规"}
    chief = payload["chief_review"]
    assert chief["verdict"] == "复核"
    assert chief["source"] == "rules_first_llm_assisted"
    assert chief["llm_used"] is False


def test_vector_index_rebuilds_chunks_when_embedding_model_changes(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    client.get("/chemical/vector-store")

    app = client.app
    runner = app.state.chemical_runner
    index_path = runner.vector_store.index_path
    chunk_count = runner.vector_store.stats()["vector_count"]
    first_chunk_id = runner.store.get_knowledge_chunks()[0].id

    with runner.vector_store.connect() as connection:
        connection.execute(
            "UPDATE vectors SET embedding_model = ? WHERE chunk_id = ?",
            ("legacy-embedding-model", first_chunk_id),
        )

    rebuilt = SQLiteVectorStore(index_path, runner.embedding_client).upsert_chunks(runner.store.get_knowledge_chunks())

    assert rebuilt >= 1
    stats = SQLiteVectorStore(index_path, runner.embedding_client).stats()
    assert stats["vector_count"] == chunk_count
    assert stats["embedding_model"] == runner.ai_config.embedding_model


def test_vector_index_rebuilds_chunks_when_chunk_content_changes(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    client.get("/chemical/vector-store")

    runner = client.app.state.chemical_runner
    first_chunk = runner.store.get_knowledge_chunks()[0]

    with runner.vector_store.connect() as connection:
        connection.execute(
            "UPDATE vectors SET content = ? WHERE chunk_id = ?",
            ("stale indexed content", first_chunk.id),
        )

    rebuilt = SQLiteVectorStore(runner.vector_store.index_path, runner.embedding_client).upsert_chunks(
        runner.store.get_knowledge_chunks()
    )

    assert rebuilt >= 1
    with runner.vector_store.connect() as connection:
        row = connection.execute("SELECT content FROM vectors WHERE chunk_id = ?", (first_chunk.id,)).fetchone()
    assert row["content"] == first_chunk.content


def test_settings_prefers_project_env_file_over_machine_openai_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENAI_API_KEY=project-bailian-key",
                "RCR_ENABLE_LLM=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_BASE", "https://wrong.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "machine-openai-key")

    settings = Settings(_env_file=env_file)

    assert settings.openai_compatible_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.openai_compatible_api_key == "project-bailian-key"
    assert settings.enable_llm is True


def test_vector_store_prunes_chunks_missing_from_current_knowledge_set(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _ingest_rules(client)
    runner = client.app.state.chemical_runner
    runner.vector_store.upsert_chunks(runner.store.get_knowledge_chunks())
    chunk_count = runner.vector_store.stats()["vector_count"]

    kept_chunks = runner.store.get_knowledge_chunks()[1:]
    removed_id = runner.store.get_knowledge_chunks()[0].id
    pruned = SQLiteVectorStore(runner.vector_store.index_path, runner.embedding_client).sync_chunks(kept_chunks)

    assert pruned == 1
    assert runner.vector_store.stats()["vector_count"] == chunk_count - 1
    with runner.vector_store.connect() as connection:
        row = connection.execute("SELECT chunk_id FROM vectors WHERE chunk_id = ?", (removed_id,)).fetchone()
    assert row is None


def test_vector_store_embeds_pending_chunks_in_small_batches(tmp_path: Path) -> None:
    class FakeEmbeddingClient:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.last_provider = "openai_compatible"
            self.config = type(
                "Config",
                (),
                {
                    "embedding_provider": "qwen",
                    "base_url": "https://example.test/v1",
                    "api_key": "fake",
                    "embedding_model": "fake-embedding",
                    "embedding_dimensions": 8,
                },
            )()

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(len(texts))
            return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

    chunks = [
        KnowledgeChunk(
            id=f"chunk_{index}",
            source_id=f"source_{index}",
            jurisdiction="GLOBAL",
            source_type="internal_rule",
            source_url="internal://test",
            version="v1",
            effective_date="2026-05-01",
            content=f"rule content {index}",
            tokens=["rule", str(index)],
        )
        for index in range(35)
    ]
    client = FakeEmbeddingClient()
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite3", client)

    inserted = store.upsert_chunks(chunks)

    assert inserted == 35
    assert client.calls == [10, 10, 10, 5]


def test_evaluation_does_not_call_remote_llm(tmp_path: Path) -> None:
    client = _make_client(tmp_path, enable_llm=True)
    runner = client.app.state.chemical_runner

    def fail_if_called(**_: object) -> dict:
        raise AssertionError("evaluation should not call LLM")

    runner.llm_client.summarize_agent = fail_if_called

    payload = runner.evaluate_dataset()

    assert payload["case_count"] >= 12
    assert payload["metrics"]["verdict_match_rate"] == 1.0


def test_chemical_evaluation_endpoint_uses_fast_rules_mode_when_llm_enabled(tmp_path: Path) -> None:
    client = _make_client(tmp_path, enable_llm=True)
    runner = client.app.state.chemical_runner

    def fail_if_called(**_: object) -> dict:
        raise AssertionError("evaluation endpoint should not call LLM")

    runner.llm_client.summarize_agent = fail_if_called

    response = client.get("/chemical/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_count"] >= 12
    assert payload["metrics"]["verdict_match_rate"] == 1.0


def test_run_trace_calls_llm_agents_concurrently(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    runner = client.app.state.chemical_runner
    calls = []

    def slow_summary(**kwargs: object) -> dict:
        calls.append(kwargs["agent_name"])
        time.sleep(0.1)
        runner.llm_client.last_provider = "openai_compatible"
        return {"llm_used": True, "llm_reasoning": f"{kwargs['agent_name']} explanation", "llm_error": None}

    runner.llm_client.summarize_agent = slow_summary

    started = time.perf_counter()
    payload = runner.run_trace("chemical_compliant_formula")
    elapsed = time.perf_counter() - started

    assert payload["agent_orchestration"]["llm_provider"] == "openai_compatible"
    assert set(calls) == {"资料完整性", "物料", "工艺", "储运", "法规"}
    assert elapsed < 0.35
    assert all(result["llm_used"] for result in payload["sub_agent_results"].values())


def test_llm_client_uses_low_latency_non_thinking_request_for_agent_explanations() -> None:
    captured = {}

    @contextmanager
    def fake_urlopen(request, timeout: float):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps({"choices": [{"message": {"content": "证据解释"}}]}).encode("utf-8")

        yield FakeResponse()

    client = LLMClient(
        AIClientConfig(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="fake",
            embedding_provider="qwen",
            embedding_model="text-embedding-v4",
            embedding_dimensions=1024,
            llm_provider="qwen",
            llm_model="qwen3.6-plus",
            timeout_seconds=7,
        )
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.summarize_agent(agent_name="物料", verdict="复核", reasons=["缺少 CAS"], evidence_snippets=["SDS 证据"])

    assert result["llm_used"] is True
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "qwen3.6-plus"
    assert captured["payload"]["enable_thinking"] is False
    assert captured["payload"]["max_tokens"] == 220
    assert "/no_think" in captured["payload"]["messages"][-1]["content"]


def test_embedding_client_uses_qwen_v4_dimensions_and_float_encoding() -> None:
    captured = {}

    @contextmanager
    def fake_urlopen(request, timeout: float):
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]}).encode("utf-8")

        yield FakeResponse()

    from app.ai_clients import EmbeddingClient

    client = EmbeddingClient(
        AIClientConfig(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="fake",
            embedding_provider="qwen",
            embedding_model="text-embedding-v4",
            embedding_dimensions=1024,
            llm_provider="qwen",
            llm_model="qwen3.6-plus",
            timeout_seconds=7,
        )
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        vectors = client.embed_texts(["化工规则"])

    assert vectors
    assert captured["payload"]["model"] == "text-embedding-v4"
    assert captured["payload"]["dimensions"] == 1024
    assert captured["payload"]["encoding_format"] == "float"


def _make_client(tmp_path: Path, enable_llm: bool = False) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=str(tmp_path / "risk-review.db"),
                storage_dir=str(tmp_path / "objects"),
                chem_rag_vector_store_dir=str(tmp_path / "vector_store"),
                enable_llm=enable_llm,
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
