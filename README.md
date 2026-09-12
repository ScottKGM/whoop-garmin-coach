# WHOOP + Garmin → Claude coach connector

A small remote MCP server that gives Claude live access to your WHOOP and
Garmin data from any device, including your phone.

## Files

| File | What it is |
|---|---|
| `server.py` | The MCP server. Tools + one-time WHOOP OAuth routes. Start here. |
| `whoop.py` | WHOOP API v2 client (OAuth 2.0, auto token refresh). |
| `garmin.py` | Garmin Connect wrapper. Never logs in from the server - refreshes seeded tokens only. |
| `storage.py` | Atomic JSON file store on the persistent volume. |
| `local_setup.py` | **Run on your laptop, once.** Produces the Garmin token blob. |
| `requirements.txt` | Python dependencies. |
| `Procfile` | Tells Railway how to start the server. |
| `.python-version` | Pins Python 3.12 (required by `garminconnect`). |

There is nothing to edit inside any of these files. All configuration is
environment variables.

## Environment variables

| Name | Required | Example | Notes |
|---|---|---|---|
| `MCP_SECRET` | yes | `k3Jx9...` (32+ chars) | Unguessable string. Forms the secret URL path. |
| `PUBLIC_URL` | yes | `https://your-app.up.railway.app` | No trailing slash. |
| `DATA_DIR` | yes | `/data` | Must match the volume mount path. |
| `WHOOP_CLIENT_ID` | yes | from WHOOP dashboard | |
| `WHOOP_CLIENT_SECRET` | yes | from WHOOP dashboard | Never commit this. |
| `GARMIN_TOKENS_B64` | optional | output of `local_setup.py` | Omit to run WHOOP-only. |
| `LOCAL_TZ` | no | `America/Chicago` | Defaults to America/Chicago. |

## URLs the server exposes

| Path | Purpose |
|---|---|
| `/healthz` | Liveness probe. Returns `ok`. No secret needed. |
| `/auth/whoop/start?k=MCP_SECRET` | One-time WHOOP authorization. Open in a browser. |
| `/auth/whoop/callback` | WHOOP redirects here. Register this exact URL in the WHOOP dashboard. |
| `/mcp/MCP_SECRET` | The MCP endpoint. This is what you give Claude. |

## Design notes

**Garmin logins never happen on the server.** Garmin has no personal API and
blocks datacenter IPs. You log in once on your laptop with `local_setup.py`;
the server only refreshes those tokens. This removes the single most common
failure mode.

**One provider failing never takes down the other.** `get_morning_snapshot`
catches per-provider errors and returns whatever it has, so a Garmin outage
degrades you to WHOOP-only for a day rather than breaking the morning.

**Tokens live on a persistent volume.** Without one, every redeploy wipes
your WHOOP refresh token and you re-authorize by hand.
