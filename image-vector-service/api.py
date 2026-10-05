from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from config import VECTOR_ALLOWED_ORIGINS, VECTOR_TOP_K_DEFAULT
from models import AuditStatusResponse, SearchResponse
from service import ImageVectorService


service = ImageVectorService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await service.initialize()
    yield


app = FastAPI(title="Image Vector Search Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=VECTOR_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/vector/health")
def health() -> dict[str, int | bool | str]:
    return {
        "ok": True,
        "datasetSize": len(service.records),
        "modelVersion": service.audit_status().modelVersion,
        "indexVersion": service.audit_status().indexVersion,
    }


@app.post("/api/vector/search", response_model=SearchResponse)
async def search_similar_images(
    file: UploadFile = File(...),
    method: str = Query(default="cnn"),
    top_k: int = Query(default=VECTOR_TOP_K_DEFAULT, ge=1),
) -> SearchResponse:
    return await service.search(file, method, top_k)


@app.get("/api/vector/audit-status", response_model=AuditStatusResponse)
def audit_status(snapshot_id: int | None = Query(default=None, ge=1)) -> AuditStatusResponse:
    return service.audit_status(snapshot_id)


@app.post("/api/vector/rebuild-index", response_model=AuditStatusResponse)
async def rebuild_index() -> AuditStatusResponse:
    await service.rebuild_index()
    await service.initialize()
    return service.audit_status()