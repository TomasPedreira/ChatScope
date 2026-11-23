"""Render selected edits and upload them privately for YouTube review."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from getpass import getpass
from hashlib import file_digest, sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time
from urllib.parse import urlsplit

import shorts_youtube as youtube
from shorts_style import format_description, timed_captions


ROOT = Path(__file__).resolve().parents[3]
MEDIA = ROOT / "media" / "twitch" / "shorts"
CONFIG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ChatScope" / "Shorts"
INTERVAL = 60
PUBLICATION_GAP = 30 * 60


def save_config(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_config(path, command):
    if not path.is_file():
        raise ValueError(f"Falta a configuração local. Usa o comando {command}.")
    return json.loads(path.read_text(encoding="utf-8"))


def queue():
    CONFIG.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CONFIG / "queue.sqlite")
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS shorts (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, digest TEXT NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL, made_for_kids INTEGER NOT NULL,
            session_url TEXT, video_id TEXT, notified INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_titles (
            short_id TEXT PRIMARY KEY REFERENCES shorts(id),
            title TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_publications (
            short_id TEXT PRIMARY KEY REFERENCES shorts(id),
            session TEXT NOT NULL, candidate TEXT NOT NULL,
            reason TEXT NOT NULL, published_at TEXT,
            UNIQUE(session, candidate)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_reviews (
            short_id TEXT PRIMARY KEY REFERENCES short_publications(short_id),
            action_at REAL NOT NULL, action TEXT NOT NULL,
            outcome_at REAL NOT NULL, outcome TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_publication_clock (
            slot INTEGER PRIMARY KEY CHECK (slot = 1),
            next_available REAL NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_withdrawals (
            short_id TEXT PRIMARY KEY REFERENCES short_publications(short_id),
            withdrawn_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS short_metrics (
            video_id TEXT NOT NULL, measured_at TEXT NOT NULL,
            published_at TEXT NOT NULL, views INTEGER,
            likes INTEGER, comments INTEGER, duration TEXT NOT NULL,
            PRIMARY KEY(video_id, measured_at)
        )
    """)
    return connection


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def probe(path):
    output = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height:format=duration", "-of", "json", str(path),
    ])
    media = json.loads(output)
    video = next((s for s in media["streams"] if s["codec_type"] == "video"), None)
    seconds = float(media["format"]["duration"])
    if not video or not 0 < seconds <= 180:
        raise ValueError("Escolhe um corte de vídeo com até três minutos.")
    return video["width"], video["height"], seconds


def crop(value, width, height):
    if not re.fullmatch(r"\d+:\d+:\d+:\d+", value):
        raise ValueError("O recorte usa largura:altura:x:y.")
    w, h, x, y = map(int, value.split(":"))
    if min(w, h) < 2 or x + w > width or y + h > height:
        raise ValueError("O recorte fica fora da imagem.")
    return f"{w}:{h}:{x}:{y}"


