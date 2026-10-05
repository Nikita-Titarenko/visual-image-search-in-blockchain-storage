from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


@dataclass
class DatasetImageRecord:
    dataset_path: Path
    relative_path: str
    class_name: str
    file_name: str
    ipfs_hash: str
    ipfs_uri: str
    gateway_url: str
    content_hash: str
    source: str = "pinata"

    def to_json(self) -> dict[str, Any]:
        return {
            "datasetPath": str(self.dataset_path),
            "relativePath": self.relative_path,
            "className": self.class_name,
            "fileName": self.file_name,
            "ipfsHash": self.ipfs_hash,
            "ipfsUri": self.ipfs_uri,
            "gatewayUrl": self.gateway_url,
            "contentHash": self.content_hash,
            "source": self.source,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DatasetImageRecord":
        return cls(
            dataset_path=Path(payload["datasetPath"]),
            relative_path=payload["relativePath"],
            class_name=payload["className"],
            file_name=payload["fileName"],
            ipfs_hash=payload["ipfsHash"],
            ipfs_uri=payload["ipfsUri"],
            gateway_url=payload["gatewayUrl"],
            content_hash=payload["contentHash"],
            source=payload.get("source", "pinata"),
        )


class SearchResult(BaseModel):
    rank: int
    score: float
    distance: float
    className: str
    fileName: str
    ipfsUri: str
    gatewayUrl: str
    contentHash: str
    relativePath: str


class SearchResponse(BaseModel):
    method: str
    topK: int
    modelVersion: str
    indexVersion: str
    queryHash: str
    results: list[SearchResult]


class AuditStatusResponse(BaseModel):
    modelVersion: str
    modelHash: str
    indexVersion: str
    indexHash: str
    datasetSize: int
    snapshotId: int | None = None
    onChainMatch: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)