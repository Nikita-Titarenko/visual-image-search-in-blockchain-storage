from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from audit import load_audit_metadata
from config import VECTOR_ALLOWED_ORIGINS, VECTOR_TOP_K_DEFAULT
from logger import get_logger
from models import AuditStatusResponse, SearchResponse


if TYPE_CHECKING:
    from service import ImageVectorService


logger = get_logger()
service: ImageVectorService | None = None


def create_app(
    service_instance: ImageVectorService | None = None,
    *,
    enable_lifespan: bool = True,
) -> FastAPI:
    current_service = service_instance

    def get_service() -> ImageVectorService:
        nonlocal current_service
        global service
        if current_service is not None:
            return current_service
        if service is None:
            from service import ImageVectorService

            service = ImageVectorService()
        current_service = service
        return current_service

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("FastAPI lifespan startup started")
        sync_task: asyncio.Task[None] | None = None
        try:
            runtime_service = get_service()
            await runtime_service.initialize()
            sync_task = asyncio.create_task(runtime_service.listen_for_registered_images())
            logger.info("FastAPI lifespan startup completed")
            yield
        except Exception:
            logger.exception("FastAPI lifespan startup failed")
            raise
        finally:
            if sync_task is not None:
                sync_task.cancel()
                try:
                    await sync_task
                except asyncio.CancelledError:
                    logger.info("Background ImageRegistered sync task stopped")
            logger.info("FastAPI lifespan shutdown reached")

    app = FastAPI(
        title="Image Vector Search Service",
        version="1.0.0",
        lifespan=lifespan if enable_lifespan else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=VECTOR_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/vector/health")
    def health() -> dict[str, int | bool | str]:
        logger.info("Health check requested")
        runtime_service = get_service()
        status = runtime_service.audit_status()
        return {
            "ok": True,
            "datasetSize": len(runtime_service.records),
            "modelVersion": status.modelVersion,
            "indexVersion": status.indexVersion,
        }

    @app.post("/api/vector/search", response_model=SearchResponse)
    async def search_similar_images(
        file: UploadFile = File(...),
        top_k: int = Query(default=VECTOR_TOP_K_DEFAULT, ge=1),
    ) -> SearchResponse:
        logger.info("Search request received: file=%s top_k=%s", file.filename, top_k)
        return await get_service().search(file, top_k)

    @app.get("/api/vector/audit-status", response_model=AuditStatusResponse)
    def audit_status(snapshot_id: int | None = Query(default=None, ge=1)) -> AuditStatusResponse:
        logger.info("Audit status requested: snapshot_id=%s", snapshot_id)
        return get_service().audit_status(snapshot_id)

    @app.get("/api/vector/audit-metadata")
    def audit_metadata() -> dict[str, object]:
        logger.info("Audit metadata requested")
        return load_audit_metadata()

    @app.post("/api/vector/rebuild-index", response_model=AuditStatusResponse)
    async def rebuild_index() -> AuditStatusResponse:
        logger.info("Rebuild index endpoint triggered")
        runtime_service = get_service()
        await runtime_service.rebuild_index()
        await runtime_service.initialize()
        logger.info("Rebuild index endpoint completed")
        return runtime_service.audit_status()

    return app


app = create_app()