"""Run this ONCE on your own laptop. It does not belong on the server.

It logs in to Garmin Connect (handling MFA interactively), then prints a
single base64 blob you paste into Railway as GARMIN_TOKENS_B64.

Why: logging in from a cloud datacenter IP is what gets blocked by Garmin's
bot protection. Logging in from your home laptop looks like a normal person,
and the resulting tokens refresh happily from anywhere.

    python3 local_setup.py
"""

import base64
import os
import sys
from getpass import getpass
from pathlib import Path

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit(
        "Missing dependency. Run:\n"
        "    pip3 install --upgrade garminconnect curl_cffi"
    )

TOKEN_DIR = Path.home() / ".garminconnect"


def main() -> None:
    email = os.getenv("GARMIN_EMAIL") or input("Garmin Connect email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass("Garmin Connect password: ")

    print("\nLogging in to Garmin (you may be asked for an MFA code)...")
    client = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    client.login(str(TOKEN_DIR))

    # Prove the tokens actually work before shipping them anywhere.
    from datetime import date

    stats = client.get_stats(date.today().isoformat())
    steps = stats.get("totalSteps") if isinstance(stats, dict) else None
    print(f"Login OK. Garmin reports {steps} steps today.\n")

    token_file = TOKEN_DIR / "garmin_tokens.json"
    if not token_file.exists():
        sys.exit(f"Expected token file at {token_file} but it was not created.")

    blob = base64.b64encode(token_file.read_bytes()).decode()
    print("=" * 72)
    print("Copy EVERYTHING between the lines below into Railway as GARMIN_TOKENS_B64")
    print("=" * 72)
    print(blob)
    print("=" * 72)
    print(f"\n({len(blob)} characters. It is one single line - no line breaks.)")


if __name__ == "__main__":
    main()
