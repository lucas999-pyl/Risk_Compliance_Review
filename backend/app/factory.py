from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    CaseCreate,
    ChemicalKnowledgeSearchCreate,
    ChemicalRunCreate,
    CaseRecord,
    DocumentRecord,
    ExtractionReviewCreate,
    ExtractionReviewRecord,
    FindingRecord,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceRecord,
    ReviewDecisionCreate,
    ReviewDecisionRecord,
    RunReviewResponse,
    TechnologyRunCreate,
)
from app.ai_clients import AIClientConfig, EmbeddingClient
from app.chemical_rag import ChemicalRagRunner
from app.service import ComplianceReviewService
from app.settings import Settings
from app.store import SQLiteStore
from app.vector_store import SQLiteVectorStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = SQLiteStore(settings.database_path, settings.storage_dir)
    ai_config = AIClientConfig(
        base_url=settings.openai_compatible_base_url,
        api_key=settings.openai_compatible_api_key,
        embedding_provider=settings.chem_rag_embedding_provider if settings.enable_llm else "hash",
        embedding_model=settings.chem_rag_embedding_model,
        embedding_dimensions=settings.chem_rag_embedding_dimensions,
        llm_provider=settings.chem_rag_llm_provider if settings.enable_llm else "disabled",
        llm_model=settings.chem_rag_llm_model,
        timeout_seconds=settings.chem_rag_request_timeout_seconds,
    )
    embedding_client = EmbeddingClient(ai_config)
    vector_store = SQLiteVectorStore(Path(settings.chem_rag_vector_store_dir) / "vectors.sqlite3", embedding_client)
    service = ComplianceReviewService(store, vector_store)
    chemical_runner = ChemicalRagRunner(store, settings=settings, vector_store=vector_store)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.service = service
    app.state.chemical_runner = chemical_runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_service() -> ComplianceReviewService:
        return app.state.service

    def get_chemical_runner() -> ChemicalRagRunner:
        return app.state.chemical_runner

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def workbench() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/data_samples/chemical_rag_dataset/upload_samples/{filename}", include_in_schema=False)
    def chemical_upload_sample(filename: str) -> FileResponse:
        sample_dir = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset" / "upload_samples"
        sample_path = (sample_dir / filename).resolve()
        if sample_path.parent != sample_dir.resolve() or not sample_path.exists():
            raise HTTPException(status_code=404, detail="Sample file not found")
        return FileResponse(sample_path)

    @app.get("/data_samples/chemical_knowledge_sources/official_pack_2026_05/{filename}", include_in_schema=False)
    def chemical_official_knowledge_sample(filename: str) -> FileResponse:
        sample_dir = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_knowledge_sources" / "official_pack_2026_05"
        sample_path = (sample_dir / filename).resolve()
        if sample_path.parent != sample_dir.resolve() or not sample_path.exists():
            raise HTTPException(status_code=404, detail="Knowledge source file not found")
        return FileResponse(sample_path)

    @app.get("/chemical/knowledge/source-files/{filename}", include_in_schema=False)
    def chemical_knowledge_source_file(filename: str) -> FileResponse:
        sample_dir = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_knowledge_sources" / "official_pack_2026_05"
        sample_path = (sample_dir / filename).resolve()
        if sample_path.parent != sample_dir.resolve() or not sample_path.exists():
            raise HTTPException(status_code=404, detail="Knowledge source file not found")
        media_type = "application/json" if sample_path.suffix == ".json" else "text/markdown; charset=utf-8"
        return FileResponse(sample_path, filename=sample_path.name, media_type=media_type)

    @app.get("/chemical/knowledge/source-pack.zip", include_in_schema=False)
    def chemical_knowledge_source_pack_zip() -> Response:
        import io

        sample_dir = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_knowledge_sources" / "official_pack_2026_05"
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for path in sorted(sample_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt", ".pdf"}:
                    archive.write(path, arcname=path.name)
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="official_pack_2026_05.zip"'},
        )

    @app.post("/cases", response_model=CaseRecord, status_code=201)
    def create_case(payload: CaseCreate, service: ComplianceReviewService = Depends(get_service)) -> dict:
        return service.create_case(payload)

    @app.post("/cases/{case_id}/documents", response_model=DocumentRecord, status_code=201)
    async def upload_document(
        case_id: str,
        document_type: str = Form("sds"),
        source_name: str | None = Form(None),
        file: UploadFile = File(...),
        service: ComplianceReviewService = Depends(get_service),
    ) -> dict:
        return await service.add_document(
            case_id=case_id,
            upload=file,
            document_type=document_type,
            source_name=source_name,
        )

    @app.post("/knowledge/sources", response_model=KnowledgeSourceRecord, status_code=201)
    def create_knowledge_source(
        payload: KnowledgeSourceCreate,
        service: ComplianceReviewService = Depends(get_service),
    ) -> dict:
        return service.create_knowledge_source(payload)

    @app.post("/knowledge/ingest", response_model=KnowledgeIngestResponse, status_code=201)
    def ingest_knowledge(
        payload: KnowledgeIngestRequest,
        service: ComplianceReviewService = Depends(get_service),
    ) -> dict:
        return service.ingest_knowledge(payload)

    @app.post("/cases/{case_id}/run-review", response_model=RunReviewResponse, status_code=202)
    def run_review(case_id: str, service: ComplianceReviewService = Depends(get_service)) -> dict:
        return service.run_review(case_id)

    @app.get("/cases/{case_id}/findings", response_model=list[FindingRecord])
    def get_findings(case_id: str, service: ComplianceReviewService = Depends(get_service)) -> list[dict]:
        return service.get_findings(case_id)

    @app.post("/findings/{finding_id}/review", response_model=ReviewDecisionRecord, status_code=201)
    def review_finding(
        finding_id: str,
        payload: ReviewDecisionCreate,
        service: ComplianceReviewService = Depends(get_service),
    ) -> dict:
        return service.review_finding(finding_id, payload)

    @app.post("/documents/{document_id}/extraction-review", response_model=ExtractionReviewRecord, status_code=201)
    def review_extraction(
        document_id: str,
        payload: ExtractionReviewCreate,
        service: ComplianceReviewService = Depends(get_service),
    ) -> dict:
        return service.review_extraction(document_id, payload)

    @app.get("/cases/{case_id}/report")
    def report(case_id: str, service: ComplianceReviewService = Depends(get_service)) -> dict:
        return service.build_report(case_id)

    @app.post("/chemical/runs", status_code=201)
    def create_chemical_run(
        payload: ChemicalRunCreate,
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        return runner.run_trace(payload.case_id, top_k=payload.top_k)

    @app.get("/chemical/evaluation")
    def chemical_evaluation(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.evaluate_dataset()

    @app.get("/chemical/vector-store")
    def chemical_vector_store(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.vector_store_status()

    @app.get("/chemical/knowledge/status")
    def chemical_knowledge_status(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.knowledge_status()

    @app.get("/chemical/knowledge/chunks")
    def chemical_knowledge_chunks(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.knowledge_chunks()

    @app.post("/chemical/knowledge/search")
    def chemical_knowledge_search(
        payload: ChemicalKnowledgeSearchCreate,
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        return runner.search_knowledge(payload.query, payload.target_markets, top_k=payload.top_k)

    @app.post("/chemical/knowledge/import-demo-pack", status_code=201)
    def chemical_import_demo_pack(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.import_demo_pack()

    @app.post("/chemical/knowledge/upload-pack", status_code=201)
    async def chemical_upload_knowledge_pack(
        manifest_file: UploadFile = File(...),
        source_files: list[UploadFile] = File(...),
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        manifest_raw = await manifest_file.read()
        try:
            import json

            manifest = json.loads(manifest_raw.decode("utf-8-sig"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {exc}") from exc
        source_texts = {}
        for upload in source_files:
            raw = await upload.read()
            text = runner.uploaded_document_from_bytes(
                filename=upload.filename or "source.txt",
                content_type=upload.content_type,
                raw=raw,
            )["content"]
            source_texts[upload.filename or "source.txt"] = text
        return runner.upload_knowledge_pack(manifest, source_texts)

    @app.delete("/chemical/knowledge")
    def chemical_clear_knowledge(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.clear_knowledge()

    @app.get("/chemical/query-presets")
    def chemical_query_presets(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.query_presets()

    @app.post("/chemical/retrieval-preview")
    def chemical_retrieval_preview(
        payload: ChemicalRunCreate,
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        return runner.retrieval_preview(payload.case_id, top_k=payload.top_k)

    @app.post("/chemical/upload-review", status_code=201)
    async def chemical_upload_review(
        title: str = Form(...),
        review_task: str = Form("请基于上传资料执行化工物料准入风险预审。"),
        check_types: str = Form(""),
        target_markets: str = Form("CN,EU,US"),
        top_k: int = Form(5),
        sds_file: UploadFile = File(...),
        formula_file: UploadFile = File(...),
        process_file: UploadFile = File(...),
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        top_k = max(1, min(int(top_k), 20))
        return runner.run_uploaded_documents(
            title=title,
            review_task=review_task,
            check_types=_parse_check_types(check_types),
            target_markets=_parse_target_markets(target_markets),
            top_k=top_k,
            sds=runner.uploaded_document_from_bytes(
                filename=sds_file.filename or "sds.txt",
                content_type=sds_file.content_type,
                raw=await sds_file.read(),
            ),
            formula=runner.uploaded_document_from_bytes(
                filename=formula_file.filename or "formula.txt",
                content_type=formula_file.content_type,
                raw=await formula_file.read(),
            ),
            process=runner.uploaded_document_from_bytes(
                filename=process_file.filename or "process.txt",
                content_type=process_file.content_type,
                raw=await process_file.read(),
            ),
        )

    @app.post("/technology/runs", status_code=201)
    def create_technology_run(
        payload: TechnologyRunCreate,
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        return runner.run_trace(payload.case_id, top_k=payload.top_k)

    @app.get("/technology/evaluation")
    def technology_evaluation(runner: ChemicalRagRunner = Depends(get_chemical_runner)) -> dict:
        return runner.evaluate_dataset()

    return app


def _parse_target_markets(value: str) -> list[str]:
    allowed = {"CN", "EU", "US", "GLOBAL"}
    markets = [item.strip().upper() for item in value.replace(";", ",").split(",") if item.strip()]
    filtered = [item for item in markets if item in allowed]
    return filtered or ["CN", "EU", "US"]


def _parse_check_types(value: str) -> list[str] | None:
    allowed = {"material", "process", "storage", "regulatory"}
    items = [item.strip().lower() for item in value.replace(";", ",").split(",") if item.strip()]
    filtered = [item for item in items if item in allowed]
    return filtered or None
