from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from config import PINATA_GATEWAY_BASE_URL


async def pin_file_to_ipfs(file_name: str, content: bytes, content_type: str, pinata_jwt: str) -> dict[str, Any]:
    files = {
        "file": (file_name, content, content_type),
        "pinataMetadata": (None, json.dumps({"name": file_name}), "application/json"),
    }
    headers = {"Authorization": f"Bearer {pinata_jwt}"}

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post("https://api.pinata.cloud/pinning/pinFileToIPFS", files=files, headers=headers)

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    ipfs_hash = payload["IpfsHash"]
    return {
        "ipfsHash": ipfs_hash,
        "ipfsUri": f"ipfs://{ipfs_hash}",
        "gatewayUrl": f"{PINATA_GATEWAY_BASE_URL.rstrip('/')}/{ipfs_hash}",
        "pinSize": payload.get("PinSize", 0),
        "timestamp": payload.get("Timestamp", ""),
    }


async def fetch_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(url)

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Unable to fetch image from {url}")

    return response.content