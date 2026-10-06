from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from config import PINATA_GATEWAY_BASE_URL
from logger import get_logger


logger = get_logger()


def to_gateway_url(uri_or_url: str) -> str:
    if uri_or_url.startswith("ipfs://"):
        return f"{PINATA_GATEWAY_BASE_URL.rstrip('/')}/{uri_or_url.removeprefix('ipfs://')}"
    return uri_or_url


async def pin_file_to_ipfs(file_name: str, content: bytes, content_type: str, pinata_jwt: str) -> dict[str, Any]:
    logger.info("Pinata upload started: file=%s bytes=%s content_type=%s", file_name, len(content), content_type)
    files = {
        "file": (file_name, content, content_type),
        "pinataMetadata": (None, json.dumps({"name": file_name}), "application/json"),
    }
    headers = {"Authorization": f"Bearer {pinata_jwt}"}

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post("https://api.pinata.cloud/pinning/pinFileToIPFS", files=files, headers=headers)

    if response.status_code >= 400:
        logger.error("Pinata upload failed: file=%s status=%s body=%s", file_name, response.status_code, response.text)
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    ipfs_hash = payload["IpfsHash"]
    logger.info("Pinata upload completed: file=%s ipfsHash=%s", file_name, ipfs_hash)
    return {
        "ipfsHash": ipfs_hash,
        "ipfsUri": f"ipfs://{ipfs_hash}",
        "gatewayUrl": f"{PINATA_GATEWAY_BASE_URL.rstrip('/')}/{ipfs_hash}",
        "pinSize": payload.get("PinSize", 0),
        "timestamp": payload.get("Timestamp", ""),
    }


async def pin_json_to_ipfs(name: str, content: dict[str, Any], pinata_jwt: str) -> dict[str, Any]:
    logger.info("Pinata JSON upload started: name=%s", name)
    headers = {
        "Authorization": f"Bearer {pinata_jwt}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.pinata.cloud/pinning/pinJSONToIPFS",
            json={
                "pinataMetadata": {"name": name},
                "pinataContent": content,
            },
            headers=headers,
        )

    if response.status_code >= 400:
        logger.error("Pinata JSON upload failed: name=%s status=%s body=%s", name, response.status_code, response.text)
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    ipfs_hash = payload["IpfsHash"]
    logger.info("Pinata JSON upload completed: name=%s ipfsHash=%s", name, ipfs_hash)
    return {
        "ipfsHash": ipfs_hash,
        "ipfsUri": f"ipfs://{ipfs_hash}",
        "gatewayUrl": f"{PINATA_GATEWAY_BASE_URL.rstrip('/')}/{ipfs_hash}",
        "pinSize": payload.get("PinSize", 0),
        "timestamp": payload.get("Timestamp", ""),
    }


async def fetch_json(uri_or_url: str) -> dict[str, Any]:
    gateway_url = to_gateway_url(uri_or_url)
    logger.info("Gateway JSON fetch started: url=%s", gateway_url)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(gateway_url)

    if response.status_code >= 400:
        logger.error("Gateway JSON fetch failed: url=%s status=%s", gateway_url, response.status_code)
        raise HTTPException(status_code=502, detail=f"Unable to fetch JSON from {gateway_url}")

    logger.info("Gateway JSON fetch completed: url=%s", gateway_url)
    return response.json()


async def fetch_bytes(uri_or_url: str) -> bytes:
    gateway_url = to_gateway_url(uri_or_url)
    logger.info("Gateway fetch started: url=%s", gateway_url)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(gateway_url)

    if response.status_code >= 400:
        logger.error("Gateway fetch failed: url=%s status=%s", gateway_url, response.status_code)
        raise HTTPException(status_code=502, detail=f"Unable to fetch image from {gateway_url}")

    logger.info("Gateway fetch completed: url=%s bytes=%s", gateway_url, len(response.content))
    return response.content