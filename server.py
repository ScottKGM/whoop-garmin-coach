"""Remote MCP server exposing WHOOP + Garmin data to Claude.

Runs over streamable HTTP so Claude can reach it from any device, including
the phone app. Everything is served under an unguessable secret path.
"""

import os
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

import garmin
import storage
import whoop

MCP_SECRET = os.getenv("MCP_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TZ", "America/Chicago"))
REDIRECT_PATH = "/auth/whoop/callback"

if not MCP_SECRET or len(MCP_SECRET) < 16:
    raise SystemExit(
        "MCP_SECRET must be set to a random string of at least 16 characters."
    )

MCP_PATH = f"/mcp/{MCP_SECRET}"

mcp = FastMCP("Whoop + Garmin Coach")


# --- helpers --------------------------------------------------------------

def _ms_to_hours(value):
    return round(value / 3_600_000, 2) if isinstance(value, (int, float)) else None


def _whoop_summary() -> dict:
    """Flatten the numbers a coach actually reasons about."""
    out = {}
    errors = []

    try:
        records = whoop.recovery(days=2)
        if records:
            score = records[0].get("score") or {}
            out["recovery_score"] = score.get("recovery_score")
            out["hrv_ms"] = score.get("hrv_rmssd_milli")
            out["resting_hr"] = score.get("resting_heart_rate")
            out["spo2"] = score.get("spo2_percentage")
            out["skin_temp_c"] = score.get("skin_temp_celsius")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"recovery: {exc}")

    try:
        records = whoop.sleep(days=2)
        if records:
            score = records[0].get("score") or {}
            stages = score.get("stage_summary") or {}
            out["sleep_performance_pct"] = score.get("sleep_performance_percentage")
            out["sleep_efficiency_pct"] = score.get("sleep_efficiency_percentage")
            out["sleep_consistency_pct"] = score.get("sleep_consistency_percentage")
            out["respiratory_rate"] = score.get("respiratory_rate")
            in_bed = stages.get("total_in_bed_time_milli")
            awake = stages.get("total_awake_time_milli") or 0
            if isinstance(in_bed, (int, float)):
                out["sleep_hours"] = _ms_to_hours(in_bed - awake)
            out["rem_hours"] = _ms_to_hours(stages.get("total_rem_sleep_time_milli"))
            out["deep_hours"] = _ms_to_hours(
                stages.get("total_slow_wave_sleep_time_milli")
            )
            out["disturbances"] = stages.get("disturbance_count")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"sleep: {exc}")

    try:
        records = whoop.cycles(days=2)
        if records:
            score = records[0].get("score") or {}
            out["current_strain"] = score.get("strain")
            out["avg_hr"] = score.get("average_heart_rate")
        if len(records) > 1:
            prev = (records[1].get("score") or {})
            out["yesterday_strain"] = prev.get("strain")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cycle: {exc}")

    if errors:
        out["_errors"] = errors
    return out


# --- MCP tools ------------------------------------------------------------

@mcp.tool
def health_check() -> dict:
    """Report which data providers are currently authorized and reachable.

    Run this first after any deploy or when data looks stale.
    """
    return {
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "local_date": datetime.now(LOCAL_TZ).date().isoformat(),
        "whoop_authorized": whoop.is_authorized(),
        "garmin_authorized": garmin.is_authorized(),
    }


@mcp.tool
def get_morning_snapshot() -> dict:
    """The single call a morning readiness check should make.

    Returns last night's WHOOP recovery, HRV, RHR and sleep, yesterday's
    strain, plus Garmin's body battery, training readiness and training
    status. If one provider is down the other still returns.
    """
    now_local = datetime.now(LOCAL_TZ)
    snapshot = {
        "local_time": now_local.isoformat(),
        "local_date": now_local.date().isoformat(),
        "weekday": now_local.strftime("%A"),
        "whoop": {},
        "garmin": {},
        "provider_errors": [],
    }

    try:
        snapshot["whoop"] = _whoop_summary()
    except Exception as exc:  # noqa: BLE001
        snapshot["provider_errors"].append(f"whoop: {type(exc).__name__}: {exc}")

    try:
        snapshot["garmin"] = garmin.daily(now_local.date().isoformat())
    except Exception as exc:  # noqa: BLE001
        snapshot["provider_errors"].append(f"garmin: {type(exc).__name__}: {exc}")

    return snapshot


