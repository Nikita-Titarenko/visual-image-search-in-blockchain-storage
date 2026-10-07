from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = Path(__file__).resolve().parent
SMART_CONTRACTS_DIR = ROOT_DIR / "smart-contracts"

load_dotenv(ROOT_DIR / ".env")

STATE_DIR = SERVICE_DIR / "state"
MANIFEST_PATH = STATE_DIR / "dataset_manifest.json"
INDEX_PATH = STATE_DIR / "feature_index.npz"
AUDIT_METADATA_PATH = STATE_DIR / "audit_metadata.json"
LOG_PATH = STATE_DIR / "image-vector-service.log"
ARTIFACTS_DIR = SMART_CONTRACTS_DIR / "artifacts" / "contracts"
PINATA_GATEWAY_BASE_URL = os.getenv("PINATA_GATEWAY_BASE_URL", "https://gateway.pinata.cloud/ipfs")
VECTOR_ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("VECTOR_ALLOWED_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]
VECTOR_PUBLIC_BASE_URL = os.getenv("VECTOR_PUBLIC_BASE_URL", "http://localhost:8010").rstrip("/")
VECTOR_TOP_K_DEFAULT = int(os.getenv("VECTOR_TOP_K_DEFAULT", "10"))
VECTOR_TOP_K_MAX = int(os.getenv("VECTOR_TOP_K_MAX", "25"))
VECTOR_BOOTSTRAP_LIMIT = int(os.getenv("VECTOR_BOOTSTRAP_LIMIT", "0"))
AUDIT_SNAPSHOT_IMAGE_INTERVAL = int(os.getenv("AUDIT_SNAPSHOT_IMAGE_INTERVAL", "1000"))
POLYGON_AMOY_WS_URL = os.getenv("POLYGON_AMOY_WS_URL", "").strip()
VECTOR_MODEL_VERSION = os.getenv("VECTOR_MODEL_VERSION", "resnet18-imagenet1k-v1")
VECTOR_INDEX_VERSION = os.getenv("VECTOR_INDEX_VERSION", "cnn-and-hist-v1")
VECTOR_TEST_DATASET_ID = os.getenv("VECTOR_TEST_DATASET_ID", "imbikramsaha/caltech-101")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value