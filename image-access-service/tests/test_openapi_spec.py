from __future__ import annotations

import unittest

from tests.api_test_utils import load_openapi_spec


class OracleOpenApiSpecificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_openapi_spec()

    def test_spec_has_metadata(self) -> None:
        info = self.spec["info"]
        self.assertEqual(info["title"], "Encrypted Asset Oracle")
        self.assertEqual(info["version"], "1.0.0")

    def test_spec_contains_expected_paths(self) -> None:
        paths = self.spec["paths"]
        self.assertIn("/api/oracle/health", paths)
        self.assertIn("/api/oracle/encrypt-upload", paths)
        self.assertIn("/api/oracle/download", paths)

    def test_download_references_request_schema(self) -> None:
        request_schema = self.spec["paths"]["/api/oracle/download"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(request_schema["$ref"], "#/components/schemas/ClaimAccessRequest")


if __name__ == "__main__":
    unittest.main()