def render(source, destination, game_crop, face_crop, captions=None, trim=None, cuts=None, face_only=()):
    width, height, duration = probe(source)
    seek = []
    audio = []
    audio_map = "0:a:0?"
    norm = "loudnorm=I=-16:TP=-2:LRA=7,aresample=48000"
    splice = []
    if cuts:
        if not all(0 <= start < end <= duration for start, end in cuts):
            raise ValueError("Os cortes precisam de ficar dentro do vídeo.")
        duration = round(sum(end - start for start, end in cuts), 3)
        for index, (start, end) in enumerate(cuts):
            splice.extend((
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[partv{index}]",
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[parta{index}]",
            ))
        inputs = "".join(f"[partv{index}][parta{index}]" for index in range(len(cuts)))
        splice.extend((f"{inputs}concat=n={len(cuts)}:v=1:a=1[edit][sound]", f"[sound]{norm}[audio]"))
        audio_map = "[audio]"
    elif trim is not None:
        start, end = trim
        if not 0 <= start < end <= duration:
            raise ValueError("O corte precisa de ficar dentro do vídeo.")
        duration = round(end - start, 3)
        seek = ["-ss", f"{start:.3f}"]
        audio = ["-t", f"{duration:.3f}", "-af", norm]
    backdrop = (
        "[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
        "gblur=sigma=16,eq=brightness=-0.16:saturation=0.65,scale=1080:1920[base];"
    )
    if face_only and (not game_crop or not face_crop or
                      not all(0 <= start < end <= duration for start, end in face_only)):
        raise ValueError("O destaque da cara precisa dos dois recortes e de tempos dentro da edição.")
    fit = "force_original_aspect_ratio=decrease:force_divisible_by=2"
    if game_crop and face_crop:
        game = crop(game_crop, width, height)
        face = crop(face_crop, width, height)
        game_height = 730 if captions else 1100
        game_top = "744+(730-h)/2" if captions else "660+(1100-h)/2"
        start_graph = (
            "[0:v]split=3[bg][game][face];" + backdrop
            + f"[game]crop={game},scale=1080:{game_height}:{fit}:flags=lanczos,setsar=1[play];"
        )
        if face_only:
            when = "+".join(f"gte(t,{start:.3f})*lt(t,{end:.3f})" for start, end in face_only)
            graph = (
                start_graph + f"[face]crop={face},split[small][large];"
                + f"[small]scale=760:500:{fit},setsar=1[cam];"
                + f"[large]scale=1080:1050:{fit}:flags=lanczos,setsar=1[focus];"
                + f"[base][cam]overlay=(W-w)/2:80+(600-h)/2:enable='not({when})'[panel];"
                + f"[panel][play]overlay=(W-w)/2:{game_top}:enable='not({when})'[mixed];"
                + f"[mixed][focus]overlay=(W-w)/2:(1420-h)/2:enable='{when}',setsar=1[v]"
            )
        else:
            graph = (
                start_graph + f"[face]crop={face},scale=760:500:{fit},setsar=1[cam];"
                + "[base][cam]overlay=(W-w)/2:80+(600-h)/2[panel];"
                + f"[panel][play]overlay=(W-w)/2:{game_top},setsar=1[v]"
            )
    elif face_crop:
        face = crop(face_crop, width, height)
        graph = (
            f"[0:v]crop={face},split[bg][face];" + backdrop
            + f"[face]scale=1080:1120:{fit}:flags=lanczos,setsar=1[focus];"
            + "[base][focus]overlay=(W-w)/2:(1420-h)/2,setsar=1[v]"
        )
    elif game_crop:
        raise ValueError("Indica os dois recortes para separar o jogo e a câmera.")
    else:
        game_height = 1120 if captions else 1920
        graph = (
            "[0:v]split[bg][game];" + backdrop
            + f"[game]scale=1080:{game_height}:{fit}:flags=lanczos,setsar=1[play];"
            + "[base][play]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
        )
    with TemporaryDirectory(prefix="chatscope-short-") as scratch:
        if captions:
            ass = timed_captions(captions.decode("utf-8-sig"), duration)
            (Path(scratch) / "caption.ass").write_text(ass, encoding="utf-8-sig")
            graph = graph.removesuffix("[v]") + ",ass=caption.ass[v]"
        if splice:
            graph = ";".join([*splice, graph.replace("[0:v]", "[edit]")])
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            *seek, "-i", str(source.resolve()),
            "-filter_complex_threads", "3", "-filter_complex", graph, "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-threads", "4",
            *audio, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination.resolve()),
        ], cwd=scratch, check=True)
    if probe(destination)[:2] != (1080, 1920):
        raise ValueError("O Short não saiu em 1080 × 1920.")


