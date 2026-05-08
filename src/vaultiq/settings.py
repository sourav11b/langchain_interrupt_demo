"""VaultIQ settings loader.

Reads `config/vaultiq.properties` (INI with ${ENV_VAR:default} interpolation)
and exposes a frozen Settings object consumable across the project.
"""
from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROPS_PATH = _REPO_ROOT / "config" / "vaultiq.properties"
_ENV_PATH = _REPO_ROOT / ".env"


def _interp(value: str) -> str:
    def repl(m: re.Match[str]) -> str:
        var, default = m.group(1), m.group(2) or ""
        return os.getenv(var, default)
    return _ENV_RE.sub(repl, value).strip()


def _coerce(v: str) -> Any:
    low = v.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _load_properties(path: Path) -> dict[str, dict[str, Any]]:
    cp = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=("#", ";"),
    )
    cp.optionxform = str  # preserve key case
    cp.read(path, encoding="utf-8")
    out: dict[str, dict[str, Any]] = {}
    for section in cp.sections():
        out[section] = {k: _coerce(_interp(v)) for k, v in cp.items(section)}
    return out


@dataclass(frozen=True)
class Settings:
    raw: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ── helpers ──────────────────────────────────────────────────────────────
    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.raw.get(section, {}).get(key, default)

    # ── shortcuts ────────────────────────────────────────────────────────────
    @property
    def mongo_uri(self) -> str:
        return self.get("mongodb", "uri")

    @property
    def mongo_db(self) -> str:
        return self.get("mongodb", "database", "vaultiq")

    @property
    def collections(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for sec, data in self.raw.items():
            if sec.startswith("mongodb.collections."):
                merged.update(data)
        return merged

    def coll(self, logical_name: str) -> str:
        return self.collections[logical_name]

    @property
    def index_names(self) -> dict[str, str]:
        return self.section("mongodb.indexes")

    @property
    def llm(self) -> dict[str, Any]:
        return self.section("llm")

    @property
    def embeddings(self) -> dict[str, Any]:
        return self.section("embeddings")

    @property
    def observability(self) -> dict[str, Any]:
        return self.section("observability")

    @property
    def mcp_mongodb(self) -> dict[str, Any]:
        return self.section("mcp.mongodb")

    @property
    def agents(self) -> dict[str, dict[str, Any]]:
        return {k.split(".", 1)[1]: v for k, v in self.raw.items() if k.startswith("agents.")}

    @property
    def stream(self) -> dict[str, Any]:
        return self.section("stream")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)

    # Activate LangSmith from .env so any langchain import below is traced.
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true" and os.getenv("LANGCHAIN_API_KEY"):
        os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "vaultiq-fsi"))

    raw = _load_properties(_PROPS_PATH)
    return Settings(raw=raw)


settings = get_settings()
