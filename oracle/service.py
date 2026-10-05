from __future__ import annotations

import mimetypes
import os
import secrets
from base64 import b64decode, b64encode
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from eth_account.messages import encode_defunct
from fastapi import HTTPException, UploadFile
from web3 import Web3

from .blockchain import send_confirm_transaction
from .config import ACCESS_TTL_MINUTES, SIGNATURE_TTL_MINUTES
from .models import ClaimAccessRequest, OracleContracts
from .pinata import fetch_bytes, fetch_json, pin_file_to_ipfs
from .storage import ensure_store, get_asset_record, save_store
from .utils import build_claim_message, hex_bytes32, to_iso, utcnow


class OracleService:
    def __init__(self, contracts: OracleContracts):
        self.contracts = contracts

    async def encrypt_upload(self, file: UploadFile, content_hash: str) -> dict[str, Any]:
        normalized_hash = hex_bytes32(content_hash)
        original_bytes = await file.read()
        if not original_bytes:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        encrypted_bytes = AESGCM(key).encrypt(nonce, original_bytes, None)
        file_name = f"{Path(file.filename or 'asset').stem}.enc"

        upload_result = await pin_file_to_ipfs(file_name, encrypted_bytes, "application/octet-stream", self.contracts.pinata_jwt)

        store = ensure_store()
        store["assets"][normalized_hash] = {
            "contentHash": normalized_hash,
            "encryptedAssetUri": upload_result["ipfsUri"],
            "encryptedGatewayUrl": upload_result["gatewayUrl"],
            "decryptionKey": b64encode(key).decode("utf-8"),
            "nonce": b64encode(nonce).decode("utf-8"),
            "originalFileName": file.filename or "image",
            "contentType": file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream",
            "createdAt": to_iso(utcnow()),
        }
        save_store(store)

        return {
            **upload_result,
            "encrypted": True,
            "contentHash": normalized_hash,
        }

    async def claim_access(self, request: ClaimAccessRequest) -> dict[str, Any]:
        issued_at = datetime.fromisoformat(request.issuedAt.replace("Z", "+00:00"))
        if utcnow() - issued_at > timedelta(minutes=SIGNATURE_TTL_MINUTES):
            raise HTTPException(status_code=400, detail="The signed claim message has expired.")

        buyer_address = Web3.to_checksum_address(request.buyerAddress)
        message = build_claim_message(request.purchaseId, buyer_address, request.issuedAt)
        recovered = self.contracts.w3.eth.account.recover_message(encode_defunct(text=message), signature=request.signedMessage)
        if recovered.lower() != buyer_address.lower():
            raise HTTPException(status_code=403, detail="Signature does not match the buyer wallet.")

        purchase = self.contracts.licensing.functions.getPurchase(request.purchaseId).call()
        purchase_buyer = Web3.to_checksum_address(purchase[2])
        if purchase_buyer.lower() != buyer_address.lower():
            raise HTTPException(status_code=403, detail="This wallet is not the buyer for the purchase.")

        image_id = int(purchase[1])
        image = self.contracts.registry.functions.getImage(image_id).call()
        content_hash = Web3.to_hex(image[4]).lower()
        metadata_uri = image[5]
        metadata = await fetch_json(metadata_uri)

        store = ensure_store()
        asset_record = get_asset_record(store, content_hash)

        token = secrets.token_urlsafe(32)
        token_hash = Web3.keccak(text=token)
        proof_hex = Web3.to_hex(token_hash)

        transaction_hash = None
        if not purchase[7]:
            transaction_hash = send_confirm_transaction(self.contracts, request.purchaseId, token_hash)

        expires_at = utcnow() + timedelta(minutes=ACCESS_TTL_MINUTES)
        store["accessTokens"][proof_hex] = {
            "purchaseId": request.purchaseId,
            "buyerAddress": buyer_address,
            "contentHash": content_hash,
            "expiresAt": to_iso(expires_at),
            "issuedAt": to_iso(utcnow()),
        }
        save_store(store)

        return {
            "purchaseId": request.purchaseId,
            "imageId": image_id,
            "buyerAddress": buyer_address,
            "encryptedAssetUri": asset_record["encryptedAssetUri"],
            "metadataUri": metadata_uri,
            "metadataName": metadata.get("name", ""),
            "accessToken": token,
            "accessProof": proof_hex,
            "expiresAt": to_iso(expires_at),
            "downloadUrl": f"/api/oracle/download/{request.purchaseId}",
            "confirmationTransactionHash": transaction_hash,
        }

    async def download_decrypted_file(self, purchase_id: int, token: str) -> tuple[bytes, dict[str, str], str]:
        proof_hex = Web3.to_hex(Web3.keccak(text=token))
        store = ensure_store()
        grant = store["accessTokens"].get(proof_hex)

        if not grant or int(grant["purchaseId"]) != purchase_id:
            raise HTTPException(status_code=403, detail="Invalid access token.")

        expires_at = datetime.fromisoformat(grant["expiresAt"].replace("Z", "+00:00"))
        if utcnow() > expires_at:
            raise HTTPException(status_code=403, detail="The access token has expired.")

        asset_record = get_asset_record(store, grant["contentHash"])
        encrypted_bytes = await fetch_bytes(asset_record["encryptedGatewayUrl"])

        key = b64decode(asset_record["decryptionKey"])
        nonce = b64decode(asset_record["nonce"])
        decrypted_bytes = AESGCM(key).decrypt(nonce, encrypted_bytes, None)

        headers = {
            "Content-Disposition": f"attachment; filename={asset_record['originalFileName']}",
            "X-Encrypted-Source": asset_record["encryptedAssetUri"],
        }

        return decrypted_bytes, headers, asset_record["contentType"]