from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np


SERVICE_DIR = Path(__file__).resolve().parent.parent


def load_service_module():
    if str(SERVICE_DIR) not in sys.path:
        sys.path.insert(0, str(SERVICE_DIR))
    return importlib.import_module("service")


class ImageVectorServiceEventSyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service_module = load_service_module()

    def _make_service(self):
        service = self.service_module.ImageVectorService.__new__(self.service_module.ImageVectorService)
        service.logger = Mock()
        service.test_records = []
        service.records = []
        service.cnn_index = None
        service.hist_index = None
        service._sync_lock = asyncio.Lock()
        service._refresh_audit_metadata = Mock()
        service._maybe_record_audit_snapshot = AsyncMock(return_value=False)
        service._append_records_to_index = AsyncMock()
        service.rebuild_index = AsyncMock()
        service._search_corpus_size = self.service_module.ImageVectorService._search_corpus_size.__get__(service, self.service_module.ImageVectorService)
        service._index_matches_corpus = self.service_module.ImageVectorService._index_matches_corpus.__get__(service, self.service_module.ImageVectorService)
        service._coerce_block_number = self.service_module.ImageVectorService._coerce_block_number
        return service

    async def test_event_append_uses_incremental_index_when_existing_index_matches_manifest(self) -> None:
        service = self._make_service()
        old_record = SimpleNamespace(image_id=3)
        new_record = SimpleNamespace(image_id=4)
        service.records = [old_record]
        service.cnn_index = np.zeros((1, 512), dtype=np.float32)
        service.hist_index = np.zeros((1, 24), dtype=np.float32)

        persisted_records: list[object] = [old_record]

        def fake_save_manifest(records):
            persisted_records[:] = list(records)

        with (
            patch.object(self.service_module, "build_record_from_image_registered_log", new=AsyncMock(return_value=new_record)),
            patch.object(self.service_module, "save_manifest", side_effect=fake_save_manifest) as save_manifest,
            patch.object(self.service_module, "write_last_processed_block") as write_last_processed_block,
        ):
            updated = await service._upsert_record_from_event_log({"blockNumber": 77})

        self.assertTrue(updated)
        self.assertEqual([record.image_id for record in service.records], [3, 4])
        self.assertEqual([record.image_id for record in persisted_records], [3, 4])
        service._append_records_to_index.assert_awaited_once_with([new_record])
        service.rebuild_index.assert_not_awaited()
        save_manifest.assert_called_once()
        write_last_processed_block.assert_called_once_with(78)

    async def test_event_rebuild_persists_new_record_before_manifest_reload(self) -> None:
        service = self._make_service()
        old_record = SimpleNamespace(image_id=3)
        new_record = SimpleNamespace(image_id=4)
        service.records = [old_record]
        service.cnn_index = np.zeros((0, 512), dtype=np.float32)
        service.hist_index = np.zeros((0, 24), dtype=np.float32)

        persisted_records: list[object] = [old_record]

        def fake_save_manifest(records):
            persisted_records[:] = list(records)

        async def fake_rebuild_index():
            service.records = list(persisted_records)

        service.rebuild_index = AsyncMock(side_effect=fake_rebuild_index)

        with (
            patch.object(self.service_module, "build_record_from_image_registered_log", new=AsyncMock(return_value=new_record)),
            patch.object(self.service_module, "save_manifest", side_effect=fake_save_manifest) as save_manifest,
            patch.object(self.service_module, "write_last_processed_block") as write_last_processed_block,
        ):
            updated = await service._upsert_record_from_event_log({"blockNumber": 91})

        self.assertTrue(updated)
        self.assertEqual([record.image_id for record in service.records], [3, 4])
        self.assertEqual([record.image_id for record in persisted_records], [3, 4])
        service._append_records_to_index.assert_not_awaited()
        service.rebuild_index.assert_awaited_once()
        self.assertEqual(save_manifest.call_count, 2)
        write_last_processed_block.assert_called_once_with(92)


if __name__ == "__main__":
    unittest.main()