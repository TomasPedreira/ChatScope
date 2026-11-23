"""Read-only browser view for one study, served locally behind Tailscale Serve."""

import argparse
import json
import re
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


CLIP_ID = r"\d{4,}-[a-z0-9_]+"
SESSION_ID = r"\d{8}-\d{6}-[0-9a-f]{8}"
SHORT_NAME = r"\d{2}-[a-z0-9-]+\.mp4"


def render_selection(clips, base):
    players = []
    for clip in clips:
        if not re.fullmatch(SHORT_NAME, clip["file"]):
            continue
        title = escape(clip["title"])
        creator = escape(clip["creator"])
        source = escape(clip["source"], quote=True)
        video = f'{base}{clip["file"]}'
        chat = clip["chat"]
        evidence = (
            f'{chat["reactors"]} pessoas a reagir em {chat["messages"]} mensagens amostradas'
            if chat else "Momento sem replay de chat"
        )
        players.append(f"""
<article>
<p class="details">{creator} · {clip["duration"]:.0f} s</p>
<h2>{title}</h2>
<video controls playsinline preload="none" src="{video}" aria-label="{title}"></video>
<p class="details">{evidence}</p>
<p><a href="{video}" download>Transferir MP4</a> · <a href="{source}">Original na Twitch</a></p>
</article>
""")
    return f"""<!doctype html>
<html lang="pt-PT"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shorts para revisão</title>
<style>
:root {{ color-scheme: light dark }}
body {{ font: 1rem/1.45 system-ui, sans-serif; max-width: 58rem; margin: auto; padding: 1rem }}
header {{ border-bottom: 1px solid GrayText; margin-bottom: 1rem; padding-bottom: .65rem }}
h1 {{ font-size: 1.6rem; margin: 0 }} h2 {{ font-size: 1.05rem; margin: 0 }}
p {{ margin: .35rem 0 }}
section {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,16rem),1fr)); gap: 1rem }}
article {{ border: 1px solid GrayText; border-radius: .5rem; padding: .75rem }}
video {{ display: block; width: 100%; aspect-ratio: 9 / 16; background: #111; margin: .65rem 0 }}
.details {{ font-size: .85rem }}
</style>
<main>
<header><h1>Shorts para revisão</h1>
<p>{len(players)} cortes em inglês · <a href="{base}selecao.json">Descrições e hashtags</a></p></header>
<section>{"".join(players)}</section>
</main></html>
"""


def render_study(state, health, kind, clip_base="/clips"):
    clips = []
    for sample in reversed(state["samples"]):
        if sample["kind"] != kind:
            continue
        clip_id = sample["id"]
        metrics = sample["metrics"]
        audience = ""
        if metrics.get("viewers"):
            audience = f' de {metrics["viewers"]} espectadores'
            if kind == "candidate":
                audience += f' (mínimo de {metrics["minReactors"]})'
        status = {"queued": "A preparar", "unavailable": "Vídeo indisponível"}
        player = escape(status.get(sample["status"], "Vídeo indisponível"))
        if sample["status"] == "ready" and re.fullmatch(CLIP_ID, clip_id):
            source = f"{clip_base}/{clip_id}.mp4"
            player = (
                f'<video controls playsinline preload="none" src="{source}" '
                f'aria-label="Clip {clip_id}"></video><a href="{source}" download>'
                'Transferir MP4</a>'
            )
        peak = escape(sample["peakEnd"][11:19])
        clips.append(f"""
            <article><h2>{escape(clip_id)}</h2>
            <p>{peak} UTC · {metrics["rate"]:.2f}× mensagens ·
            {metrics["reactors"]} pessoas a reagir{audience}</p>{player}</article>
        """)

    if kind == "candidate":
        heading = "Clips candidatos"
        refresh = "/"
        other_view = '<a href="/amostras">Amostras aleatórias</a>'
        description = ""
        empty = "Ainda não há candidatos pela atividade do chat."
    else:
        heading = "Amostras aleatórias"
        refresh = "/amostras"
        other_view = '<a href="/">Clips candidatos</a>'
        description = "<p>Trechos sorteados para comparar com os candidatos.</p>"
        empty = "Ainda não há amostras aleatórias."

    active = escape(", ".join(state["activeChannels"]) or "Nenhum")
    check = escape(health.get("utc", "")[11:19] or "—")
    last_check = escape(health.get("status", "a iniciar"))
    updated = escape(state["updated"])
    channels = "".join(
        f"<li>{escape(channel)} · {count} janelas de chat</li>"
        for channel, count in state["measuredWindows"].items()
    )
    return f"""<!doctype html>
<html lang="pt-PT"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estudo de clips Twitch</title>
<style>
:root {{ color-scheme: light dark }}
body {{ font: 1rem/1.5 system-ui,sans-serif; max-width: 64rem; margin: auto; padding: 1.5rem }}
header {{ border-bottom: 1px solid GrayText; padding-bottom: 1rem; margin-bottom: 1rem }}
h1 {{ margin: 0 }} h2 {{ font-size: 1rem; margin: 0 }} p {{ margin: .4rem 0 }}
.clips {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit,minmax(min(100%,26rem),1fr)) }}
article {{ border: 1px solid GrayText; padding: 1rem; border-radius: .4rem }}
video {{ width: 100%; aspect-ratio: 16/9; background: #111; display: block; margin: .75rem 0 .4rem }}
</style>
<main><header>
<h1>{heading}</h1>
{description}
<p>{escape(state["status"]).capitalize()} · {active}</p>
<p>Atualizado {updated} · Até {escape(state["deadline"])}</p>
<p>Vigia às {check} UTC · {last_check}</p>
<ul>{channels}</ul>
<a href="{refresh}">Atualizar</a> · {other_view} · <a href="/resultado.md">Relatório com audiência</a>
</header><section class="clips" aria-label="{heading}">
{"".join(clips) or f"<p>{empty}</p>"}
</section></main></html>
"""


