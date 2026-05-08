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
from functools import lru_cache
from typing import Any

from langchain_core.tools import BaseTool

from ..settings import settings

log = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def get_mongodb_mcp_tools() -> list[BaseTool]:
    """Return MCP-backed LangChain tools, or an empty list if MCP is unavailable."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except Exception as exc:  # pragma: no cover
        log.warning("langchain_mcp_adapters not installed: %s", exc)
        return []

    try:
        client = MultiServerMCPClient(_build_server_config())
        tools = asyncio.run(client.get_tools())
        log.info("Loaded %d MongoDB MCP tools", len(tools))
        return tools
    except Exception as exc:  # pragma: no cover
        log.warning("MongoDB MCP server unavailable (%s) — continuing without it.", exc)
        return []
