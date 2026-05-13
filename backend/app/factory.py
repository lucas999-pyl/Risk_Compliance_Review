from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
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
from app.chemical_rag import ChemicalRagRunner, CHECK_TYPE_LABELS, LEGACY_CHECK_TYPE_MAP, SCENARIO_RECOMMENDED_CHECK_TYPES
from app.demo_cases import demo_case_catalog
from app import reporting
from app.service import ComplianceReviewService
from app.settings import Settings
from app.store import SQLiteStore
from app.vector_store import SQLiteVectorStore


REVIEW_SCENARIO_LABELS_FOR_FACTORY = {
    "market_access": "市场准入预审",
    "substitution": "替代物料评估",
    "supplier_intake": "供应商资料准入",
    "process_introduction": "工艺导入风险评估",
    "storage_safety": "储运与现场安全评估",
}


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

    @app.get("/data_samples/chemical_rag_dataset/documents/{filename}", include_in_schema=False)
    def chemical_dataset_document(filename: str) -> FileResponse:
        sample_dir = Path(__file__).resolve().parents[2] / "data_samples" / "chemical_rag_dataset" / "documents"
        sample_path = (sample_dir / filename).resolve()
        if sample_path.parent != sample_dir.resolve() or not sample_path.exists():
            raise HTTPException(status_code=404, detail="Dataset file not found")
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

    @app.get("/chemical/demo-cases")
    def chemical_demo_cases() -> dict:
        return demo_case_catalog()

    @app.get("/chemical/cases")
    def chemical_case_list() -> dict:
        return {"cases": store.list_cases()}

    @app.delete("/chemical/cases")
    def chemical_case_clear() -> dict:
        return store.delete_cases()

    @app.post("/chemical/cases", status_code=201)
    def chemical_case_create(payload: CaseCreate) -> dict:
        return store.create_case(
            CaseCreate(
                title=payload.title,
                material_type=payload.material_type,
                target_markets=payload.target_markets,
                intended_use=payload.intended_use,
                review_scenario=payload.review_scenario,
                check_types=_normalize_check_type_list(payload.check_types, payload.review_scenario),
            )
        )

    @app.get("/chemical/cases/{case_id}")
    def chemical_case_detail(case_id: str) -> dict:
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        latest_report = store.latest_report(case_id)
        latest_payload = latest_report["payload"] if latest_report else None
        return {
            "case": case,
            "documents": store.get_documents(case_id),
            "document_count": len(store.get_documents(case_id)),
            "latest_report": latest_payload,
            "package_precheck": latest_payload.get("package_precheck") if latest_payload else None,
        }

    @app.get("/chemical/cases/{case_id}/report.json")
    def chemical_case_report_json(case_id: str) -> JSONResponse:
        report = _latest_customer_report_or_404(store, case_id)
        return JSONResponse(report, headers={"Content-Disposition": f'attachment; filename="{reporting.customer_report_filename(report, "json")}"'})

    @app.get("/chemical/cases/{case_id}/report.html")
    def chemical_case_report_html(case_id: str) -> Response:
        report = _latest_customer_report_or_404(store, case_id)
        return Response(
            content=reporting.render_customer_report_html(report),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{reporting.customer_report_filename(report, "html")}"'},
        )

    @app.get("/chemical/cases/{case_id}/report.pdf")
    async def chemical_case_report_pdf(case_id: str) -> Response:
        report = _latest_customer_report_or_404(store, case_id)
        try:
            pdf = await reporting.render_customer_report_pdf_async(report)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{reporting.customer_report_filename(report, "pdf")}"'},
        )

    @app.post("/chemical/cases/{case_id}/documents", status_code=201)
    async def chemical_case_upload_documents(
        case_id: str,
        documents: list[UploadFile] = File(...),
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        uploaded_documents = [
            runner.uploaded_document_from_bytes(
                filename=upload.filename or "document.txt",
                content_type=upload.content_type,
                raw=await upload.read(),
            )
            for upload in documents
        ]
        package = runner._classify_uploaded_package(uploaded_documents)
        package_precheck = runner.build_package_precheck(
            package["original_documents"],
            review_scenario=case.get("review_scenario", "market_access"),
            check_types=case.get("check_types") or None,
        )
        saved = _persist_uploaded_documents(store, case_id, package["original_documents"])
        return {"case_id": case_id, "document_count": len(saved), "documents": saved, "package_precheck": package_precheck}

    @app.post("/chemical/cases/{case_id}/run-review", status_code=201)
    def chemical_case_run_review(
        case_id: str,
        review_task: str = Form("请基于上传资料执行化工物料准入风险预审。"),
        top_k: int = Form(5),
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        documents = _documents_for_runner(store, case_id)
        if not any(document.get("text_source") != "missing" for document in documents):
            raise HTTPException(status_code=400, detail="Case has no uploaded documents")
        trace = runner.run_uploaded_document_package(
            title=case["title"],
            case_id=case_id,
            review_task=review_task,
            review_scenario=case.get("review_scenario", "market_access"),
            check_types=case.get("check_types") or None,
            target_markets=case.get("target_markets", ["CN", "EU", "US"]),
            top_k=max(1, min(int(top_k), 20)),
            documents=documents,
        )
        _persist_case_review(store, case_id, trace)
        return trace

    @app.post("/chemical/upload-review", status_code=201)
    async def chemical_upload_review(
        title: str = Form(...),
        review_task: str = Form("请基于上传资料执行化工物料准入风险预审。"),
        review_scenario: str = Form("market_access"),
        check_types: str = Form(""),
        target_markets: str = Form("CN,EU,US"),
        top_k: int = Form(5),
        documents: list[UploadFile] | None = File(None),
        sds_file: UploadFile | None = File(None),
        formula_file: UploadFile | None = File(None),
        process_file: UploadFile | None = File(None),
        runner: ChemicalRagRunner = Depends(get_chemical_runner),
    ) -> dict:
        top_k = max(1, min(int(top_k), 20))
        selected_checks = _parse_check_types(check_types, review_scenario)
        case = store.create_case(
            CaseCreate(
                title=title,
                target_markets=_parse_target_markets(target_markets),
                intended_use=REVIEW_SCENARIO_LABELS_FOR_FACTORY.get(review_scenario, review_scenario),
                review_scenario=review_scenario,
                check_types=selected_checks,
            )
        )
        if documents:
            uploaded_documents = [
                runner.uploaded_document_from_bytes(
                    filename=upload.filename or "document.txt",
                    content_type=upload.content_type,
                    raw=await upload.read(),
                )
                for upload in documents
            ]
            trace = runner.run_uploaded_document_package(
                title=title,
                case_id=case["id"],
                review_task=review_task,
                review_scenario=review_scenario,
                check_types=selected_checks,
                target_markets=_parse_target_markets(target_markets),
                top_k=top_k,
                documents=uploaded_documents,
            )
            _persist_uploaded_documents(store, case["id"], trace.get("_classified_documents", uploaded_documents))
            trace.pop("_classified_documents", None)
            _persist_case_review(store, case["id"], trace)
            return trace
        if not sds_file or not formula_file or not process_file:
            raise HTTPException(status_code=400, detail="请上传 documents 文件列表，或同时上传 sds_file、formula_file、process_file。")
        sds_document = runner.uploaded_document_from_bytes(
            filename=sds_file.filename or "sds.txt",
            content_type=sds_file.content_type,
            raw=await sds_file.read(),
        )
        formula_document = runner.uploaded_document_from_bytes(
            filename=formula_file.filename or "formula.txt",
            content_type=formula_file.content_type,
            raw=await formula_file.read(),
        )
        process_document = runner.uploaded_document_from_bytes(
            filename=process_file.filename or "process.txt",
            content_type=process_file.content_type,
            raw=await process_file.read(),
        )
        trace = runner.run_uploaded_documents(
            title=title,
            case_id=case["id"],
            review_task=review_task,
            review_scenario=review_scenario,
            check_types=selected_checks,
            target_markets=_parse_target_markets(target_markets),
            top_k=top_k,
            sds=sds_document,
            formula=formula_document,
            process=process_document,
        )
        _persist_uploaded_documents(
            store,
            case["id"],
            [
                {**sds_document, "document_type": "sds"},
                {**formula_document, "document_type": "formula"},
                {**process_document, "document_type": "process"},
            ],
        )
        _persist_case_review(store, case["id"], trace)
        return trace

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


def _recommended_checks_for_scenario(review_scenario: str | None) -> list[str]:
    scenario = review_scenario if review_scenario in SCENARIO_RECOMMENDED_CHECK_TYPES else "market_access"
    return list(SCENARIO_RECOMMENDED_CHECK_TYPES[scenario])


def _parse_check_types(value: str, review_scenario: str | None = None) -> list[str]:
    items = [item.strip() for item in value.replace(";", ",").replace("，", ",").split(",") if item.strip()]
    return _normalize_check_type_list(items, review_scenario)


def _normalize_check_type_list(value: list[str], review_scenario: str | None = None) -> list[str]:
    normalized = []
    for item in value:
        for mapped in LEGACY_CHECK_TYPE_MAP.get(item, [item]):
            if mapped in CHECK_TYPE_LABELS and mapped not in normalized:
                normalized.append(mapped)
    return normalized or _recommended_checks_for_scenario(review_scenario)


def _persist_uploaded_documents(store: SQLiteStore, case_id: str, documents: list[dict]) -> list[dict]:
    saved = []
    for document in documents:
        if document.get("text_source") == "missing":
            continue
        parsed = document.get("parsed_document")
        saved.append(
            store.insert_document(
                case_id=case_id,
                document_type=document.get("document_type", "document"),
                filename=document.get("filename", "document.txt"),
                source_name=None,
                content_type=document.get("content_type"),
                sha256=document.get("sha256", ""),
                storage_path=document.get("path") or document.get("filename", "document.txt"),
                text_content=document.get("content", ""),
                metadata=getattr(parsed, "metadata", {}) if parsed is not None else {},
                parse_status=getattr(parsed, "parse_status", "needs_manual_review") if parsed is not None else "needs_manual_review",
                extracted_fields=getattr(parsed, "extracted_fields", {}) if parsed is not None else {},
                missing_fields=getattr(parsed, "missing_fields", []) if parsed is not None else [],
                needs_manual_review=getattr(parsed, "needs_manual_review", True) if parsed is not None else True,
                text_source=document.get("text_source", "text"),
            )
        )
    return saved


def _documents_for_runner(store: SQLiteStore, case_id: str) -> list[dict]:
    documents = []
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM documents WHERE case_id = ? ORDER BY created_at",
            (case_id,),
        ).fetchall()
    for row in rows:
        data = dict(row)
        documents.append(
            {
                "filename": data["filename"],
                "path": data["storage_path"],
                "content": data["text_content"],
                "content_type": data["content_type"],
                "text_source": data.get("text_source", "text"),
                "parse_status": data.get("parse_status", "needs_manual_review"),
                "sha256": data["sha256"],
                "document_type": data["document_type"],
            }
        )
    return documents


def _latest_customer_report_or_404(store: SQLiteStore, case_id: str) -> dict:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    latest = store.latest_report(case_id)
    report = reporting.latest_customer_report(latest["payload"] if latest else None)
    if not report:
        raise HTTPException(status_code=404, detail="Case has no customer report")
    return report


def _persist_case_review(store: SQLiteStore, case_id: str, trace: dict) -> None:
    report = store.create_report(case_id, trace)
    verdict = trace.get("customer_report", {}).get("verdict")
    store.update_case_review_state(
        case_id=case_id,
        status=_case_status_from_customer_verdict(verdict),
        latest_verdict=verdict,
        latest_report_id=report["id"],
    )


def _case_status_from_customer_verdict(verdict: str | None) -> str:
    return {
        "pass": "ready_for_next_step",
        "needs_supplement": "needs_supplement",
        "needs_review": "needs_review",
        "not_approved": "not_approved",
    }.get(verdict or "", "draft")
