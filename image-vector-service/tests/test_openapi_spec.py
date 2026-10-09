from __future__ import annotations

import unittest

from api_test_utils import load_openapi_spec


class ImageVectorOpenApiSpecificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_openapi_spec()

    def test_spec_has_metadata(self) -> None:
        info = self.spec["info"]
        self.assertEqual(info["title"], "Image Vector Search Service")
        self.assertEqual(info["version"], "1.0.0")

    def test_spec_contains_expected_paths(self) -> None:
        paths = self.spec["paths"]
        self.assertIn("/api/vector/health", paths)
        self.assertIn("/api/vector/search", paths)
        self.assertIn("/api/vector/audit-status", paths)
        self.assertIn("/api/vector/rebuild-index", paths)

    def test_search_declares_multipart_body(self) -> None:
        request_body = self.spec["paths"]["/api/vector/search"]["post"]["requestBody"]
        self.assertIn("multipart/form-data", request_body["content"])

    def test_search_declares_top_k_constraint(self) -> None:
        parameters = self.spec["paths"]["/api/vector/search"]["post"]["parameters"]
        top_k = next(item for item in parameters if item["name"] == "top_k")
        self.assertEqual(top_k["schema"]["minimum"], 1)

    def test_audit_status_uses_response_schema(self) -> None:
        response_schema = self.spec["paths"]["/api/vector/audit-status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(response_schema["$ref"], "#/components/schemas/AuditStatusResponse")


if __name__ == "__main__":
    unittest.main()