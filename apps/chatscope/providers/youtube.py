"""Metadata-only YouTube adapter. stdout is one JSON object; no media is downloaded."""
import json
import sys


def extract(url):
    from yt_dlp import YoutubeDL
    from yt_dlp.version import __version__

    options = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "ignore_no_formats_error": True,
        "socket_timeout": 12, "retries": 1, "extractor_retries": 1,
        # Metadata and public replay markers do not need media manifests or JS formats.
        "extractor_args": {"youtube": {"player_client": ["web"],
                                      "skip": ["hls", "dash"], "player_skip": ["configs", "js"]}},
    }
    with YoutubeDL(options) as client:
        # A transient player response can contain only a placeholder title/id.
        # Retry incomplete metadata once, without treating it as a missing heatmap.
        for _ in range(2):
            info = client.extract_info(url, download=False)
            if info and info.get("id") and info.get("duration") and info.get("channel"):
                break
    if not info or not info.get("id") or not info.get("duration") or not info.get("channel"):
        raise ValueError("O vídeo não está disponível ou não devolveu metadados suficientes.")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise ValueError("Escolhe um vídeo publicado ou um direto já processado pelo YouTube.")
    return {
        "id": info["id"], "title": info.get("title") or info["id"],
        "channel": info["channel"], "duration": info["duration"],
        "heatmap": info.get("heatmap"), "extractorVersion": __version__,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(extract(sys.argv[1]), ensure_ascii=True, allow_nan=False))
    except ModuleNotFoundError:
        print("Falta yt-dlp. Executa Setup-YouTube.ps1 na pasta apps/chatscope.", file=sys.stderr)
        raise SystemExit(2)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
