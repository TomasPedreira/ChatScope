"""Run the collector and record a health check every 30 minutes."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

INTERVAL = 30 * 60
STALE_AFTER = 3 * 60
COLLECTOR = Path(__file__).with_name("collector.py")
DRAFTS = Path(__file__).with_name("drafts.py")


def observe(folder, collector_pid, exit_code, previous_windows):
    state_file = folder / "estado.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        age = round(time.time() - state_file.stat().st_mtime)
    except (OSError, ValueError):
        state, age = {}, None
    channels = state.get("activeChannels", [])
    windows = sum(state.get("measuredWindows", {}).values())
    samples = state.get("samples", [])
    if exit_code is not None:
        status = "terminado" if exit_code == 0 and state.get("status") == "terminado" else "falha"
    elif age is None:
        status = "a iniciar" if previous_windows is None else "sem estado"
    elif age > STALE_AFTER:
        status = "estado desatualizado"
    elif not channels:
        status = "à espera de canais"
    elif previous_windows is not None and windows <= previous_windows:
        status = "sem novas janelas de chat"
    else:
        status = "em recolha"
    return {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collectorPid": collector_pid,
        "collectorExitCode": exit_code,
        "status": status,
        "stateAgeSeconds": age,
        "channels": channels,
        "chatWindows": windows,
        "newChatWindows": windows - previous_windows if previous_windows is not None else None,
        "clipsReady": sum(sample.get("status") == "ready" for sample in samples),
        "failures": state.get("failures", {}),
    }


def record(folder, snapshot):
    line = json.dumps(snapshot, ensure_ascii=False)
    with (folder / "vigia.jsonl").open("a", encoding="utf-8") as log:
        log.write(line + "\n")
    temp = folder / "vigia.json.tmp"
    temp.write_text(line + "\n", encoding="utf-8")
    temp.replace(folder / "vigia.json")


def supervise(folder, argv, interval=INTERVAL):
    with (folder / "collector.stdout.log").open("ab") as stdout, \
         (folder / "collector.stderr.log").open("ab") as stderr, \
         (folder / "drafts.log").open("ab") as draft_log:
        collector = subprocess.Popen(
            argv, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        drafts = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(DRAFTS), str(folder), "--vigiar"],
            stdout=draft_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            last = observe(folder, collector.pid, None, None)
            record(folder, last)
            while True:
                try:
                    code = collector.wait(timeout=interval)
                except subprocess.TimeoutExpired:
                    code = None
                current = observe(folder, collector.pid, code, last["chatWindows"])
                record(folder, current)
                if code is not None:
                    return code
                last = current
        finally:
            try:
                drafts.wait(timeout=10)
            except subprocess.TimeoutExpired:
                drafts.terminate()
                drafts.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--hours", required=True, type=float)
    parser.add_argument("--fora-do-horario", action="store_true")
    args = parser.parse_args()
    argv = [
        sys.executable, str(COLLECTOR), "run",
        "--hours", str(args.hours), "--folder", str(args.folder),
    ]
    if args.fora_do_horario:
        argv.append("--fora-do-horario")
    raise SystemExit(supervise(args.folder, argv))


if __name__ == "__main__":
    main()
