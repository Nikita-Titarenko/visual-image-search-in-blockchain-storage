from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api_test_utils import load_image_api_module


class FakeImageVectorService:
    def __init__(self, api_module) -> None:
        self._api_module = api_module
        self.records = [object(), object()]
        self.search_calls: list[tuple[str | None, int]] = []

    def audit_status(self, snapshot_id: int | None = None):
        return SimpleNamespace(
            modelVersion="resnet18-dev",
            modelHash="0xabc",
            indexVersion="index-v1",
            indexHash="0xdef",
            datasetSize=len(self.records),
            snapshotId=snapshot_id,
            onChainMatch=True,
            metadata={"source": "test"},
        )

    async def search(self, file, top_k: int):
        self.search_calls.append((file.filename, top_k))
        return self._api_module.SearchResponse(
            method="cnn+knn",
            topK=top_k,
            modelVersion="resnet18-dev",
            indexVersion="index-v1",
            queryHash="0xquery",
            results=[
                {
                    "rank": 1,
                    "score": 0.95,
                    "distance": 0.05,
                    "imageId": 11,
                    "className": "accordion",
                    "fileName": "image_0001.jpg",
                    "ipfsUri": "ipfs://example",
                    "gatewayUrl": "https://gateway.example/image_0001.jpg",
                    "contentHash": "0xcontent",
                    "relativePath": "accordion/image_0001.jpg",
                }
            ],
        )

class ImageVectorApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.api_module = load_image_api_module()

    def setUp(self) -> None:
        self.service = FakeImageVectorService(self.api_module)
        self.client = TestClient(self.api_module.create_app(service_instance=self.service, enable_lifespan=False))

    def test_health_endpoint_returns_expected_payload(self) -> None:
        response = self.client.get("/api/vector/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True,
            "datasetSize": 2,
            "modelVersion": "resnet18-dev",
            "indexVersion": "index-v1",
        })

    def test_search_endpoint_returns_stubbed_result(self) -> None:
        response = self.client.post(
            "/api/vector/search?top_k=4",
            files={"file": ("query.png", b"query-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["topK"], 4)
        self.assertEqual(payload["results"][0]["className"], "accordion")
        self.assertEqual(self.service.search_calls, [("query.png", 4)])

    def test_search_endpoint_rejects_invalid_top_k(self) -> None:
        response = self.client.post(
            "/api/vector/search?top_k=0",
            files={"file": ("query.png", b"query-bytes", "image/png")},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()