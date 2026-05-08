"""Run a single injected fraud scenario through the 3-agent flow.

    python -m scripts.run_one --scenario ato_sim_swap
"""
from __future__ import annotations

import argparse
import json

from src.vaultiq.agents.graph import run_once
from src.vaultiq.logging_setup import configure_logging
from src.vaultiq.scenarios.injector import SCENARIOS, build_scenario_transaction


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="ato_sim_swap",
                   choices=[s.id for s in SCENARIOS])
    args = p.parse_args()

    tx = build_scenario_transaction(args.scenario)
    print("INJECTED TX:")
    print(json.dumps(tx, default=str, indent=2))
    result = run_once(tx)
    print("\n=== RESULT ===")
    for k in ("fraud", "kyc", "case"):
        if k in result:
            print(f"\n[{k}]")
            print(json.dumps(result[k], default=str, indent=2))
    print("\n=== TRACE ===")
    for step in result.get("trace", []):
        print(json.dumps(step, default=str))


if __name__ == "__main__":
    main()
