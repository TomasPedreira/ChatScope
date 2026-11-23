"""Draft vertical edits from the live study's own captured sources."""

import argparse
from datetime import datetime
import json
from math import floor
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time


RESULTS = Path(__file__).resolve().parents[3] / "media" / "twitch" / "estudo-ao-vivo"
CLIP_ID = re.compile(r"\d{4,}-[a-z0-9_]+")


def candidate(session, clip_id, state):
    if not CLIP_ID.fullmatch(clip_id):
        raise ValueError("Usa um ID de candidato da sessão.")
    item = next((row for row in state["samples"] if row["id"] == clip_id), None)
    if item is None or item["kind"] != "candidate" or item["status"] != "ready":
        raise ValueError("O ID precisa de corresponder a um candidato capturado.")
    master = item.get("master")
    source = session / "masters" / f"{clip_id}.mp4"
    if not master or master["height"] < 720 or not source.is_file():
        raise ValueError("O candidato precisa da fonte do direto a pelo menos 720p.")
    return item, source


def transcript(model, source, offset, duration):
    segments, _ = model.transcribe(
        str(source), language="en", clip_timestamps=[offset, offset + duration],
        initial_prompt=None, condition_on_previous_text=False, word_timestamps=True,
        vad_filter=False, beam_size=3,
    )
    return [
        [round(max(0, word.start - offset), 3), round(min(duration, word.end - offset), 3), clean]
        for segment in segments
        for word in (segment.words or ())
        if word.end > offset and word.start < offset + duration and word.end > word.start
        if (clean := word.word.strip().translate(str.maketrans("", "", "\\{}\n\r")))
    ]


def suggestion(words, peak, available):
    start, end = max(0, peak - 22), min(available, peak + 8)
    gaps = [(left[1] + right[0]) / 2 for left, right in zip(words, words[1:])
            if right[0] - left[1] >= 0.25]
    for gap in sorted(gaps, key=lambda at: abs(at - start)):
        if abs(gap - start) < 2:
            start = gap
            break
    for gap in sorted(gaps, key=lambda at: abs(at - end)):
        if abs(gap - end) < 2:
            end = gap
            break
    return round(start, 3), round(end, 3)


def caption_cues(words, start, end):
    groups, group = [], []
    for begin, finish, word in words:
        if begin < start - 0.04 or begin >= end or finish <= start:
            continue
        tick = round((max(begin, start) - start) * 100)
        if group and tick <= group[-1][0]:
            continue
        if group and (len(group) == 5 or len(" ".join(line[2] for line in group)) + len(word) >= 29
                      or begin - group[-1][1] > 0.38 or group[-1][2].endswith((".", "!", "?"))):
            groups.append(group)
            group = []
        group.append((tick, finish, word))
    if group:
        groups.append(group)

    cues = []
    for index, group in enumerate(groups):
        boundary = groups[index + 1][0][0] if index + 1 < len(groups) else floor((end - start) * 100 + 1e-8)
        finish = min(boundary, round((group[-1][1] - start + 0.08) * 100))
        if finish > group[-1][0]:
            cues.append({"text": " ".join(word for _, _, word in group),
                         "times": [tick / 100 for tick, _, _ in group] + [finish / 100]})
    return cues


def kept_spans(start, end, omitted):
    spans = []
    position = start
    for left, right in omitted:
        if not position < left < right < end:
            raise ValueError("Cada intervalo removido precisa de ficar dentro do corte e separado dos restantes.")
        spans.append((position, left))
        position = right
    return [*spans, (position, end)]


def render_draft(session, item, source, model, args):
    from shorts import digest, probe, render

    folder = session / "drafts"
    folder.mkdir(exist_ok=True)
    destination = folder / f"{item['id']}.mp4"
    record_path = destination.with_suffix(".json")
    old = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    source_digest = digest(source)
    if (old.get("sourceDigest") == source_digest and not args.force and destination.is_file()
            and old.get("draftDigest") == digest(destination) and not any(value is not None for value in (
                args.start, args.end, args.game_crop, args.face_crop, args.captions, args.omit, args.face_only,
            ))):
        return destination

    _, _, length = probe(source)
    offset = item["master"]["previewOffset"]
    available = min(item["seconds"], length - offset)
    if old.get("sourceDigest") != source_digest:
        old = {}
    words = old.get("transcript")
    if words is None:
        words = transcript(model(), source, offset, available)
    peak = item["peakTimestamp"] - datetime.fromisoformat(item["start"]).timestamp()
    start, end = old.get("trim", suggestion(words, peak, available))
    start = start if args.start is None else args.start
    end = end if args.end is None else args.end
    omitted = sorted(args.omit) if args.omit is not None else old.get("omitted", [])
    spans = kept_spans(start, end, omitted)
    if not 0 <= start < end <= available or not 5 <= sum(right - left for left, right in spans) <= 60:
        raise ValueError("Escolhe um corte de 5 a 60 segundos dentro da janela capturada.")
    crops = args.game_crop, args.face_crop
    if crops == (None, None):
        crops = old.get("crops", crops)
    same_edit = old.get("trim") == [start, end] and old.get("omitted", []) == omitted
    face_only = old.get("faceOnly", []) if same_edit else []
    if args.face_only is not None:
        face_only = args.face_only
    edited_captions = None
    if args.captions:
        edited_captions = args.captions.read_text(encoding="utf-8-sig")
    elif same_edit:
        edited_captions = old.get("editedCaptions")
    cues = []
    elapsed = 0
    for left, right in spans:
        for cue in caption_cues(words, left, right):
            cue["times"] = [round(at + elapsed, 3) for at in cue["times"]]
            cues.append(cue)
        elapsed += right - left
    captions = (edited_captions if edited_captions is not None else (
        json.dumps(cues, ensure_ascii=False) if cues else None
    ))
    source_spans = [(round(offset + left, 3), round(offset + right, 3)) for left, right in spans]
    with TemporaryDirectory(prefix=".draft-", dir=folder) as temporary:
        draft = Path(temporary) / destination.name
        render(source, draft, *crops, captions.encode("utf-8") if captions else None,
               trim=source_spans[0] if len(source_spans) == 1 else None,
               cuts=source_spans if len(source_spans) > 1 else None, face_only=face_only)
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", str(draft),
                        "-f", "null", "-"], check=True, timeout=35)
        record = {
            "candidate": item["id"], "channel": item["channel"], "peakUtc": item["peakEnd"],
            "game": item.get("game"),
            "sourceDigest": source_digest, "draftDigest": digest(draft),
            "trim": [start, end], "omitted": omitted, "crops": list(crops),
            "transcript": words, "editedCaptions": edited_captions,
            "faceOnly": face_only,
        }
        manifest = Path(temporary) / record_path.name
        manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        draft.replace(destination)
        manifest.replace(record_path)
    return destination


