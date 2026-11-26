"""Provider-independent caption requests and timed text on the clip timeline."""

from dataclasses import dataclass
import re

MULTILINGUAL_MODELS = frozenset({"tiny", "base", "small", "medium", "large-v3"})


@dataclass(frozen=True)
class CaptionProfile:
    source_language: str = "auto"
    target_language: str = "en"
    model: str = "small"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {
            "sourceLanguage",
            "targetLanguage",
            "model",
        }:
            raise ValueError("Perfil de legendas inválido.")
        profile = cls(
            value.get("sourceLanguage", "auto"),
            value.get("targetLanguage", "en"),
            value.get("model", "small"),
        )
        if not isinstance(profile.source_language, str) or not re.fullmatch(
            r"auto|[a-z]{2,3}", profile.source_language
        ):
            raise ValueError("Indica auto ou um código de língua de origem.")
        if profile.target_language != "en":
            raise ValueError("Este provider de legendas suporta saída em inglês (en).")
        if (
            not isinstance(profile.model, str)
            or profile.model not in MULTILINGUAL_MODELS
        ):
            raise ValueError(
                "Escolhe um modelo Whisper multilingue com tradução: tiny, base, small, medium ou large-v3."
            )
        return profile


@dataclass(frozen=True)
class SubtitleCue:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class TimedTranscript:
    source_language: str
    language: str
    segments: tuple[SubtitleCue, ...]
    provider: str
    model: str
    task: str
