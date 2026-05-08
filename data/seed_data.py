"""Generate mock VaultIQ data and load it into MongoDB Atlas.

Creates 1k customers, accounts, cards, devices, merchants, edges, geo points,
30 days of historical transactions, and the fraud KB vector corpus.

Usage:
    python -m data.seed_data --customers 1000 --history-days 30
"""
from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from faker import Faker

from src.vaultiq.db.collections import C
from src.vaultiq.db.indices import ensure_all_indexes
from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.logging_setup import configure_logging

from .fraud_kb_corpus import KB_DOCS

log = logging.getLogger(__name__)

MERCHANT_CATEGORIES = [
    ("grocery", "5411"),
    ("fuel", "5541"),
    ("restaurant", "5812"),
    ("electronics", "5732"),
    ("travel", "4511"),
    ("gambling", "7995"),
    ("crypto", "6051"),
    ("wire", "4829"),
]

CITIES = [  # name, lon, lat, country
    ("New York", -74.006, 40.7128, "US"),
    ("San Francisco", -122.419, 37.774, "US"),
    ("Chicago", -87.629, 41.878, "US"),
    ("Miami", -80.191, 25.761, "US"),
    ("London", -0.127, 51.507, "GB"),
    ("Singapore", 103.819, 1.352, "SG"),
    ("Mumbai", 72.877, 19.075, "IN"),
    ("Sao Paulo", -46.633, -23.55, "BR"),
]


# ── helpers ──────────────────────────────────────────────────────────────────
def _wipe(db) -> None:
    for c in [
        C.customers, C.accounts, C.cards, C.devices, C.merchants,
        C.home_locations, C.merchant_geo, C.transaction_geo,
        C.relationships, C.fraud_kb, C.case_notes, C.cases, C.case_events,
    ]:
        db[c].delete_many({})


def _gen_customers(fake: Faker, n: int) -> list[dict]:
    out = []
    for i in range(n):
        city = random.choice(CITIES)
        out.append({
            "customer_id": f"CUST{i:06d}",
            "name": fake.name(),
            "email": fake.unique.email(),
            "phone": fake.phone_number(),
            "country": city[3],
            "home_city": city[0],
            "kyc_level": random.choice(["basic", "enhanced", "premium"]),
            "risk_score": round(random.uniform(0, 0.4), 3),
            "created_at": fake.date_time_between(start_date="-3y", tzinfo=timezone.utc),
            "_geo": {"lon": city[1], "lat": city[2]},
        })
    return out


def _gen_accounts(customers: list[dict]) -> list[dict]:
    out = []
    for i, c in enumerate(customers):
        out.append({
            "account_id": f"ACC{i:07d}",
            "customer_id": c["customer_id"],
            "currency": "USD",
            "balance": round(random.uniform(500, 50_000), 2),
            "opened_at": c["created_at"],
        })
    return out


def _gen_cards(customers: list[dict]) -> list[dict]:
    out = []
    for i, c in enumerate(customers):
        out.append({
            "card_id": f"CARD{i:07d}",
            "customer_id": c["customer_id"],
            "bin": random.choice(["411111", "401288", "542418", "601100"]),
            "last4": f"{random.randint(0, 9999):04d}",
            "type": random.choice(["debit", "credit"]),
            "status": "active",
        })
    return out


def _gen_devices(fake: Faker, customers: list[dict]) -> list[dict]:
    out = []
    for c in customers:
        for j in range(random.randint(1, 3)):
            out.append({
                "device_id": f"DEV-{c['customer_id']}-{j}",
                "customer_id": c["customer_id"],
                "fingerprint": fake.sha1(),
                "platform": random.choice(["ios", "android", "web"]),
                "first_seen": fake.date_time_between(start_date="-2y", tzinfo=timezone.utc),
                "trusted": j == 0,
            })
    return out


def _gen_merchants(fake: Faker, n: int = 200) -> list[dict]:
    out = []
    for i in range(n):
        cat, mcc = random.choice(MERCHANT_CATEGORIES)
        city = random.choice(CITIES)
        out.append({
            "merchant_id": f"MERCH{i:05d}",
            "name": fake.company(),
            "category": cat,
            "mcc": mcc,
            "country": city[3],
            "_geo": {"lon": city[1] + random.uniform(-0.2, 0.2), "lat": city[2] + random.uniform(-0.2, 0.2)},
            "risk": round(random.uniform(0, 0.6), 3),
        })
    return out


