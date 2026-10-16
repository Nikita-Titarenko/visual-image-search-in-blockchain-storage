from __future__ import annotations

import asyncio
import base64
import unittest
from datetime import timedelta
from types import SimpleNamespace

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tests.api_test_utils import load_oracle_service_module


class FakeGateway:
    def __init__(self) -> None:
        pass

    def recover_claim_signer(self, message: str, signature: str) -> str:
        return "0x1234567890AbcdEF1234567890aBcdef12345678"

    def get_purchase(self, purchase_id: int):
        return SimpleNamespace(
            purchase_id=purchase_id,
            image_id=7,
            buyer="0x1234567890AbcdEF1234567890aBcdef12345678",
            seller="0x9999999999999999999999999999999999999999",
            paid_amount=1,
            purchased_at=1,
        )

    def get_image(self, image_id: int):
        return SimpleNamespace(
            image_id=image_id,
            collection_id=0,
            current_owner="0x9999999999999999999999999999999999999999",
            content_hash="0xcontent",
            metadata_uri="ipfs://metadata",
            registered_at=1,
        )

class OracleServiceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service_module = load_oracle_service_module()

    def setUp(self) -> None:
        self.gateway = FakeGateway()
        self.gateway.service_module = self.service_module
        self.service = self.service_module.OracleService(self.gateway)

        original_bytes = b"original-image-bytes"
        key = AESGCM.generate_key(bit_length=256)
        nonce = b"123456789012"
        encrypted_bytes = AESGCM(key).encrypt(nonce, original_bytes, None)

        async def fetch_bytes_stub(_uri):
            return encrypted_bytes

        self.service_module.fetch_bytes = fetch_bytes_stub
        self.service_module.ensure_store = lambda: {
            "assets": {
                "0xcontent": {
                    "encryptedGatewayUrl": "https://gateway.pinata.cloud/ipfs/QmEncrypted",
                    "encryptedAssetUri": "ipfs://QmEncrypted",
                    "decryptionKey": base64.b64encode(key).decode("utf-8"),
                    "nonce": base64.b64encode(nonce).decode("utf-8"),
                    "originalFileName": "image.jpg",
                    "contentType": "image/jpeg",
                }
            }
        }
        self.service_module.get_asset_record = lambda store, content_hash: store["assets"][content_hash]

    def _build_request(self):
        issued_at = self.service_module.to_iso(self.service_module.utcnow() - timedelta(minutes=1))
        return self.service_module.ClaimAccessRequest(
            purchaseId=9,
            buyerAddress="0x1234567890AbcdEF1234567890aBcdef12345678",
            signedMessage="0xsigned",
            issuedAt=issued_at,
        )

    def test_download_returns_decrypted_image(self) -> None:
        decrypted_bytes, headers, media_type = asyncio.run(
            self.service.download_decrypted_file(self._build_request())
        )

        self.assertEqual(decrypted_bytes, b"original-image-bytes")
        self.assertEqual(media_type, "image/jpeg")
        self.assertEqual(headers["X-Encrypted-Source"], "ipfs://QmEncrypted")


if __name__ == "__main__":
    unittest.main()