from __future__ import annotations

import json
from typing import Any

from web3 import Web3

from config import ARTIFACTS_DIR, require_env
from models import OracleContracts


def load_artifact(contract_name: str) -> dict[str, Any]:
    artifact_path = ARTIFACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_path.exists():
        raise RuntimeError(f"Artifact not found: {artifact_path}")
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def build_contracts() -> OracleContracts:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    licensing_address = Web3.to_checksum_address(require_env("LICENSING_AND_PAYMENT_ADDRESS"))
    registry_address = Web3.to_checksum_address(require_env("IMAGE_REGISTRY_ADDRESS"))
    pinata_jwt = require_env("PINATA_JWT")

    w3 = Web3(Web3.HTTPProvider(rpc_url))

    licensing_artifact = load_artifact("LicensingAndPayment")
    registry_artifact = load_artifact("ImageRegistry")

    licensing = w3.eth.contract(address=licensing_address, abi=licensing_artifact["abi"])
    registry = w3.eth.contract(address=registry_address, abi=registry_artifact["abi"])

    return OracleContracts(
        w3=w3,
        licensing=licensing,
        registry=registry,
        pinata_jwt=pinata_jwt,
    )
