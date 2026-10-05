from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
ORACLE_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")

ARTIFACTS_DIR = ROOT_DIR / "artifacts" / "contracts"
STORE_PATH = ORACLE_DIR / "state.json"
DEFAULT_GATEWAY = os.getenv("PINATA_GATEWAY_BASE_URL", "https://gateway.pinata.cloud/ipfs")
ACCESS_TTL_MINUTES = int(os.getenv("ORACLE_ACCESS_TOKEN_TTL_MINUTES", "30"))
SIGNATURE_TTL_MINUTES = int(os.getenv("ORACLE_SIGNATURE_TTL_MINUTES", "10"))
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ORACLE_ALLOWED_ORIGINS", "http://localhost:4200").split(",") if origin.strip()]


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value