"""Rendering is platform independent and consumes only local files and explicit intervals."""
from abc import ABC, abstractmethod
import math
from pathlib import Path

from .tools import ffmpeg, probe, run


def validate_render(profile):
    if (set(profile) - {"aspect", "fit", "captions"}
            or profile.get("aspect", "9:16") not in ("9:16", "16:9", "1:1")
            or profile.get("fit", "pad") not in ("pad", "crop")
            or not isinstance(profile.get("captions", False), bool)):
        raise ValueError("Perfil de rendering inválido.")


class Renderer(ABC):
    @abstractmethod
    def render(self, source, output, start, end, profile):
        pass


class FFmpegRenderer(Renderer):
    def render(self, source, output, start, end, profile):
        validate_render(profile)
        info = probe(source)
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= info["duration"] + .1:
            raise ValueError("O corte fica fora do vídeo adquirido.")
        if end - start > 180.001:
            raise ValueError("O clip não pode ultrapassar 180 segundos.")
        width, height = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}[profile.get("aspect", "9:16")]
        fit = profile.get("fit", "pad")
        if fit == "pad":
            filters = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        else:
            filters = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        filters += ",setsar=1"
        output = Path(output).resolve()
        if profile.get("captions"):
            from .captions import WhisperTranscriber
            if WhisperTranscriber().captions(source, start, end, output.parent):
                filters += ",subtitles=captions.srt"
        audio = ["-af", "loudnorm=I=-16:TP=-2:LRA=7"] if info["audio"] else []
        run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-ss", str(start),
             "-i", str(Path(source).resolve()), "-t", str(end - start), "-vf", filters, "-map", "0:v:0",
             "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4",
             "-pix_fmt", "yuv420p", *audio, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
             str(output)], cwd=output.parent)
        actual = probe(output)
        if ((actual["width"], actual["height"]) != (width, height)
                or abs(actual["duration"] - (end - start)) > .35):
            raise ValueError("O MP4 produzido não corresponde ao perfil e à duração pedidos.")
        return actual
