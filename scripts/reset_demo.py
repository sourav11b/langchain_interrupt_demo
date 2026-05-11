"""Full demo reset — wipes every VaultIQ collection then re-seeds.

By default this clears both the seed-side fixtures (customers, merchants,
fraud KB, etc.) AND the runtime / agent-generated state that ``scripts.seed``
leaves alone (live transactions, agent metrics, semantic memory, LangGraph
checkpoints, chat history, LLM caches).

    python -m scripts.reset_demo                  # full reset + reseed
    python -m scripts.reset_demo --dry-run        # print plan, change nothing
    python -m scripts.reset_demo --keep-history   # preserve tx + metrics
    python -m scripts.reset_demo --no-seed        # wipe only, do not reseed
    python -m scripts.reset_demo --customers 1000 --history-days 30
"""
from __future__ import annotations

import argparse
import logging
from typing import Iterable

from data.seed_data import seed
from src.vaultiq.db.collections import C
from src.vaultiq.db.indices import ensure_all_indexes
from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.logging_setup import configure_logging

log = logging.getLogger(__name__)


# Re-created by data.seed_data.seed().
SEED_COLLS: tuple[str, ...] = (
    C.customers, C.accounts, C.cards, C.devices, C.merchants,
    C.home_locations, C.merchant_geo, C.transaction_geo,
    C.relationships, C.fraud_kb, C.case_notes, C.cases, C.case_events,
)

# Live transaction stream + per-run agent latency. `--keep-history` excludes these.
HISTORY_COLLS: tuple[str, ...] = (
    C.transactions, C.transaction_geo, C.agent_metrics,
)

# Agent runtime state never touched by scripts.seed.
RUNTIME_COLLS: tuple[str, ...] = (
    C.transactions, C.agent_metrics,           # time-series streams
    C.sem_memory,
    C.checkpoints, C.checkpoint_writes, C.store,
    C.chat_history,
    C.semantic_cache, C.llm_cache,
)

# Time-series collections must be dropped (delete_many is rejected on TS).
TIMESERIES_COLLS: frozenset[str] = frozenset({C.transactions, C.agent_metrics})


def _doc_count(name: str) -> int:
    try:
        return get_db()[name].estimated_document_count()
    except Exception:
        return -1


def _plan(keep_history: bool) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for group in (SEED_COLLS, RUNTIME_COLLS):
        for name in group:
            if keep_history and name in HISTORY_COLLS:
                continue
            if name not in seen:
                targets.append(name)
                seen.add(name)
    return targets


def _print_plan(targets: Iterable[str]) -> None:
    db = get_db()
    existing = set(db.list_collection_names())
    log.info("Collections to wipe (%d):", sum(1 for _ in targets))
    for name in targets:
        present = name in existing
        kind = "ts " if name in TIMESERIES_COLLS else "doc"
        action = "drop" if name in TIMESERIES_COLLS else "delete_many"
        n = _doc_count(name) if present else 0
        marker = "[x]" if present else "[ ]"
        log.info("  %s %s  %-30s  %-12s ~%d docs", marker, kind, name, action, n)


def _wipe(targets: Iterable[str]) -> None:
    db = get_db()
    existing = set(db.list_collection_names())
    for name in targets:
        if name not in existing:
            continue
        if name in TIMESERIES_COLLS:
            db.drop_collection(name)
            log.info("dropped time-series collection %s", name)
        else:
            res = db[name].delete_many({})
            log.info("cleared %s (%d docs)", name, res.deleted_count)


def reset(*, customers: int, history_days: int, keep_history: bool,
          do_seed: bool, dry_run: bool) -> None:
    targets = _plan(keep_history)
    log.info("==== reset_demo plan (dry_run=%s, keep_history=%s, do_seed=%s) ====",
             dry_run, keep_history, do_seed)
    _print_plan(targets)

    if dry_run:
        log.info("dry-run: no changes made.")
        return

    log.info("==== wiping ====")
    _wipe(targets)

    log.info("==== ensuring indexes (re-creates dropped time-series) ====")
    ensure_all_indexes()

    if do_seed:
        log.info("==== reseeding (customers=%d, history_days=%d) ====",
                 customers, history_days)
        seed(customers=customers, history_days=history_days, wipe=False)
    else:
        log.info("--no-seed: skipping seed.")

    log.info("[OK] reset_demo complete.")


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--customers", type=int, default=500)
    p.add_argument("--history-days", type=int, default=14)
    p.add_argument("--keep-history", action="store_true",
                   help="preserve transactions, transaction_geo, agent_metrics")
    p.add_argument("--no-seed", action="store_true",
                   help="wipe only — do not reload fixture data")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be wiped, change nothing")
    args = p.parse_args()
    reset(
        customers=args.customers,
        history_days=args.history_days,
        keep_history=args.keep_history,
        do_seed=not args.no_seed,
        dry_run=args.dry_run,
    )


def main() -> None:
    configure_logging()
    _cli()


if __name__ == "__main__":
    main()
