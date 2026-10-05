from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from .config import STORE_PATH


def ensure_store() -> dict[str, Any]:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))

    initial = {"assets": {}, "accessTokens": {}}
    STORE_PATH.write_text(json.dumps(initial, indent=2), encoding="utf-8")
    return initial


def save_store(store: dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def get_asset_record(store: dict[str, Any], content_hash: str) -> dict[str, Any]:
    asset = store["assets"].get(content_hash.lower())
    if not asset:
        raise HTTPException(status_code=404, detail="Encrypted asset record not found for this image.")
    return asset