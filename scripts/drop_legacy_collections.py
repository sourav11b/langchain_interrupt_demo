"""Drop any collections whose names contain a stray '#' inline-comment leak.

Background: an early version of `settings.py` did not strip inline comments
from `config/vaultiq.properties`, so collections were created with names like
`transactions      # tx stream — ts, customer_id metaField`. Run this once to
clean them up; subsequent `build_indexes` runs will create the proper names.

    python -m scripts.drop_legacy_collections
"""
from __future__ import annotations

import logging

from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.logging_setup import configure_logging

log = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    db = get_db()
    dropped = 0
    for name in db.list_collection_names():
        if "#" in name or name != name.strip():
            log.warning("Dropping legacy collection %r", name)
            db.drop_collection(name)
            dropped += 1
    log.info("Dropped %d legacy collection(s).", dropped)


if __name__ == "__main__":
    main()
