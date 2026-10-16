from __future__ import annotations

import json
from typing import Any

from web3 import Web3

from config import ARTIFACTS_DIR, PINATA_JWT, require_env
from gateway import build_defunct_message
from models import OracleContracts, OracleImageRecord, OraclePurchaseRecord


def load_artifact(contract_name: str) -> dict[str, Any]:
    artifact_path = ARTIFACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_path.exists():
        raise RuntimeError(f"Artifact not found: {artifact_path}")
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def build_contracts() -> OracleContracts:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    licensing_address = Web3.to_checksum_address(require_env("LICENSING_AND_PAYMENT_ADDRESS"))
    registry_address = Web3.to_checksum_address(require_env("IMAGE_REGISTRY_ADDRESS"))

    w3 = Web3(Web3.HTTPProvider(rpc_url))

    licensing_artifact = load_artifact("LicensingAndPayment")
    registry_artifact = load_artifact("ImageRegistry")

    licensing = w3.eth.contract(address=licensing_address, abi=licensing_artifact["abi"])
    registry = w3.eth.contract(address=registry_address, abi=registry_artifact["abi"])

    return OracleContracts(
        w3=w3,
        licensing=licensing,
        registry=registry,
        pinata_jwt=PINATA_JWT,
    )


class BlockchainOracleGateway:
    def __init__(self, contracts: OracleContracts) -> None:
        self.contracts = contracts
        self.pinata_jwt = contracts.pinata_jwt

    def recover_claim_signer(self, message: str, signature: str) -> str:
        return self.contracts.w3.eth.account.recover_message(build_defunct_message(message), signature=signature)

    def get_purchase(self, purchase_id: int) -> OraclePurchaseRecord:
        purchase = self.contracts.licensing.functions.getPurchase(purchase_id).call()
        return OraclePurchaseRecord(
            purchase_id=int(purchase[0]),
            image_id=int(purchase[1]),
            buyer=Web3.to_checksum_address(purchase[2]),
            seller=Web3.to_checksum_address(purchase[3]),
            paid_amount=int(purchase[4]),
            purchased_at=int(purchase[5]),
        )

    def get_image(self, image_id: int) -> OracleImageRecord:
        image = self.contracts.registry.functions.getImage(image_id).call()
        return OracleImageRecord(
            image_id=int(image[0]),
            collection_id=int(image[1]),
            current_owner=Web3.to_checksum_address(image[2]),
            content_hash=Web3.to_hex(image[3]).lower(),
            metadata_uri=str(image[4]),
            registered_at=int(image[5]),
        )

    def verify_image_hash(self, image_id: int, candidate_hash: str) -> bool:
        return bool(self.contracts.registry.functions.verifyImageHash(image_id, candidate_hash).call())


def build_gateway() -> BlockchainOracleGateway:
    return BlockchainOracleGateway(build_contracts())
