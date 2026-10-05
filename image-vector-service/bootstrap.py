from __future__ import annotations

from pathlib import Path

from dataset_analysis.download_dataset import download_caltech101

from config import MANIFEST_PATH, STATE_DIR, VECTOR_BOOTSTRAP_LIMIT, require_env
from models import DatasetImageRecord, IMAGE_SUFFIXES
from pinata import pin_file_to_ipfs
from utils import ensure_directory, read_json, sha256_hex, write_json


def collect_dataset_images(dataset_root: Path) -> list[Path]:
    image_paths = [path for path in dataset_root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    image_paths.sort()
    if VECTOR_BOOTSTRAP_LIMIT > 0:
        return image_paths[:VECTOR_BOOTSTRAP_LIMIT]
    return image_paths


def load_manifest() -> list[DatasetImageRecord]:
    payload = read_json(MANIFEST_PATH, [])
    return [DatasetImageRecord.from_json(item) for item in payload]


def save_manifest(records: list[DatasetImageRecord]) -> None:
    ensure_directory(STATE_DIR)
    write_json(MANIFEST_PATH, [record.to_json() for record in records])


async def ensure_pinata_dataset() -> list[DatasetImageRecord]:
    existing = load_manifest()
    if existing:
        return existing

    ensure_directory(STATE_DIR)
    pinata_jwt = require_env("PINATA_JWT")
    dataset_root = download_caltech101()
    dataset_images = collect_dataset_images(dataset_root)
    records: list[DatasetImageRecord] = []

    for image_path in dataset_images:
        content = image_path.read_bytes()
        upload_result = await pin_file_to_ipfs(image_path.name, content, "application/octet-stream", pinata_jwt)
        relative_path = image_path.relative_to(dataset_root).as_posix()
        record = DatasetImageRecord(
            dataset_path=image_path,
            relative_path=relative_path,
            class_name=image_path.parent.name,
            file_name=image_path.name,
            ipfs_hash=upload_result["ipfsHash"],
            ipfs_uri=upload_result["ipfsUri"],
            gateway_url=upload_result["gatewayUrl"],
            content_hash=f"0x{sha256_hex(content)}",
        )
        records.append(record)

    save_manifest(records)
    return records