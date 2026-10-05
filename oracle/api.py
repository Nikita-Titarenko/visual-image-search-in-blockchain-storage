from __future__ import annotations

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .blockchain import build_contracts
from .config import ALLOWED_ORIGINS
from .models import ClaimAccessRequest
from .service import OracleService


contracts = build_contracts()
service = OracleService(contracts)

app = FastAPI(title="Encrypted Asset Oracle", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/oracle/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "oracleAddress": contracts.oracle_address}


@app.post("/api/oracle/encrypt-upload")
async def encrypt_upload(file: UploadFile = File(...), contentHash: str = Form(...)) -> dict[str, object]:
    return await service.encrypt_upload(file, contentHash)


@app.post("/api/oracle/claim-access")
async def claim_access(request: ClaimAccessRequest) -> dict[str, object]:
    return await service.claim_access(request)


@app.get("/api/oracle/download/{purchase_id}")
async def download_decrypted_file(purchase_id: int, token: str = Query(min_length=20)) -> Response:
    decrypted_bytes, headers, media_type = await service.download_decrypted_file(purchase_id, token)
    return Response(content=decrypted_bytes, media_type=media_type, headers=headers)