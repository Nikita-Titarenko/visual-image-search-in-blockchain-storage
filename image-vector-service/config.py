from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = Path(__file__).resolve().parent
SMART_CONTRACTS_DIR = ROOT_DIR / "smart-contracts"

load_dotenv(ROOT_DIR / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value

STATE_DIR = SERVICE_DIR / "state"
MANIFEST_PATH = STATE_DIR / "dataset_manifest.json"
INDEX_PATH = STATE_DIR / "feature_index.npz"
DEV_INDEX_PATH = STATE_DIR / "development_feature_index.npz"
DEV_PLOTS_DIR = STATE_DIR / "development_plots"
FINETUNED_MODEL_PATH = STATE_DIR / "fine_tuned_resnet18_backbone.pt"
AUDIT_METADATA_PATH = STATE_DIR / "audit_metadata.json"
LOG_PATH = STATE_DIR / "image-vector-service.log"
DEV_EVALUATION_PATH = STATE_DIR / "development_evaluation.json"
ARTIFACTS_DIR = SMART_CONTRACTS_DIR / "artifacts" / "contracts"
PINATA_GATEWAY_BASE_URL = require_env("PINATA_GATEWAY_BASE_URL")
VECTOR_ALLOWED_ORIGINS = [origin.strip() for origin in require_env("VECTOR_ALLOWED_ORIGINS").split(",") if origin.strip()]
VECTOR_PUBLIC_BASE_URL = require_env("VECTOR_PUBLIC_BASE_URL").rstrip("/")
VECTOR_TOP_K_DEFAULT = int(require_env("VECTOR_TOP_K_DEFAULT"))
VECTOR_TOP_K_MAX = int(require_env("VECTOR_TOP_K_MAX"))
VECTOR_BOOTSTRAP_LIMIT = int(require_env("VECTOR_BOOTSTRAP_LIMIT"))
AUDIT_SNAPSHOT_IMAGE_INTERVAL = int(require_env("AUDIT_SNAPSHOT_IMAGE_INTERVAL"))
POLYGON_AMOY_WS_URL = require_env("POLYGON_AMOY_WS_URL")
VECTOR_MODEL_VERSION = require_env("VECTOR_MODEL_VERSION")
VECTOR_INDEX_VERSION = require_env("VECTOR_INDEX_VERSION")
VECTOR_TEST_DATASET_ID = require_env("VECTOR_TEST_DATASET_ID")
VECTOR_RUNTIME_MODE = require_env("VECTOR_RUNTIME_MODE").lower()
VECTOR_RANDOM_SEED = int(require_env("VECTOR_RANDOM_SEED"))
VECTOR_TRAIN_RATIO = float(require_env("VECTOR_TRAIN_RATIO"))
VECTOR_VAL_RATIO = float(require_env("VECTOR_VAL_RATIO"))
VECTOR_TEST_RATIO = float(require_env("VECTOR_TEST_RATIO"))
VECTOR_DEV_DATASET_LIMIT = int(require_env("VECTOR_DEV_DATASET_LIMIT"))