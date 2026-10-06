from __future__ import annotations

import logging
from pathlib import Path

from config import LOG_PATH


LOGGER_NAME = "image-vector-service"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    log_dir = Path(LOG_PATH).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logger.addHandler(handler)
    logger.info("Logger initialized. Writing to %s", LOG_PATH)
    return logger