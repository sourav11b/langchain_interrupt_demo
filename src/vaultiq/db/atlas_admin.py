"""MongoDB Atlas Admin API client — paused-cluster autoresume on app startup.

Uses the Service Account OAuth flow (`mdb_sa_id_…` / `mdb_sa_sk_…` credentials
from `.env`). Public surface:

    get_cluster_status() -> dict   # {state, paused, ready, raw}
    resume_cluster()     -> None
    ensure_cluster_running(callback=None) -> dict
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests
from requests.auth import HTTPBasicAuth

from ..settings import settings

log = logging.getLogger(__name__)

ATLAS_BASE = "https://cloud.mongodb.com"
API_VERSION_ACCEPT = "application/vnd.atlas.2024-11-13+json"


class AtlasAdminError(RuntimeError):
    """Raised on any non-2xx response from the Atlas Admin API."""


# ── credentials ──────────────────────────────────────────────────────────────
def _cfg() -> dict[str, str]:
    s = settings.section("mongodb")
    missing = [k for k in
               ("atlas_client_id", "atlas_client_secret", "atlas_project_id", "atlas_cluster_name")
               if not s.get(k)]
    if missing:
        raise AtlasAdminError(f"Missing Atlas Admin config: {missing}")
    return {
        "client_id":    s["atlas_client_id"],
        "client_secret": s["atlas_client_secret"],
        "project_id":   s["atlas_project_id"],
        "cluster_name": s["atlas_cluster_name"],
    }


# ── OAuth token (cached until a few seconds before expiry) ───────────────────
_TOKEN: dict[str, Any] = {"value": None, "exp": 0.0}


def _get_token() -> str:
    now = time.time()
    if _TOKEN["value"] and _TOKEN["exp"] > now + 30:
        return _TOKEN["value"]
    cfg = _cfg()
    resp = requests.post(
        f"{ATLAS_BASE}/api/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=HTTPBasicAuth(cfg["client_id"], cfg["client_secret"]),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise AtlasAdminError(f"oauth/token {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    _TOKEN["value"] = body["access_token"]
    _TOKEN["exp"] = now + int(body.get("expires_in", 1800))
    log.debug("Atlas OAuth token refreshed (ttl=%ss)", body.get("expires_in"))
    return _TOKEN["value"]


def _headers(write: bool = False) -> dict[str, str]:
    h = {"Authorization": f"Bearer {_get_token()}", "Accept": API_VERSION_ACCEPT}
    if write:
        h["Content-Type"] = "application/json"
    return h


# ── public API ───────────────────────────────────────────────────────────────
def get_cluster_status() -> dict[str, Any]:
    cfg = _cfg()
    url = f"{ATLAS_BASE}/api/atlas/v2/groups/{cfg['project_id']}/clusters/{cfg['cluster_name']}"
    r = requests.get(url, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise AtlasAdminError(f"GET cluster {r.status_code}: {r.text[:200]}")
    body = r.json()
    state = body.get("stateName", "UNKNOWN")
    paused = bool(body.get("paused", False))
    return {
        "cluster": cfg["cluster_name"],
        "state": state,
        "paused": paused,
        "ready": (state == "IDLE" and not paused),
        "mongo_version": body.get("mongoDBVersion"),
        "instance_size": (body.get("replicationSpecs", [{}])[0]
                          .get("regionConfigs", [{}])[0]
                          .get("electableSpecs", {})
                          .get("instanceSize")),
    }


def resume_cluster() -> None:
    """Idempotent: PATCH `paused=false`. Atlas no-ops if already running."""
    cfg = _cfg()
    url = f"{ATLAS_BASE}/api/atlas/v2/groups/{cfg['project_id']}/clusters/{cfg['cluster_name']}"
    r = requests.patch(url, headers=_headers(write=True), json={"paused": False}, timeout=30)
    if r.status_code >= 400:
        raise AtlasAdminError(f"PATCH resume {r.status_code}: {r.text[:200]}")
    log.info("Resume request accepted for cluster %s", cfg["cluster_name"])


def ensure_cluster_running(
    callback: Callable[[dict[str, Any]], None] | None = None,
    *,
    max_wait_s: int = 900,
    poll_s: int = 10,
) -> dict[str, Any]:
    """Block until the cluster is `IDLE && !paused`, resuming if needed.

    `callback(status)` is invoked on every poll so a UI can render progress.
    """
    status = get_cluster_status()
    log.info("Initial cluster status: %s", status)
    if callback:
        callback(status)
    if status["ready"]:
        return status
    if status["paused"]:
        log.info("Cluster %s is PAUSED — resuming…", status["cluster"])
        resume_cluster()
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        time.sleep(poll_s)
        try:
            status = get_cluster_status()
        except AtlasAdminError as exc:
            log.warning("poll failed: %s", exc)
            continue
        if callback:
            callback(status)
        log.info("Cluster %s state=%s paused=%s",
                 status["cluster"], status["state"], status["paused"])
        if status["ready"]:
            return status
    raise AtlasAdminError(
        f"Cluster {status['cluster']} not ready after {max_wait_s}s "
        f"(last state={status['state']}, paused={status['paused']})"
    )
