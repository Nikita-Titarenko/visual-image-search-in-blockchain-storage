from __future__ import annotations

import unittest

from api_test_utils import load_openapi_spec


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
        self.assertIn("/api/oracle/claim-access", paths)
        self.assertIn("/api/oracle/download/{purchase_id}", paths)

    def test_claim_access_references_request_schema(self) -> None:
        request_schema = self.spec["paths"]["/api/oracle/claim-access"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(request_schema["$ref"], "#/components/schemas/ClaimAccessRequest")

    def test_download_declares_path_parameter(self) -> None:
        parameters = self.spec["paths"]["/api/oracle/download/{purchase_id}"]["get"]["parameters"]
        purchase_id = next(item for item in parameters if item["name"] == "purchase_id")
        self.assertEqual(purchase_id["in"], "path")
        self.assertTrue(purchase_id["required"])

    def test_download_declares_token_min_length(self) -> None:
        parameters = self.spec["paths"]["/api/oracle/download/{purchase_id}"]["get"]["parameters"]
        token = next(item for item in parameters if item["name"] == "token")
        self.assertEqual(token["schema"]["minLength"], 20)


if __name__ == "__main__":
    unittest.main()