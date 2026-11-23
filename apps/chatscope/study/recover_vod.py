"""Recover a review window from a public archive of the original broadcast."""

import argparse
import json
from math import isfinite
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import urlopen

from collector import write_capture
from twitch import Segment, clip_segments, fetch, query, rendition


def archive_playlist(video, height):
    if not re.fullmatch(r"[0-9]+", video):
        raise ValueError("Indica o ID numérico do arquivo da Twitch.")
    data = query(
        'query($id:ID!){videoPlaybackAccessToken(id:$id,'
        'params:{platform:"web",playerBackend:"mediaplayer",playerType:"site"}){value signature}}',
        {"id": video},
    )
    token = data.get("videoPlaybackAccessToken")
    if not token:
        raise ValueError("Arquivo público indisponível.")
    params = urlencode({"nauthsig": token["signature"], "nauth": token["value"], "allow_source": "true"})
    master = f"https://usher.ttvnw.net/vod/{video}.m3u8?{params}"
    return rendition(master, fetch(master).decode(), height)


def archive_fetcher(playlist):
    host = urlsplit(playlist).hostname or ""
    if not host.endswith((".ttvnw.net", ".twitch.tv", ".cloudfront.net")):
        raise ValueError("CDN do arquivo inválida.")

    def validate(url):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != host:
            raise ValueError("Segmento fora da CDN do arquivo.")

    def retrieve(url, limit=2_000_000):
        validate(url)
        with urlopen(url, timeout=12) as response:
            validate(response.geturl())
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Resposta de arquivo acima do limite.")
        return content

    return retrieve


def archive_segments(playlist, body):
    if not body.startswith("#EXTM3U") or "#EXT-X-KEY:" in body or "#EXT-X-BYTERANGE:" in body:
        raise ValueError("Playlist do arquivo inválida ou incompatível.")
    duration = init_url = None
    elapsed = 0.0
    gap = discontinuity = False
    for line in body.splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line.removeprefix("#EXTINF:").split(",")[0])
        elif line.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', line)
            if not match or "BYTERANGE=" in line:
                raise ValueError("Cabeçalho de vídeo incompatível.")
            init_url = urljoin(playlist, match[1])
        elif line == "#EXT-X-GAP":
            gap = True
        elif line == "#EXT-X-DISCONTINUITY":
            discontinuity = True
        elif line and not line.startswith("#"):
            if duration is None or not 0 < duration <= 15:
                raise ValueError("Segmento sem duração válida.")
            if not gap:
                yield Segment(elapsed, duration, urljoin(playlist, line), discontinuity, init_url)
            elapsed += duration
            duration = None
            gap = discontinuity = False


def recover(video, start, end, destination, original):
    if not (isfinite(end) and 0 <= start < end <= start + 180):
        raise ValueError("Os tempos do arquivo são em segundos e a janela pode ter até três minutos.")
    playlist = archive_playlist(video, 1080 if original else 360)
    retrieve = archive_fetcher(playlist)
    segments = clip_segments(archive_segments(playlist, retrieve(playlist, limit=8_000_000).decode()), start, end)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = write_capture(segments, start, end, destination, original, retrieve=retrieve)
    return {
        "videoId": video, "archiveOffset": start, "masterArchiveOffset": segments[0].utc if original else None,
        **result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vod")
    parser.add_argument("inicio", type=float)
    parser.add_argument("fim", type=float)
    parser.add_argument("previa", type=Path)
    parser.add_argument("--original", type=Path)
    args = parser.parse_args()
    try:
        if args.original and args.original.resolve() == args.previa.resolve():
            raise ValueError("Escolhe caminhos distintos para a prévia e a fonte de edição.")
        result = recover(args.vod, args.inicio, args.fim, args.previa, args.original)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
