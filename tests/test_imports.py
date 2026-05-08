"""Smoke test — every public module must import cleanly.

Doesn't talk to MongoDB / OpenAI / Voyage; only validates the static graph.
"""
from __future__ import annotations


def test_settings_loads():
    from src.vaultiq.settings import settings
    assert settings.mongo_db
    assert settings.coll("transactions")
    assert "fraud_sentinel" in settings.agents


def test_modules_import():
    import importlib

    for mod in [
        "src.vaultiq.db.collections",
        "src.vaultiq.db.mongo_client",
        "src.vaultiq.db.indices",
        "src.vaultiq.llm.factory",
        "src.vaultiq.llm.cache",
        "src.vaultiq.memory.checkpointer",
        "src.vaultiq.memory.chat_history",
        "src.vaultiq.memory.semantic_memory",
        "src.vaultiq.retrievers.fraud_kb",
        "src.vaultiq.retrievers.case_notes",
        "src.vaultiq.tools",
        "src.vaultiq.tools.mcp_tools",
        "src.vaultiq.scenarios.injector",
        "src.vaultiq.agents.state",
        "src.vaultiq.agents.fraud_agent",
        "src.vaultiq.agents.kyc_agent",
        "src.vaultiq.agents.case_agent",
        "src.vaultiq.agents.graph",
        "src.vaultiq.ui.stream_runner",
    ]:
        importlib.import_module(mod)


def test_scenarios_registered():
    from src.vaultiq.scenarios.injector import SCENARIOS
    ids = {s.id for s in SCENARIOS}
    assert {"normal", "geo_velocity", "ato_sim_swap", "card_testing", "low_risk"} <= ids
