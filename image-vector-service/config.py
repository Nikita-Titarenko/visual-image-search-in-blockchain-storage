from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")

STATE_DIR = SERVICE_DIR / "state"
MANIFEST_PATH = STATE_DIR / "dataset_manifest.json"
INDEX_PATH = STATE_DIR / "feature_index.npz"
AUDIT_METADATA_PATH = STATE_DIR / "audit_metadata.json"
ARTIFACTS_DIR = ROOT_DIR / "artifacts" / "contracts"
PINATA_GATEWAY_BASE_URL = os.getenv("PINATA_GATEWAY_BASE_URL", "https://gateway.pinata.cloud/ipfs")
VECTOR_ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("VECTOR_ALLOWED_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]
VECTOR_TOP_K_DEFAULT = int(os.getenv("VECTOR_TOP_K_DEFAULT", "10"))
VECTOR_TOP_K_MAX = int(os.getenv("VECTOR_TOP_K_MAX", "25"))
VECTOR_BOOTSTRAP_LIMIT = int(os.getenv("VECTOR_BOOTSTRAP_LIMIT", "0"))
VECTOR_MODEL_VERSION = os.getenv("VECTOR_MODEL_VERSION", "resnet18-imagenet1k-v1")
VECTOR_INDEX_VERSION = os.getenv("VECTOR_INDEX_VERSION", "cnn-and-hist-v1")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value