"""Bounded, shell-free access to FFmpeg and media metadata."""
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path


def ffmpeg():
    installed = shutil.which("ffmpeg")
    if installed:
        return installed
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        vendor = Path(get_ffmpeg_exe())
        # yt-dlp's capability check searches a bare ffmpeg name. imageio uses a
        # versioned filename, so expose a stable name inside this isolated venv.
        executable = Path(sys.executable).parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not executable.exists():
            try:
                os.link(vendor, executable)
            except FileExistsError:
                pass
            except OSError:
                shutil.copy2(vendor, executable)
        directory = str(executable.parent)
        if directory not in os.environ.get("PATH", "").split(os.pathsep):
            # yt-dlp's downloader capability check also searches PATH, even when
            # ffmpeg_location is supplied. This affects this worker only.
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        return str(executable)
    except ImportError as error:
        raise ValueError("Executa Setup-Media.ps1 para instalar as ferramentas de vídeo.") from error


def run(arguments, timeout=900, **kwargs):
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=timeout, creationflags=0x08000000 if __import__('os').name == 'nt' else 0,
                            **kwargs)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[-1800:])
    return result.stdout


def probe(path):
    if shutil.which("ffprobe"):
        data = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                               "-of", "json", str(path)], timeout=30))
        video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
        if not video:
            raise ValueError("O ficheiro não contém vídeo.")
        return {"width": video["width"], "height": video["height"],
                "duration": float(data["format"]["duration"]),
                "audio": any(s["codec_type"] == "audio" for s in data["streams"])}
    from imageio_ffmpeg import read_frames
    frames = read_frames(str(Path(path).resolve()), pix_fmt="rgb24")
    try:
        meta = next(frames)
        return {"width": meta["size"][0], "height": meta["size"][1],
                "duration": meta["duration"], "audio": bool(meta.get("audio_codec"))}
    finally:
        frames.close()
