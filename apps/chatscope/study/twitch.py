"""Read-only access to Twitch chat and public playback for the live study."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import re
import secrets
import ssl
import time
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from chat_signals import emote_ids

CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
LOGIN = re.compile(r"[a-z0-9_]{1,25}")
CHANNELS = {
    "gaming": ["theburntpeanut", "summit1g", "timthetatman", "shroud"],
    "gameplay": ["lirik", "ludwig", "cdawgva"],
    "conversa": ["sodapoppin", "nmplol", "pokimane"],
    "eventos": ["kaicenat", "rdcgaming"],
    "variedade": ["ishowspeed", "adinross"],
    "competitivo": ["jynxzi", "tarik", "fl0m", "tenz"],
    "horror": ["caseoh_"],
    "colabs": ["agent00", "erobb221", "fanfan", "jasontheween", "stableronaldo", "plaqueboymax"],
    "irl": ["extraemily", "vanillamace"],
}


def twitch_media(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.username or parts.password or not (
        host == "ttvnw.net" or host.endswith(".ttvnw.net")
        or host == "twitch.tv" or host.endswith(".twitch.tv")
    ):
        raise ValueError("Origem de vídeo fora dos domínios da Twitch")
    return url


def fetch(url, limit=2_000_000):
    with urlopen(twitch_media(url), timeout=10) as response:
        twitch_media(response.geturl())
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Resposta de vídeo acima do limite")
    return body


def query(graphql, variables):
    request = Request(
        "https://gql.twitch.tv/gql",
        data=json.dumps({"query": graphql, "variables": variables}).encode(),
        headers={"Client-ID": CLIENT_ID, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if result.get("errors") or result.get("data") is None:
        raise ValueError("Consulta web da Twitch indisponível")
    return result["data"]


def live_channels(names):
    data = query(
        "query($names:[String!]!){users(logins:$names){login stream{id viewersCount title game{name}}}}",
        {"names": list(names)},
    )
    return {
        user["login"]: user["stream"]
        for user in data["users"]
        if user and user.get("stream") and not (user["stream"].get("title") or "").casefold().startswith(
            ("rerun:", "[rerun]", "retransmissão:", "replay:")
        )
    }


def public_playlist(channel, target_height=360):
    if not LOGIN.fullmatch(channel):
        raise ValueError("Canal inválido")
    data = query(
        'query($name:String!){streamPlaybackAccessToken(channelName:$name,'
        'params:{platform:"web",playerBackend:"mediaplayer",playerType:"site"}){value signature}}',
        {"name": channel},
    )
    token = data.get("streamPlaybackAccessToken")
    if token is None:
        raise ValueError("Vídeo público indisponível")
    params = urlencode({"sig": token["signature"], "token": token["value"], "allow_source": "true"})
    master = f"https://usher.ttvnw.net/api/channel/hls/{channel}.m3u8?{params}"
    return twitch_media(rendition(master, fetch(master).decode(), target_height))


def rendition(master, body, target_height):
    lines = body.splitlines()
    options = []
    for index, line in enumerate(lines[:-1]):
        if line.startswith("#EXT-X-STREAM-INF:") and not lines[index + 1].startswith("#"):
            resolution = re.search(r"RESOLUTION=\d+x(\d+)", line)
            if resolution:
                options.append((int(resolution[1]), urljoin(master, lines[index + 1])))
    if not options:
        raise ValueError("Sem faixas públicas de vídeo")
    return min(options, key=lambda option: (option[0] > target_height, abs(option[0] - target_height)))[1]


@dataclass(frozen=True)
class Segment:
    utc: float
    duration: float
    url: str
    discontinuity: bool
    init_url: str | None = None

    @property
    def end(self):
        return self.utc + self.duration


def media_segments(playlist, body):
    """Require program timestamps. Never infer live time from download time."""
    if "#EXT-X-KEY:" in body or "#EXT-X-BYTERANGE:" in body:
        raise ValueError("Playlist cifrada ou com segmentos parciais")
    advertisements = []
    for line in body.splitlines():
        if line.startswith("#EXT-X-DATERANGE:") and 'CLASS="twitch-stitched-ad"' in line:
            ad_start = re.search(r'START-DATE="([^"]+)"', line)
            ad_length = re.search(r'(?:^|,)DURATION=(\d+(?:\.\d+)?)', line)
            if ad_start and ad_length:
                start = datetime.fromisoformat(ad_start[1]).timestamp()
                advertisements.append((start, start + float(ad_length[1])))
    utc = duration = None
    init_url = None
    gap = discontinuity = False
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            timestamp = datetime.fromisoformat(line.split(":", 1)[1].replace("Z", "+00:00"))
            utc = timestamp.timestamp() if timestamp.tzinfo else None
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line.startswith("#EXT-X-MAP:"):
            init = re.search(r'URI="([^"]+)"', line)
            if not init or "BYTERANGE=" in line:
                raise ValueError("Cabeçalho de vídeo não suportado")
            init_url = twitch_media(urljoin(playlist, init[1]))
        elif line == "#EXT-X-GAP":
            gap = True
        elif line == "#EXT-X-DISCONTINUITY":
            discontinuity = True
            utc = None
        elif line and not line.startswith("#"):
            if utc is not None and duration is not None and 0 < duration <= 15:
                advert = any(start < utc + duration and end > utc + 0.1 for start, end in advertisements)
                if not gap and not advert and "/stitched-ad/" not in line:
                    yield Segment(utc, duration, twitch_media(urljoin(playlist, line)), discontinuity, init_url)
                utc += duration
            gap = discontinuity = False
            duration = None


def clip_segments(segments, start, end):
    selected = sorted(
        (segment for segment in segments if segment.end > start and segment.utc < end),
        key=lambda segment: segment.utc,
    )
    if not selected or selected[0].utc > start + 0.25 or selected[-1].end < end - 0.25:
        raise ValueError("Janela sem vídeo completo")
    for left, right in zip(selected, selected[1:]):
        if abs(right.utc - left.end) > 0.30 or right.discontinuity or left.init_url != right.init_url:
            raise ValueError("Janela com falha ou descontinuidade de vídeo")
    return selected


async def chat(channel, receive, emit, stop):
    """Anonymous IRC over TLS. Reconnect independently for each channel."""
    delay = 2
    while not stop.is_set():
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("irc.chat.twitch.tv", 6697, ssl=ssl.create_default_context()),
                12,
            )
            nickname = f"justinfan{secrets.randbelow(89999999) + 10000000}"
            writer.write(
                f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nPASS SCHMOOPIIE\r\n"
                f"NICK {nickname}\r\nJOIN #{channel}\r\n".encode()
            )
            await writer.drain()
            while not stop.is_set():
                raw = await asyncio.wait_for(reader.readline(), 360)
                if not raw:
                    raise ConnectionError("Twitch fechou o chat")
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("PING "):
                    writer.write(f"PONG {line[5:]}\r\n".encode())
                    await writer.drain()
                elif line.endswith(" RECONNECT") or "Login authentication failed" in line:
                    raise ConnectionError("Twitch pediu reconexão")
                elif " 366 " in line:
                    emit("chat_connected")
                    delay = 2
                elif line.startswith("@") and f" PRIVMSG #{channel} :" in line:
                    tags, _, rest = line.partition(" ")
                    user = rest.removeprefix(":").split("!", 1)[0].casefold()
                    text = rest.partition(f" PRIVMSG #{channel} :")[2]
                    fields = dict(part.split("=", 1) for part in tags[1:].split(";") if "=" in part)
                    sent = fields.get("tmi-sent-ts", "")
                    receive(sent and sent.isdecimal() and int(sent) / 1000 or time.time(), user, text,
                            emote_ids(fields.get("emotes", "")))
        except (OSError, TimeoutError, URLError, ValueError) as exc:
            emit("chat_error", reason=type(exc).__name__)
        finally:
            if writer:
                writer.close()
        await asyncio.sleep(delay)
        delay = min(60, delay * 2)
