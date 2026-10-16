from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from web3 import AsyncWeb3, Web3, WebSocketProvider

from audit import ensure_audit_snapshot, verify_snapshot
from bootstrap import (
    build_record_from_image_registered_log,
    ensure_pinata_dataset,
    get_image_registered_topic,
    get_image_registry_address,
    resolve_websocket_rpc_url,
    write_last_processed_block,
)
from logger import get_logger
from models import DatasetImageRecord


class BlockchainImageDataBackend:
    def __init__(self) -> None:
        self.logger = get_logger()

    async def sync_registered_images(self) -> tuple[list[DatasetImageRecord], int]:
        return await ensure_pinata_dataset()

    async def listen_for_registered_images(self, on_record, on_reset=None) -> None:
        registry_address = get_image_registry_address()
        topic = get_image_registered_topic()
        websocket_url = resolve_websocket_rpc_url()
        self.logger.info("Starting ImageRegistered websocket listener for %s via %s", registry_address, websocket_url)

        while True:
            provider = WebSocketProvider(websocket_url)
            websocket_client = AsyncWeb3(provider)
            try:
                await provider.connect()
                subscription_id = await websocket_client.eth.subscribe(
                    "logs",
                    {
                        "address": Web3.to_checksum_address(registry_address),
                        "topics": [topic],
                    },
                )
                self.logger.info("Subscribed to ImageRegistered logs with subscription id %s", subscription_id)
                async for message in websocket_client.socket.process_subscriptions():
                    result = message.get("result")
                    if not isinstance(result, Mapping):
                        self.logger.warning("Skipping subscription payload with unexpected result type %s", type(result).__name__)
                        continue
                    event_log = dict(result)
                    record = await build_record_from_image_registered_log(event_log)
                    if record is None:
                        continue
                    updated = await on_record(record)
                    if updated:
                        block_number = self._coerce_block_number(event_log["blockNumber"])
                        write_last_processed_block(block_number + 1)
            except asyncio.CancelledError:
                self.logger.info("ImageRegistered websocket listener cancelled")
                raise
            except Exception:
                self.logger.exception("ImageRegistered websocket listener failed; reconnecting")
                await asyncio.sleep(1)
            finally:
                await provider.disconnect()

    async def ensure_audit_snapshot(
        self,
        model_version: str,
        model_hash: str,
        index_version: str,
        index_hash: str,
        dataset_size: int,
    ) -> dict[str, Any]:
        return await ensure_audit_snapshot(model_version, model_hash, index_version, index_hash, dataset_size)

    def verify_snapshot(self, snapshot_id: int, model_hash: str, index_hash: str) -> bool:
        return verify_snapshot(snapshot_id, model_hash, index_hash)

    @staticmethod
    def _coerce_block_number(value: object) -> int:
        if isinstance(value, str):
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        return int(value)


def build_backend() -> BlockchainImageDataBackend:
    return BlockchainImageDataBackend()