"""Collect a daytime sample of live chat, audience counts and local video clips."""

import argparse
import asyncio
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, time as clock_time, timezone
import json
from math import ceil, sqrt
from pathlib import Path
from random import Random
import re
import shutil
from statistics import median
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.error import URLError
from zoneinfo import ZoneInfo

from chat_signals import Activity, ChatSignals, chat_flow

from twitch import (
    CHANNELS, chat, clip_segments, fetch, live_channels,
    media_segments, public_playlist,
)

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "media" / "twitch" / "estudo-ao-vivo"
LISBON = ZoneInfo("Europe/Lisbon")
REACTIONS = re.compile(
    r"\b(?:lulp?|lulw|omegalul|lol+|lmao|lmfao|kekw|kekl|pog(?:gers|champ)?|"
    r"pepelaugh|monka\w{0,12}|cinema|holy|aura|wtf|(?:ha){2,10}|(?:ah){2,10}|k{4,20}|"
    r"clip (?:it|that)|clipa(?: isso)?)\b|[😂🤣💀]", re.I,
)
WINDOW = 10
# Chat timestamps arrive after viewers have seen the triggering action.
PRE = 55
POST = 18
COOLDOWN = 90
MAX_CLIPS = 6
MAX_CANDIDATES_PER_SLOT = 2
MAX_CONTROLS = 2
CAPTURE_RESERVE = 90
MIN_CHANNEL_VIEWERS = 1000
VIEWERS_PER_REACTOR = 500
LARGE_AUDIENCE = 15_000
BURST_AUDIENCE_SCALE = 8.5
AUDIENCE_MAX_AGE = 120
NETWORK_ERRORS = (OSError, TimeoutError, URLError, ValueError, KeyError)
LOG = subprocess.CREATE_NO_WINDOW


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def local(timestamp):
    return datetime.fromtimestamp(timestamp, LISBON).strftime("%Y-%m-%d %H:%M:%S %Z")


def session_deadline(now, hours, outside_hours=False):
    requested = now + hours * 3600
    if outside_hours:
        return requested
    today = datetime.fromtimestamp(now, LISBON)
    end_of_day = datetime.combine(today.date(), clock_time(22), LISBON)
    return min(requested, end_of_day.timestamp())


def save_text(path, text):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


@dataclass
class Window:
    messages: int = 0
    participants: set = field(default_factory=set)
    reactors: set = field(default_factory=set)
    reactions: Counter = field(default_factory=Counter)
    extra_signals: ChatSignals = field(default_factory=ChatSignals)

    def add(self, user, text, emotes=()):
        if not user or text.startswith(("/", "!")):
            return
        self.messages += 1
        self.participants.add(user)
        self.extra_signals.add(user, text, emotes)
        match = REACTIONS.search(text)
        if match and user not in self.reactors:
            self.reactors.add(user)
            self.reactions[match.group().casefold()] += 1


