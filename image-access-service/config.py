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


def optional_path_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser() if value else default


def optional_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"{name} must be either 'true' or 'false'.")
    return normalized == "true"

ARTIFACTS_DIR = SMART_CONTRACTS_DIR / "artifacts" / "contracts"
STORE_PATH = optional_path_env("ORACLE_STORE_PATH", ORACLE_DIR / "state.json")
DEFAULT_GATEWAY = require_env("PINATA_GATEWAY_BASE_URL")
PINATA_JWT = os.getenv("PINATA_JWT", "").strip()
ACCESS_TTL_MINUTES = int(require_env("ORACLE_ACCESS_TOKEN_TTL_MINUTES"))
SIGNATURE_TTL_MINUTES = int(require_env("ORACLE_SIGNATURE_TTL_MINUTES"))
ALLOWED_ORIGINS = [origin.strip() for origin in require_env("ORACLE_ALLOWED_ORIGINS").split(",") if origin.strip()]
ORACLE_USE_CENTRALIZED_BACKEND = optional_bool_env("ORACLE_USE_CENTRALIZED_BACKEND", False)
CONTRACTS_MOCK_BASE_URL = os.getenv("CONTRACTS_MOCK_BASE_URL", "").strip().rstrip("/")