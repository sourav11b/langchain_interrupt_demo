"""Single shared PyMongo client for the whole app."""
from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from ..settings import settings


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(
        settings.mongo_uri,
        appname="vaultiq-fsi-demo",
        retryWrites=True,
        tz_aware=True,
    )


def get_db(name: str | None = None) -> Database:
    return get_client()[name or settings.mongo_db]


def get_collection(logical_name: str) -> Collection:
    return get_db()[settings.coll(logical_name)]