class StudyHandler(BaseHTTPRequestHandler):
    timeout = 20

    def do_HEAD(self):
        self.do_GET()

    def current_folder(self):
        folder = self.server.folder
        if not self.server.follow:
            return folder
        latest = (folder.parent / "ultima-sessao.txt").read_text(encoding="ascii").strip()
        if not re.fullmatch(SESSION_ID, latest):
            raise FileNotFoundError("Sessão inválida")
        current = folder.parent / latest
        return current if (current / "estado.json").is_file() else folder

    def do_GET(self):
        path = urlsplit(self.path).path if self.path.startswith("/") else ""
        folder = self.server.folder
        try:
            if path in ("/", "/amostras", "/resultado.md"):
                current = self.current_folder()
                clips = "/recolha/clips" if self.server.legacy else "/clips"
                if self.server.follow:
                    clips = f"/s/{current.name}/clips"
                if path == "/resultado.md":
                    report = (current / "resultado.md").read_bytes()
                    report = report.replace(b"](clips/", f"]({clips}/".encode("ascii"))
                    self.send_bytes(report, "text/plain; charset=utf-8")
                    return
                state = json.loads((current / "estado.json").read_text(encoding="utf-8"))
                health_file = current / "vigia.json"
                health = json.loads(health_file.read_text(encoding="utf-8")) if health_file.is_file() else {}
                kind = "candidate" if path == "/" else "control"
                page = render_study(state, health, kind, clips)
                self.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
                return
            selection = re.fullmatch(rf"/selecao/(en-\d{{8}})/({SHORT_NAME}|selecao\.json)?", path)
            if selection:
                date, name = selection.groups()
                shorts = folder.parent.parent / "shorts" / f"selecao-{date}"
                if name is None:
                    clips = json.loads((shorts / "selecao.json").read_text(encoding="utf-8"))
                    page = render_selection(clips, f"/selecao/{date}/")
                    self.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
                elif name == "selecao.json":
                    self.send_bytes((shorts / name).read_bytes(), "application/json; charset=utf-8")
                else:
                    self.send_clip(shorts / name)
                return
            session = re.fullmatch(rf"/s/({SESSION_ID})/clips/({CLIP_ID}\.mp4)", path)
            if self.server.follow and session:
                self.send_clip(folder.parent / session[1] / "clips" / session[2])
                return
            match = re.fullmatch(rf"/(?:(anteriores|recolha)/)?clips/({CLIP_ID}\.mp4)", path)
            if match:
                clip_folder = {
                    "anteriores": self.server.archive,
                    "recolha": folder,
                    None: self.server.legacy or folder,
                }[match[1]]
                if clip_folder is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_clip(clip_folder / "clips" / match[2])
                return
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except FileNotFoundError:
            pass
        self.send_error(HTTPStatus.NOT_FOUND)

    def send_bytes(self, data, content_type):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(data)

    def send_clip(self, path):
        with path.open("rb") as clip:
            size = clip.seek(0, 2)
            start, end = 0, size - 1
            range_value = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d{1,19})?-(\d{1,19})?", range_value)
            partial = match and any(match.groups())
            if partial:
                first, last = match.groups()
                if first is None:
                    start = max(0, size - int(last))
                else:
                    start = int(first)
                    if last is not None:
                        end = min(end, int(last))
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

            remaining = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(remaining))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "GET":
                clip.seek(start)
                while remaining:
                    data = clip.read(min(remaining, 64 * 1024))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--legacy", type=Path, help="Keep existing /clips URLs pointing to this session")
    parser.add_argument("--follow", action="store_true", help="Show the latest study and use session URLs")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), StudyHandler) as server:
        server.folder = args.folder.resolve(strict=True)
        server.archive = args.archive.resolve(strict=True) if args.archive else None
        server.legacy = args.legacy.resolve(strict=True) if args.legacy else None
        server.follow = args.follow
        server.serve_forever()
