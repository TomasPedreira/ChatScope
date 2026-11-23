"""Reproduz a amostragem do piloto usando apenas a fixture local da ChatScope."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from random import Random
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "apps/chatscope/tests/fixtures/vod.json"
WINDOW = 10
BASELINE_WINDOWS = 6
BUDGET = 3


def measure(capture):
    messages_by_window = defaultdict(list)
    for message in capture["messages"]:
        window_start = int(message["offset"] // WINDOW) * WINDOW
        messages_by_window[window_start].append(message)

    windows = []
    for start in range(int(capture["source"]["start"]), int(capture["source"]["end"]), WINDOW):
        messages = messages_by_window[start]
        participants = {message["user"].casefold() for message in messages}
        reactors = {message["user"].casefold() for message in messages if message["reaction"]}
        previous = windows[-BASELINE_WINDOWS:]
        typical = median(row["messages"] for row in previous) if len(previous) == BASELINE_WINDOWS else None
        windows.append({
            "start": start,
            "messages": len(messages),
            "participants": len(participants),
            "reactors": len(reactors),
            "reaction_share": len(reactors) / max(1, len(participants)),
            "rate_ratio": len(messages) / max(1, typical) if typical is not None else None,
        })
    return windows


def pick(windows, score):
    chosen = []
    for row in sorted(windows, key=score, reverse=True):
        if all(abs(row["start"] - other["start"]) >= 30 for other in chosen):
            chosen.append(row)
        if len(chosen) == BUDGET:
            break
    return [row["start"] for row in chosen]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Mostra também todas as janelas medidas")
    args = parser.parse_args()
    capture = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    windows = measure(capture)
    eligible = [row for row in windows if row["rate_ratio"] is not None]
    combined = [row for row in eligible if row["reactors"] >= 5]
    policies = {
        "ritmo": pick(eligible, lambda row: row["rate_ratio"]),
        "proporcao_reacoes": pick(eligible, lambda row: row["reaction_share"]),
        "combinado": pick(combined, lambda row: row["rate_ratio"] * (1 + 4 * row["reaction_share"])),
    }
    sample = {start for starts in policies.values() for start in starts}
    control_pool = [
        row["start"] for row in eligible
        if all(abs(row["start"] - start) >= 25 for start in sample)
    ]
    result = {
        "messages": len(capture["messages"]),
        "participants": len({message["user"].casefold() for message in capture["messages"]}),
        "windows": len(windows),
        "eligible_windows": len(eligible),
        "median_messages_per_window": median(row["messages"] for row in windows),
        "original_suggestions": len(capture["analysis"]["highlights"]),
        "picks": policies,
        "strict_combined_gate": [
            row["start"] for row in combined if row["rate_ratio"] >= 1.5
        ],
        "controls": Random(42).sample(control_pool, min(2, len(control_pool))),
    }
    if args.json:
        result["metrics"] = windows
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
