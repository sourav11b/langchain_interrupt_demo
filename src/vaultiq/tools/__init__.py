"""Agent tools (LangChain @tool functions) backed by MongoDB PolyStorage."""
from .fraud_tools import (
    score_transaction,
    get_recent_transactions,
    get_customer_profile,
    fraud_kb_lookup,
)
from .geo_tools import distance_from_home_km, last_tx_location, geo_velocity_anomaly
from .graph_tools import device_owner_graph, customer_merchant_path
from .timeseries_tools import customer_velocity, mcc_burst
from .kyc_tools import (
    verify_identity_factors,
    request_otp,
    confirm_otp,
    flag_kyc_step_up,
)
from .case_tools import (
    open_case,
    update_case,
    log_case_event,
    list_open_cases,
    add_case_note,
)

__all__ = [
    "score_transaction", "get_recent_transactions", "get_customer_profile", "fraud_kb_lookup",
    "distance_from_home_km", "last_tx_location", "geo_velocity_anomaly",
    "device_owner_graph", "customer_merchant_path",
    "customer_velocity", "mcc_burst",
    "verify_identity_factors", "request_otp", "confirm_otp", "flag_kyc_step_up",
    "open_case", "update_case", "log_case_event", "list_open_cases", "add_case_note",
]
