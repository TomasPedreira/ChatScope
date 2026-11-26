"""Extension point for directions beyond Whisper's speech-to-English translation."""

from abc import ABC, abstractmethod
from .caption_models import TimedTranscript


class TranscriptTranslator(ABC):
    @abstractmethod
    def supports(self, source_language: str, target_language: str) -> bool:
        """Declare supported translation directions, for example en -> pt."""

    @abstractmethod
    def translate(
        self, transcript: TimedTranscript, target_language: str
    ) -> TimedTranscript:
        """Return target-language text while retaining cue timing and provenance."""
