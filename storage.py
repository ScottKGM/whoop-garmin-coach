"""Tiny JSON file store that lives on the Railway persistent volume."""

import json
import os
from pathlib import Path

# Railway injects RAILWAY_VOLUME_MOUNT_PATH automatically when a volume is attached.
DATA_DIR = Path(
    os.getenv("DATA_DIR")
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or "./data"
)


def data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def read_json(filename: str):
    path = data_dir() / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_json(filename: str, payload) -> None:
    path = data_dir() / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)  # atomic write so a crash mid-write can't corrupt tokens
    os.chmod(path, 0o600)