def verified_draft(path):
    from shorts import digest

    source = path.resolve(strict=True)
    session = source.parent.parent
    if source.parent.name != "drafts" or source.suffix != ".mp4" or not session.is_relative_to(RESULTS):
        raise ValueError("Escolhe um rascunho gerado pela recolha ao vivo.")
    state = json.loads((session / "estado.json").read_text(encoding="utf-8"))
    item, master = candidate(session, source.stem, state)
    record = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    if (record["candidate"] != item["id"] or record["sourceDigest"] != digest(master)
            or record["draftDigest"] != digest(source)):
        raise ValueError("O rascunho ou a origem mudou depois da edição.")
    if record.get("discarded"):
        raise ValueError("Este rascunho foi descartado. Refaz a edição para o voltar a rever.")
    return session, item, source


def draft_session(session, args, model):
    seen = set()
    state_path = session / "estado.json"
    while True:
        if args.watch and not state_path.is_file():
            time.sleep(5)
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if args.watch and state["status"] != "em execução":
            return
        deadline = state.get("deadlineUtc")
        if args.watch and deadline and datetime.fromisoformat(deadline).timestamp() - time.time() < 90:
            return
        ids = [args.id] if args.id else [
            row["id"] for row in state["samples"]
            if row["kind"] == "candidate" and row["status"] == "ready" and row.get("master")
            and row["id"] not in seen
        ]
        for clip_id in ids:
            seen.add(clip_id)
            try:
                item, source = candidate(session, clip_id, state)
                print(render_draft(session, item, source, model, args), flush=True)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                if not args.watch:
                    raise
                print(f"{clip_id}: {error}", flush=True)
        if not args.watch:
            return
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, nargs="?")
    parser.add_argument("id", nargs="?")
    parser.add_argument("--inicio", dest="start", type=float)
    parser.add_argument("--fim", dest="end", type=float)
    parser.add_argument("--remover", dest="omit", metavar="INICIO:FIM", action="append")
    parser.add_argument("--game-crop")
    parser.add_argument("--face-crop")
    parser.add_argument("--so-cara", dest="face_only", metavar="INICIO:FIM", nargs="*",
                        help="Mostrar só a cara nestes tempos do MP4 final")
    parser.add_argument("--legendas", dest="captions", type=Path)
    parser.add_argument("--refazer", dest="force", action="store_true")
    parser.add_argument("--vigiar", dest="watch", action="store_true")
    parser.add_argument("--descartar", dest="discard", metavar="MOTIVO")
    args = parser.parse_args()
    if args.watch and (not args.session or args.id):
        parser.error("A vigia precisa de uma sessão e acompanha a lista de candidatos.")
    if not args.id and any(value is not None for value in (
        args.start, args.end, args.game_crop, args.face_crop, args.captions, args.discard, args.omit, args.face_only,
    )):
        parser.error("Indica o ID do rascunho a retocar.")
    model = None

    def get_model():
        nonlocal model
        if model is None:
            from faster_whisper import WhisperModel
            model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4)
        return model

    try:
        if args.omit is not None:
            intervals = [interval.split(":") for interval in args.omit]
            if any(len(pair) != 2 for pair in intervals):
                raise ValueError("Usa --remover INICIO:FIM em segundos.")
            args.omit = [[float(left), float(right)] for left, right in intervals]
        if args.face_only is not None:
            args.face_only = [(float(start), float(end)) for start, end in
                              (interval.split(":") for interval in args.face_only)]
        session = args.session or RESULTS / (RESULTS / "ultima-sessao.txt").read_text(encoding="ascii").strip()
        if args.discard is not None:
            reason = args.discard.strip()
            if not reason or not CLIP_ID.fullmatch(args.id):
                raise ValueError("Indica um ID de rascunho e o motivo do descarte.")
            record = session / "drafts" / f"{args.id}.json"
            data = json.loads(record.read_text(encoding="utf-8"))
            data["discarded"] = reason
            temporary = record.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(record)
            return
        draft_session(session, args, get_model)
    except (ValueError, ImportError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
