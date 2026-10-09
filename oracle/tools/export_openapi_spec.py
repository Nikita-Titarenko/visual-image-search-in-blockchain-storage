from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = SERVICE_DIR.parent
OPENAPI_DIR = SERVICE_DIR / "openapi"


def load_api_module():
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    return importlib.import_module("oracle.api")


def export_spec() -> None:
    OPENAPI_DIR.mkdir(parents=True, exist_ok=True)
    api_module = load_api_module()
    openapi_spec = api_module.create_app().openapi()
    (OPENAPI_DIR / "oracle.openapi.json").write_text(
        json.dumps(openapi_spec, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    export_spec()