from __future__ import annotations

from typing import Protocol

from eth_account.messages import SignableMessage, encode_defunct

from config import CONTRACTS_MOCK_BASE_URL, ORACLE_USE_CENTRALIZED_BACKEND
from models import OracleImageRecord, OraclePurchaseRecord


class OracleDataGateway(Protocol):
    pinata_jwt: str

    def recover_claim_signer(self, message: str, signature: str) -> str: ...

    def get_purchase(self, purchase_id: int) -> OraclePurchaseRecord: ...

    def get_image(self, image_id: int) -> OracleImageRecord: ...

    def verify_image_hash(self, image_id: int, candidate_hash: str) -> bool: ...


def build_gateway(*, use_centralized_backend: bool | None = None) -> OracleDataGateway:
    resolved = ORACLE_USE_CENTRALIZED_BACKEND if use_centralized_backend is None else use_centralized_backend
    if resolved:
        if not CONTRACTS_MOCK_BASE_URL:
            raise RuntimeError("CONTRACTS_MOCK_BASE_URL is required when ORACLE_USE_CENTRALIZED_BACKEND=true.")
        from centralized import build_gateway as build_centralized_gateway

        return build_centralized_gateway()

    from blockchain import build_gateway as build_blockchain_gateway

    return build_blockchain_gateway()


def build_defunct_message(text: str) -> SignableMessage:
    return encode_defunct(text=text)