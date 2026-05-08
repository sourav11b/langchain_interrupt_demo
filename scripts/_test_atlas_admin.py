"""Smoke test for the Atlas Admin API client (cluster autoresume)."""
from __future__ import annotations

import json

from src.vaultiq.db.atlas_admin import get_cluster_status
from src.vaultiq.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    status = get_cluster_status()
    print("CLUSTER STATUS:")
    print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()
