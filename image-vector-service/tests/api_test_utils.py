from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parent.parent
OPENAPI_DIR = SERVICE_DIR / "openapi"


def load_image_api_module():
    module_name = "image_vector_service_api_tests"
    if module_name in sys.modules:
        return sys.modules[module_name]

    if str(SERVICE_DIR) not in sys.path:
        sys.path.insert(0, str(SERVICE_DIR))

    spec = importlib.util.spec_from_file_location(module_name, SERVICE_DIR / "api.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load image-vector-service API module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_openapi_spec() -> dict[str, object]:
    return json.loads((OPENAPI_DIR / "image-vector-service.openapi.json").read_text(encoding="utf-8"))