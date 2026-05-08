"""Per-session chat history backed by `MongoDBChatMessageHistory`."""
from __future__ import annotations

from langchain_mongodb.chat_message_histories import MongoDBChatMessageHistory

from ..db.collections import C
from ..settings import settings


def get_chat_history(session_id: str) -> MongoDBChatMessageHistory:
    return MongoDBChatMessageHistory(
        connection_string=settings.mongo_uri,
        database_name=settings.mongo_db,
        collection_name=C.chat_history,
        session_id=session_id,
    )