def _gen_history(customers: list[dict], cards: list[dict], merchants: list[dict],
                 days: int) -> tuple[list[dict], list[dict]]:
    """Return (transactions, transaction_geo) — `days` of mostly-legit history."""
    cards_by_cust = {c["customer_id"]: c for c in cards}
    txs: list[dict] = []
    geos: list[dict] = []
    now = datetime.now(tz=timezone.utc)
    for c in customers:
        card = cards_by_cust[c["customer_id"]]
        for _ in range(random.randint(15, 45)):
            m = random.choice(merchants)
            ts = now - timedelta(days=random.randint(0, days), seconds=random.randint(0, 86_400))
            amt = round(abs(random.gauss(60, 80)), 2) + 1
            tx = {
                "ts": ts,
                "tx_id": f"TX{random.randint(10**11, 10**12 - 1)}",
                "customer_id": c["customer_id"],
                "card_id": card["card_id"],
                "merchant_id": m["merchant_id"],
                "merchant_category": m["category"],
                "mcc": m["mcc"],
                "amount": amt,
                "currency": "USD",
                "country": m["country"],
                "device_id": f"DEV-{c['customer_id']}-0",
                "channel": random.choice(["pos", "ecom", "atm"]),
                "status": "approved",
                "is_fraud": False,
            }
            txs.append(tx)
            geos.append({
                "ts": ts,
                "tx_id": tx["tx_id"],
                "customer_id": c["customer_id"],
                "location": {"type": "Point", "coordinates": [m["_geo"]["lon"], m["_geo"]["lat"]]},
            })
    return txs, geos


def _gen_edges(customers: list[dict], cards: list[dict], devices: list[dict],
               merchants: list[dict]) -> list[dict]:
    edges: list[dict] = []
    for crd in cards:
        edges.append({"from": crd["customer_id"], "to": crd["card_id"], "type": "OWNS_CARD", "weight": 1})
    for d in devices:
        edges.append({"from": d["customer_id"], "to": d["device_id"], "type": "USES_DEVICE",
                      "weight": 1.0 if d["trusted"] else 0.4})
    for c in customers:
        for m in random.sample(merchants, k=min(5, len(merchants))):
            edges.append({"from": c["customer_id"], "to": m["merchant_id"],
                          "type": "TRANSACTED_WITH", "weight": round(random.uniform(0.1, 1.0), 2)})
    return edges


def _embed_kb() -> list[dict]:
    """Return KB docs unchanged — Atlas AutoEmbeddings vectorises the `text`
    field server-side at index time, so no client-side embedding is needed."""
    return [dict(d) for d in KB_DOCS]


# ── public ───────────────────────────────────────────────────────────────────
def seed(customers: int = 1000, history_days: int = 30, wipe: bool = True, seed_val: int = 42) -> None:
    configure_logging()
    random.seed(seed_val)
    fake = Faker()
    Faker.seed(seed_val)

    log.info("Ensuring indexes …")
    ensure_all_indexes()

    db = get_db()
    if wipe:
        log.info("Wiping target collections …")
        _wipe(db)

    log.info("Generating %s customers …", customers)
    custs = _gen_customers(fake, customers)
    accts = _gen_accounts(custs)
    cards = _gen_cards(custs)
    devs = _gen_devices(fake, custs)
    merchs = _gen_merchants(fake)

    db[C.customers].insert_many(custs)
    db[C.accounts].insert_many(accts)
    db[C.cards].insert_many(cards)
    db[C.devices].insert_many(devs)
    db[C.merchants].insert_many(merchs)

    log.info("Geo points …")
    db[C.home_locations].insert_many([
        {"customer_id": c["customer_id"],
         "location": {"type": "Point", "coordinates": [c["_geo"]["lon"], c["_geo"]["lat"]]}}
        for c in custs
    ])
    db[C.merchant_geo].insert_many([
        {"merchant_id": m["merchant_id"],
         "category": m["category"],
         "location": {"type": "Point", "coordinates": [m["_geo"]["lon"], m["_geo"]["lat"]]}}
        for m in merchs
    ])

    log.info("Graph edges …")
    db[C.relationships].insert_many(_gen_edges(custs, cards, devs, merchs))

    log.info("Generating %d days of historical transactions …", history_days)
    txs, geos = _gen_history(custs, cards, merchs, history_days)
    if txs:
        db[C.transactions].insert_many(txs)
        db[C.transaction_geo].insert_many(geos)
    log.info("Inserted %d transactions", len(txs))

    log.info("Embedding + inserting fraud KB …")
    db[C.fraud_kb].insert_many(_embed_kb())
    log.info("Inserted %d KB docs", len(KB_DOCS))

    log.info("✅ Seed complete.")


def _cli() -> None:
    p = argparse.ArgumentParser(description="Seed VaultIQ demo data into MongoDB Atlas.")
    p.add_argument("--customers", type=int, default=1000)
    p.add_argument("--history-days", type=int, default=30)
    p.add_argument("--no-wipe", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    seed(customers=args.customers, history_days=args.history_days,
         wipe=not args.no_wipe, seed_val=args.seed)


if __name__ == "__main__":
    _cli()