@mcp.tool
def get_whoop_recovery(days: int = 7) -> list:
    """Raw WHOOP recovery records (recovery score, HRV, RHR, SpO2, skin temp)."""
    return whoop.recovery(days)


@mcp.tool
def get_whoop_sleep(days: int = 7) -> list:
    """Raw WHOOP sleep records including full sleep-stage breakdown."""
    return whoop.sleep(days)


@mcp.tool
def get_whoop_workouts(days: int = 7) -> list:
    """WHOOP workout records: strain, heart-rate zones, calories per session."""
    return whoop.workouts(days)


@mcp.tool
def get_whoop_cycles(days: int = 7) -> list:
    """WHOOP physiological cycles: day strain, average and max heart rate."""
    return whoop.cycles(days)


@mcp.tool
def get_garmin_day(day: str | None = None) -> dict:
    """Garmin data for one day (YYYY-MM-DD, defaults to today).

    Includes steps, stress, sleep, HRV status, training readiness,
    training status, resting HR, body battery and VO2 max.
    """
    return garmin.daily(day)


@mcp.tool
def get_garmin_activities(limit: int = 10) -> list:
    """Most recent Garmin activities with distance, pace, duration and HR."""
    return garmin.activities(limit)


@mcp.tool
def get_trend_series(days: int = 14) -> dict:
    """WHOOP recovery/HRV/RHR/sleep series for trend and baseline analysis.

    Use this rather than eyeballing one morning in isolation - a single
    depressed HRV reading means much less than a three-day slide.
    """
    series = []
    for record in whoop.recovery(days):
        score = record.get("score") or {}
        series.append(
            {
                "created_at": record.get("created_at"),
                "recovery_score": score.get("recovery_score"),
                "hrv_ms": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
            }
        )
    values = [s["hrv_ms"] for s in series if isinstance(s["hrv_ms"], (int, float))]
    rhr = [s["resting_hr"] for s in series if isinstance(s["resting_hr"], (int, float))]
    return {
        "days_requested": days,
        "records": series,
        "hrv_mean": round(sum(values) / len(values), 1) if values else None,
        "rhr_mean": round(sum(rhr) / len(rhr), 1) if rhr else None,
    }


# --- One-time WHOOP authorization routes ----------------------------------

@mcp.custom_route("/auth/whoop/start", methods=["GET"])
async def whoop_start(request: Request) -> RedirectResponse | HTMLResponse:
    if request.query_params.get("k") != MCP_SECRET:
        return HTMLResponse("<h1>403</h1><p>Bad or missing ?k= secret.</p>", 403)
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    state = secrets.token_urlsafe(16)
    return RedirectResponse(whoop.authorize_url(base + REDIRECT_PATH, state))


@mcp.custom_route(REDIRECT_PATH, methods=["GET"])
async def whoop_callback(request: Request) -> HTMLResponse:
    error = request.query_params.get("error")
    if error:
        return HTMLResponse(f"<h1>WHOOP returned an error</h1><p>{error}</p>", 400)
    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("<h1>Missing ?code= from WHOOP</h1>", 400)
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    try:
        whoop.exchange_code(code, base + REDIRECT_PATH)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"<h1>Token exchange failed</h1><pre>{exc}</pre>", 500)
    return HTMLResponse(
        "<h1>WHOOP connected</h1>"
        "<p>Tokens stored. You can close this tab and go back to Claude.</p>"
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> HTMLResponse:
    """Unauthenticated liveness probe - deliberately leaks nothing."""
    return HTMLResponse("ok")


@mcp.custom_route("/status", methods=["GET"])
async def status(request: Request) -> JSONResponse:
    """Secret-protected setup check. Use this to verify each build phase."""
    if request.query_params.get("k") != MCP_SECRET:
        return JSONResponse({"error": "bad or missing ?k= secret"}, 403)
    return JSONResponse(
        {
            "whoop_authorized": whoop.is_authorized(),
            "garmin_authorized": garmin.is_authorized(),
            "whoop_client_id_set": bool(os.getenv("WHOOP_CLIENT_ID")),
            "garmin_tokens_provided": bool(os.getenv("GARMIN_TOKENS_B64")),
            "data_dir": str(storage.data_dir()),
            "mcp_path": MCP_PATH,
            "local_time": datetime.now(LOCAL_TZ).isoformat(),
        }
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        path=MCP_PATH,
    )