def enqueue(args):
    source = args.source.resolve(strict=True)
    title = args.title.strip()
    description = format_description(args.description, args.hashtags, args.twitch_url, args.youtube_url)
    if not title or len(title) > 100 or len(description.encode("utf-8")) > 5000:
        raise ValueError("Usa um título de até 100 caracteres e uma descrição de até 5 000 bytes.")
    clip_id = digest(source)
    if args.renderizado and (args.game_crop or args.face_crop or args.legendas):
        raise ValueError("Um Short já renderizado entra sem recortes ou legendas adicionais.")
    captions = args.legendas.read_bytes() if args.legendas else None
    if captions is not None:
        if not captions:
            raise ValueError("O ficheiro de legendas está vazio.")
        render_key = json.dumps([clip_id, args.game_crop, args.face_crop]).encode()
        clip_id = sha256(render_key + captions).hexdigest()
    with closing(queue()) as db, db:
        present = db.execute("SELECT path FROM shorts WHERE id = ?", (clip_id,)).fetchone()
        if present:
            return Path(present["path"])
    if args.renderizado:
        if probe(source)[:2] != (1080, 1920):
            raise ValueError("Um Short já renderizado precisa de 1080 × 1920 e entra sem recortes adicionais.")
        with closing(queue()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO shorts(id,path,digest,title,description,made_for_kids) VALUES (?,?,?,?,?,?)",
                (clip_id, str(source), clip_id, title, description, int(args.made_for_kids)),
            )
            row = db.execute("SELECT path FROM shorts WHERE id = ?", (clip_id,)).fetchone()
        return Path(row["path"])
    MEDIA.mkdir(parents=True, exist_ok=True)
    destination = MEDIA / f"{source.stem}-{clip_id[:12]}.mp4"
    with NamedTemporaryFile(dir=MEDIA, suffix=".mp4", delete=False) as file:
        temporary = Path(file.name)
    try:
        render(source, temporary, args.game_crop, args.face_crop, captions)
        checksum = digest(temporary)
        with closing(queue()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            present = db.execute("SELECT path FROM shorts WHERE id = ?", (clip_id,)).fetchone()
            if present:
                return Path(present["path"])
            temporary.replace(destination)
            db.execute(
                "INSERT INTO shorts(id,path,digest,title,description,made_for_kids) VALUES (?,?,?,?,?,?)",
                (clip_id, str(destination), checksum, title, description, int(args.made_for_kids)),
            )
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def connect(args):
    from google.oauth2.credentials import Credentials

    if args.channel and not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", args.channel):
        raise ValueError("Usa o ID do canal de revisão, começado por UC.")
    existing = CONFIG / "youtube.json"
    pending = CONFIG / "youtube-pendente.json"
    saved_channel = load_config(existing, "ligar")["channel"] if existing.is_file() else None
    if saved_channel and args.channel and saved_channel != args.channel:
        raise ValueError("A fila já está ligada a outro canal. A ligação só pode ser renovada para o mesmo canal.")
    expected = args.channel or saved_channel
    if args.resume:
        saved = load_config(pending, "ligar")
        if expected and saved["expected"] and expected != saved["expected"]:
            raise ValueError("A autorização pendente foi pedida para outro canal.")
        expected = expected or saved["expected"]
        info = saved["credentials"]
        credentials = Credentials.from_authorized_user_info(info, info.get("scopes") or youtube.SCOPES)
    else:
        if not args.client:
            raise ValueError("Indica o ficheiro JSON do cliente em --client.")
        credentials = youtube.connect(args.client, args.account)
        if not credentials.refresh_token:
            raise ValueError("O Google não concedeu acesso para o envio em segundo plano.")
        save_config(pending, {"expected": expected, "credentials": json.loads(credentials.to_json())})
    with youtube.authorized_session(credentials) as session:
        channel_id, name = youtube.selected_channel(session)
    if expected and channel_id != expected:
        raise ValueError("A conta autorizada não corresponde ao ID do canal de revisão.")
    if not expected:
        print(f"Canal escolhido no YouTube: {name} ({channel_id})", flush=True)
        if input("Se este for o canal de revisão, escreve o ID para confirmar: ").strip() != channel_id:
            raise ValueError("Ligação por confirmar.")
    save_config(existing, {"channel": channel_id, "credentials": json.loads(credentials.to_json())})
    pending.unlink(missing_ok=True)
    print(f"Canal de revisão ligado: {name}")


def studio_link(video_id):
    return f"https://studio.youtube.com/video/{video_id}/edit"


def stage_title(source, title):
    title = title.strip()
    if not 0 < len(title) <= 100:
        raise ValueError("Usa um título de até 100 caracteres.")
    with closing(queue()) as db, db:
        row = db.execute("SELECT id FROM shorts WHERE path=?", (str(source.resolve()),)).fetchone()
        if row is None:
            raise ValueError("O ficheiro ainda não está na fila de Shorts.")
        db.execute("""
            INSERT INTO short_titles(short_id, title) VALUES (?, ?)
            ON CONFLICT(short_id) DO UPDATE SET title=excluded.title
        """, (row["id"], title))


def apply_titles_before_upload(db):
    with db:
        db.execute("""
            UPDATE shorts SET title = (SELECT title FROM short_titles WHERE short_id=shorts.id)
            WHERE video_id IS NULL AND session_url IS NULL
              AND id IN (SELECT short_id FROM short_titles)
        """)
        db.execute("""
            DELETE FROM short_titles WHERE short_id IN (
                SELECT id FROM shorts WHERE video_id IS NULL AND session_url IS NULL
            )
        """)


def apply_uploaded_titles(db, session, channel_id):
    import requests

    edits = db.execute("""
        SELECT short_titles.short_id, short_titles.title, video_id,
               published_at IS NOT NULL AND withdrawn_at IS NULL AS allow_public
        FROM short_titles
        JOIN shorts ON shorts.id=short_titles.short_id
        LEFT JOIN short_publications ON short_publications.short_id=shorts.id
        LEFT JOIN short_withdrawals ON short_withdrawals.short_id=shorts.id
        WHERE video_id IS NOT NULL
    """).fetchall()
    for edit in edits:
        try:
            youtube.update_title(session, edit["video_id"], channel_id, edit["title"],
                                 allow_public=bool(edit["allow_public"]))
        except (youtube.UploadError, requests.RequestException) as error:
            detail = str(error) if isinstance(error, youtube.UploadError) else type(error).__name__
            print(f"Título pendente: {detail}", file=sys.stderr, flush=True)
            continue
        with db:
            db.execute("UPDATE shorts SET title=? WHERE id=?", (edit["title"], edit["short_id"]))
            db.execute("DELETE FROM short_titles WHERE short_id=? AND title=?",
                       (edit["short_id"], edit["title"]))


def configure_alerts(args):
    endpoint = urlsplit(args.topic)
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or not re.fullmatch(r"/[A-Za-z0-9_-]+", endpoint.path)):
        raise ValueError("Indica o endereço HTTPS completo do tópico privado do ntfy.")
    token = getpass("Token do tópico ntfy: ").strip()
    if not token:
        raise ValueError("Falta o token do tópico ntfy.")
    save_config(CONFIG / "alerts.json", {"topic": args.topic, "token": token})


