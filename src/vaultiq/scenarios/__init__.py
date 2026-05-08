"""Library of fraud scenarios used by the live UI to inject test events."""
from .injector import (
    SCENARIOS,
    Scenario,
    build_scenario_transaction,
    pick_random_customer,
)

__all__ = ["SCENARIOS", "Scenario", "build_scenario_transaction", "pick_random_customer"]
