"""MongoDB layer (PolyStorage)."""
from .mongo_client import get_client, get_db, get_collection
from .collections import C

__all__ = ["get_client", "get_db", "get_collection", "C"]
