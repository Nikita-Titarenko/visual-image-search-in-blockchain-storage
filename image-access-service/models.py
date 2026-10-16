from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from web3 import Web3


@dataclass
class OracleContracts:
    w3: Web3
    licensing: Any
    registry: Any
    pinata_jwt: str


@dataclass(frozen=True)
class OraclePurchaseRecord:
    purchase_id: int
    image_id: int
    buyer: str
    seller: str
    paid_amount: int
    purchased_at: int


@dataclass(frozen=True)
class OracleImageRecord:
    image_id: int
    collection_id: int
    current_owner: str
    content_hash: str
    metadata_uri: str
    registered_at: int


class ClaimAccessRequest(BaseModel):
    purchaseId: int = Field(gt=0)
    buyerAddress: str
    signedMessage: str
    issuedAt: str