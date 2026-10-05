from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from .config import DEFAULT_GATEWAY
from .utils import ipfs_to_gateway


async def pin_file_to_ipfs(file_name: str, content: bytes, content_type: str, pinata_jwt: str) -> dict[str, Any]:
    files = {
        "file": (file_name, content, content_type),
        "pinataMetadata": (None, json.dumps({"name": file_name}), "application/json"),
    }
    headers = {"Authorization": f"Bearer {pinata_jwt}"}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.pinata.cloud/pinning/pinFileToIPFS", files=files, headers=headers)

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    return {
        "ipfsHash": payload["IpfsHash"],
        "ipfsUri": f"ipfs://{payload['IpfsHash']}",
        "gatewayUrl": f"{DEFAULT_GATEWAY.rstrip('/')}/{payload['IpfsHash']}",
        "pinSize": payload.get("PinSize", 0),
        "timestamp": payload.get("Timestamp", ""),
    }


async def fetch_json(uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(ipfs_to_gateway(uri))

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"Unable to fetch metadata from {uri}")

    return response.json()


async def fetch_bytes(uri: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(ipfs_to_gateway(uri))

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Unable to download encrypted asset from IPFS.")

    return response.content