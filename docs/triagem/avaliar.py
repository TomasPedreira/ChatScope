"""Compare reviewed live captures and randomize the first paired editing experiment."""

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
import json
from math import sqrt
from pathlib import Path
from random import Random
import re
import sys


RESULTS = Path(__file__).resolve().parents[2] / "media" / "twitch" / "estudo-ao-vivo"
SESSION = re.compile(r"\d{8}-\d{6}-[0-9a-f]{8}")
VERDICTS = ("aproveitar", "reserva", "descartar", "inconclusivo")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def marks(folder):
    file = folder / "classificacao.json"
    return read_json(file) if file.is_file() else {}


def register(folder, clip, verdict, reason, seconds, final_reaction=False):
    state = read_json(folder / "estado.json")
    if not any(row["id"] == clip and row["status"] == "ready" for row in state["samples"]):
        raise ValueError("A classificação precisa de uma prévia disponível.")
    if not reason.strip() or (seconds is not None and seconds <= 0):
        raise ValueError("Indica o motivo e, quando medido, um tempo de revisão positivo.")
    entries = marks(folder)
    previous = entries.get(clip)
    entry = {"veredito": verdict, "motivo": reason.strip(), "segundosRevisao": seconds,
             "reacaoFinalAproveitavel": final_reaction}
    if previous:
        current = {key: value for key, value in previous.items() if key != "revisoesAnteriores"}
        history = previous.get("revisoesAnteriores", [])
        if entry != current:
            history = [*history, current]
        if history:
            entry["revisoesAnteriores"] = history
    entries[clip] = entry
    temporary = folder / "classificacao.tmp"
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(folder / "classificacao.json")


def completed_sessions(first, maximum):
    sessions = []
    for folder in sorted(RESULTS.iterdir()):
        if not SESSION.fullmatch(folder.name) or folder.name < first:
            continue
        state_path = folder / "estado.json"
        if state_path.is_file() and (state := read_json(state_path))["status"] == "terminado":
            sessions.append((folder, state, marks(folder)))
        if len(sessions) == maximum:
            break
    return sessions


def summarize(sessions):
    fields = ("selecionados", "capturados", "revistos", *VERDICTS)
    totals = {kind: Counter(dict.fromkeys(fields, 0)) for kind in ("candidate", "control")}
    for _, state, entries in sessions:
        for sample in state["samples"]:
            counts = totals[sample["kind"]]
            counts["selecionados"] += 1
            if sample["status"] != "ready":
                continue
            counts["capturados"] += 1
            entry = entries.get(sample["id"])
            if entry is None:
                continue
            counts["revistos"] += 1
            counts[entry["veredito"]] += 1
            if (seconds := entry.get("segundosRevisao")) is not None:
                counts["revistosCronometrados"] += 1
                counts["segundosRevisao"] += seconds
                counts["aproveitaveisCronometrados"] += entry["veredito"] == "aproveitar"

    for counts in totals.values():
        if counts["revistos"]:
            counts["proporcaoAproveitavel"] = counts["aproveitar"] / counts["revistos"]
        if counts["segundosRevisao"]:
            counts["aproveitaveisPorMinutoMedido"] = (
                counts["aproveitaveisCronometrados"] * 60 / counts["segundosRevisao"]
            )
    return totals


def experiment(sessions, seed):
    if len(sessions) < 2:
        raise ValueError("A experiência começa depois de pelo menos duas sessões terminadas.")
    eligible = []
    for folder, state, entries in sessions:
        for sample in state["samples"]:
            entry = entries.get(sample["id"], {})
            if (sample["kind"] == "candidate" and sample["status"] == "ready" and sample.get("master")
                    and entry.get("veredito") == "aproveitar" and entry.get("reacaoFinalAproveitavel")):
                eligible.append((folder.name, sample["id"]))
    if not eligible:
        raise ValueError("Falta classificar um momento com fonte de edição e reação final aproveitável.")
    rng = Random(seed)
    eligible.sort()
    order = [index % 2 for index in range(len(eligible))]
    if rng.randrange(2):
        order = [1 - index for index in order]
    rng.shuffle(order)
    variants = ["corte-no-impacto", "corte-com-reacao-final"]
    return {
        "seed": seed, "variavel": "momento do corte final",
        "pares": [{"sessao": session, "clip": clip,
                   "ordem": [variants[first], variants[1 - first]]}
                  for (session, clip), first in zip(eligible, order)],
    }


