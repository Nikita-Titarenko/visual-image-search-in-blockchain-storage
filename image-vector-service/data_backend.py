from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from config import CONTRACTS_MOCK_BASE_URL, VECTOR_USE_CENTRALIZED_BACKEND
from models import DatasetImageRecord


class ImageDataBackend(Protocol):
    async def sync_registered_images(self) -> tuple[list[DatasetImageRecord], int]: ...

    async def listen_for_registered_images(
        self,
        on_record: Callable[[DatasetImageRecord], Awaitable[bool]],
        on_reset: Callable[[], Awaitable[None]] | None = None,
    ) -> None: ...

    async def ensure_audit_snapshot(
        self,
        model_version: str,
        model_hash: str,
        index_version: str,
        index_hash: str,
        dataset_size: int,
    ) -> dict[str, Any]: ...

    def verify_snapshot(self, snapshot_id: int, model_hash: str, index_hash: str) -> bool: ...


def build_data_backend(*, use_centralized_backend: bool | None = None) -> ImageDataBackend:
    resolved = VECTOR_USE_CENTRALIZED_BACKEND if use_centralized_backend is None else use_centralized_backend
    if resolved:
        if not CONTRACTS_MOCK_BASE_URL:
            raise RuntimeError("CONTRACTS_MOCK_BASE_URL is required when VECTOR_USE_CENTRALIZED_BACKEND=true.")
        from centralized_backend import build_backend as build_centralized_backend

        return build_centralized_backend()

    from blockchain_backend import build_backend as build_blockchain_backend

    return build_blockchain_backend()