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
    oracle_account: Any
    oracle_address: str
    pinata_jwt: str


class ClaimAccessRequest(BaseModel):
    purchaseId: int = Field(gt=0)
    buyerAddress: str
    signedMessage: str
    issuedAt: str