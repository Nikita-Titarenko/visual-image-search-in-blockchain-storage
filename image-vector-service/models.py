from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


@dataclass
class DatasetImageRecord:
    image_id: int
    relative_path: str
    class_name: str
    file_name: str
    metadata_uri: str
    ipfs_hash: str
    ipfs_uri: str
    gateway_url: str
    content_hash: str
    source: str = "pinata"

    def to_json(self) -> dict[str, Any]:
        return {
            "imageId": self.image_id,
            "relativePath": self.relative_path,
            "className": self.class_name,
            "fileName": self.file_name,
            "metadataUri": self.metadata_uri,
            "ipfsHash": self.ipfs_hash,
            "ipfsUri": self.ipfs_uri,
            "gatewayUrl": self.gateway_url,
            "contentHash": self.content_hash,
            "source": self.source,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DatasetImageRecord":
        return cls(
            image_id=int(payload["imageId"]),
            relative_path=payload["relativePath"],
            class_name=payload["className"],
            file_name=payload["fileName"],
            metadata_uri=payload.get("metadataUri", ""),
            ipfs_hash=payload["ipfsHash"],
            ipfs_uri=payload["ipfsUri"],
            gateway_url=payload["gatewayUrl"],
            content_hash=payload["contentHash"],
            source=payload.get("source", "pinata"),
        )


@dataclass
class TestDatasetImageRecord:
    relative_path: str
    file_path: Path
    media_type: str


class SearchResult(BaseModel):
    resultType: Literal["dataset", "registered"]
    rank: int
    score: float
    distance: float
    imageBytes: str | None = None
    imageMediaType: str | None = None
    imageId: int | None = None
    className: str | None = None
    fileName: str | None = None
    ipfsUri: str | None = None
    gatewayUrl: str | None = None
    contentHash: str | None = None
    relativePath: str | None = None


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