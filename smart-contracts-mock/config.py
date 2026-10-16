from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


DATABASE_URL = require_env("SMART_CONTRACTS_MOCK_DATABASE_URL")
MOCK_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("SMART_CONTRACTS_MOCK_ALLOWED_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(",")
    if origin.strip()
]