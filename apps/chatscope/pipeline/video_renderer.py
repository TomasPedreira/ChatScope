"""Rendering is platform independent and consumes only local files and explicit intervals."""

from abc import ABC, abstractmethod
import math
from pathlib import Path

from .media_tools import resolve_ffmpeg_executable, probe_video, run_media_command


from .request_validation import validate_render_profile


class Renderer(ABC):
    @abstractmethod
    def render(
        self,
        source_path,
        output_path,
        clip_start_seconds,
        clip_end_seconds,
        render_profile,
    ):
        pass


class FFmpegRenderer(Renderer):
    def render(
        self,
        source_path,
        output_path,
        clip_start_seconds,
        clip_end_seconds,
        render_profile,
    ):
        validate_render_profile(render_profile)
        source_metadata = probe_video(source_path)
        if (
            not all(math.isfinite(t) for t in (clip_start_seconds, clip_end_seconds))
            or not 0
            <= clip_start_seconds
            < clip_end_seconds
            <= source_metadata["duration"] + 0.1
        ):
            raise ValueError("O corte fica fora do vídeo adquirido.")
        if clip_end_seconds - clip_start_seconds > 180.001:
            raise ValueError("O clip não pode ultrapassar 180 segundos.")
        width, height = {
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1080, 1080),
        }[render_profile.get("aspect", "9:16")]
        fit = render_profile.get("fit", "pad")
        if fit == "pad":
            filters = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        else:
            filters = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        filters += ",setsar=1"
        output_path = Path(output_path).resolve()
        if render_profile.get("captions"):
            from .speech_transcriber import WhisperTranscriber

            if WhisperTranscriber().captions(
                source_path, clip_start_seconds, clip_end_seconds, output_path.parent
            ):
                filters += ",subtitles=captions.srt"
        audio = (
            ["-af", "loudnorm=I=-16:TP=-2:LRA=7"] if source_metadata["audio"] else []
        )
        run_media_command(
            [
                resolve_ffmpeg_executable(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-ss",
                str(clip_start_seconds),
                "-i",
                str(Path(source_path).resolve()),
                "-t",
                str(clip_end_seconds - clip_start_seconds),
                "-vf",
                filters,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-threads",
                "4",
                "-pix_fmt",
                "yuv420p",
                *audio,
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            cwd=output_path.parent,
        )
        rendered_metadata = probe_video(output_path)
        if (rendered_metadata["width"], rendered_metadata["height"]) != (
            width,
            height,
        ) or abs(
            rendered_metadata["duration"] - (clip_end_seconds - clip_start_seconds)
        ) > 0.35:
            raise ValueError(
                "O MP4 produzido não corresponde ao perfil e à duração pedidos."
            )
        return rendered_metadata
