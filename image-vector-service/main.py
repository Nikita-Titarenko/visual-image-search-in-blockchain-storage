from __future__ import annotations

import asyncio
import os
import sys

from config import DEV_INDEX_PATH, VECTOR_RUNTIME_MODE
from logger import get_logger


def _resolve_runtime_mode(argv: list[str]) -> str:
	if not argv:
		return VECTOR_RUNTIME_MODE

	mode = argv[0].strip().lower()
	if mode not in {"production", "development"}:
		raise SystemExit("Usage: python image-vector-service/main.py [production|development]")
	return mode


def _resolve_selected_mode() -> str:
	return _resolve_runtime_mode(sys.argv[1:])


async def _run_development_mode() -> None:
	from evaluation import run_development_evaluation
	from service import ImageVectorService

	logger = get_logger()
	logger.info("Runtime mode selected: development")
	service = ImageVectorService(
		include_test_dataset=True,
		use_fine_tuned_model=False,
		index_path=DEV_INDEX_PATH,
		enable_audit_artifacts=False,
	)
	await service.initialize(include_registered_images=False)
	logger.info("Development runtime initialization completed; starting offline evaluation pipeline")
	await run_development_evaluation(service)
	logger.info("Development evaluation pipeline finished")


def _run_production_mode() -> None:
	from api import app
	import uvicorn

	logger = get_logger()
	logger.info("Runtime mode selected: production")
	logger.info(
		"Starting uvicorn server on %s:%s",
		os.getenv("VECTOR_HOST", "0.0.0.0"),
		os.getenv("VECTOR_PORT", "8010"),
	)
	uvicorn.run(
		app,
		host=os.getenv("VECTOR_HOST", "0.0.0.0"),
		port=int(os.getenv("VECTOR_PORT", "8010")),
	)


def main() -> None:
	logger = get_logger()
	mode = _resolve_selected_mode()
	logger.info("Resolved runtime mode from CLI/environment: %s", mode)

	if mode == "development":
		asyncio.run(_run_development_mode())
		return

	_run_production_mode()


if __name__ == "__main__":
	main()