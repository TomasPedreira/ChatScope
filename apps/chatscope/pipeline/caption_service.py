"""Prepare bounded audio, normalize timed text and persist reusable subtitle artifacts."""

from pathlib import Path
import math
import textwrap

from .caption_models import CaptionProfile, SubtitleCue
from .job_storage import write_json_atomically, write_text_atomically
from .media_tools import resolve_ffmpeg_executable, run_media_command
from .speech_transcriber import WhisperTranscriber
from .caption_styling import CaptionStyler


def format_subtitle_timestamp(seconds):
    milliseconds = round(seconds * 1000)
    return f"{milliseconds//3600000:02}:{milliseconds//60000%60:02}:{milliseconds//1000%60:02},{milliseconds%1000:03}"


def normalize_cues(segments, duration_seconds):
    cues = []
    previous_end = 0.0
    for segment in segments:
        if not all(
            math.isfinite(value)
            for value in (segment.start_seconds, segment.end_seconds)
        ):
            raise ValueError("O provider devolveu tempos de legendas inválidos.")
        start = max(previous_end, 0.0, segment.start_seconds)
        end = min(duration_seconds, segment.end_seconds)
        text = " ".join(segment.text.replace("-->", "→").replace("\x00", "").split())
        text = (
            text.replace("{", "(")
            .replace("}", ")")
            .replace("\\", "/")
            .replace("<", "‹")
            .replace(">", "›")
        )
        if not text or end - start < 0.001:
            continue
        lines = textwrap.wrap(
            text, width=42, break_long_words=True, break_on_hyphens=False
        )
        groups = [lines[index : index + 2] for index in range(0, len(lines), 2)]
        total_characters = sum(len(" ".join(group)) for group in groups)
        cursor = start
        for index, group in enumerate(groups):
            cue_end = (
                end
                if index == len(groups) - 1
                else cursor + (end - start) * len(" ".join(group)) / total_characters
            )
            cues.append(SubtitleCue(cursor, cue_end, "\n".join(group)))
            cursor = cue_end
        previous_end = end
    return cues


class CaptionService:
    def __init__(self, transcriber=None, translators=(), caption_styler=None):
        self.transcriber = transcriber or WhisperTranscriber()
        self.translators = tuple(translators)
        self.caption_styler = caption_styler or CaptionStyler()

    def generate(
        self,
        source_path,
        start_seconds,
        end_seconds,
        folder,
        profile=None,
        canvas_size=(1080, 1920),
    ):
        profile = CaptionProfile.from_dict({} if profile is None else profile)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        speech_path = folder / "speech.wav"
        run_media_command(
            [
                resolve_ffmpeg_executable(),
                "-v",
                "error",
                "-nostdin",
                "-n",
                "-ss",
                str(start_seconds),
                "-i",
                str(source_path),
                "-t",
                str(end_seconds - start_seconds),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(speech_path),
            ]
        )
        transcript = self.transcriber.transcribe(speech_path, profile)
        if transcript.language != profile.target_language:
            translator = next(
                (
                    provider
                    for provider in self.translators
                    if provider.supports(transcript.language, profile.target_language)
                ),
                None,
            )
            if translator is None:
                raise ValueError(
                    f"Tradução {transcript.language} → {profile.target_language} ainda sem provider. Para já, tradução PT → EN e transcrição PT/EN estão disponíveis."
                )
            transcript = translator.translate(transcript, profile.target_language)
        if transcript.language != profile.target_language:
            raise ValueError(
                "O provider devolveu legendas numa língua diferente da pedida."
            )
        cues = normalize_cues(transcript.segments, end_seconds - start_seconds)
        srt = "\n".join(
            f"{index+1}\n{format_subtitle_timestamp(cue.start_seconds)} --> {format_subtitle_timestamp(cue.end_seconds)}\n{cue.text}\n"
            for index, cue in enumerate(cues)
        )
        srt_path, transcript_path = folder / "captions.srt", folder / "transcript.json"
        write_text_atomically(srt_path, srt)
        provenance = {
            "schemaVersion": 1,
            "language": transcript.language,
            "sourceLanguage": transcript.source_language,
            "requestedSourceLanguage": profile.source_language,
            "provider": transcript.provider,
            "model": transcript.model,
            "task": transcript.task,
            "timeOrigin": "clip",
            "inputMedia": str(Path(source_path).resolve()),
            "inputStartSeconds": start_seconds,
            "inputEndSeconds": end_seconds,
            "timingMethod": "model_segments_with_proportional_line_splitting",
            "segments": [
                {"start": cue.start_seconds, "end": cue.end_seconds, "text": cue.text}
                for cue in cues
            ],
        }
        write_json_atomically(transcript_path, provenance)
        style_metadata = (
            self.caption_styler.write(
                speech_path,
                cues,
                provenance,
                folder,
                profile,
                end_seconds - start_seconds,
                canvas_size,
            )
            if cues
            else {"style": profile.style}
        )
        return {
            **style_metadata,
            "status": "ready" if cues else "no_speech",
            "language": transcript.language,
            "sourceLanguage": transcript.source_language,
            "provider": transcript.provider,
            "model": transcript.model,
            "task": transcript.task,
            "cueCount": len(cues),
            "srtPath": str(srt_path.resolve()),
            "transcriptPath": str(transcript_path.resolve()),
        }
