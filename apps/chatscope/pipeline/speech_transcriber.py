"""Speech recognition/translation adapter; no extraction, subtitle files or rendering."""

from abc import ABC, abstractmethod
from functools import lru_cache

from .caption_models import CaptionProfile, SubtitleCue, TimedTranscript


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path, profile: CaptionProfile) -> TimedTranscript:
        """Return target-language timed text, retaining the detected source language."""


@lru_cache(maxsize=2)
def load_whisper_model(model_name):
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise ValueError("As legendas exigem Setup-Media.ps1 -Captions.") from error
    return WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)


class WhisperTranscriber(Transcriber):
    def transcribe(self, audio_path, profile):
        # language describes speech input; task=translate requests English output.
        task = (
            "translate"
            if profile.target_language == "en" and profile.source_language != "en"
            else "transcribe"
        )
        segments, info = load_whisper_model(profile.model).transcribe(
            str(audio_path),
            language=(
                None if profile.source_language == "auto" else profile.source_language
            ),
            task=task,
            vad_filter=True,
        )
        return TimedTranscript(
            source_language=info.language,
            language="en" if task == "translate" else info.language,
            segments=tuple(
                SubtitleCue(segment.start, segment.end, segment.text)
                for segment in segments
            ),
            provider="faster-whisper",
            model=profile.model,
            task=task,
        )
