"""MediaSource adapters own acquisition only; all return the same local media contract."""

from abc import ABC, abstractmethod
import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from .media_tools import resolve_ffmpeg_executable, probe_video, run_media_command


class MediaSource(ABC):
    @abstractmethod
    def metadata(self):
        """Return platform metadata without downloading media."""

    @abstractmethod
    def acquire(self, start, end, directory):
        """Return (local file, absolute start time) for a bounded interval."""


class LocalSource(MediaSource):
    def __init__(self, url):
        parsed = urlparse(url)
        if parsed.netloc not in ("", "localhost"):
            raise ValueError("Escolhe um ficheiro local, sem caminhos de rede.")
        self.path = Path(url2pathname(parsed.path)).resolve(strict=True)
        if self.path.suffix.lower() not in (
            ".mp4",
            ".mkv",
            ".mov",
            ".webm",
            ".m4v",
            ".avi",
        ):
            raise ValueError("Formato de vídeo local não suportado.")

    def metadata(self):
        return {
            "id": hashlib.sha256(str(self.path).encode()).hexdigest()[:16],
            "title": self.path.stem,
            "channel": "Ficheiro local",
            "is_live": False,
            "duration": probe_video(self.path)["duration"],
            "heatmap": None,
        }

    def acquire(self, start, end, directory):
        return self.path, 0.0


class YtDlpSource(MediaSource):
    def __init__(self, url, provider):
        self.url, self.provider = url, provider
        self.info = None

    def options(self, metadata=False):
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            # yt-dlp's socket timeout does not cover its FFmpeg downloader.
            "external_downloader_args": {"ffmpeg_i": ["-rw_timeout", "20000000"]},
            "retries": 1,
            "extractor_retries": 1,
            "ffmpeg_location": resolve_ffmpeg_executable(),
            "logger": QuietLogger(),
            "cachedir": False,
        }
        if shutil.which("node"):
            options["js_runtimes"] = {"node": {"path": shutil.which("node")}}
        if metadata:
            options.update(skip_download=True, ignore_no_formats_error=True)
            if self.provider == "youtube":
                options["extractor_args"] = {
                    "youtube": {
                        "player_client": ["web"],
                        "skip": ["hls", "dash"],
                        "player_skip": ["configs", "js"],
                    }
                }
        return options

    def metadata(self):
        from yt_dlp import YoutubeDL

        with YoutubeDL(self.options(metadata=True)) as client:
            for _ in range(2):
                info = client.extract_info(self.url, download=False)
                if (
                    info
                    and info.get("id")
                    and (info.get("duration") or info.get("is_live"))
                ):
                    break
        if not info or not info.get("id"):
            raise ValueError("A origem não devolveu metadados válidos.")
        if info.get("live_status") in ("is_upcoming", "post_live"):
            raise ValueError("O direto ainda não começou ou está a ser processado.")
        if not info.get("is_live") and not info.get("duration"):
            raise ValueError("O vídeo não está disponível ou não tem duração válida.")
        self.info = info
        return info

    def acquire(self, start, end, directory):
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import download_range_func

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        options = self.options()
        options.update(
            format="bv*[height<=1080]+ba/b[height<=1080]/best",
            outtmpl=str(directory / "source.%(ext)s"),
            merge_output_format="mp4",
            overwrites=False,
            continuedl=True,
        )
        live = bool((self.info or self.metadata()).get("is_live"))
        if live:
            # A bounded recording starts now. Its offsets belong to this recording,
            # never to the broadcast's original start or a future VOD.
            with YoutubeDL(options) as client:
                info = client.extract_info(self.url, download=False)
            selected = info.get("requested_formats") or [info]
            if len(selected) > 2 or not all(item.get("url") for item in selected):
                raise ValueError("Não foi possível obter as faixas do direto.")
            inputs, mapping = [], []
            for item in selected:
                headers = "".join(
                    f"{key}: {value}\r\n"
                    for key, value in item.get("http_headers", {}).items()
                    if "\r" not in str(value) and "\n" not in str(value)
                )
                inputs.extend(["-rw_timeout", "20000000", "-thread_queue_size", "512"])
                if headers:
                    inputs.extend(["-headers", headers])
                inputs.extend(["-i", item["url"]])
            if len(selected) == 2:
                mapping = ["-map", "0:v:0", "-map", "1:a:0?"]
            target = directory / "recording.mp4"
            run_media_command(
                [
                    resolve_ffmpeg_executable(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-n",
                    *inputs,
                    *mapping,
                    "-t",
                    str(end - start),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(target),
                ],
                timeout=end - start + 90,
            )
            return target, 0.0
        options.update(
            download_ranges=download_range_func(None, [(start, end)]),
            force_keyframes_at_cuts=True,
        )
        with YoutubeDL(options) as client:
            client.extract_info(self.url, download=True)
        files = [
            p for p in directory.iterdir() if p.suffix in (".mp4", ".mkv", ".webm")
        ]
        if len(files) != 1:
            raise ValueError("O download não produziu um único vídeo utilizável.")
        return files[0], start


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


class MediaSourceRegistry:
    def resolve(self, url):
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return "local", LocalSource(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Usa um URL HTTPS de uma origem suportada.")
        host = parsed.hostname
        if host in ("kick.com", "www.kick.com"):
            from .kick_source import KickSource

            return "kick", KickSource(url)
        for provider, hosts in {
            "youtube": (
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "youtu.be",
                "www.youtu.be",
            ),
            "twitch": ("twitch.tv", "www.twitch.tv", "m.twitch.tv", "clips.twitch.tv"),
        }.items():
            if host in hosts:
                return provider, YtDlpSource(url, provider)
        raise ValueError("Origem de vídeo não suportada.")
