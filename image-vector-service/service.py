from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import kagglehub
import numpy as np
from fastapi import HTTPException, UploadFile
from web3 import AsyncWeb3, WebSocketProvider, Web3

from audit import compute_index_hash, ensure_audit_snapshot, load_audit_metadata, save_audit_metadata, verify_snapshot
from bootstrap import build_record_from_image_registered_log, ensure_pinata_dataset, get_image_registered_topic, get_image_registry_address, load_manifest, resolve_websocket_rpc_url, save_manifest, write_last_processed_block
from config import AUDIT_SNAPSHOT_IMAGE_INTERVAL, DEV_INDEX_PATH, INDEX_PATH, STATE_DIR, VECTOR_DEV_DATASET_LIMIT, VECTOR_INDEX_VERSION, VECTOR_MODEL_VERSION, VECTOR_TEST_DATASET_ID, VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX
from features import FeatureExtractor
from logger import get_logger
from models import AuditStatusResponse, DatasetImageRecord, SearchResponse, SearchResult, TestDatasetImageRecord
from pinata import fetch_bytes
from utils import ensure_directory


class ImageVectorService:
    def __init__(
        self,
        *,
        include_test_dataset: bool = False,
        use_fine_tuned_model: bool = True,
        index_path: Path | None = None,
        enable_audit_artifacts: bool = True,
    ) -> None:
        self.logger = get_logger()
        self.logger.info("Initializing ImageVectorService")
        self.logger.info("Initializing FeatureExtractor")
        self.include_test_dataset = include_test_dataset
        self.index_path = index_path or (DEV_INDEX_PATH if include_test_dataset else INDEX_PATH)
        self.enable_audit_artifacts = enable_audit_artifacts
        self.extractor = FeatureExtractor(load_fine_tuned_weights=use_fine_tuned_model)
        self.logger.info("FeatureExtractor initialized")
        self.test_records: list[TestDatasetImageRecord] = []
        self.records: list[DatasetImageRecord] = []
        self.cnn_index: np.ndarray | None = None
        self.hist_index: np.ndarray | None = None
        self.model_version = self.extractor.model_version
        self.model_hash = self.extractor.compute_model_hash()
        self.index_hash = "0x"
        self.include_registered_images = True
        self._sync_lock = asyncio.Lock()
        self.logger.info(
            "ImageVectorService initialized with model hash %s, include_test_dataset=%s, use_fine_tuned_model=%s, index_path=%s",
            self.model_hash,
            self.include_test_dataset,
            self.extractor.uses_fine_tuned_weights,
            self.index_path,
        )

    @staticmethod
    def _coerce_block_number(value: object) -> int:
        if isinstance(value, str):
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        return int(value)

    def _load_test_dataset_records(self) -> list[TestDatasetImageRecord]:
        dataset_path = Path(kagglehub.dataset_download(VECTOR_TEST_DATASET_ID))
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset was downloaded to a missing path: {dataset_path}")

        image_paths = sorted(
            path
            for path in dataset_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
        )[:VECTOR_DEV_DATASET_LIMIT]
        self.logger.info(
            "Loaded %s test dataset images from %s for the fixed development corpus (limit=%s)",
            len(image_paths),
            dataset_path,
            VECTOR_DEV_DATASET_LIMIT,
        )
        return [
            TestDatasetImageRecord(
                relative_path=path.relative_to(dataset_path).as_posix(),
                file_path=path,
                media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            for path in image_paths
        ]

    def _search_corpus_size(self) -> int:
        return len(self.test_records) + len(self.records)

    def _index_matches_corpus(self) -> bool:
        if self.cnn_index is None or self.hist_index is None:
            return False
        expected_size = self._search_corpus_size()
        return self.cnn_index.shape[0] == expected_size and self.hist_index.shape[0] == expected_size

    def _build_registered_search_result(self, index: int, rank: int, scores: np.ndarray, distances: np.ndarray) -> SearchResult:
        record = self.records[index]
        return SearchResult(
            rank=rank,
            score=float(scores[index]),
            distance=float(distances[index]),
            imageId=record.image_id,
            className=record.class_name,
            fileName=record.file_name,
            ipfsUri=record.ipfs_uri,
            gatewayUrl=record.gateway_url,
            contentHash=record.content_hash,
            relativePath=record.relative_path,
        )

    async def _upsert_record_from_event_log(self, event_log: dict[str, object]) -> bool:
        record = await build_record_from_image_registered_log(event_log)
        if record is None:
            return False

        async with self._sync_lock:
            existing_record = next((item for item in self.records if item.image_id == record.image_id), None)
            if existing_record is not None:
                self.logger.info("ImageRegistered event for image %s already exists, skipping duplicate insert", record.image_id)
                return False

            self.records.append(record)
            self.records.sort(key=lambda item: item.image_id)

            if self.cnn_index is not None and self.hist_index is not None and not self._index_matches_corpus():
                self.logger.warning("Event listener detected an index/manifest mismatch before append; rebuilding full index")
                await self.rebuild_index()
            else:
                await self._append_records_to_index([record])

            save_manifest(self.records)
            block_number = self._coerce_block_number(event_log["blockNumber"])
            write_last_processed_block(block_number + 1)
            self._refresh_audit_metadata()
            await self._maybe_record_audit_snapshot("live ImageRegistered event")
            self.logger.info("ImageRegistered event added image %s and advanced last_processed_block to %s", record.image_id, block_number + 1)
            return True

    def _save_index(self) -> None:
        if self.cnn_index is None or self.hist_index is None:
            return
        np.savez_compressed(
            self.index_path,
            cnn=self.cnn_index,
            hist=self.hist_index,
            model_hash=np.array(self.model_hash),
            corpus_kind=np.array("development" if self.include_test_dataset else "production"),
        )

    @staticmethod
    def _read_index_metadata(payload: Any, key: str) -> str | None:
        if key not in payload:
            return None
        value = payload[key]
        if isinstance(value, np.ndarray):
            return str(value.item()) if value.shape == () else None
        return str(value)

    def _loaded_index_matches_model(self, payload: Any) -> bool:
        saved_model_hash = self._read_index_metadata(payload, "model_hash")
        saved_corpus_kind = self._read_index_metadata(payload, "corpus_kind")
        expected_corpus_kind = "development" if self.include_test_dataset else "production"
        return saved_model_hash == self.model_hash and saved_corpus_kind == expected_corpus_kind

    def _refresh_audit_metadata(self) -> None:
        if not self.enable_audit_artifacts:
            self.logger.info("Skipping audit metadata refresh because audit artifacts are disabled for this service instance")
            return
        self.index_hash = compute_index_hash(self.index_path) if self.index_path.exists() else "0x"
        self.logger.info("Computed index hash %s", self.index_hash)
        existing_metadata = load_audit_metadata()
        save_audit_metadata(
            {
                **existing_metadata,
                "modelVersion": self.model_version,
                "modelHash": self.model_hash,
                "indexVersion": VECTOR_INDEX_VERSION,
                "indexHash": self.index_hash,
                "datasetSize": len(self.records),
            }
        )
        self.logger.info("Audit metadata saved")

    def _should_record_audit_snapshot(self) -> bool:
        if AUDIT_SNAPSHOT_IMAGE_INTERVAL <= 0:
            return False

        dataset_size = self._search_corpus_size()
        return dataset_size > 0 and dataset_size % AUDIT_SNAPSHOT_IMAGE_INTERVAL == 0

    async def _maybe_record_audit_snapshot(self, trigger: str) -> bool:
        if not self.enable_audit_artifacts:
            self.logger.info("Skipping on-chain audit snapshot after %s because audit artifacts are disabled", trigger)
            return False
        if not self._should_record_audit_snapshot():
            self.logger.info(
                "Skipping on-chain audit snapshot after %s because dataset size %s is not a multiple of %s",
                trigger,
                self._search_corpus_size(),
                AUDIT_SNAPSHOT_IMAGE_INTERVAL,
            )
            return False

        await ensure_audit_snapshot(
            self.model_version,
            self.model_hash,
            VECTOR_INDEX_VERSION,
            self.index_hash,
            len(self.records),
        )
        self.logger.info(
            "On-chain audit snapshot ensured after %s at dataset size %s",
            trigger,
            len(self.records),
        )
        return True

    @staticmethod
    def _stack_feature_rows(rows: list[np.ndarray]) -> np.ndarray:
        return np.vstack(rows).astype(np.float32)

    def _merge_index_rows(self, cnn_rows: list[np.ndarray], hist_rows: list[np.ndarray]) -> None:
        new_cnn_index = self._stack_feature_rows(cnn_rows)
        new_hist_index = self._stack_feature_rows(hist_rows)

        if self.cnn_index is None or self.hist_index is None:
            self.cnn_index = new_cnn_index
            self.hist_index = new_hist_index
            return

        self.cnn_index = self._stack_feature_rows([self.cnn_index, new_cnn_index])
        self.hist_index = self._stack_feature_rows([self.hist_index, new_hist_index])

    def _extract_record_features(self, image_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
        return self.extractor.extract_features(image_bytes)

    async def _append_records_to_index(self, new_records: list[DatasetImageRecord]) -> None:
        cnn_vectors: list[np.ndarray] = []
        hist_vectors: list[np.ndarray] = []

        for position, record in enumerate(new_records, start=1):
            self.logger.info(
                "Live sync indexing record %s/%s: %s",
                position,
                len(new_records),
                record.relative_path,
            )
            image_bytes = await fetch_bytes(record.gateway_url)
            cnn_feature, hist_feature = self._extract_record_features(image_bytes)
            cnn_vectors.append(cnn_feature)
            hist_vectors.append(hist_feature)

        self._merge_index_rows(cnn_vectors, hist_vectors)

        self._save_index()

    async def initialize(self, include_registered_images: bool = True) -> None:
        self.logger.info("Service initialize started with include_registered_images=%s", include_registered_images)
        historical_added_count = 0
        async with self._sync_lock:
            self.include_registered_images = include_registered_images
            ensure_directory(STATE_DIR)
            self.test_records = self._load_test_dataset_records() if self.include_test_dataset else []
            if include_registered_images:
                self.records, historical_added_count = await ensure_pinata_dataset()
            else:
                self.records = []
                historical_added_count = 0
            self.logger.info(
                "Search corpus ready with %s test records and %s registered records",
                len(self.test_records),
                len(self.records),
            )
            if self.index_path.exists():
                self.logger.info("Existing feature index found at %s, loading", self.index_path)
                index_payload = np.load(self.index_path)
                self.cnn_index = index_payload["cnn"].astype(np.float32)
                self.hist_index = index_payload["hist"].astype(np.float32)
                self.logger.info(
                    "Feature index loaded: cnn_shape=%s hist_shape=%s",
                    getattr(self.cnn_index, "shape", None),
                    getattr(self.hist_index, "shape", None),
                )
                if not self._index_matches_corpus() or not self._loaded_index_matches_model(index_payload):
                    self.logger.warning(
                        "Feature index metadata mismatch detected: cnn_rows=%s hist_rows=%s expected_rows=%s saved_model_hash=%s current_model_hash=%s",
                        self.cnn_index.shape[0],
                        self.hist_index.shape[0],
                        self._search_corpus_size(),
                        self._read_index_metadata(index_payload, "model_hash"),
                        self.model_hash,
                    )
                    if self._search_corpus_size() > 0:
                        self.logger.info("Rebuilding feature index to restore manifest alignment")
                        await self.rebuild_index()
                    else:
                        self.logger.info("Ignoring stale feature index because the search corpus is empty")
                        self.cnn_index = None
                        self.hist_index = None
            else:
                if self._search_corpus_size() > 0:
                    self.logger.info("Feature index not found at %s, rebuilding", self.index_path)
                    await self.rebuild_index()
                else:
                    self.logger.info("Feature index not found and search corpus is empty")

            self._refresh_audit_metadata()
            self.logger.info(
                "Service initialize finished: include_registered_images=%s search_corpus_size=%s index_ready=%s",
                self.include_registered_images,
                self._search_corpus_size(),
                self.cnn_index is not None and self.hist_index is not None,
            )
        if historical_added_count > 0:
            await self._maybe_record_audit_snapshot("historical image sync")
        else:
            self.logger.info("Skipping on-chain audit snapshot after startup because historical sync added 0 images")

    async def rebuild_index(self) -> None:
        self.logger.info("Rebuild index started")
        if self.include_test_dataset and not self.test_records:
            self.test_records = self._load_test_dataset_records()
        if self.include_registered_images:
            self.records = load_manifest()
        else:
            self.records = []
        self.logger.info(
            "Loaded %s test records and %s manifest records for index rebuild",
            len(self.test_records),
            len(self.records),
        )
        cnn_vectors: list[np.ndarray] = []
        hist_vectors: list[np.ndarray] = []

        if self.include_test_dataset:
            for position, record in enumerate(self.test_records, start=1):
                self.logger.info(
                    "Rebuild index processing test record %s/%s: %s",
                    position,
                    len(self.test_records),
                    record.relative_path,
                )
                image_bytes = record.file_path.read_bytes()
                cnn_feature, hist_feature = self._extract_record_features(image_bytes)
                cnn_vectors.append(cnn_feature)
                hist_vectors.append(hist_feature)

        for position, record in enumerate(self.records, start=1):
            self.logger.info(
                "Rebuild index processing registered record %s/%s: %s",
                position,
                len(self.records),
                record.relative_path,
            )
            image_bytes = await fetch_bytes(record.gateway_url)
            cnn_feature, hist_feature = self._extract_record_features(image_bytes)
            cnn_vectors.append(cnn_feature)
            hist_vectors.append(hist_feature)

        if not cnn_vectors or not hist_vectors:
            self.cnn_index = None
            self.hist_index = None
            self.logger.info("Rebuild index finished with an empty search corpus; no index file written")
            return

        self.cnn_index = self._stack_feature_rows(cnn_vectors)
        self.hist_index = self._stack_feature_rows(hist_vectors)
        self._save_index()
        self.logger.info(
            "Rebuild index finished: total_vectors=%s cnn_shape=%s hist_shape=%s",
            len(cnn_vectors),
            self.cnn_index.shape,
            self.hist_index.shape,
        )
        self.logger.info(
            "Rebuild index completed and saved to %s: cnn_shape=%s hist_shape=%s",
            self.index_path,
            self.cnn_index.shape,
            self.hist_index.shape,
        )

    async def listen_for_registered_images(self) -> None:
        registry_address = get_image_registry_address()
        topic = get_image_registered_topic()
        websocket_url = resolve_websocket_rpc_url()
        self.logger.info("Starting ImageRegistered websocket listener for %s via %s", registry_address, websocket_url)

        while True:
            provider = WebSocketProvider(websocket_url)
            websocket_client = AsyncWeb3(provider)
            try:
                await provider.connect()
                subscription_id = await websocket_client.eth.subscribe(
                    "logs",
                    {
                        "address": Web3.to_checksum_address(registry_address),
                        "topics": [topic],
                    },
                )
                self.logger.info("Subscribed to ImageRegistered logs with subscription id %s", subscription_id)
                async for message in websocket_client.socket.process_subscriptions():
                    result = message.get("result")
                    if not isinstance(result, Mapping):
                        self.logger.warning("Skipping subscription payload with unexpected result type %s", type(result).__name__)
                        continue
                    await self._upsert_record_from_event_log(dict(result))
            except asyncio.CancelledError:
                self.logger.info("ImageRegistered websocket listener cancelled")
                raise
            except Exception:
                self.logger.exception("ImageRegistered websocket listener failed; reconnecting")
                await asyncio.sleep(1)
            finally:
                await provider.disconnect()

    async def search(self, query_file: UploadFile, top_k: int) -> SearchResponse:
        self.logger.info("Search started: file=%s requested_top_k=%s method=cnn", query_file.filename, top_k)
        top_k = max(1, min(top_k or VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX))
        if len(self.records) == 0:
            self.logger.info("Search completed with no registered image records available")
            image_bytes = await query_file.read()
            if not image_bytes:
                self.logger.error("Search rejected because query image is empty")
                raise HTTPException(status_code=400, detail="Query image is empty.")
            return SearchResponse(
                method="cnn",
                topK=0,
                modelVersion=self.model_version,
                indexVersion=VECTOR_INDEX_VERSION,
                queryHash=self._hash_query(image_bytes),
                results=[],
            )

        if self.cnn_index is None or self.hist_index is None:
            self.logger.error("Search rejected because indices are not initialized")
            raise HTTPException(status_code=503, detail="Search index is not initialized.")

        image_bytes = await query_file.read()
        if not image_bytes:
            self.logger.error("Search rejected because query image is empty")
            raise HTTPException(status_code=400, detail="Query image is empty.")

        query_cnn, query_hist = self.extractor.extract_features(image_bytes)
        scores = self.cnn_index @ query_cnn
        distances = 1 - scores

        available_results = min(top_k, len(self.records), len(scores))
        ranked_indices = np.argsort(distances)[:available_results]
        results: list[SearchResult] = []
        for position, index in enumerate(ranked_indices, start=1):
            results.append(self._build_registered_search_result(int(index), position, scores, distances))

        self.logger.info(
            "Search completed: method=cnn top_k=%s results=%s query_hash=%s",
            top_k,
            len(results),
            self._hash_query(image_bytes),
        )

        return SearchResponse(
            method="cnn",
            topK=available_results,
            modelVersion=self.model_version,
            indexVersion=VECTOR_INDEX_VERSION,
            queryHash=self._hash_query(image_bytes),
            results=results,
        )

    def audit_status(self, snapshot_id: int | None = None) -> AuditStatusResponse:
        self.logger.info("Audit status computation started: snapshot_id=%s", snapshot_id)
        metadata = load_audit_metadata()
        on_chain_match = None
        if snapshot_id is not None:
            on_chain_match = verify_snapshot(snapshot_id, self.model_hash, self.index_hash)

        self.logger.info("Audit status computation completed: on_chain_match=%s", on_chain_match)

        return AuditStatusResponse(
            modelVersion=self.model_version,
            modelHash=self.model_hash,
            indexVersion=VECTOR_INDEX_VERSION,
            indexHash=self.index_hash,
            datasetSize=len(self.records),
            snapshotId=snapshot_id,
            onChainMatch=on_chain_match,
            metadata=metadata,
        )

    def _hash_query(self, image_bytes: bytes) -> str:
        import hashlib

        return f"0x{hashlib.sha256(image_bytes).hexdigest()}"