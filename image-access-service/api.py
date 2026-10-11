from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from blockchain import build_contracts
from config import ALLOWED_ORIGINS
from models import ClaimAccessRequest, OracleContracts


if TYPE_CHECKING:
    from service import OracleService


contracts: OracleContracts | None = None
service: OracleService | None = None


def create_app(
    service_instance: OracleService | None = None,
    *,
    contracts_override: OracleContracts | None = None,
) -> FastAPI:
    current_contracts = contracts_override
    current_service = service_instance

    def get_contracts() -> OracleContracts:
        nonlocal current_contracts
        global contracts
        if current_contracts is not None:
            return current_contracts
        if contracts is None:
            contracts = build_contracts()
        current_contracts = contracts
        return current_contracts

    def get_service() -> OracleService:
        nonlocal current_service
        global service
        if current_service is not None:
            return current_service
        if service is None:
            from service import OracleService

            service = OracleService(get_contracts())
        current_service = service
        return current_service

    app = FastAPI(title="Encrypted Asset Oracle", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/oracle/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/oracle/encrypt-upload")
    async def encrypt_upload(file: UploadFile = File(...), contentHash: str = Form(...)) -> dict[str, object]:
        return await get_service().encrypt_upload(file, contentHash)

    @app.post("/api/oracle/download")
    async def download_decrypted_file(request: ClaimAccessRequest) -> Response:
        decrypted_bytes, headers, media_type = await get_service().download_decrypted_file(request)
        return Response(content=decrypted_bytes, media_type=media_type, headers=headers)

    return app


app = create_app()