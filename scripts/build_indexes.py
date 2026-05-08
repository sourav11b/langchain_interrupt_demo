"""Idempotently create every MongoDB index VaultIQ needs.

    python -m scripts.build_indexes
"""
from __future__ import annotations

from src.vaultiq.db.indices import ensure_all_indexes
from src.vaultiq.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    ensure_all_indexes()


if __name__ == "__main__":
    main()
