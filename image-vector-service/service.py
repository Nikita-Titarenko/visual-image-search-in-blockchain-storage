from __future__ import annotations

import io
from typing import Any

import numpy as np
from fastapi import HTTPException, UploadFile

from audit import compute_index_hash, load_audit_metadata, save_audit_metadata, verify_snapshot
from bootstrap import ensure_pinata_dataset, load_manifest
from config import INDEX_PATH, STATE_DIR, VECTOR_INDEX_VERSION, VECTOR_MODEL_VERSION, VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX
from features import FeatureExtractor
from models import AuditStatusResponse, DatasetImageRecord, SearchResponse, SearchResult
from pinata import fetch_bytes
from utils import ensure_directory


class ImageVectorService:
    def __init__(self) -> None:
        self.extractor = FeatureExtractor()
        self.records: list[DatasetImageRecord] = []
        self.cnn_index: np.ndarray | None = None
        self.hist_index: np.ndarray | None = None
        self.model_hash = self.extractor.compute_model_hash()
        self.index_hash = "0x"

    async def initialize(self) -> None:
        ensure_directory(STATE_DIR)
        self.records = await ensure_pinata_dataset()
        if INDEX_PATH.exists():
            index_payload = np.load(INDEX_PATH)
            self.cnn_index = index_payload["cnn"].astype(np.float32)
            self.hist_index = index_payload["hist"].astype(np.float32)
        else:
            await self.rebuild_index()

        self.index_hash = compute_index_hash()
        save_audit_metadata(
            {
                "modelVersion": VECTOR_MODEL_VERSION,
                "modelHash": self.model_hash,
                "indexVersion": VECTOR_INDEX_VERSION,
                "indexHash": self.index_hash,
                "datasetSize": len(self.records),
            }
        )

    async def rebuild_index(self) -> None:
        self.records = load_manifest()
        if not self.records:
            raise RuntimeError("Dataset manifest is empty. Bootstrap must complete before indexing.")

        cnn_vectors: list[np.ndarray] = []
        hist_vectors: list[np.ndarray] = []

        for record in self.records:
            image_bytes = await fetch_bytes(record.gateway_url)
            cnn_feature, hist_feature = self.extractor.extract_features(image_bytes)
            cnn_vectors.append(cnn_feature)
            hist_vectors.append(hist_feature)

        self.cnn_index = np.vstack(cnn_vectors).astype(np.float32)
        self.hist_index = np.vstack(hist_vectors).astype(np.float32)
        np.savez_compressed(INDEX_PATH, cnn=self.cnn_index, hist=self.hist_index)

    async def search(self, query_file: UploadFile, method: str, top_k: int) -> SearchResponse:
        if self.cnn_index is None or self.hist_index is None:
            raise HTTPException(status_code=503, detail="Search index is not initialized.")

        top_k = max(1, min(top_k or VECTOR_TOP_K_DEFAULT, VECTOR_TOP_K_MAX))
        image_bytes = await query_file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Query image is empty.")

        query_cnn, query_hist = self.extractor.extract_features(image_bytes)
        normalized_method = method.lower().strip() or "cnn"
        if normalized_method not in {"cnn", "histogram"}:
            raise HTTPException(status_code=400, detail="method must be either 'cnn' or 'histogram'.")

        if normalized_method == "cnn":
            scores = self.cnn_index @ query_cnn
            distances = 1 - scores
        else:
            scores = self.hist_index @ query_hist
            distances = 1 - scores

        ranked_indices = np.argsort(distances)[:top_k]
        results = [
            SearchResult(
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

        return SearchResponse(
            method=normalized_method,
            topK=top_k,
            modelVersion=VECTOR_MODEL_VERSION,
            indexVersion=VECTOR_INDEX_VERSION,
            queryHash=self._hash_query(image_bytes),
            results=results,
        )

    def audit_status(self, snapshot_id: int | None = None) -> AuditStatusResponse:
        metadata = load_audit_metadata()
        on_chain_match = None
        if snapshot_id is not None:
            on_chain_match = verify_snapshot(snapshot_id, self.model_hash, self.index_hash)

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