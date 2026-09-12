"""WHOOP API v2 client: OAuth 2.0 token handling + read endpoints.

Endpoints and scopes verified against https://developer.whoop.com/api
"""

import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from storage import read_json, write_json

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer"

# 'offline' is what makes WHOOP return a refresh token. Without it the
# connector dies an hour after you set it up.
SCOPES = [
    "read:recovery",
    "read:cycles",
    "read:sleep",
    "read:workout",
    "read:profile",
    "read:body_measurement",
    "offline",
]

TOKEN_FILE = "whoop_tokens.json"


class WhoopNotAuthorized(Exception):
    """Raised when no usable WHOOP token exists yet."""


def _creds():
    client_id = os.getenv("WHOOP_CLIENT_ID")
    client_secret = os.getenv("WHOOP_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise WhoopNotAuthorized(
            "WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET are not set in the environment."
        )
    return client_id, client_secret


def authorize_url(redirect_uri: str, state: str) -> str:
    client_id, _ = _creds()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _store(payload: dict) -> None:
    payload = dict(payload)
    payload["expires_at"] = time.time() + int(payload.get("expires_in", 3600)) - 120
    write_json(TOKEN_FILE, payload)


def exchange_code(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = _creds()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _store(tokens)
    return tokens


def _refresh(refresh_token: str) -> dict:
    client_id, client_secret = _creds()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            # WHOOP requires 'offline' again on refresh to keep issuing
            # a rotating refresh token.
            "scope": "offline",
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _store(tokens)
    return tokens


def access_token() -> str:
    tokens = read_json(TOKEN_FILE)
    if not tokens:
        raise WhoopNotAuthorized(
            "WHOOP has not been authorized yet. Visit /auth/whoop/start on this server."
        )
    if time.time() < tokens.get("expires_at", 0):
        return tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise WhoopNotAuthorized(
            "Stored WHOOP token has no refresh_token - re-run /auth/whoop/start "
            "and make sure the 'offline' scope is enabled on the app."
        )
    return _refresh(refresh_token)["access_token"]


def is_authorized() -> bool:
    try:
        access_token()
        return True
    except Exception:
        return False


def _get(path: str, params: dict | None = None) -> dict:
    resp = httpx.get(
        f"{API_BASE}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {access_token()}"},
        params=params or {},
        timeout=30,
    )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return resp.json()


def _window(days: int) -> dict:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return {
        "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "limit": 25,
    }


# --- Read endpoints -------------------------------------------------------

def profile() -> dict:
    return _get("v2/user/profile/basic")


def recovery(days: int = 7) -> list:
    return _get("v2/recovery", _window(days)).get("records", [])


def sleep(days: int = 7) -> list:
    return _get("v2/activity/sleep", _window(days)).get("records", [])


def workouts(days: int = 7) -> list:
    return _get("v2/activity/workout", _window(days)).get("records", [])


def cycles(days: int = 7) -> list:
    return _get("v2/cycle", _window(days)).get("records", [])
