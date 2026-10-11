from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
ORACLE_DIR = Path(__file__).resolve().parent
SMART_CONTRACTS_DIR = ROOT_DIR / "smart-contracts"

load_dotenv(ROOT_DIR / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value

ARTIFACTS_DIR = SMART_CONTRACTS_DIR / "artifacts" / "contracts"
STORE_PATH = ORACLE_DIR / "state.json"
DEFAULT_GATEWAY = require_env("PINATA_GATEWAY_BASE_URL")
ACCESS_TTL_MINUTES = int(require_env("ORACLE_ACCESS_TOKEN_TTL_MINUTES"))
SIGNATURE_TTL_MINUTES = int(require_env("ORACLE_SIGNATURE_TTL_MINUTES"))
ALLOWED_ORIGINS = [origin.strip() for origin in require_env("ORACLE_ALLOWED_ORIGINS").split(",") if origin.strip()]