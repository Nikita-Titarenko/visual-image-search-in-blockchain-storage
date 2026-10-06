from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from fastapi import HTTPException
from web3 import Web3

from config import ARTIFACTS_DIR, AUDIT_METADATA_PATH, MANIFEST_PATH, INDEX_PATH, VECTOR_INDEX_VERSION, VECTOR_PUBLIC_BASE_URL, require_env
from logger import get_logger
from utils import read_json, write_json


logger = get_logger()


def _load_audit_artifact() -> dict[str, Any]:
    artifact_path = ARTIFACTS_DIR / "ModelAndIndexAudit.sol" / "ModelAndIndexAudit.json"
    logger.info("Loading audit artifact from %s", artifact_path)
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def compute_index_hash() -> str:
    logger.info("Computing index hash from %s and %s", MANIFEST_PATH, INDEX_PATH)
    digest = hashlib.sha256(VECTOR_INDEX_VERSION.encode("utf-8"))
    digest.update(MANIFEST_PATH.read_bytes())
    digest.update(INDEX_PATH.read_bytes())
    return f"0x{digest.hexdigest()}"


def save_audit_metadata(payload: dict[str, Any]) -> None:
    write_json(AUDIT_METADATA_PATH, payload)
    logger.info("Saved audit metadata to %s", AUDIT_METADATA_PATH)


def load_audit_metadata() -> dict[str, Any]:
    metadata = read_json(AUDIT_METADATA_PATH, {})
    logger.info("Loaded audit metadata from %s", AUDIT_METADATA_PATH)
    return metadata


def _get_audit_signer_private_key() -> str:
    value = os.getenv("AUDIT_PRIVATE_KEY", "").strip() or require_env("DEPLOYER_PRIVATE_KEY")
    return value if value.startswith("0x") else f"0x{value}"


def _load_audit_contract() -> tuple[Web3, Any, Any]:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    audit_address = Web3.to_checksum_address(require_env("MODEL_AND_INDEX_AUDIT_ADDRESS"))
    signer_private_key = _get_audit_signer_private_key()
    artifact = _load_audit_artifact()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    signer = w3.eth.account.from_key(signer_private_key)
    contract = w3.eth.contract(address=audit_address, abi=artifact["abi"])
    return w3, signer, contract


def verify_snapshot(snapshot_id: int, model_hash: str, index_hash: str) -> bool:
    logger.info("Verifying snapshot %s against on-chain audit contract", snapshot_id)
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    audit_address = Web3.to_checksum_address(require_env("MODEL_AND_INDEX_AUDIT_ADDRESS"))
    artifact = _load_audit_artifact()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    contract = w3.eth.contract(address=audit_address, abi=artifact["abi"])
    result = bool(contract.functions.verifySnapshot(snapshot_id, model_hash, index_hash).call())
    logger.info("Snapshot verification completed: snapshot_id=%s result=%s", snapshot_id, result)
    return result


async def ensure_audit_snapshot(
    model_version: str,
    model_hash: str,
    index_version: str,
    index_hash: str,
    dataset_size: int,
) -> dict[str, Any]:
    logger.info("Ensuring on-chain audit snapshot for model=%s index=%s", model_version, index_version)
    metadata = load_audit_metadata()
    snapshot_id = metadata.get("snapshotId")
    if snapshot_id:
        try:
            if verify_snapshot(int(snapshot_id), model_hash, index_hash):
                logger.info("Existing on-chain audit snapshot %s already matches current hashes", snapshot_id)
                metadata["onChainMatch"] = True
                save_audit_metadata(metadata)
                return metadata
        except Exception:
            logger.exception("Existing snapshot verification failed, a new snapshot will be recorded")

    metadata_payload = {
        "summary": "Automatic image-vector-service audit snapshot",
        "notes": "Recorded automatically when the dataset size reaches the configured audit threshold.",
        "modelVersion": model_version,
        "modelHash": model_hash,
        "indexVersion": index_version,
        "indexHash": index_hash,
        "datasetSize": dataset_size,
    }
    metadata_uri = f"{VECTOR_PUBLIC_BASE_URL}/api/vector/audit-metadata"

    w3, signer, contract = _load_audit_contract()
    nonce = w3.eth.get_transaction_count(signer.address, "pending")
    gas_price = w3.eth.gas_price
    transaction = contract.functions.recordSnapshot(
        model_version,
        model_hash,
        index_version,
        index_hash,
        metadata_uri,
    ).build_transaction(
        {
            "from": signer.address,
            "nonce": nonce,
            "gas": 300000,
            "gasPrice": gas_price,
        }
    )

    signed = w3.eth.account.sign_transaction(transaction, signer.key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        logger.error("Audit snapshot transaction failed: tx=%s", receipt.transactionHash.hex())
        raise HTTPException(status_code=502, detail="Audit snapshot transaction failed.")

    event = contract.events.AuditSnapshotRecorded().process_receipt(receipt)[0]
    recorded_snapshot_id = int(event["args"]["snapshotId"])
    updated_metadata = {
        **metadata_payload,
        "metadataUri": metadata_uri,
        "metadataGatewayUrl": metadata_uri,
        "snapshotId": recorded_snapshot_id,
        "transactionHash": receipt.transactionHash.hex(),
        "submittedBy": signer.address,
        "onChainMatch": True,
    }
    save_audit_metadata(updated_metadata)
    logger.info(
        "Recorded new on-chain audit snapshot: snapshot_id=%s tx=%s",
        recorded_snapshot_id,
        receipt.transactionHash.hex(),
    )
    return updated_metadata