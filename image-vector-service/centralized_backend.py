from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from bootstrap import _build_record_from_metadata, save_manifest
from config import CONTRACTS_MOCK_BASE_URL, VECTOR_AUDIT_SUBMITTER
from logger import get_logger
from models import DatasetImageRecord


class CentralizedImageDataBackend:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_url = self._build_ws_url(self.base_url)
        self.logger = get_logger()
        self._last_seen_image_id = 0

    async def sync_registered_images(self) -> tuple[list[DatasetImageRecord], int]:
        self.logger.info("Centralized historical sync started against %s", self.base_url)
        assets = await self._list_images()
        self.logger.info("Centralized historical sync fetched %s assets", len(assets))
        records: list[DatasetImageRecord] = []
        for asset in assets:
            record = await self._record_from_asset(asset)
            if record is not None:
                records.append(record)
        records.sort(key=lambda record: record.image_id)
        save_manifest(records)
        self._last_seen_image_id = max((record.image_id for record in records), default=0)
        self.logger.info(
            "Centralized historical sync completed: records=%s last_seen_image_id=%s",
            len(records),
            self._last_seen_image_id,
        )
        return records, len(records)

    async def listen_for_registered_images(self, on_record, on_reset=None) -> None:
        self.logger.info("Starting centralized image event backend against %s", self.base_url)
        while True:
            try:
                self.logger.info(
                    "Opening centralized event socket: url=%s last_seen_image_id=%s",
                    self.ws_url,
                    self._last_seen_image_id,
                )
                async with websockets.connect(self.ws_url, ping_interval=10, ping_timeout=30) as websocket:
                    self.logger.info(
                        "Centralized event socket connected: last_seen_image_id=%s",
                        self._last_seen_image_id,
                    )
                    async for raw_message in websocket:
                        await self._handle_socket_message(raw_message, on_record, on_reset)
            except asyncio.CancelledError:
                self.logger.info("Centralized image event backend cancelled")
                raise
            except ConnectionClosed:
                self.logger.warning(
                    "Centralized image event socket closed; reconnecting with last_seen_image_id=%s",
                    self._last_seen_image_id,
                )
                await asyncio.sleep(1)
            except Exception:
                self.logger.exception(
                    "Centralized image event backend failed; reconnecting with last_seen_image_id=%s",
                    self._last_seen_image_id,
                )
                await asyncio.sleep(1)

    async def ensure_audit_snapshot(
        self,
        model_version: str,
        model_hash: str,
        index_version: str,
        index_hash: str,
        dataset_size: int,
    ) -> dict[str, Any]:
        payload = {
            "modelVersion": model_version,
            "modelHash": model_hash,
            "indexVersion": index_version,
            "indexHash": index_hash,
            "metadataURI": self.base_url,
            "submittedBy": VECTOR_AUDIT_SUBMITTER,
            "datasetSize": dataset_size,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.base_url}/api/mock/audit/snapshots", json=payload)
            response.raise_for_status()
            return dict(response.json())

    def verify_snapshot(self, snapshot_id: int, model_hash: str, index_hash: str) -> bool:
        response = httpx.get(
            f"{self.base_url}/api/mock/audit/verify/{snapshot_id}",
            params={"modelHash": model_hash, "indexHash": index_hash},
            timeout=30,
        )
        response.raise_for_status()
        payload = dict(response.json())
        return bool(payload.get("match"))

    async def _list_images(self, after_id: int | None = None) -> list[dict[str, Any]]:
        params = {"afterId": after_id} if after_id else None
        self.logger.info("Listing centralized images: after_id=%s", after_id)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/api/mock/image-registry/images", params=params)
            response.raise_for_status()
            payload = response.json()
            self.logger.info("Centralized image list returned %s assets for after_id=%s", len(payload), after_id)
            return [dict(item) for item in payload]

    async def _handle_socket_message(self, raw_message: str, on_record, on_reset) -> None:
        payload = json.loads(raw_message)
        event_name = str(payload.get("event") or "message")
        if event_name == "keepalive":
            return
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            self.logger.warning("Ignoring malformed centralized websocket payload: %s", payload)
            return
        self.logger.info(
            "Received centralized event: event=%s payload_keys=%s last_seen_image_id=%s",
            event_name,
            sorted(event_payload.keys()),
            self._last_seen_image_id,
        )
        if event_name == "state_reset":
            self.logger.info("Received centralized state reset event")
            self._last_seen_image_id = 0
            if on_reset is not None:
                await on_reset()
            return
        if event_name != "image_registered":
            self.logger.debug("Ignoring unsupported centralized event %s", event_name)
            return
        record = await self._record_from_asset(dict(event_payload))
        if record is None:
            self.logger.warning("Centralized image_registered event produced no record: payload=%s", event_payload)
            return
        self.logger.info(
            "Processing centralized image_registered event: image_id=%s previous_last_seen_image_id=%s",
            record.image_id,
            self._last_seen_image_id,
        )
        await on_record(record)
        self._last_seen_image_id = max(self._last_seen_image_id, record.image_id)
        self.logger.info("Processed centralized image_registered event: image_id=%s new_last_seen_image_id=%s", record.image_id, self._last_seen_image_id)

    @staticmethod
    def _build_ws_url(base_url: str) -> str:
        parts = urlsplit(base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, "/api/mock/ws/events", "", ""))

    async def _record_from_asset(self, asset: dict[str, Any]) -> DatasetImageRecord | None:
        self.logger.info(
            "Building record from centralized asset: image_id=%s collection_id=%s metadata_uri=%s",
            asset.get("id"),
            asset.get("collectionId"),
            asset.get("metadataURI"),
        )
        return await _build_record_from_metadata(
            image_id=int(asset["id"]),
            metadata_uri=str(asset["metadataURI"]),
            collection_id=str(asset["collectionId"]),
            content_hash=str(asset["contentHash"]),
            creator_wallet=str(asset["currentOwner"]),
        )


def build_backend() -> CentralizedImageDataBackend:
    return CentralizedImageDataBackend(CONTRACTS_MOCK_BASE_URL)