def window_flows(events):
    study = Path(__file__).resolve().parents[2] / "apps" / "chatscope" / "study"
    sys.path.insert(0, str(study))
    from chat_signals import Activity, chat_flow

    history = defaultdict(lambda: deque(maxlen=18))
    for event in events:
        channel = event.get("channel")
        if event["type"] in ("chat_connected", "chat_error", "channel_started"):
            history[channel].clear()
        if event["type"] != "window" or "participants" not in event:
            continue
        current = Activity(event["messages"], event["participants"])
        prior = history[channel]
        flow = chat_flow(current, list(prior), event.get("viewers"))
        prior.append(current)
        if flow is not None:
            yield event, flow


def replay_flow(folder, limit):
    study = Path(__file__).resolve().parents[2] / "apps" / "chatscope" / "study"
    sys.path.insert(0, str(study))
    from collector import CAPTURE_RESERVE, COOLDOWN, POST, WINDOW

    with (folder / "eventos.jsonl").open(encoding="utf-8") as source:
        events = [json.loads(line) for line in source]
    cutoff = datetime.fromisoformat(events[0]["deadline"]).timestamp()
    captured = defaultdict(list)
    for event in events:
        if event["type"] == "selected" and event.get("kind") == "candidate":
            captured[event["channel"]].append(datetime.fromisoformat(event["peakEnd"]).timestamp())

    totals = Counter(dict.fromkeys(("avaliadas", "regraAtual", "fluxo", "ambos", "soFluxo"), 0))
    alternatives = []
    for event, flow in window_flows(events):
        channel = event["channel"]
        end = datetime.fromisoformat(event["start"]).timestamp() + WINDOW
        if end + POST + CAPTURE_RESERVE >= cutoff:
            continue
        totals["avaliadas"] += 1
        old = bool(event.get("rule"))
        new = bool(flow["rule"])
        totals["regraAtual"] += old
        totals["fluxo"] += new
        totals["ambos"] += old and new
        totals["soFluxo"] += new and not old
        if new and not old and not any(abs(end - peak) < COOLDOWN for peak in captured[channel]):
            strength = flow["excessPeople"] / sqrt(flow["baselinePeople"] + 1)
            alternatives.append((strength, end, channel, event, flow))

    examples = []
    recent = defaultdict(list)
    for _, end, channel, event, flow in sorted(alternatives, key=lambda item: item[:2], reverse=True):
        if any(abs(end - other) < COOLDOWN for other in recent[channel]):
            continue
        recent[channel].append(end)
        examples.append({
            "canal": channel, "inicio": event["start"], "stream": event["stream"],
            "mensagens": event["messages"], "pessoas": event["participants"],
            "reacoesLexico": event["reactors"], "espectadores": event["viewers"], **flow,
        })
        if len(examples) == limit:
            break
    return {"sessao": folder.name, "janelas": totals, "exemplosParaRever": examples}


