"""End-to-end test of every Atlas AutoEmbeddings read + write path.

Writes a uniquely-tagged test document into each vector-backed collection,
waits for `mongot` to embed and index, then issues a similarity search using
the unique tag and asserts the test document is recalled.

Exits non-zero on the first failure; cleans up its own writes at the end.
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Callable

from src.vaultiq.db.collections import C
from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.logging_setup import configure_logging
from src.vaultiq.memory.semantic_memory import get_semantic_memory
from src.vaultiq.retrievers.case_notes import (
    case_notes_hybrid_retriever, case_notes_vector_retriever, case_notes_vectorstore,
)
from src.vaultiq.retrievers.fraud_kb import (
    fraud_kb_fts_retriever, fraud_kb_hybrid_retriever,
    fraud_kb_vector_retriever, fraud_kb_vectorstore,
)
from src.vaultiq.tools.case_tools import add_case_note

log = logging.getLogger(__name__)

TAG = f"AETEST-{uuid.uuid4().hex[:8]}"
WAIT_S = 240  # autoEmbed indexing latency budget (Voyage round-trip + mongot)
POLL = 5


def _retry(label: str, fn: Callable[[], list], probe: Callable[[list], bool]) -> list:
    """Poll fn() until probe(result) is truthy or WAIT_S elapses."""
    start = time.time()
    last: list = []
    while time.time() - start < WAIT_S:
        try:
            last = fn() or []
        except Exception as exc:
            log.warning("%s raised %s; retrying", label, exc)
            last = []
        if probe(last):
            log.info("OK %s recalled %d docs after %.1fs", label, len(last), time.time() - start)
            return last
        time.sleep(POLL)
    raise AssertionError(f"FAIL {label} did not return matching docs in {WAIT_S}s; got {len(last)} docs")


def _has_tag(docs) -> bool:
    return any(TAG in (getattr(d, "page_content", "") or "") for d in docs)


def test_fraud_kb() -> None:
    log.info("=== fraud_kb (write via vectorstore.add_texts → vector/FTS/hybrid) ===")
    vs = fraud_kb_vectorstore()
    text = f"{TAG} card-not-present anomaly playbook for high-velocity merchant categories"
    ids = vs.add_texts([text], metadatas=[{"category": "fraud_test", "severity": "high"}])
    log.info("inserted fraud_kb doc id=%s", ids[0])
    _retry("fraud_kb vector", lambda: fraud_kb_vector_retriever(k=5).invoke(TAG), _has_tag)
    _retry("fraud_kb fts",    lambda: fraud_kb_fts_retriever(k=5).invoke(TAG),    _has_tag)
    _retry("fraud_kb hybrid", lambda: fraud_kb_hybrid_retriever(k=5).invoke(TAG), _has_tag)


def test_case_notes() -> None:
    log.info("=== case_notes (write via add_case_note tool → vector/hybrid) ===")
    case_id, customer_id = f"CASE-{TAG}", f"CUST-{TAG}"
    note = f"{TAG} suspicious wire transfer to crypto exchange after geo velocity flag"
    out = add_case_note.invoke({"case_id": case_id, "customer_id": customer_id, "note": note})
    assert out.get("stored"), f"add_case_note returned {out}"
    log.info("inserted case_note via tool")
    _retry("case_notes vector",
           lambda: case_notes_vector_retriever(k=5).invoke(TAG), _has_tag)
    _retry("case_notes hybrid",
           lambda: case_notes_hybrid_retriever(k=5).invoke(TAG), _has_tag)


def test_sem_memory() -> None:
    log.info("=== sem_memory (remember -> recall) ===")
    mem = get_semantic_memory()
    text = f"{TAG} agent observed coordinated card-testing across 12 small merchants"
    mid = mem.remember(text, agent="fraud_sentinel", customer_id=f"CUST-{TAG}",
                       metadata={"tx_id": f"TX-{TAG}"})
    log.info("inserted sem_memory id=%s", mid)
    _retry("sem_memory recall",
           lambda: mem.recall(query=TAG, agent="fraud_sentinel"), _has_tag)


def cleanup() -> None:
    db = get_db()
    for coll, q in [
        (C.fraud_kb,   {"text":  {"$regex": TAG}}),
        (C.case_notes, {"text":  {"$regex": TAG}}),
        (C.sem_memory, {"text":  {"$regex": TAG}}),
    ]:
        try:
            r = db[coll].delete_many(q)
            log.info("cleanup %s: deleted %d", coll, r.deleted_count)
        except Exception as exc:
            log.warning("cleanup %s failed: %s", coll, exc)


def main() -> int:
    configure_logging()
    log.info("Auto-embed roundtrip test  TAG=%s  budget=%ds", TAG, WAIT_S)
    failed: list[str] = []
    for label, fn in [("fraud_kb", test_fraud_kb),
                      ("case_notes", test_case_notes),
                      ("sem_memory", test_sem_memory)]:
        try:
            fn()
        except Exception as exc:
            log.error("FAIL %s: %s", label, exc)
            failed.append(label)
    cleanup()
    if failed:
        log.error("FAILED: %s", failed)
        return 1
    log.info("ALL AUTOEMBED PATHS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