def evaluate(window, preceding, viewers):
    count = len(window.participants)
    reactions = len(window.reactors)
    volume = median(prior.messages for prior in preceding) if preceding else 0
    typical_reactions = median(len(prior.reactors) for prior in preceding) if preceding else 0
    rate = window.messages / max(1, volume)
    share = reactions / max(1, count)
    minimum = max(4, (viewers + VIEWERS_PER_REACTOR - 1) // VIEWERS_PER_REACTOR) if viewers else None
    burst_minimum = None
    if viewers and viewers >= LARGE_AUDIENCE:
        burst_minimum = ceil(max(sqrt(viewers) / BURST_AUDIENCE_SCALE, 3 * typical_reactions))
    rule = None
    if minimum is not None and len(preceding) >= 6 and count >= 5 and share >= 0.12:
        if reactions >= max(minimum, 1.8 * typical_reactions) and (rate >= 1.45 or share >= 0.25):
            rule = "ritmo+reações" if rate >= 1.45 else "proporção de reações"
        elif (
            burst_minimum is not None and reactions >= burst_minimum
            and rate >= 1.5 and share >= 0.22 and rate * share >= 0.75
        ):
            rule = "pico acima da rotina do canal"
            minimum = burst_minimum
    return {
        "messages": window.messages, "participants": count, "reactors": reactions,
        "viewers": viewers, "minReactors": minimum,
        "burstMinReactors": burst_minimum, "reactionBaseline": round(typical_reactions, 2),
        "rate": round(rate, 2), "reactionShare": round(share, 3),
        "baseline": round(volume, 2), "signals": dict(window.reactions.most_common(4)),
        "rule": rule,
    }


def inspect_clip(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=10, creationflags=LOG,
    )
    details = json.loads(probe.stdout)
    video = next((stream for stream in details["streams"] if stream["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("A captura não contém vídeo.")
    return video["width"], video["height"], float(details["format"]["duration"])


def write_capture(selected, start, end, destination, master=None, retrieve=fetch):
    """Download one interval and create a review proxy and, for candidates, an editing source."""
    with TemporaryDirectory(prefix=".capture-", dir=destination.parent) as temp:
        folder = Path(temp)
        playlist = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-TARGETDURATION:15"]
        init_url = selected[0].init_url
        if init_url:
            (folder / "init.mp4").write_bytes(retrieve(init_url))
            playlist.append('#EXT-X-MAP:URI="init.mp4"')
        extension = "mp4" if init_url else "ts"
        def save_segment(index, segment):
            name = f"{index:03}.{extension}"
            (folder / name).write_bytes(retrieve(segment.url, limit=16_000_000))
            return [f"#EXTINF:{segment.duration:.6f},", name]

        with ThreadPoolExecutor(max_workers=5) as downloads:
            for entry in downloads.map(save_segment, range(len(selected)), selected):
                playlist.extend(entry)
        playlist.append("#EXT-X-ENDLIST")
        (folder / "preview.m3u8").write_text("\n".join(playlist) + "\n", encoding="ascii")
        preview = folder / "preview.mp4"
        ffmpeg = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(folder / "preview.m3u8")]
        offset = max(0, start - selected[0].utc)
        args = ffmpeg + [
            "-ss", f"{offset:.3f}",
            "-t", f"{end - start:.3f}", "-map", "0:v:0", "-map", "0:a?",
            "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-maxrate", "1100k", "-bufsize", "2200k", "-threads", "2",
            "-c:a", "aac", "-b:a", "80k", "-movflags", "+faststart", str(preview),
        ]
        subprocess.run(args, check=True, timeout=75, capture_output=True, creationflags=LOG)
        _, _, length = inspect_clip(preview)
        if not end - start - 0.75 <= length <= end - start + 0.75:
            raise ValueError(f"Prévia incompleta ({length:.2f} s)")
        result = {"seconds": round(length, 3)}
        if master is not None:
            source = folder / "master.mp4"
            try:
                subprocess.run(
                    ffmpeg + ["-map", "0:v:0", "-map", "0:a?", "-c", "copy",
                              "-movflags", "+faststart", str(source)],
                    check=True, timeout=30, capture_output=True, creationflags=LOG,
                )
                width, height, duration = inspect_clip(source)
                if height < 720 or duration < offset + length - 0.25:
                    raise ValueError("Fonte sem 720p ou com contexto incompleto")
                master.parent.mkdir(exist_ok=True)
                source.replace(master)
                result["master"] = {
                    "file": f"masters/{master.name}", "width": width, "height": height,
                    "previewOffset": round(offset, 3), "seconds": round(duration, 3),
                }
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                result["masterError"] = str(error) if isinstance(error, ValueError) else type(error).__name__
        preview.replace(destination)
        return result


class Study:
    def __init__(self, folder, start, end):
        self.folder = folder
        self.start = start
        self.end = end
        self.stop = asyncio.Event()
        self.active = {}
        self.windows = Counter()
        self.occupied = Counter()
        self.hourly_candidates = Counter()
        self.last_selected = {}
        self.jobs = set()
        self.encoder = asyncio.Semaphore(1)
        self.candidates = {}
        self.audience = {}
        self.games = {}
        self.failures = Counter()
        self.clip_dir = folder / "clips"
        self.clip_dir.mkdir()

    def emit(self, event_type, **details):
        now = time.time()
        with (self.folder / "eventos.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps({"at": utc(now), "type": event_type, **details}, ensure_ascii=False) + "\n")

    def selected(self, feed, end, metrics):
        hour = max(0, int((end - self.start) // 3600))
        group = feed.group
        if end - self.last_selected.get(feed.name, 0) < COOLDOWN:
            return
        # Pick two slots and times independently of their chat metrics.
        scheduler = Random(hour + 2929044358)
        control_slots = scheduler.sample(list(CHANNELS), MAX_CONTROLS)
        control_at = {slot: self.start + 3600 * hour + scheduler.randrange(300, 3200)
                      for slot in control_slots}
        target = control_at.get(group)
        control = target is not None and end - WINDOW <= target < end
        key = (hour, group, "control" if control else "candidate")
        # Reserve a slot for a later peak instead of taking both early in the hour.
        limit = 1 if control or (end - self.start) % 3600 < 1800 else MAX_CANDIDATES_PER_SLOT
        if self.occupied[key] >= limit or (not control and not metrics["rule"]):
            return
        if not control and self.hourly_candidates[hour] >= MAX_CLIPS:
            return
        clip_id = f"{len(self.candidates)+1:04d}-{feed.name}"
        self.occupied[key] += 1
        if not control:
            self.hourly_candidates[hour] += 1
        self.last_selected[feed.name] = end
        start, finish = end - PRE, end + POST
        self.candidates[clip_id] = {
            "id": clip_id, "channel": feed.name, "stream": feed.stream_id,
            "game": self.games.get((feed.name, feed.stream_id)),
            "slot": group, "kind": "control" if control else "candidate",
            "peakEnd": utc(end), "start": utc(start), "end": utc(finish),
            "peakTimestamp": end, "metrics": metrics, "status": "queued",
        }
        self.emit("selected", **self.candidates[clip_id])
        job = asyncio.create_task(feed.capture(clip_id, start, finish))
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)

    def update_report(self, status):
        state = {
            "status": status, "start": local(self.start), "deadline": local(self.end),
            "deadlineUtc": utc(self.end),
            "updated": local(time.time()), "activeChannels": [feed.name for feed in self.active.values()],
            "measuredWindows": dict(self.windows), "failures": dict(self.failures),
            "samples": list(self.candidates.values()),
        }
        save_text(self.folder / "estado.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        lines = [
            "# Estudo de clipping ao vivo", "",
            f"Estado: **{status}** · {state['start']} → {state['deadline']}", "",
            f"Última atualização: {state['updated']}", "",
            f"Canais ativos: {', '.join(state['activeChannels']) or 'nenhum'}", "",
            "| Canal | Janelas de chat (10 s) | Amostras de audiência |",
            "| --- | ---: | ---: |",
        ]
        audience_channels = {name for name, _ in self.audience}
        for name in sorted(set(self.windows) | audience_channels):
            samples = sum(len(values) for key, values in self.audience.items() if key[0] == name)
            lines.append(f"| {name} | {self.windows[name]} | {samples} |")
        threshold = 100 / VIEWERS_PER_REACTOR
        lines += ["", "## Candidatos e controlos", "",
                  f"Regra base: {threshold:.2f}% da audiência a reagir em 10 s, com um mínimo de quatro pessoas.",
                  "Em grandes diretos, também entram picos fortes que superem a rotina do próprio canal.",
                  "A lista liga a cada prévia. A ordem de revisão cega está em revisao.md.", "",
                  "| ID | Tipo | Regra | Pico UTC | Ritmo | Pessoas a reagir | Mínimo | Audiência no pico | Audiência antes → depois* | Vídeo |",
                  "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |"]
        for sample in self.candidates.values():
            timestamp = sample["peakTimestamp"]
            audience = self.audience.get((sample["channel"], sample["stream"]), ())
            before = [count for at, count in audience if timestamp - 180 <= at < timestamp - 15]
            after = [count for at, count in audience if timestamp + 30 <= at <= timestamp + 180]
            comparison = f"{median(before):g} → {median(after):g}" if len(before) >= 2 and len(after) >= 2 else "—"
            metric = sample["metrics"]
            video = f"[MP4](clips/{sample['id']}.mp4)" if sample["status"] == "ready" else sample["status"]
            rule = metric["rule"] if sample["kind"] == "candidate" else "—"
            lines.append(f"| {sample['id']} | {sample['kind']} | {rule} | {sample['peakEnd']} | "
                         f"{metric['rate']:.2f}× | {metric['reactors']} | {metric['minReactors'] or '—'} | "
                         f"{metric['viewers'] or '—'} | {comparison} | {video} |")
        lines += ["", "* Medianas de espectadores em simultâneo, com pelo menos duas amostras de cada lado. "
                          "A contagem não mede retenção individual.", ""]
        save_text(self.folder / "resultado.md", "\n".join(lines))
        ready = sorted(sample["id"] for sample in self.candidates.values() if sample["status"] == "ready")
        Random(int(self.start)).shuffle(ready)
        review = ["# Revisão sem pontuação", "",
                  "Para cada prévia, registar veredito, categoria, início, ação, fim e motivo.", "",
                  "| ID | Vídeo | Veredito | Categoria | Início / ação / fim | Motivo |",
                  "| --- | --- | --- | --- | --- | --- |"]
        review += [f"| {clip_id} | [MP4](clips/{clip_id}.mp4) | | | | |" for clip_id in ready]
        save_text(self.folder / "revisao.md", "\n".join(review) + "\n")

    async def run(self):
        self.emit("start", deadline=utc(self.end))
        discovery_at = 0
        live = {}
        self.update_report("em execução")
        status = "terminado"
        try:
            while time.time() < self.end and not (self.folder / "parar").exists():
                now = time.time()
                if now >= discovery_at:
                    try:
                        names = dict.fromkeys(name for group in CHANNELS.values() for name in group)
                        live = await asyncio.to_thread(live_channels, names)
                    except NETWORK_ERRORS as exc:
                        self.failures["discovery"] += 1
                        self.emit("discovery_error", reason=type(exc).__name__)
                    else:
                        self.assign(live, now)
                    discovery_at = time.time() + 45
                    self.update_report("em execução")
                if shutil.disk_usage(self.folder).free < 2 * 1024**3:
                    self.emit("stop", reason="disk")
                    break
                await asyncio.sleep(2)
        except Exception:
            status = "interrompido por erro"
            raise
        finally:
            self.stop.set()
            if self.jobs:
                await asyncio.wait(self.jobs, timeout=110)
            for feed in list(self.active.values()):
                await feed.close()
            for task in self.jobs.copy():
                task.cancel()
            for sample in self.candidates.values():
                if sample["status"] == "queued":
                    sample.update(status="indisponível", reason="Sessão terminou durante o corte")
            self.active.clear()
            self.emit("end")
            self.update_report(status)

    def assign(self, live, now):
        for group, feed in list(self.active.items()):
            if live.get(feed.name, {}).get("id") != feed.stream_id:
                asyncio.create_task(feed.close())
                del self.active[group]
        used = {feed.name for feed in self.active.values()}
        for group, preferences in CHANNELS.items():
            feed = self.active.get(group)
            if feed is not None:
                priority = preferences[0]
                if (
                    priority in used or (live.get(priority, {}).get("viewersCount") or 0) < MIN_CHANNEL_VIEWERS
                    or any(sample["channel"] == feed.name and sample["status"] == "queued"
                           for sample in self.candidates.values())
                ):
                    continue
                asyncio.create_task(feed.close())
                del self.active[group]
                used.remove(feed.name)
            name = next((n for n in preferences if n not in used and n in live
                         and (live[n].get("viewersCount") or 0) >= MIN_CHANNEL_VIEWERS), None)
            if name is None:
                continue
            self.active[group] = Feed(self, group, name, live[name]["id"])
            used.add(name)
        overflow = iter(name for name, stream in live.items()
                        if name not in used and (stream.get("viewersCount") or 0) >= MIN_CHANNEL_VIEWERS)
        for group in CHANNELS:
            if group not in self.active and (name := next(overflow, None)) is not None:
                self.active[group] = Feed(self, group, name, live[name]["id"])
        for feed in self.active.values():
            stream = live[feed.name]
            self.games[feed.name, feed.stream_id] = (stream.get("game") or {}).get("name")
            viewers = stream.get("viewersCount")
            if isinstance(viewers, int):
                self.audience.setdefault((feed.name, feed.stream_id), []).append((now, viewers))
                self.emit("audience", channel=feed.name, stream=feed.stream_id, viewers=viewers)


class Feed:
    def __init__(self, study, group, name, stream_id):
        self.study = study
        self.group = group
        self.name = name
        self.stream_id = stream_id
        self.stop = asyncio.Event()
        self.segments = {}
        self.buckets = {}
        self.history = deque(maxlen=18)
        self.connected = False
        self.next_window = (int(time.time()) // WINDOW + 1) * WINDOW
        self.tasks = [
            asyncio.create_task(chat(name, self.receive, self.emit, self.stop)),
            asyncio.create_task(self.video()),
            asyncio.create_task(self.score()),
        ]
        self.emit("channel_started", slot=group, stream=stream_id)

    def emit(self, kind, **details):
        if kind in ("chat_connected", "chat_error"):
            self.connected = kind == "chat_connected"
            self.history.clear()
            self.buckets.clear()
            self.next_window = (int(time.time()) // WINDOW + 1) * WINDOW
        self.study.emit(kind, channel=self.name, **details)

    def receive(self, timestamp, user, text, emotes=()):
        start = int(timestamp) // WINDOW * WINDOW
        if self.connected and self.next_window <= start <= time.time() + WINDOW:
            self.buckets.setdefault(start, Window()).add(user, text, emotes)

    async def close(self):
        self.stop.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.emit("channel_stopped", stream=self.stream_id)

    async def video(self):
        playlist = None
        failures = 0
        while not self.stop.is_set():
            try:
                if playlist is None:
                    playlist = await asyncio.to_thread(public_playlist, self.name, 1080)
                body = (await asyncio.to_thread(fetch, playlist)).decode()
                if "#EXTM3U" not in body:
                    raise ValueError("Resposta sem playlist")
                segments = list(media_segments(playlist, body))
                cutoff = time.time() - 180
                self.segments = {key: value for key, value in self.segments.items() if value.end >= cutoff}
                for segment in segments:
                    self.segments[round(segment.utc, 2)] = segment
                failures = 0
                await asyncio.sleep(3)
            except NETWORK_ERRORS as exc:
                failures += 1
                self.study.failures["playlist"] += 1
                if failures == 1 or failures % 5 == 0:
                    self.emit("video_error", reason=type(exc).__name__)
                playlist = None
                await asyncio.sleep(min(45, 3 * failures))

    async def score(self):
        while not self.stop.is_set() and not self.study.stop.is_set():
            # On resume after Windows sleep, don't backfill disconnected time as zero chat.
            now = time.time()
            if now - self.next_window > 45:
                self.history.clear()
                self.next_window = (int(now) // WINDOW + 1) * WINDOW
                self.buckets.clear()
            if self.connected and self.next_window + WINDOW + 2 <= now:
                start = self.next_window
                window = self.buckets.pop(start, Window())
                self.next_window += WINDOW
                end = start + WINDOW
                audience = self.study.audience.get((self.name, self.stream_id), ())
                viewers = next((count for at, count in reversed(audience)
                                if end - AUDIENCE_MAX_AGE <= at <= end), None)
                metric = evaluate(window, self.history, viewers)
                metric["experimentalSignals"] = window.extra_signals.top(
                    participants=len(window.participants),
                    baseline=[(prior.extra_signals, len(prior.participants)) for prior in self.history],
                )
                flow = chat_flow(Activity(window.messages, len(window.participants)),
                                 [Activity(prior.messages, len(prior.participants)) for prior in self.history], viewers)
                if flow is not None:
                    recent_people = set().union(*(prior.participants for prior in self.history))
                    flow["peopleAbsentFromBaseline"] = len(window.participants - recent_people)
                    metric["experimentalFlow"] = flow
                self.study.windows[self.name] += 1
                self.emit("window", stream=self.stream_id, start=utc(start), **metric)
                # Leave time to finish fetching and encoding before the daytime cutoff.
                if len(self.history) >= 6 and self.segments and end + POST + CAPTURE_RESERVE < self.study.end:
                    self.study.selected(self, end, metric)
                self.history.append(window)
            await asyncio.sleep(0.5)

    async def capture(self, clip_id, start, end):
        sample = self.study.candidates[clip_id]
        reason = "Janela de vídeo indisponível"
        try:
            while time.time() < end + 35 and not self.stop.is_set():
                try:
                    segments = clip_segments(self.segments.values(), start, end)
                except ValueError as exc:
                    reason = str(exc)
                    await asyncio.sleep(2)
                    continue
                async with self.study.encoder:
                    path = self.study.clip_dir / f"{clip_id}.mp4"
                    master = self.study.folder / "masters" / path.name if sample["kind"] == "candidate" else None
                    media = await asyncio.to_thread(write_capture, segments, start, end, path, master)
                if "masterError" in media:
                    self.study.failures["master"] += 1
                sample.update(status="ready", **media)
                self.emit("clip_ready", id=clip_id, **media)
                return
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            reason = type(exc).__name__
        sample.update(status="indisponível", reason=reason)
        self.study.failures["clip"] += 1
        self.emit("clip_unavailable", id=clip_id, reason=reason)


def preflight():
    names = dict.fromkeys(name for group in CHANNELS.values() for name in group)
    live = live_channels(names)
    verified = []
    for name, stream in list(live.items())[:5]:
        try:
            playlist = public_playlist(name, 1080)
            segments = list(media_segments(playlist, fetch(playlist).decode()))
            if not segments:
                continue
            with TemporaryDirectory(prefix="chatscope-preflight-") as temp:
                segment = segments[-1]
                media = write_capture(
                    [segment], segment.utc, segment.end, Path(temp) / "preview.mp4",
                    Path(temp) / "masters" / "source.mp4",
                )
            verified.append({"channel": name, "viewers": stream.get("viewersCount"),
                             "previewSeconds": media["seconds"], "sourceHeight": media.get("master", {}).get("height"),
                             "playlistClockLag": round(time.time() - segment.end, 2)})
        except (NETWORK_ERRORS + (subprocess.SubprocessError,)):
            continue
        if len(verified) == 3:
            break
    print(json.dumps({"live": len(live), "playbackChecks": verified}, indent=2))
    if not verified:
        raise SystemExit("Sem fontes públicas verificadas neste momento")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="Verificação pontual sem iniciar a recolha")
    run = commands.add_parser("run", help="Iniciar a recolha diurna")
    run.add_argument("--hours", type=float, default=8)
    run.add_argument("--folder", type=Path, required=True)
    run.add_argument("--fora-do-horario", action="store_true")
    args = parser.parse_args()
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        parser.error("FFmpeg e FFprobe são necessários")
    if args.command == "preflight":
        preflight()
        return
    if not 0 < args.hours <= 10:
        parser.error("Escolhe uma duração entre 0 e 10 horas")
    start = time.time()
    end = session_deadline(start, args.hours, args.fora_do_horario)
    if not args.fora_do_horario and (end - start < 120 or datetime.fromtimestamp(start, LISBON).hour < 8):
        parser.error("A recolha só corre entre as 08:00 e as 22:00 de Lisboa")
    folder = args.folder.resolve()
    if not folder.is_relative_to(RESULTS.resolve()) or folder == RESULTS.resolve():
        parser.error("A sessão precisa de uma pasta própria dentro dos resultados do estudo")
    folder.mkdir(parents=True, exist_ok=True)
    asyncio.run(Study(folder, start, end).run())


if __name__ == "__main__":
    main()
