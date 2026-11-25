"""One JSON request on stdin, one JSON result on stdout. Progress lives in job.json."""
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
import time

from .providers import SourceRegistry
from .render import FFmpegRenderer, validate_render
from .signals import audio_energy, validate_profile
from .tools import probe


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))


def atomic_text(path, value):
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
            time.sleep(.025 * (attempt + 1))


def save_manifest(folder, root, manifest):
    atomic_json(folder / "job.json", manifest)
    atomic_json(root / "current.json", manifest)


def analyze(request):
    profile = request["clipProfile"]
    validate_profile(profile)
    provider, adapter = SourceRegistry().resolve(request["url"])
    info = adapter.metadata()
    live = bool(info.get("is_live"))
    duration = float(info.get("duration") or 0)
    start = float(request.get("start") or 0)
    end = request.get("end")
    if live:
        if start or end is not None:
            raise ValueError("Num direto, deixa o intervalo vazio e escolhe a duração da captura.")
        end = float(request.get("captureSeconds", 120))
        if not 30 <= end <= 600:
            raise ValueError("A captura de um direto deve durar entre 30 e 600 segundos.")
    else:
        end = duration if end is None else float(end)
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end or (not live and end > duration):
        raise ValueError("O intervalo tem de ficar dentro da duração do vídeo.")
    heatmap = info.get("heatmap") or []
    validate_points(heatmap, duration)
    heatmap = [{**p, "start_time": max(start, p["start_time"]), "end_time": min(end, p["end_time"])}
               for p in heatmap if p["end_time"] > start and p["start_time"] < end]
    media, origin = None, 0.0
    signal, points = "youtube_heatmap", heatmap
    availability = "available" if heatmap else "unavailable"
    if not heatmap:
        # Bounded fallback prevents an accidental multi-hour download/analysis.
        if end - start > 600:
            raise ValueError("Sem heatmap: escolhe um intervalo até 10 minutos para analisar o áudio.")
        cache = Path(request["root"]) / "cache" / request["id"]
        media, origin = adapter.acquire(start, end, cache)
        actual = probe(media)
        if live:
            duration = end = actual["duration"]
        else:
            end = min(end, origin + actual["duration"])
        points = audio_energy(media, start, end, origin) if actual["audio"] else []
        signal = "audio_energy"
        availability = "available" if points else "unavailable"
    from yt_dlp.version import __version__
    source = {"url": request["url"], "kind": f"{provider}_live" if live else provider,
              "id": str(info["id"]), "title": info.get("title") or str(info["id"]),
              "channel": info.get("channel") or info.get("uploader") or provider,
              "duration": duration, "start": start, "end": end}
    analysis = {"clipProfile": profile, "availability": availability, "heatmap": heatmap,
                "points": points, "signal": signal, "timeOrigin": "recording" if live else "source",
                "moments": [], "extractorVersion": __version__,
                "localMedia": str(media.resolve()) if media else None, "mediaOrigin": origin}
    result = {"source": source, "analysis": analysis}
    atomic_json(Path(request["root"]) / "cache" / request["id"] / "analysis.json", result)
    return result


def validate_points(points, duration):
    if len(points) > 10000:
        raise ValueError("Demasiados pontos no heatmap.")
    previous = 0.0
    for item in sorted(points, key=lambda p: p["start_time"]):
        start, end, value = (item[key] for key in ("start_time", "end_time", "value"))
        if (not all(math.isfinite(v) for v in (start, end, value)) or start < previous - .001
                or not 0 <= start < end <= duration + 1 or not 0 <= value <= 1):
            raise ValueError("Heatmap inválido.")
        previous = end


def local_day():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%Y-%m-%d")
    except Exception:
        # tzdata is installed by Setup-Media. Never silently use a different day.
        raise ValueError("Falta tzdata para organizar os clips pela data de Lisboa.")


