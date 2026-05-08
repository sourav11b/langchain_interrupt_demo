"""One-shot seed — wraps `data.seed_data.seed`.

    python -m scripts.seed
"""
from __future__ import annotations

from data.seed_data import seed
from src.vaultiq.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    seed(customers=500, history_days=14)


if __name__ == "__main__":
    main()
