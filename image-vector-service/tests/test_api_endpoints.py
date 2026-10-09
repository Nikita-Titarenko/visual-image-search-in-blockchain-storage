from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api_test_utils import load_image_api_module


class FakeImageVectorService:
    def __init__(self, api_module) -> None:
        self._api_module = api_module
        self.records = [object(), object()]
        self.last_snapshot_id = None
        self.search_calls: list[tuple[str | None, int]] = []
        self.rebuild_calls = 0
        self.initialize_calls = 0

    def audit_status(self, snapshot_id: int | None = None):
        self.last_snapshot_id = snapshot_id
        return self._api_module.AuditStatusResponse(
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

    async def rebuild_index(self):
        self.rebuild_calls += 1

    async def initialize(self):
        self.initialize_calls += 1


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

    def test_audit_status_forwards_snapshot_id(self) -> None:
        response = self.client.get("/api/vector/audit-status", params={"snapshot_id": 7})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.last_snapshot_id, 7)
        self.assertEqual(response.json()["snapshotId"], 7)

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

    def test_rebuild_index_endpoint_reinitializes_service(self) -> None:
        response = self.client.post("/api/vector/rebuild-index")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.rebuild_calls, 1)
        self.assertEqual(self.service.initialize_calls, 1)


if __name__ == "__main__":
    unittest.main()