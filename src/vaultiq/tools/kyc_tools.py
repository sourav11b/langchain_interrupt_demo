"""Customer Trust agent tools — identity verification + (mock) OTP."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db


def _otp_for(customer_id: str) -> str:
    h = hashlib.sha256(f"vaultiq:{customer_id}".encode()).hexdigest()
    return str(int(h[:6], 16) % 1_000_000).zfill(6)


@tool
def verify_identity_factors(customer_id: str, factors: dict) -> dict:
    """Verify supplied identity factors (email/phone/government_id_last4)
    against the structured customer record. Returns a per-factor match map."""
    cust = get_db()[C.customers].find_one({"customer_id": customer_id})
    if not cust:
        return {"matched": 0, "details": {"customer_found": False}}
    details: dict[str, bool] = {}
    if "email" in factors:
        details["email"] = factors["email"].lower() == (cust.get("email") or "").lower()
    if "phone" in factors:
        details["phone"] = "".join(filter(str.isdigit, factors["phone"]))[-4:] == \
                          "".join(filter(str.isdigit, cust.get("phone", "")))[-4:]
    if "country" in factors:
        details["country"] = factors["country"] == cust.get("country")
    matched = sum(1 for v in details.values() if v)
    return {"matched": matched, "kyc_level": cust.get("kyc_level"), "details": details}


@tool
def request_otp(customer_id: str) -> dict:
    """(Mock) Send an OTP to the customer's registered phone. The OTP is
    deterministic per customer_id so a demo operator can read it back."""
    code = _otp_for(customer_id)
    get_db()[C.case_events].insert_one({
        "ts": datetime.now(tz=timezone.utc),
        "case_id": None,
        "customer_id": customer_id,
        "type": "otp_sent",
        "channel": "sms",
        "code_hash": hashlib.sha256(code.encode()).hexdigest()[:12],
    })
    return {"sent": True, "customer_id": customer_id, "demo_code": code}


@tool
def confirm_otp(customer_id: str, code: str) -> dict:
    """Validate the OTP supplied by the customer."""
    expected = _otp_for(customer_id)
    return {"valid": code == expected, "customer_id": customer_id}


@tool
def flag_kyc_step_up(customer_id: str, reason: str) -> dict:
    """Persist a KYC step-up flag on the customer profile."""
    get_db()[C.customers].update_one(
        {"customer_id": customer_id},
        {"$set": {"kyc_step_up": True, "kyc_step_up_reason": reason,
                  "kyc_step_up_at": datetime.now(tz=timezone.utc)}},
    )
    return {"customer_id": customer_id, "step_up": True, "reason": reason}
