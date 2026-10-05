from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from web3 import Web3

from .config import ARTIFACTS_DIR, require_env
from .models import OracleContracts


def load_artifact(contract_name: str) -> dict[str, Any]:
    artifact_path = ARTIFACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_path.exists():
        raise RuntimeError(f"Artifact not found: {artifact_path}")
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def build_contracts() -> OracleContracts:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    oracle_private_key = require_env("ORACLE_PRIVATE_KEY")
    licensing_address = Web3.to_checksum_address(require_env("LICENSING_AND_PAYMENT_ADDRESS"))
    registry_address = Web3.to_checksum_address(require_env("IMAGE_REGISTRY_ADDRESS"))
    pinata_jwt = require_env("PINATA_JWT")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    oracle_account = w3.eth.account.from_key(oracle_private_key)

    licensing_artifact = load_artifact("LicensingAndPayment")
    registry_artifact = load_artifact("ImageRegistry")

    licensing = w3.eth.contract(address=licensing_address, abi=licensing_artifact["abi"])
    registry = w3.eth.contract(address=registry_address, abi=registry_artifact["abi"])

    return OracleContracts(
        w3=w3,
        licensing=licensing,
        registry=registry,
        oracle_account=oracle_account,
        oracle_address=oracle_account.address,
        pinata_jwt=pinata_jwt,
    )


def send_confirm_transaction(contracts: OracleContracts, purchase_id: int, access_hash: bytes) -> str:
    nonce = contracts.w3.eth.get_transaction_count(contracts.oracle_address, "pending")
    gas_price = contracts.w3.eth.gas_price

    transaction = contracts.licensing.functions.confirmDownloadAccess(purchase_id, access_hash).build_transaction(
        {
            "from": contracts.oracle_address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": gas_price,
        }
    )

    signed = contracts.w3.eth.account.sign_transaction(transaction, contracts.oracle_account.key)
    tx_hash = contracts.w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = contracts.w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1:
        raise HTTPException(status_code=502, detail="Oracle confirmation transaction failed.")

    return receipt.transactionHash.hex()