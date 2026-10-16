from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

PINATA_API_BASE_URL = os.getenv("PINATA_API_BASE_URL", "https://api.pinata.cloud").rstrip("/")
PINATA_UPLOAD_URL = f"{PINATA_API_BASE_URL}/pinning/pinFileToIPFS"
PINATA_PIN_JSON_URL = f"{PINATA_API_BASE_URL}/pinning/pinJSONToIPFS"
PINATA_UNPIN_URL = f"{PINATA_API_BASE_URL}/pinning/unpin"
PINATA_GATEWAY_BASE_URL = os.getenv("PINATA_GATEWAY_BASE_URL", "https://gateway.pinata.cloud/ipfs")
PINATA_UPLOAD_PORT = int(os.getenv("PINATA_UPLOAD_PORT", "3001"))
PINATA_JWT = os.getenv("PINATA_JWT", "").strip()
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("PINATA_PROXY_ALLOWED_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]


class PinJsonRequest(BaseModel):
    name: str
    content: dict[str, Any]


app = FastAPI(title="Pinata Proxy", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_pinata_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ipfs_hash = payload["IpfsHash"]
    return {
        "ipfsHash": ipfs_hash,
        "ipfsUri": f"ipfs://{ipfs_hash}",
        "gatewayUrl": f"{PINATA_GATEWAY_BASE_URL.rstrip('/')}/{ipfs_hash}",
        "pinSize": payload.get("PinSize", 0),
        "timestamp": payload.get("Timestamp", ""),
    }


def _pinata_headers(content_type: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if PINATA_JWT:
        headers["Authorization"] = f"Bearer {PINATA_JWT}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


@app.get("/api/pinata/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/pinata/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A file is required.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="A file is required.")

    files = {
        "file": (file.filename, file_bytes, file.content_type or "application/octet-stream"),
        "pinataMetadata": (None, '{"name": "%s"}' % file.filename, "application/json"),
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            PINATA_UPLOAD_URL,
            files=files,
            headers=_pinata_headers(),
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return _build_pinata_payload(response.json())


@app.post("/api/pinata/pin-json")
async def pin_json(request: PinJsonRequest) -> dict[str, Any]:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="A metadata name is required.")

    if not isinstance(request.content, dict) or not request.content:
        raise HTTPException(status_code=400, detail="A metadata JSON object is required.")

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            PINATA_PIN_JSON_URL,
            json={
                "pinataMetadata": {"name": request.name},
                "pinataContent": request.content,
            },
            headers=_pinata_headers("application/json"),
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return _build_pinata_payload(response.json())


@app.delete("/api/pinata/unpin/{ipfs_hash}")
async def unpin(ipfs_hash: str) -> dict[str, Any]:
    normalized_hash = ipfs_hash.strip()
    if not normalized_hash:
        raise HTTPException(status_code=400, detail="An IPFS hash is required.")

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.delete(
            f"{PINATA_UNPIN_URL}/{normalized_hash}",
            headers=_pinata_headers(),
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return {"ok": True, "ipfsHash": normalized_hash}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PINATA_UPLOAD_PORT, reload=False)