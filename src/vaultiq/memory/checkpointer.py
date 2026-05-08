"""LangGraph MongoDB checkpointer.

Persists every step of the graph so a paused run (e.g. waiting on customer OTP)
can be resumed later, and so the UI can replay the agent timeline.
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.mongodb import MongoDBSaver

from ..db.collections import C
from ..db.mongo_client import get_client
from ..settings import settings


@lru_cache(maxsize=1)
def get_checkpointer() -> MongoDBSaver:
    return MongoDBSaver(
        client=get_client(),
        db_name=settings.mongo_db,
        checkpoint_collection_name=C.checkpoints,
        writes_collection_name=C.checkpoint_writes,
    )
