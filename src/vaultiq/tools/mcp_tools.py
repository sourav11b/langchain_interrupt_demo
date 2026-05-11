"""MongoDB MCP server bridge.

Exposes the official `mongodb-mcp-server` (Node) as LangChain tools through
`langchain-mcp-adapters`. The Case Resolution agent uses these tools for ad-hoc
read-only inspection (collection listing, schema, sample queries) without
having to hand-write a tool for every collection.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

from langchain_core.tools import BaseTool

from ..settings import settings

log = logging.getLogger(__name__)

# Serializes the cold-cache MCP load so two concurrent agent threads can't
# both spawn `npx mongodb-mcp-server` and race on stdio. lru_cache by itself
# only caches return values — it does NOT coalesce in-flight callers.
_MCP_LOAD_LOCK = threading.Lock()


def _build_server_config() -> dict[str, Any]:
    cfg = settings.mcp_mongodb
    transport = (cfg.get("transport") or "embedded").lower()
    common_args: dict[str, Any] = {}
    if cfg.get("read_only", True):
        common_args["read_only"] = True
    disabled = (cfg.get("disabled_tools") or "").strip()

    if transport == "embedded":
        # Spawn `npx mongodb-mcp-server` over stdio.
        cli_args = ["-y", "mongodb-mcp-server@latest"]
        if cfg.get("read_only", True):
            cli_args.append("--readOnly")
        if disabled:
            cli_args += ["--disabledTools", disabled]
        return {
            "vaultiq_mongodb_mcp": {
                "command": "npx",
                "args": cli_args,
                "transport": "stdio",
                "env": {**os.environ, "MDB_MCP_CONNECTION_STRING": settings.mongo_uri},
            }
        }

    # http transport — server is started externally.
    host = cfg.get("host", "localhost")
    port = int(cfg.get("port", 3001))
    return {
        "vaultiq_mongodb_mcp": {
            "url": f"http://{host}:{port}/mcp",
            "transport": "streamable_http",
        }
    }


_MCP_TOOLS_CACHE: list[BaseTool] | None = None


def get_mongodb_mcp_tools() -> list[BaseTool]:
    """Return MCP-backed LangChain tools, or an empty list if MCP is unavailable.

    Wraps the cold-cache load in a threading.Lock so concurrent agent threads
    don't both spawn `npx mongodb-mcp-server`. Logs entry/exit + elapsed time
    so a hang here is visible in the timeline.
    """
    global _MCP_TOOLS_CACHE
    if _MCP_TOOLS_CACHE is not None:
        return _MCP_TOOLS_CACHE

    tid = threading.get_ident()
    log.info("get_mongodb_mcp_tools ENTER  tid=%s (cold cache, acquiring lock)", tid)
    t0 = time.time()
    with _MCP_LOAD_LOCK:
        if _MCP_TOOLS_CACHE is not None:
            log.info("get_mongodb_mcp_tools tid=%s — another thread populated cache, "
                     "returning cached (%.2fs lock-wait)", tid, time.time() - t0)
            return _MCP_TOOLS_CACHE

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except Exception as exc:  # pragma: no cover
            log.warning("langchain_mcp_adapters not installed: %s", exc)
            _MCP_TOOLS_CACHE = []
            return _MCP_TOOLS_CACHE

        try:
            log.info("get_mongodb_mcp_tools tid=%s — spawning MCP client + npx subprocess", tid)
            t1 = time.time()
            client = MultiServerMCPClient(_build_server_config())
            tools = asyncio.run(client.get_tools())
            log.info("get_mongodb_mcp_tools tid=%s — MCP client.get_tools() returned %d tools "
                     "in %.2fs (asyncio.run total %.2fs)",
                     tid, len(tools), time.time() - t1, time.time() - t0)
            _MCP_TOOLS_CACHE = tools
            return _MCP_TOOLS_CACHE
        except Exception as exc:  # pragma: no cover
            log.warning("MongoDB MCP server unavailable (%s) — continuing without it.", exc)
            _MCP_TOOLS_CACHE = []
            return _MCP_TOOLS_CACHE

