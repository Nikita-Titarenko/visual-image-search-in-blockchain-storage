from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

PINATA_MOCK_PORT = int(os.getenv("PINATA_MOCK_PORT", "3101"))
PINATA_MOCK_STATE_DIR = Path(os.getenv("PINATA_MOCK_STATE_DIR", str(Path(__file__).resolve().parent / "state"))).expanduser()
OBJECTS_DIR = PINATA_MOCK_STATE_DIR / "objects"
META_DIR = PINATA_MOCK_STATE_DIR / "metadata"
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("PINATA_PROXY_ALLOWED_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]


class PinJsonRequest(BaseModel):
    pinataMetadata: dict[str, Any] | None = None
    pinataContent: dict[str, Any]


app = FastAPI(title="Pinata Mock", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_state_dirs() -> None:
    OBJECTS_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def startup() -> None:
    ensure_state_dirs()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _object_path(ipfs_hash: str) -> Path:
    return OBJECTS_DIR / ipfs_hash


def _meta_path(ipfs_hash: str) -> Path:
    return META_DIR / f"{ipfs_hash}.json"


def _write_object(ipfs_hash: str, content: bytes, content_type: str, name: str) -> dict[str, Any]:
    ensure_state_dirs()
    object_path = _object_path(ipfs_hash)
    meta_path = _meta_path(ipfs_hash)
    object_path.write_bytes(content)
    metadata = {
        "IpfsHash": ipfs_hash,
        "PinSize": len(content),
        "Timestamp": _timestamp(),
        "ContentType": content_type,
        "Name": name,
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _hash_bytes(name: str, content: bytes, content_type: str) -> str:
    digest = hashlib.sha256()
    digest.update(name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(content_type.encode("utf-8"))
    digest.update(b"\0")
    digest.update(content)
    return f"mock-{digest.hexdigest()}"


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/pinning/pinFileToIPFS")
async def pin_file_to_ipfs(file: UploadFile = File(...), pinataMetadata: str | None = None) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A file is required.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="A file is required.")

    metadata_name = file.filename
    if pinataMetadata:
        try:
            parsed = json.loads(pinataMetadata)
            metadata_name = str(parsed.get("name") or metadata_name)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="pinataMetadata must be valid JSON.")

    content_type = file.content_type or "application/octet-stream"
    ipfs_hash = _hash_bytes(metadata_name, file_bytes, content_type)
    return _write_object(ipfs_hash, file_bytes, content_type, metadata_name)


@app.post("/pinning/pinJSONToIPFS")
def pin_json_to_ipfs(request: PinJsonRequest) -> dict[str, Any]:
    metadata_name = str((request.pinataMetadata or {}).get("name") or "metadata.json")
    content = json.dumps(request.pinataContent, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ipfs_hash = _hash_bytes(metadata_name, content, "application/json")
    return _write_object(ipfs_hash, content, "application/json", metadata_name)


@app.delete("/pinning/unpin/{ipfs_hash}")
def unpin(ipfs_hash: str) -> dict[str, Any]:
    removed = False
    for candidate in (_object_path(ipfs_hash), _meta_path(ipfs_hash)):
        if candidate.exists():
            candidate.unlink()
            removed = True
    if not removed:
        raise HTTPException(status_code=404, detail="Object not found.")
    return {"ok": True, "ipfsHash": ipfs_hash}


@app.get("/ipfs/{ipfs_hash}")
def get_gateway_object(ipfs_hash: str) -> Response:
    object_path = _object_path(ipfs_hash)
    meta_path = _meta_path(ipfs_hash)
    if not object_path.exists() or not meta_path.exists():
        raise HTTPException(status_code=404, detail="Object not found.")

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    content = object_path.read_bytes()
    content_type = metadata.get("ContentType", "application/octet-stream")
    if content_type == "application/json":
        return JSONResponse(content=json.loads(content.decode("utf-8")))
    return Response(content=content, media_type=content_type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PINATA_MOCK_PORT, reload=False)
