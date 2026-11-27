"""Caption language, timing and provenance contracts; model downloads are opt-in."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.caption_models import CaptionProfile, SubtitleCue, TimedTranscript
from pipeline.caption_service import (
    CaptionService,
    normalize_cues,
    format_subtitle_timestamp,
)
from pipeline.speech_transcriber import WhisperTranscriber
from pipeline.request_validation import validate_render_profile


class CaptionContracts(unittest.TestCase):
    def test_legacy_render_profile_defaults_to_english_with_source_detection(self):
        validate_render_profile({"captions": True})
        profile = CaptionProfile.from_dict({})
        self.assertEqual(
            (profile.source_language, profile.target_language, profile.model),
            ("auto", "en", "small"),
        )

    def test_wrong_targets_and_models_that_cannot_translate_are_rejected(self):
        for profile in (
            {"targetLanguage": "fr"},
            {"model": "turbo"},
            {"model": "small.en"},
            {"sourceLanguage": "English"},
            {"sourceLanguage": None},
            {"unknown": 1},
            [],
            {"model": []},
        ):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_render_profile({"captions": True, "captionProfile": profile})

    def test_foreign_speech_uses_translate_without_forcing_english_input(self):
        model = SimpleNamespace(
            transcribe=lambda *args, **kwargs: (
                iter([SimpleNamespace(start=0, end=2, text="Good morning.")]),
                SimpleNamespace(language="pt"),
            )
        )
        with patch(
            "pipeline.speech_transcriber.load_whisper_model", return_value=model
        ), patch.object(model, "transcribe", wraps=model.transcribe) as call:
            result = WhisperTranscriber().transcribe(
                "audio.wav", CaptionProfile(source_language="pt")
            )
        self.assertEqual(
            call.call_args.kwargs,
            {"language": "pt", "task": "translate", "vad_filter": True},
        )
        self.assertEqual((result.source_language, result.language), ("pt", "en"))

    def test_known_english_speech_uses_transcription(self):
        model = SimpleNamespace(
            transcribe=lambda *args, **kwargs: (
                iter([]),
                SimpleNamespace(language="en"),
            )
        )
        with patch(
            "pipeline.speech_transcriber.load_whisper_model", return_value=model
        ), patch.object(model, "transcribe", wraps=model.transcribe) as call:
            result = WhisperTranscriber().transcribe(
                "audio.wav", CaptionProfile(source_language="en")
            )
        self.assertEqual(call.call_args.kwargs["task"], "transcribe")
        self.assertEqual(result.language, "en")

    def test_cues_are_bounded_non_overlapping_and_max_two_lines(self):
        cues = normalize_cues(
            [
                SubtitleCue(-1, 3, "A short introduction."),
                SubtitleCue(
                    2,
                    20,
                    "A long sentence with enough words to require several subtitle lines and preserve readable text without leaving the selected clip timeline.",
                ),
                SubtitleCue(20, 21, "outside"),
            ],
            7,
        )
        self.assertEqual(cues[0].start_seconds, 0)
        self.assertEqual(cues[-1].end_seconds, 7)
        self.assertTrue(
            all(a.end_seconds <= b.start_seconds for a, b in zip(cues, cues[1:]))
        )
        self.assertTrue(all(len(cue.text.splitlines()) <= 2 for cue in cues))
        self.assertTrue(
            all(len(line) <= 42 for cue in cues for line in cue.text.splitlines())
        )
        self.assertEqual(format_subtitle_timestamp(59.9996), "00:01:00,000")

    def test_provider_timing_errors_are_not_silently_hidden(self):
        with self.assertRaises(ValueError):
            normalize_cues([SubtitleCue(0, float("nan"), "invalid")], 5)

    def test_caption_service_accepts_an_independent_provider_and_handles_no_speech(
        self,
    ):
        class EmptyProvider:
            def transcribe(self, source, profile):
                return TimedTranscript(
                    "es", "en", (), "test-provider", "fixture", "translate"
                )

        with TemporaryDirectory() as folder, patch(
            "pipeline.caption_service.run_media_command"
        ):
            result = CaptionService(EmptyProvider()).generate(
                "source.mp4", 25, 30, folder
            )
            import json

            transcript = json.loads(
                Path(result["transcriptPath"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "no_speech")
            self.assertEqual(
                (transcript["sourceLanguage"], transcript["language"]), ("es", "en")
            )
            self.assertEqual(transcript["inputStartSeconds"], 25)
            self.assertEqual(transcript["timeOrigin"], "clip")
            self.assertEqual(Path(result["srtPath"]).read_text(encoding="utf-8"), "")

    def test_provider_output_language_mismatch_fails_explicitly(self):
        class WrongProvider:
            def transcribe(self, source, profile):
                return TimedTranscript(
                    "es", "es", (), "test-provider", "fixture", "transcribe"
                )

        with TemporaryDirectory() as folder, patch(
            "pipeline.caption_service.run_media_command"
        ), self.assertRaises(ValueError):
            CaptionService(WrongProvider()).generate("source.mp4", 0, 5, folder)

    def test_portuguese_output_transcribes_portuguese_instead_of_translating_to_english(
        self,
    ):
        model = SimpleNamespace(
            transcribe=lambda *args, **kwargs: (
                iter([SimpleNamespace(start=0, end=2, text="Bom dia.")]),
                SimpleNamespace(language="pt"),
            )
        )
        with patch(
            "pipeline.speech_transcriber.load_whisper_model", return_value=model
        ), patch.object(model, "transcribe", wraps=model.transcribe) as call:
            result = WhisperTranscriber().transcribe(
                "audio.wav", CaptionProfile(source_language="pt", target_language="pt")
            )
        self.assertEqual(call.call_args.kwargs["task"], "transcribe")
        self.assertEqual(result.language, "pt")

    def test_english_to_portuguese_is_not_silently_claimed_without_a_provider(self):
        class EnglishProvider:
            def transcribe(self, source, profile):
                return TimedTranscript(
                    "en",
                    "en",
                    (SubtitleCue(0, 2, "Good morning."),),
                    "fixture",
                    "fixture",
                    "transcribe",
                )

        with TemporaryDirectory() as folder, patch(
            "pipeline.caption_service.run_media_command"
        ), self.assertRaisesRegex(ValueError, "ainda sem provider"):
            CaptionService(EnglishProvider()).generate(
                "source.mp4", 0, 5, folder, {"targetLanguage": "pt"}
            )

    def test_future_translation_adapter_can_be_injected_without_changing_the_renderer(
        self,
    ):
        from pipeline.transcript_translation import TranscriptTranslator

        class EnglishProvider:
            def transcribe(self, source, profile):
                return TimedTranscript(
                    "en",
                    "en",
                    (SubtitleCue(0, 2, "Good morning."),),
                    "fixture",
                    "fixture",
                    "transcribe",
                )

        class FixtureTranslator(TranscriptTranslator):
            def supports(self, source_language, target_language):
                return (source_language, target_language) == ("en", "pt")

            def translate(self, transcript, target_language):
                return TimedTranscript(
                    transcript.source_language,
                    target_language,
                    (SubtitleCue(0, 2, "Bom dia."),),
                    "fixture-translator",
                    "fixture",
                    "translate",
                )

        with TemporaryDirectory() as folder, patch(
            "pipeline.caption_service.run_media_command"
        ):
            result = CaptionService(
                EnglishProvider(), translators=(FixtureTranslator(),)
            ).generate(
                "source.mp4", 0, 5, folder, {"targetLanguage": "pt", "style": "plain"}
            )
            self.assertEqual(result["language"], "pt")
            self.assertEqual(result["provider"], "fixture-translator")


if __name__ == "__main__":
    unittest.main()
