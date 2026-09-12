"""Garmin Connect wrapper.

Garmin has no personal API, so this uses the community `garminconnect`
library. The important design decision: this server NEVER performs a fresh
Garmin login. Logging in from a datacenter IP is what triggers Cloudflare
blocks, MFA prompts and 429s. Instead you log in ONCE on your own laptop
(local_setup.py), and paste the resulting token blob in as an environment
variable. The server only ever *refreshes* those tokens.
"""

import base64
import json
import os
from datetime import date, timedelta
from pathlib import Path

from storage import data_dir

TOKEN_DIRNAME = "garmin"
_client = None


class GarminUnavailable(Exception):
    """Raised when Garmin data cannot be reached. Never fatal - the coach
    degrades to WHOOP-only for the day."""


def token_dir() -> Path:
    path = data_dir() / TOKEN_DIRNAME
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def seed_tokens_from_env() -> bool:
    """Write GARMIN_TOKENS_B64 to disk on first boot. Returns True if tokens exist."""
    target = token_dir() / "garmin_tokens.json"
    if target.exists():
        return True
    blob = os.getenv("GARMIN_TOKENS_B64")
    if not blob:
        return False
    try:
        decoded = base64.b64decode(blob)
        json.loads(decoded)  # validate before writing
    except Exception as exc:  # noqa: BLE001
        raise GarminUnavailable(f"GARMIN_TOKENS_B64 is not valid base64 JSON: {exc}")
    target.write_bytes(decoded)
    os.chmod(target, 0o600)
    return True


def client():
    global _client
    if _client is not None:
        return _client
    try:
        from garminconnect import Garmin
    except ImportError as exc:
        raise GarminUnavailable(f"garminconnect is not installed: {exc}")

    if not seed_tokens_from_env():
        raise GarminUnavailable(
            "No Garmin tokens found. Run local_setup.py on your laptop and set "
            "GARMIN_TOKENS_B64 in the environment."
        )
    try:
        api = Garmin()
        api.login(str(token_dir()))
    except Exception as exc:  # noqa: BLE001
        raise GarminUnavailable(f"Garmin token login failed: {exc}")
    _client = api
    return _client


def reset():
    """Drop the cached client so the next call re-reads tokens from disk."""
    global _client
    _client = None


def is_authorized() -> bool:
    try:
        client()
        return True
    except Exception:
        return False


def _try(label: str, fn, *args):
    """Call a garminconnect method, returning None instead of raising.

    Garmin's unofficial endpoints change without notice; one dead endpoint
    must never take down the whole snapshot.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{label}: {type(exc).__name__}: {exc}"}


def daily(day: str | None = None) -> dict:
    """Everything useful Garmin knows about one day."""
    api = client()
    day = day or date.today().isoformat()
    out = {"date": day}

    out["stats"] = _try("stats", api.get_stats, day)
    out["sleep"] = _try("sleep", api.get_sleep_data, day)
    out["hrv"] = _try("hrv", api.get_hrv_data, day)
    out["training_readiness"] = _try("training_readiness", api.get_training_readiness, day)
    out["training_status"] = _try("training_status", api.get_training_status, day)
    out["rhr"] = _try("rhr", api.get_rhr_day, day)
    out["body_battery"] = _try("body_battery", api.get_body_battery, day, day)
    out["max_metrics"] = _try("max_metrics", api.get_max_metrics, day)
    return out


def activities(limit: int = 10) -> list:
    api = client()
    result = _try("activities", api.get_activities, 0, limit)
    return result if isinstance(result, list) else [result]


def summary_series(days: int = 14) -> list:
    """Light daily summaries for trend maths - one call per day, so keep it small."""
    api = client()
    out = []
    for offset in range(days):
        day = (date.today() - timedelta(days=offset)).isoformat()
        out.append({"date": day, "stats": _try("stats", api.get_stats, day)})
    return out
