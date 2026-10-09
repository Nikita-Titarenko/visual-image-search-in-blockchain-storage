from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = SERVICE_DIR.parent
OPENAPI_DIR = SERVICE_DIR / "openapi"


def load_oracle_api_module():
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    return importlib.import_module("oracle.api")


def load_openapi_spec() -> dict[str, object]:
    return json.loads((OPENAPI_DIR / "oracle.openapi.json").read_text(encoding="utf-8"))