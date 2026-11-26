"""Reproducible live metadata probe. Run with .venv-youtube/Scripts/python.exe."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers.youtube import extract


def probe(url):
    started = time.monotonic()
    try:
        info = extract(url)
        result = {"url": url, "status": "available" if info["heatmap"] else "unavailable", **info}
    except Exception as error:
        result = {"url": url, "status": "error", "error": str(error)}
    result["elapsedSeconds"] = round(time.monotonic() - started, 2)
    print(json.dumps({key: value for key, value in result.items() if key != "heatmap"}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", default=[
        "https://www.youtube.com/watch?v=YE7VzlLtp-4",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "https://www.youtube.com/watch?v=BaW_jenozKc",
    ])
    args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, args.urls))
    destination = Path(__file__).resolve().parents[1] / "artifacts/youtube-probe.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps({"testedAt": datetime.now(timezone.utc).isoformat(), "videos": results},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)