def prospect(folder, seed):
    """Return time ranges for review, with an equal budget for each live feed."""
    state = read_json(folder / "estado.json")
    ready = defaultdict(list)
    for sample in state["samples"]:
        if sample["status"] == "ready":
            channel = (sample["channel"], sample["stream"])
            ready[channel].append(datetime.fromisoformat(sample["peakEnd"]))

    by_channel = defaultdict(list)
    with (folder / "eventos.jsonl").open(encoding="utf-8") as source:
        for row, flow in window_flows(map(json.loads, source)):
            channel = (row["channel"], row["stream"])
            at = datetime.fromisoformat(row["start"]) + timedelta(seconds=10)
            if any(abs((at - other).total_seconds()) < 100 for other in ready[channel]):
                continue
            signals = row.get("experimentalSignals") or {}
            repeated = max((*signals.get("text", {}).values(), *signals.get("emotes", {}).values()), default=0)
            share = repeated / max(1, row["participants"])
            scores = {
                "regra original": row["reactors"] / max(1, row["reactionBaseline"]) if row["rule"] else 0,
                "fluxo": flow["excessPeople"] / sqrt(flow["baselinePeople"] + 1) if flow["rule"] else 0,
                "emote ou expressão": share if repeated >= 5 and share >= 0.12 else 0,
            }
            by_channel[channel].append((at, scores, row))

    rng = Random(seed)
    proposals = []
    for (channel, stream), windows in sorted(by_channel.items()):
        used = []
        for method in ("regra original", "fluxo", "emote ou expressão", "amostra sem pico"):
            available = [entry for entry in windows
                         if all(abs((entry[0] - other).total_seconds()) >= 125 for other in used)]
            if method == "amostra sem pico":
                controls = [entry for entry in available if not any(entry[1].values())]
                chosen = rng.choice(controls) if controls else None
            else:
                chosen = max(available, key=lambda entry: entry[1][method], default=None)
                if chosen and not chosen[1][method]:
                    chosen = None
            if chosen is None:
                continue
            at, scores, row = chosen
            used.append(at)
            proposals.append({
                "canal": channel, "stream": stream, "origem": method, "janelaUtc": row["start"],
                "reverDe": (at - timedelta(seconds=55)).isoformat(),
                "reverAte": (at + timedelta(seconds=70)).isoformat(),
                "pessoas": row["participants"], "reacoesLexico": row["reactors"],
                "sinais": [name for name, value in scores.items() if value],
            })
    return {"sessao": folder.name, "seed": seed, "rever": proposals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    label = commands.add_parser("registar")
    label.add_argument("sessao")
    label.add_argument("clip")
    label.add_argument("veredito", choices=VERDICTS)
    label.add_argument("--motivo", required=True)
    label.add_argument("--segundos", type=int)
    label.add_argument("--reacao-final", action="store_true")
    flow = commands.add_parser("fluxo")
    flow.add_argument("sessao")
    flow.add_argument("--limite", type=int, default=6)
    search = commands.add_parser("prospetar")
    search.add_argument("sessao")
    search.add_argument("--seed", type=int, default=22)
    for command in ("comparar", "sortear"):
        analysis = commands.add_parser(command)
        analysis.add_argument("desde", help="ID da primeira sessão comparável")
        analysis.add_argument("--sessoes", type=int, choices=(2, 3), default=3)
        if command == "sortear":
            analysis.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "registar":
            if not SESSION.fullmatch(args.sessao):
                raise ValueError("ID de sessão inválido.")
            register(RESULTS / args.sessao, args.clip, args.veredito, args.motivo, args.segundos, args.reacao_final)
            return
        if args.command == "fluxo":
            if not SESSION.fullmatch(args.sessao) or args.limite < 1:
                raise ValueError("Indica um ID de sessão e um limite positivo.")
            print(json.dumps(replay_flow(RESULTS / args.sessao, args.limite), ensure_ascii=False, indent=2))
            return
        if args.command == "prospetar":
            if not SESSION.fullmatch(args.sessao):
                raise ValueError("ID de sessão inválido.")
            print(json.dumps(prospect(RESULTS / args.sessao, args.seed), ensure_ascii=False, indent=2))
            return
        if not SESSION.fullmatch(args.desde):
            raise ValueError("Indica o ID da primeira sessão comparável.")
        sessions = completed_sessions(args.desde, args.sessoes)
        result = (experiment(sessions, args.seed) if args.command == "sortear" else {
            "sessoesTerminadas": [folder.name for folder, _, _ in sessions],
            "grupos": summarize(sessions),
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
