from __future__ import annotations

import hashlib
import json
from typing import Any

from web3 import Web3

from config import ARTIFACTS_DIR, AUDIT_METADATA_PATH, MANIFEST_PATH, INDEX_PATH, VECTOR_INDEX_VERSION, require_env
from utils import read_json, write_json


def _load_audit_artifact() -> dict[str, Any]:
    artifact_path = ARTIFACTS_DIR / "ModelAndIndexAudit.sol" / "ModelAndIndexAudit.json"
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def compute_index_hash() -> str:
    digest = hashlib.sha256(VECTOR_INDEX_VERSION.encode("utf-8"))
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(INDEX_PATH.read_bytes())
    return f"0x{digest.hexdigest()}"


def save_audit_metadata(payload: dict[str, Any]) -> None:
    write_json(AUDIT_METADATA_PATH, payload)


def load_audit_metadata() -> dict[str, Any]:
    return read_json(AUDIT_METADATA_PATH, {})


def verify_snapshot(snapshot_id: int, model_hash: str, index_hash: str) -> bool:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    audit_address = Web3.to_checksum_address(require_env("MODEL_AND_INDEX_AUDIT_ADDRESS"))
    artifact = _load_audit_artifact()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    contract = w3.eth.contract(address=audit_address, abi=artifact["abi"])
    return bool(contract.functions.verifySnapshot(snapshot_id, model_hash, index_hash).call())