def notify(alerts, video_id, title):
    import requests

    result = requests.post(
        alerts["topic"], data=f"Short privado pronto para rever: {title}".encode("utf-8"),
        headers={"Authorization": f"Bearer {alerts['token']}", "Title": "Short pronto para rever",
                 "Click": studio_link(video_id), "Priority": "high"},
        timeout=15, allow_redirects=False,
    )
    if not 200 <= result.status_code < 300:
        raise ValueError(f"O aviso ntfy devolveu HTTP {result.status_code}.")


@contextmanager
def worker_lock():
    import msvcrt

    CONFIG.mkdir(parents=True, exist_ok=True)
    with (CONFIG / "worker.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError("Já está a correr um trabalhador da fila Shorts.") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def upload_private(db, session, row):
    video_id = row["video_id"]
    if not video_id:
        path = Path(row["path"])
        if digest(path) != row["digest"]:
            raise ValueError("O ficheiro preparado foi alterado depois de entrar na fila.")
        size = path.stat().st_size
        upload = row["session_url"]
        if not upload:
            upload = youtube.begin_upload(
                session, size, row["title"], row["description"], bool(row["made_for_kids"]),
            )
            with db:
                db.execute("UPDATE shorts SET session_url=? WHERE id=?", (upload, row["id"]))
        with path.open("rb") as file:
            video_id = youtube.send_media(session, upload, file, size)
        with db:
            db.execute("UPDATE shorts SET video_id=?,session_url=NULL WHERE id=?", (video_id, row["id"]))
    return video_id


def process_job(db, session, channel_id, alerts, row):
    video_id = upload_private(db, session, row)
    if youtube.video_status(session, video_id, channel_id):
        if alerts is None:
            print(f"Short privado pronto para rever: {studio_link(video_id)}", flush=True)
            return
        notify(alerts, video_id, row["title"])
        with db:
            db.execute("UPDATE shorts SET notified=1 WHERE id=?", (row["id"],))
        print(f"Aviso enviado: {studio_link(video_id)}", flush=True)


def reserve_publication(db, now, *, skip_gap=False):
    # Keep a buffer for an edit request whose response may be lost after it takes effect.
    with db:
        reservation = db.execute("""
            INSERT INTO short_publication_clock(slot, next_available) VALUES (1, ?)
            ON CONFLICT(slot) DO UPDATE SET next_available=excluded.next_available
            WHERE short_publication_clock.next_available <= ? OR ?
        """, (now + PUBLICATION_GAP + 30, now, skip_gap))
        if reservation.rowcount:
            return None
        return db.execute("SELECT next_available FROM short_publication_clock WHERE slot=1").fetchone()[0]


def record_withdrawal(db, short_id):
    with db:
        db.execute(
            "INSERT OR IGNORE INTO short_withdrawals(short_id,withdrawn_at) VALUES (?,?)",
            (short_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def collect_metrics(db, session, channel_id):
    ids = [row[0] for row in db.execute("SELECT DISTINCT video_id FROM shorts WHERE video_id IS NOT NULL")]
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    measurements = []
    for start in range(0, len(ids), 50):
        batch = youtube.checked(session.get(
            youtube.API + "videos",
            params={"part": "snippet,status,statistics,contentDetails", "id": ",".join(ids[start:start + 50])},
            timeout=20, allow_redirects=False,
        )).json()
        for item in batch.get("items", ()):
            details = item["snippet"]
            if details["channelId"] != channel_id or item["status"]["privacyStatus"] != "public":
                continue
            published = details.get("publishedAt")
            if not published:
                continue
            statistics = item.get("statistics", {})
            views, likes, comments = (
                int(statistics[key]) if key in statistics else None
                for key in ("viewCount", "likeCount", "commentCount")
            )
            duration = item.get("contentDetails", {}).get("duration", "")
            measurements.append((item["id"], stamp, published, views, likes, comments, duration))
    with db:
        db.executemany("INSERT OR REPLACE INTO short_metrics VALUES (?,?,?,?,?,?,?)", measurements)
    return stamp, len(measurements)


def refresh_feedback():
    from google.oauth2.credentials import Credentials

    settings = load_config(CONFIG / "youtube.json", "ligar")
    info = settings["credentials"]
    credentials = Credentials.from_authorized_user_info(info, info.get("scopes") or youtube.SCOPES)
    with closing(queue()) as db, youtube.authorized_session(credentials) as session:
        youtube.verify_channel(session, settings["channel"])
        stamp, _ = collect_metrics(db, session, settings["channel"])
        rows = db.execute("""
            SELECT shorts.title, metric.* FROM short_metrics AS metric
            JOIN shorts ON shorts.video_id=metric.video_id
            WHERE metric.measured_at=?
            ORDER BY metric.published_at
        """, (stamp,))
        result = []
        for row in rows:
            item = dict(row)
            age = datetime.fromisoformat(item["measured_at"]) - datetime.fromisoformat(item["published_at"])
            item["ageMinutes"] = round(age.total_seconds() / 60)
            result.append(item)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def review_evidence(action, outcome, duration):
    action_at, action_text = action
    outcome_at, outcome_text = outcome
    try:
        action_at, outcome_at = float(action_at), float(outcome_at)
    except ValueError:
        raise ValueError("Indica os tempos da ação e do desfecho em segundos.") from None
    if not (isfinite(duration) and 0 <= action_at < outcome_at < duration):
        raise ValueError("A ação e o desfecho têm de aparecer por ordem dentro do corte final.")
    action_text, outcome_text = action_text.strip(), outcome_text.strip()
    if not action_text or not outcome_text or action_text.casefold() == outcome_text.casefold():
        raise ValueError("Descreve o que acontece no vídeo e o desfecho que se vê ou ouve.")
    return action_at, action_text, outcome_at, outcome_text


def publish_draft(args):
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import GoogleAuthError
    from requests import RequestException
    from drafts import verified_draft

    study_session, candidate, source = verified_draft(args.source)
    reason = args.reason.strip()
    if not reason:
        raise ValueError("Regista o motivo editorial para publicar este corte.")
    _, _, duration = probe(source)
    evidence = review_evidence(args.action_evidence, args.outcome_evidence, duration)
    settings = load_config(CONFIG / "youtube.json", "ligar")
    info = settings["credentials"]
    scopes = info.get("scopes") or youtube.SCOPES
    if youtube.EDIT_SCOPE not in scopes:
        raise ValueError("O canal ainda precisa da permissão de edição.")
    credentials = Credentials.from_authorized_user_info(info, scopes)
    channel_id = settings["channel"]
    short_id = digest(source)
    with worker_lock(), closing(queue()) as db, youtube.authorized_session(credentials) as session:
        youtube.verify_channel(session, channel_id)
        existing = db.execute(
            """SELECT short_publications.short_id, published_at, withdrawn_at
               FROM short_publications LEFT JOIN short_withdrawals
               ON short_publications.short_id=short_withdrawals.short_id
               WHERE session=? AND candidate=?""",
            (study_session.name, candidate["id"]),
        ).fetchone()
        if existing and existing["withdrawn_at"]:
            raise ValueError("Este Short foi retirado da publicação.")
        if existing and existing["short_id"] != short_id:
            raise ValueError("Já existe uma decisão de publicação para outro corte deste candidato.")
        args.source = source
        args.twitch_url = f"https://www.twitch.tv/{candidate['channel']}"
        args.renderizado = True
        args.game_crop = args.face_crop = args.legendas = None
        args.made_for_kids = False
        enqueue(args)
        with db:
            db.execute(
                """INSERT OR IGNORE INTO short_publications(short_id,session,candidate,reason) VALUES (?,?,?,?)""",
                (short_id, study_session.name, candidate["id"], reason),
            )
            db.execute(
                "INSERT OR IGNORE INTO short_reviews(short_id,action_at,action,outcome_at,outcome) VALUES (?,?,?,?,?)",
                (short_id, *evidence),
            )
            db.execute("UPDATE shorts SET title=? WHERE id=? AND video_id IS NULL AND session_url IS NULL",
                       (args.title.strip(), short_id))
        row = db.execute("SELECT * FROM shorts WHERE id=?", (short_id,)).fetchone()
        video_id = upload_private(db, session, row)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            video = youtube.lookup_video(session, video_id)
            if video is not None:
                status = video["status"]["uploadStatus"]
                if status in ("deleted", "failed", "rejected"):
                    raise youtube.UploadError(f"O YouTube devolveu o estado {status}.")
                if existing and existing["published_at"] and video["status"]["privacyStatus"] != "public":
                    record_withdrawal(db, short_id)
                    raise ValueError("Este Short foi retirado da publicação.")
                if status == "processed":
                    was_private = video["status"]["privacyStatus"] == "private"
                    if was_private:
                        if video["snippet"]["title"] != args.title.strip():
                            youtube.update_title(session, video_id, channel_id, args.title.strip())
                        available = reserve_publication(db, time.time(), skip_gap=getattr(args, "skip_gap", False))
                        if available is not None:
                            when = datetime.fromtimestamp(available).isoformat(timespec="seconds")
                            print(f"Short processado e privado. Próxima publicação disponível {when}.")
                            return
                    youtube.publish_video(session, video, channel_id)
                    confirmed = time.time()
                    stamp = datetime.fromtimestamp(confirmed, timezone.utc).isoformat(timespec="seconds")
                    with db:
                        if was_private:
                            db.execute("UPDATE short_publication_clock SET next_available=? WHERE slot=1",
                                       (confirmed + PUBLICATION_GAP,))
                        db.execute(
                            "UPDATE short_publications SET published_at=COALESCE(published_at, ?) WHERE short_id=?",
                            (stamp, short_id),
                        )
                    print(f"Publicado · https://www.youtube.com/shorts/{video_id}")
                    if was_private:
                        try:
                            _, count = collect_metrics(db, session, channel_id)
                            print(f"Métricas guardadas para {count} Shorts públicos.")
                        except (youtube.UploadError, RequestException, GoogleAuthError) as error:
                            print(f"Métricas pendentes ({type(error).__name__}).", file=sys.stderr)
                    return
            time.sleep(5)
        raise ValueError(f"O YouTube ainda está a processar {video_id}. O upload fica guardado para retoma.")


def resume_publication(short_id, not_before):
    earliest = datetime.fromisoformat(not_before)
    if earliest.tzinfo is None:
        raise ValueError("Indica a hora da retoma com fuso horário.")
    if datetime.now(timezone.utc) < earliest:
        raise ValueError(f"Retoma disponível a partir de {earliest.isoformat()}.")

    with closing(queue()) as db:
        approved = db.execute("""
            SELECT shorts.path, COALESCE(short_titles.title, shorts.title) AS title,
                   short_publications.reason, short_publications.published_at, withdrawn_at,
                   action_at, action, outcome_at, outcome
            FROM short_publications
            JOIN shorts ON shorts.id=short_publications.short_id
            JOIN short_reviews ON short_reviews.short_id=shorts.id
            LEFT JOIN short_titles ON short_titles.short_id=shorts.id
            LEFT JOIN short_withdrawals ON short_withdrawals.short_id=shorts.id
            WHERE shorts.id=?
        """, (short_id,)).fetchone()
    if approved is None or approved["withdrawn_at"]:
        raise ValueError("A retoma exige uma publicação aprovada e com revisão registada.")
    if approved["published_at"]:
        print("Este Short já foi publicado.")
        return
    source = Path(approved["path"])
    if digest(source) != short_id:
        raise ValueError("O ficheiro aprovado mudou depois da revisão.")
    publish_draft(argparse.Namespace(
        source=source,
        title=approved["title"],
        reason=approved["reason"],
        action_evidence=(approved["action_at"], approved["action"]),
        outcome_evidence=(approved["outcome_at"], approved["outcome"]),
        description="", youtube_url=None, hashtags=(),
    ))


def process(db, alerts):
    from google.oauth2.credentials import Credentials
    import requests

    apply_titles_before_upload(db)
    has_edits = db.execute("SELECT 1 FROM short_titles LIMIT 1").fetchone() is not None
    pending = "WHERE notified=0 AND id NOT IN (SELECT short_id FROM short_publications)"
    has_jobs = db.execute("SELECT 1 FROM shorts " + pending + " LIMIT 1").fetchone() is not None
    if not (has_edits or has_jobs):
        return
    settings = load_config(CONFIG / "youtube.json", "ligar")
    info = settings["credentials"]
    scopes = info.get("scopes") or youtube.SCOPES
    can_edit = youtube.EDIT_SCOPE in scopes
    if not has_jobs and not can_edit:
        return
    credentials = Credentials.from_authorized_user_info(info, scopes)
    with youtube.authorized_session(credentials) as session:
        youtube.verify_channel(session, settings["channel"])
        if can_edit and has_edits:
            apply_uploaded_titles(db, session, settings["channel"])
        jobs = db.execute("SELECT * FROM shorts " + pending + " ORDER BY rowid").fetchall()
        for row in jobs:
            try:
                process_job(db, session, settings["channel"], alerts, row)
            except (youtube.UploadError, ValueError) as error:
                print(f"{row['title']}: {error}", file=sys.stderr, flush=True)
            except (requests.RequestException, OSError) as error:
                print(f"{row['title']}: {type(error).__name__}; envio pendente.", file=sys.stderr, flush=True)


def status():
    with closing(queue()) as db:
        rows = db.execute("""
            SELECT shorts.*, short_titles.title AS pending_title, short_publications.published_at,
                   short_publications.reason AS review_reason, short_withdrawals.withdrawn_at
            FROM shorts LEFT JOIN short_titles ON short_titles.short_id=shorts.id
            LEFT JOIN short_publications ON short_publications.short_id=shorts.id
            LEFT JOIN short_withdrawals ON short_withdrawals.short_id=shorts.id ORDER BY shorts.rowid
        """)
        for row in rows:
            if row["withdrawn_at"]:
                label = "Retirado"
            elif row["published_at"]:
                label = "Publicado"
            elif row["review_reason"]:
                label = "Publicação pendente"
            elif row["notified"]:
                label = "Aviso enviado"
            elif row["video_id"]:
                label = "À espera de processamento ou aviso"
            elif row["session_url"]:
                label = "Upload iniciado"
            else:
                label = "Na fila"
            print(f"{label} · {row['title']}")
            print(studio_link(row["video_id"]) if row["video_id"] else row["path"])
            if row["pending_title"]:
                print(f"Novo título pendente · {row['pending_title']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("preparar", help="Renderizar um corte revisto e colocá-lo na fila")
    add.add_argument("source", type=Path)
    add.add_argument("--title", required=True)
    add.add_argument("--description", default="")
    add.add_argument("--twitch-url", help="Canal Twitch do criador para os créditos")
    add.add_argument("--youtube-url", help="Canal YouTube do criador para os créditos")
    add.add_argument("--game-crop")
    add.add_argument("--face-crop")
    add.add_argument("--legendas", type=Path, help="JSON com o tempo de cada palavra no clip")
    add.add_argument("--hashtags", nargs="+", default=(), help="Hashtags do criador, do jogo ou do momento")
    add.add_argument("--made-for-kids", action="store_true")
    add.add_argument("--renderizado", action="store_true", help="Usar um MP4 vertical já editado sem recodificar")
    rename = actions.add_parser("titulo", help="Guardar um novo título para um Short da fila")
    rename.add_argument("source", type=Path)
    rename.add_argument("--title", required=True)
    publish = actions.add_parser("publicar", help="Publicar um rascunho do direto após revisão editorial")
    publish.add_argument("source", type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--motivo", dest="reason", required=True)
    publish.add_argument("--acao", dest="action_evidence", nargs=2, metavar=("SEGUNDOS", "DESCRIÇÃO"), required=True)
    publish.add_argument("--desfecho", dest="outcome_evidence", nargs=2, metavar=("SEGUNDOS", "DESCRIÇÃO"),
                         required=True)
    publish.add_argument("--description", default="")
    publish.add_argument("--youtube-url")
    publish.add_argument("--hashtags", nargs="+", default=())
    publish.add_argument("--sem-intervalo", dest="skip_gap", action="store_true",
                         help="Publicar agora quando o utilizador dispensar o intervalo da fila")
    retry = actions.add_parser("retomar", help="Retomar uma publicação aprovada depois da hora indicada")
    retry.add_argument("short_id", help="Identificador do corte aprovado na fila")
    retry.add_argument("--apos", required=True, help="Hora ISO 8601 com fuso horário")
    link = actions.add_parser("ligar", help="Autorizar o canal privado de revisão")
    source = link.add_mutually_exclusive_group(required=True)
    source.add_argument("--client", type=Path, help="JSON do cliente OAuth")
    source.add_argument("--retomar", dest="resume", action="store_true", help="Reutilizar uma autorização pendente")
    link.add_argument("--channel", help="ID do canal, se já for conhecido")
    link.add_argument("--account", help="Endereço Google a sugerir no início de sessão")
    alerts = actions.add_parser("avisos", help="Configurar um tópico privado no ntfy")
    alerts.add_argument("--topic", required=True)
    actions.add_parser("estado", help="Ver a fila e os links para o Studio")
    actions.add_parser("feedback", help="Guardar vistas, gostos e comentários com a idade de cada Short")
    run = actions.add_parser("enviar", help="Tratar da fila de uploads privados")
    delivery = run.add_mutually_exclusive_group()
    delivery.add_argument("--vigiar", action="store_true")
    delivery.add_argument("--aviso-no-chat", action="store_true", help="Mostrar o link de revisão uma vez")
    args = parser.parse_args()

    try:
        if args.action == "preparar":
            print(enqueue(args))
        elif args.action == "titulo":
            stage_title(args.source, args.title)
            print("Título guardado na fila.")
        elif args.action in ("publicar", "retomar"):
            from google.auth.exceptions import GoogleAuthError
            from requests import RequestException

            try:
                if args.action == "retomar":
                    resume_publication(args.short_id, args.apos)
                else:
                    publish_draft(args)
            except (GoogleAuthError, RequestException) as error:
                raise ValueError(f"Ligação ao YouTube pendente ({type(error).__name__}).") from error
        elif args.action == "ligar":
            connect(args)
        elif args.action == "avisos":
            configure_alerts(args)
        elif args.action == "estado":
            status()
        elif args.action == "feedback":
            from google.auth.exceptions import GoogleAuthError
            from requests import RequestException

            try:
                refresh_feedback()
            except (GoogleAuthError, RequestException) as error:
                raise ValueError(f"Ligação ao YouTube pendente ({type(error).__name__}).") from error
        else:
            load_config(CONFIG / "youtube.json", "ligar")
            alerts = None if args.aviso_no_chat else load_config(CONFIG / "alerts.json", "avisos")
            with worker_lock(), closing(queue()) as db:
                while True:
                    from google.auth.exceptions import GoogleAuthError
                    import requests

                    try:
                        process(db, alerts)
                    except (GoogleAuthError, requests.RequestException) as error:
                        print(f"Ligação ao YouTube pendente ({type(error).__name__}).",
                              file=sys.stderr, flush=True)
                    if not args.vigiar:
                        break
                    time.sleep(INTERVAL)
    except (ValueError, youtube.UploadError, FileNotFoundError) as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        parser.exit()


if __name__ == "__main__":
    main()
