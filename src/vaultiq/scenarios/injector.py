"""Fraud scenario library.

Each Scenario builds a single synthetic transaction document that exercises a
specific risk pattern (geo-velocity, ATO, mule, card-testing, low-risk normal,
etc.). The Streamlit UI calls `build_scenario_transaction(scenario_id)` to
inject the transaction into the live stream.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..db.collections import C
from ..db.mongo_client import get_db


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    description: str
    risk_hint: float
    builder: Callable[[dict, dict, dict], dict]


# ── helpers ──────────────────────────────────────────────────────────────────
def pick_random_customer() -> dict:
    db = get_db()
    return next(iter(db[C.customers].aggregate([{"$sample": {"size": 1}}])))


def _pick_card(customer_id: str) -> dict:
    db = get_db()
    return db[C.cards].find_one({"customer_id": customer_id}) or {}


def _pick_merchant(category: str | None = None) -> dict:
    db = get_db()
    q = {"category": category} if category else {}
    docs = list(db[C.merchants].aggregate([{"$match": q}, {"$sample": {"size": 1}}]))
    return docs[0] if docs else {}


def _base_tx(customer: dict, card: dict, merchant: dict, **overrides) -> dict:
    tx = {
        "ts": datetime.now(tz=timezone.utc),
        "tx_id": f"TX{uuid.uuid4().hex[:12].upper()}",
        "customer_id": customer["customer_id"],
        "card_id": card.get("card_id"),
        "merchant_id": merchant.get("merchant_id"),
        "merchant_category": merchant.get("category"),
        "mcc": merchant.get("mcc"),
        "amount": 50.0,
        "currency": "USD",
        "country": merchant.get("country", customer.get("country")),
        "device_id": f"DEV-{customer['customer_id']}-0",
        "channel": "ecom",
        "status": "pending",
        "is_fraud": False,
        "_injected": True,
    }
    tx.update(overrides)
    return tx


# ── scenario builders ───────────────────────────────────────────────────────
def _normal(c, card, merch):
    return _base_tx(c, card, merch, amount=round(random.uniform(8, 80), 2),
                    channel=random.choice(["pos", "ecom"]), status="pending")


def _geo_velocity(c, card, _merch):
    far = _pick_merchant()  # likely different country
    return _base_tx(c, card, far, amount=round(random.uniform(120, 400), 2),
                    channel="pos", country=far.get("country"),
                    note="Card-present in distant geography vs. last tx")


def _ato_sim_swap(c, card, _merch):
    wire = _pick_merchant("wire")
    return _base_tx(c, card, wire, amount=round(random.uniform(3500, 9500), 2),
                    channel="ecom", device_id=f"DEV-NEW-{uuid.uuid4().hex[:6]}",
                    note="New device + outbound wire — possible ATO via SIM swap")


def _card_testing(c, card, _merch):
    ecom = _pick_merchant("electronics")
    return _base_tx(c, card, ecom, amount=round(random.uniform(0.5, 4.99), 2),
                    channel="ecom", note="Small probe charge — BIN attack pattern")


def _mule_funnel(c, card, _merch):
    crypto = _pick_merchant("crypto")
    return _base_tx(c, card, crypto, amount=round(random.uniform(2500, 7500), 2),
                    channel="ecom", note="Crypto on-ramp after burst of inbound P2P")


def _gambling_burst(c, card, _merch):
    g = _pick_merchant("gambling")
    return _base_tx(c, card, g, amount=round(random.uniform(800, 2500), 2),
                    channel="ecom", note="High-risk MCC, first-time use")


def _trusted_low_risk(c, card, _merch):
    grocery = _pick_merchant("grocery")
    return _base_tx(c, card, grocery, amount=round(random.uniform(15, 75), 2),
                    channel="pos", note="Repeat merchant, trusted device, home country")


SCENARIOS: list[Scenario] = [
    Scenario("normal",          "Normal traffic",            "Routine purchase, low risk", 0.10, _normal),
    Scenario("geo_velocity",    "Geo-velocity impossible",   "Card present far from last location", 0.85, _geo_velocity),
    Scenario("ato_sim_swap",    "Account takeover (SIM swap)","New device + large outbound wire", 0.93, _ato_sim_swap),
    Scenario("card_testing",    "Card-testing burst",         "Tiny CNP probe charge", 0.70, _card_testing),
    Scenario("mule_funnel",     "Mule / crypto funnel",       "Layering into crypto on-ramp", 0.80, _mule_funnel),
    Scenario("gambling_burst",  "High-risk MCC",              "Gambling, first-time, high amount", 0.65, _gambling_burst),
    Scenario("low_risk",        "Trusted low-risk",           "Repeat merchant + trusted device", 0.05, _trusted_low_risk),
]


def build_scenario_transaction(scenario_id: str, customer: dict | None = None) -> dict:
    s = next((x for x in SCENARIOS if x.id == scenario_id), None)
    if s is None:
        raise ValueError(f"Unknown scenario {scenario_id}")
    cust = customer or pick_random_customer()
    card = _pick_card(cust["customer_id"])
    merch = _pick_merchant()
    tx = s.builder(cust, card, merch)
    tx["scenario_id"] = s.id
    tx["scenario_label"] = s.label
    tx["risk_hint"] = s.risk_hint
    return tx
