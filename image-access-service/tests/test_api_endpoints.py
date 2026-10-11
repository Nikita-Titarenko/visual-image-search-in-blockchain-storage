from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api_test_utils import load_oracle_api_module


class FakeOracleService:
    def __init__(self) -> None:
        self.encrypt_calls: list[tuple[str | None, str]] = []
        self.download_payloads: list[dict[str, object]] = []

    async def encrypt_upload(self, file, content_hash: str):
        self.encrypt_calls.append((file.filename, content_hash))
        return {
            "encrypted": True,
            "contentHash": content_hash,
            "ipfsUri": "ipfs://encrypted",
            "gatewayUrl": "https://gateway.example/encrypted",
        }

    async def download_decrypted_file(self, request):
        self.download_payloads.append(request.model_dump())
        return b"decrypted-bytes", {"X-Encrypted-Source": "ipfs://encrypted"}, "image/png"


class OracleApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.api_module = load_oracle_api_module()

    def setUp(self) -> None:
        self.contracts = SimpleNamespace()
        self.service = FakeOracleService()
        self.client = TestClient(
            self.api_module.create_app(
                service_instance=self.service,
                contracts_override=self.contracts,
            )
        )

    def test_health_endpoint_returns_ok_flag(self) -> None:
        response = self.client.get("/api/oracle/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_encrypt_upload_returns_stubbed_payload(self) -> None:
        response = self.client.post(
            "/api/oracle/encrypt-upload",
            data={"contentHash": "0xhash"},
            files={"file": ("image.png", b"raw-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["contentHash"], "0xhash")
        self.assertEqual(self.service.encrypt_calls, [("image.png", "0xhash")])

    def test_download_endpoint_returns_binary_payload(self) -> None:
        response = self.client.post(
            "/api/oracle/download",
            json={
                "purchaseId": 9,
                "buyerAddress": "0x1234567890abcdef1234567890abcdef12345678",
                "signedMessage": "0xsigned",
                "issuedAt": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"decrypted-bytes")
        self.assertEqual(response.headers["x-encrypted-source"], "ipfs://encrypted")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(self.service.download_payloads[0]["buyerAddress"], "0x1234567890abcdef1234567890abcdef12345678")

    def test_download_requires_body_fields(self) -> None:
        response = self.client.post("/api/oracle/download", json={"purchaseId": 9})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()