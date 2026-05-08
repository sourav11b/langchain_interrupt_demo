"""Centralised logging configuration."""
from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)
    # Quiet down chatty libs.
    for noisy in ("httpx", "httpcore", "urllib3", "pymongo", "pymongo.command"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
