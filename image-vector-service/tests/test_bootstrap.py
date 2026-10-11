from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SERVICE_DIR = Path(__file__).resolve().parent.parent


def load_bootstrap_module():
    if str(SERVICE_DIR) not in sys.path:
        sys.path.insert(0, str(SERVICE_DIR))
    return importlib.import_module("bootstrap")


class BootstrapRegistrySyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = load_bootstrap_module()

    async def test_registry_enumeration_uses_current_owner(self) -> None:
        fake_record = SimpleNamespace(image_id=7)

        with (
            patch.object(self.bootstrap, "require_env", return_value="http://localhost:8545"),
            patch.object(self.bootstrap, "load_registry_contract", return_value=object()),
            patch.object(
                self.bootstrap,
                "_fetch_all_registry_images",
                return_value=[
                    {
                        "id": 7,
                        "collectionId": 3,
                        "currentOwner": "0xabc123",
                        "contentHash": b"\x01" * 32,
                        "metadataURI": "ipfs://metadata-7",
                        "registeredAt": 123,
                    }
                ],
            ),
            patch.object(self.bootstrap, "save_manifest"),
            patch.object(self.bootstrap, "_build_record_from_metadata", new=AsyncMock(return_value=fake_record)) as build_record,
        ):
            records, added_records = await self.bootstrap._sync_registered_images_from_registry({})

        self.assertEqual(added_records, 1)
        self.assertEqual(records, [fake_record])
        build_record.assert_awaited_once_with(
            image_id=7,
            metadata_uri="ipfs://metadata-7",
            collection_id="3",
            content_hash="0x0101010101010101010101010101010101010101010101010101010101010101",
            creator_wallet="0xabc123",
        )


if __name__ == "__main__":
    unittest.main()