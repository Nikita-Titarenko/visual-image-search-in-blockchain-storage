from __future__ import annotations

from datetime import datetime, timezone

from .config import DEFAULT_GATEWAY


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ipfs_to_gateway(uri: str) -> str:
    if uri.startswith("ipfs://"):
        return f"{DEFAULT_GATEWAY.rstrip('/')}/{uri.removeprefix('ipfs://')}"
    return uri


def hex_bytes32(value: str) -> str:
    if value.startswith("0x") and len(value) == 66:
        return value.lower()
    raise ValueError("Expected 32-byte hex string.")


def build_claim_message(purchase_id: int, buyer_address: str, issued_at: str) -> str:
    return (
        "Claim encrypted image access\n"
        f"Purchase ID: {purchase_id}\n"
        f"Buyer: {buyer_address.lower()}\n"
        f"Issued At: {issued_at}"
    )