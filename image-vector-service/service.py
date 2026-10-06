from __future__ import annotations

import asyncio
import io
from collections.abc import Mapping
from typing import Any

import numpy as np
from fastapi import HTTPException, UploadFile
from web3 import AsyncWeb3, WebSocketProvider, Web3

from audit import compute_index_hash, ensure_audit_snapshot, load_audit_metadata, save_audit_metadata, verify_snapshot
from bootstrap import build_record_from_image_registered_log, ensure_pinata_dataset, get_image_registered_topic, get_image_registry_address, load_manifest, resolve_websocket_rpc_url, save_manifest, write_last_processed_block
from config import AUDIT_SNAPSHOT_IMAGE_INTERVAL, INDEX_PATH, STATE_DIR, VECTOR_INDEX_VERSION, VECTOR_MODEL_VERSION, VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX
from features import FeatureExtractor
from logger import get_logger
from models import AuditStatusResponse, DatasetImageRecord, SearchResponse, SearchResult
from pinata import fetch_bytes
from utils import ensure_directory


class ImageVectorService:
    def __init__(self) -> None:
        self.logger = get_logger()
        self.logger.info("Initializing ImageVectorService")
        self.logger.info("Initializing FeatureExtractor")
        self.extractor = FeatureExtractor()
        self.logger.info("FeatureExtractor initialized")
        self.records: list[DatasetImageRecord] = []
        self.records_by_relative_path: dict[str, DatasetImageRecord] = {}
        self.cnn_index: np.ndarray | None = None
        self.hist_index: np.ndarray | None = None
        self.model_hash = self.extractor.compute_model_hash()
        self.index_hash = "0x"
        self._sync_lock = asyncio.Lock()
        self.logger.info("ImageVectorService initialized with model hash %s", self.model_hash)

    @staticmethod
    def _coerce_block_number(value: object) -> int:
        if isinstance(value, str):
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        return int(value)

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
            self.records_by_relative_path[record.relative_path] = record

            if self.cnn_index is not None and self.hist_index is not None and not self._loaded_index_matches_manifest():
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
        np.savez_compressed(INDEX_PATH, cnn=self.cnn_index, hist=self.hist_index)

    def _refresh_audit_metadata(self) -> None:
        self.index_hash = compute_index_hash() if INDEX_PATH.exists() else "0x"
        self.logger.info("Computed index hash %s", self.index_hash)
        existing_metadata = load_audit_metadata()
        save_audit_metadata(
            {
                **existing_metadata,
                "modelVersion": VECTOR_MODEL_VERSION,
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

        dataset_size = len(self.records)
        return dataset_size > 0 and dataset_size % AUDIT_SNAPSHOT_IMAGE_INTERVAL == 0

    async def _maybe_record_audit_snapshot(self, trigger: str) -> bool:
        if not self._should_record_audit_snapshot():
            self.logger.info(
                "Skipping on-chain audit snapshot after %s because dataset size %s is not a multiple of %s",
                trigger,
                len(self.records),
                AUDIT_SNAPSHOT_IMAGE_INTERVAL,
            )
            return False

        await ensure_audit_snapshot(
            VECTOR_MODEL_VERSION,
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
            cnn_feature, hist_feature = self.extractor.extract_features(image_bytes)
            cnn_vectors.append(cnn_feature)
            hist_vectors.append(hist_feature)

        new_cnn_index = np.vstack(cnn_vectors).astype(np.float32)
        new_hist_index = np.vstack(hist_vectors).astype(np.float32)

        if self.cnn_index is None or self.hist_index is None:
            self.cnn_index = new_cnn_index
            self.hist_index = new_hist_index
        else:
            self.cnn_index = np.vstack([self.cnn_index, new_cnn_index]).astype(np.float32)
            self.hist_index = np.vstack([self.hist_index, new_hist_index]).astype(np.float32)

        self._save_index()

    def _loaded_index_matches_manifest(self) -> bool:
        if self.cnn_index is None or self.hist_index is None:
            return False
        expected_size = len(self.records)
        return self.cnn_index.shape[0] == expected_size and self.hist_index.shape[0] == expected_size

    async def initialize(self) -> None:
        self.logger.info("Service initialize started")
        historical_added_count = 0
        async with self._sync_lock:
            ensure_directory(STATE_DIR)
            self.records, historical_added_count = await ensure_pinata_dataset()
            self.records_by_relative_path = {record.relative_path: record for record in self.records}
            self.logger.info("Dataset manifest ready with %s records", len(self.records))
            if INDEX_PATH.exists():
                self.logger.info("Existing feature index found at %s, loading", INDEX_PATH)
                index_payload = np.load(INDEX_PATH)
                self.cnn_index = index_payload["cnn"].astype(np.float32)
                self.hist_index = index_payload["hist"].astype(np.float32)
                self.logger.info(
                    "Feature index loaded: cnn_shape=%s hist_shape=%s",
                    getattr(self.cnn_index, "shape", None),
                    getattr(self.hist_index, "shape", None),
                )
                if not self._loaded_index_matches_manifest():
                    self.logger.warning(
                        "Feature index shape does not match manifest size: cnn_rows=%s hist_rows=%s manifest_records=%s",
                        self.cnn_index.shape[0],
                        self.hist_index.shape[0],
                        len(self.records),
                    )
                    if self.records:
                        self.logger.info("Rebuilding feature index to restore manifest alignment")
                        await self.rebuild_index()
                    else:
                        self.logger.info("Ignoring stale feature index because the dataset manifest is empty")
                        self.cnn_index = None
                        self.hist_index = None
            else:
                if self.records:
                    self.logger.info("Feature index not found at %s, rebuilding", INDEX_PATH)
                    await self.rebuild_index()
                else:
                    self.logger.info("Feature index not found and dataset manifest is empty")

            self._refresh_audit_metadata()
        if historical_added_count > 0:
            await self._maybe_record_audit_snapshot("historical image sync")
        else:
            self.logger.info("Skipping on-chain audit snapshot after startup because historical sync added 0 images")

    async def rebuild_index(self) -> None:
        self.logger.info("Rebuild index started")
        self.records = load_manifest()
        if not self.records:
            self.logger.error("Rebuild index aborted because manifest is empty")
            raise RuntimeError("Dataset manifest is empty. Bootstrap must complete before indexing.")

        self.logger.info("Loaded %s manifest records for index rebuild", len(self.records))
        self.records_by_relative_path = {record.relative_path: record for record in self.records}
        cnn_vectors: list[np.ndarray] = []
        hist_vectors: list[np.ndarray] = []

        for position, record in enumerate(self.records, start=1):
            self.logger.info(
                "Rebuild index processing record %s/%s: %s",
                position,
                len(self.records),
                record.relative_path,
            )
            image_bytes = await fetch_bytes(record.gateway_url)
            cnn_feature, hist_feature = self.extractor.extract_features(image_bytes)
            cnn_vectors.append(cnn_feature)
            hist_vectors.append(hist_feature)

        self.cnn_index = np.vstack(cnn_vectors).astype(np.float32)
        self.hist_index = np.vstack(hist_vectors).astype(np.float32)
        self._save_index()
        self.logger.info(
            "Rebuild index completed and saved to %s: cnn_shape=%s hist_shape=%s",
            INDEX_PATH,
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

    async def search(self, query_file: UploadFile, method: str, top_k: int) -> SearchResponse:
        self.logger.info("Search started: file=%s method=%s requested_top_k=%s", query_file.filename, method, top_k)
        top_k = max(1, min(top_k or VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX))
        if not self.records:
            self.logger.info("Search completed with no dataset records available")
            image_bytes = await query_file.read()
            if not image_bytes:
                self.logger.error("Search rejected because query image is empty")
                raise HTTPException(status_code=400, detail="Query image is empty.")
            return SearchResponse(
                method=(method.lower().strip() or "cnn"),
                topK=0,
                modelVersion=VECTOR_MODEL_VERSION,
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
        normalized_method = method.lower().strip() or "cnn"
        if normalized_method not in {"cnn", "histogram"}:
            self.logger.error("Search rejected because method %s is invalid", normalized_method)
            raise HTTPException(status_code=400, detail="method must be either 'cnn' or 'histogram'.")

        if normalized_method == "cnn":
            scores = self.cnn_index @ query_cnn
            distances = 1 - scores
        else:
            scores = self.hist_index @ query_hist
            distances = 1 - scores

        available_results = min(top_k, len(self.records), len(scores))
        ranked_indices = np.argsort(distances)[:available_results]
        results = [
            SearchResult(
                imageId=self.records[index].image_id,
                rank=position + 1,
                score=float(scores[index]),
                distance=float(distances[index]),
                className=self.records[index].class_name,
                fileName=self.records[index].file_name,
                ipfsUri=self.records[index].ipfs_uri,
                gatewayUrl=self.records[index].gateway_url,
                contentHash=self.records[index].content_hash,
                relativePath=self.records[index].relative_path,
            )
            for position, index in enumerate(ranked_indices)
        ]

        self.logger.info(
            "Search completed: method=%s top_k=%s results=%s query_hash=%s",
            normalized_method,
            top_k,
            len(results),
            self._hash_query(image_bytes),
        )

        return SearchResponse(
            method=normalized_method,
            topK=available_results,
            modelVersion=VECTOR_MODEL_VERSION,
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
            modelVersion=VECTOR_MODEL_VERSION,
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