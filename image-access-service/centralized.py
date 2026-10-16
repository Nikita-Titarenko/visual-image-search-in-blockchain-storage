from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from web3 import Web3

from config import CONTRACTS_MOCK_BASE_URL, PINATA_JWT
from gateway import build_defunct_message
from models import OracleImageRecord, OraclePurchaseRecord


class CentralizedOracleGateway:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.pinata_jwt = PINATA_JWT
        self._account = Web3().eth.account

    def recover_claim_signer(self, message: str, signature: str) -> str:
        return self._account.recover_message(build_defunct_message(message), signature=signature)

    def _get_json(self, path: str) -> dict[str, Any]:
        response = httpx.get(f"{self.base_url}{path}", timeout=30)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return dict(response.json())

    def get_purchase(self, purchase_id: int) -> OraclePurchaseRecord:
        payload = self._get_json(f"/api/mock/licensing/purchases/{purchase_id}")
        return OraclePurchaseRecord(
            purchase_id=int(payload["id"]),
            image_id=int(payload["imageId"]),
            buyer=Web3.to_checksum_address(payload["buyer"]),
            seller=Web3.to_checksum_address(payload["seller"]),
            paid_amount=int(payload["paidAmount"]),
            purchased_at=int(payload["purchasedAt"]),
        )

    def get_image(self, image_id: int) -> OracleImageRecord:
        payload = self._get_json(f"/api/mock/image-registry/images/{image_id}")
        return OracleImageRecord(
            image_id=int(payload["id"]),
            collection_id=int(payload["collectionId"]),
            current_owner=Web3.to_checksum_address(payload["currentOwner"]),
            content_hash=str(payload["contentHash"]).lower(),
            metadata_uri=str(payload["metadataURI"]),
            registered_at=int(payload["registeredAt"]),
        )

    def verify_image_hash(self, image_id: int, candidate_hash: str) -> bool:
        return self.get_image(image_id).content_hash == candidate_hash.lower()


def build_gateway() -> CentralizedOracleGateway:
    return CentralizedOracleGateway(CONTRACTS_MOCK_BASE_URL)