def render_batch(request):
    profile = request["renderProfile"]
    validate_render(profile)
    validate_profile(request["clipProfile"])
    root = Path(request["root"]).resolve()
    folder = root / local_day() / "jobs" / request["id"]
    folder.mkdir(parents=True, exist_ok=False)
    items = request["moments"]
    if not 1 <= len(items) <= 30:
        raise ValueError("Escolhe entre 1 e 30 momentos.")
    topic = request.get("topic", "geral")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", topic):
        raise ValueError("O tema só pode conter letras, números, _ e -.")
    manifest = {"schemaVersion": 1, "id": request["id"], "status": "running", "folder": str(folder),
                "source": request["source"], "clipProfile": request["clipProfile"], "renderProfile": profile,
                "clips": [{"index": i, "moment": item, "status": "queued"} for i, item in enumerate(items)]}
    save_manifest(folder, root, manifest)
    source_url = request["source"]["url"]
    if request["source"]["kind"] == "clip":
        # Twitch chat offsets for clips refer to their parent VOD.
        source_url = f"https://www.twitch.tv/videos/{request['source']['id']}"
    _, adapter = SourceRegistry().resolve(source_url)
    day_folder = folder.parent.parent
    try:
        for clip in manifest["clips"]:
            try:
                clip["status"] = "acquiring"
                save_manifest(folder, root, manifest)
                moment = clip["moment"]
                start, end = float(moment["start"]), float(moment["end"])
                bounds = request["source"]
                if (not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end
                        or end - start > 180.001 or start < bounds["start"] - .001
                        or end > bounds["end"] + .001):
                    raise ValueError("Momento fora do intervalo da origem.")
                clip_folder = folder / str(clip["index"] + 1)
                clip_folder.mkdir()
                media = request.get("localMedia")
                if media:
                    media = Path(media).resolve(strict=True)
                    if bounds["kind"] != "local" and not media.is_relative_to(root / "cache"):
                        raise ValueError("O master não pertence à cache desta aplicação.")
                    origin = request.get("mediaOrigin", 0)
                else:
                    if bounds["kind"].endswith("_live") or bounds["kind"] == "live":
                        raise ValueError("Este direto não tem vídeo capturado. Usa o modo Vídeo/áudio.")
                    media, origin = adapter.acquire(start, end, clip_folder / "master")
                clip["status"] = "rendering"
                save_manifest(folder, root, manifest)
                output_folder = day_folder / "clips" / topic
                output_folder.mkdir(parents=True, exist_ok=True)
                final = output_folder / f"{request['id']}-{clip['index'] + 1:02}.mp4"
                temporary = clip_folder / "draft.mp4"
                actual = FFmpegRenderer().render(media, temporary, start - origin, end - origin, profile)
                with temporary.open("rb") as stream:
                    from hashlib import sha256
                    hasher = sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(chunk)
                    digest = hasher.hexdigest()
                if final.exists():
                    raise ValueError("O destino já existe; o clip anterior foi preservado.")
                temporary.rename(final)
                clip.update(status="ready", path=str(final), sha256=digest, media=str(media),
                            mediaOrigin=origin, duration=actual["duration"], dimensions=[actual["width"], actual["height"]])
            except Exception as error:
                clip.update(status="error", error=str(error)[:1800])
            save_manifest(folder, root, manifest)
            build_review(day_folder)
        ready = sum(item["status"] == "ready" for item in manifest["clips"])
        manifest["status"] = "complete" if ready == len(items) else "partial" if ready else "error"
    finally:
        save_manifest(folder, root, manifest)
        build_review(day_folder)
    return manifest


def build_review(day_folder):
    # Own index: preserve any human-maintained review.md.
    lines = ["# Clips locais", "", "Gerado automaticamente; confirma vídeo e áudio antes de publicar.", ""]
    for file in sorted(day_folder.glob("jobs/*/job.json")):
        job = json.loads(file.read_text(encoding="utf-8"))
        title = job["source"]["title"].replace("\n", " ").replace("[", "(").replace("]", ")")
        for clip in job["clips"]:
            if clip["status"] == "ready":
                relative = Path(clip["path"]).relative_to(day_folder).as_posix()
                moment = clip["moment"]
                lines.append(f"- [{title} · {clip['duration']:.1f} s](<{relative}>) — {moment['reason']} · {moment['start']:.2f}–{moment['end']:.2f} s")
    atomic_text(day_folder / "clips-index.md", "\n".join(lines) + "\n")


def main():
    request = json.load(sys.stdin)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request.get("id", "")):
        raise ValueError("Identificador de job inválido.")
    action = request["action"]
    result = analyze(request) if action == "analyze" else render_batch(request) if action == "render" else None
    if result is None:
        raise ValueError("Operação desconhecida.")
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
