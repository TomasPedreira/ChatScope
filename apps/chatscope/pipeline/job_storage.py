"""Atomic output state and manifests; dates use the production timezone."""

from datetime import datetime
from pathlib import Path
import json
import time


def write_json_atomically(path, value):
    write_text_atomically(
        path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    )


def write_text_atomically(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    # WebView/antivirus/OneDrive can briefly hold a Windows file without delete
    # sharing. Retry only the atomic rename; never truncate the last valid state.
    for attempt in range(12):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(0.025 * (attempt + 1))


def save_production_manifest(folder, root, manifest):
    write_json_atomically(folder / "job.json", manifest)
    write_json_atomically(root / "current.json", manifest)


def current_lisbon_date():
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%Y-%m-%d")
    except Exception:
        # tzdata is installed by Setup-Media. Never silently use a different day.
        raise ValueError("Falta tzdata para organizar os clips pela data de Lisboa.")
