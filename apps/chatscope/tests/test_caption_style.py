"""Classic visual style and approved-text preservation, without model/network dependencies."""

from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.caption_models import CaptionProfile, SubtitleCue
from pipeline.caption_style import timed_captions, highlight_cues
from pipeline.caption_styling import CaptionStyler
from pipeline.saved_caption_service import SavedCaptionService
from pipeline.word_alignment import TimedWord, preserve_words


class CaptionStyleTests(unittest.TestCase):
    def test_classic_style_highlights_exactly_one_word_and_keeps_animation(self):
        ass = timed_captions('[{"text":"O carro","times":[1,1.2,1.5]}]', 2)
        events = [line for line in ass.splitlines() if line.startswith("Dialogue")]
        self.assertEqual(len(events), 2)
        self.assertIn("Style: Main,Arial,69,", ass)
        self.assertIn(r"\pos(540,1588)", events[0])
        self.assertIn(r"\fscx105\fscy105\t(0,130,\fscx100\fscy100)", events[0])
        self.assertIn(r"{\1c&H48D5FF&}O", events[0])
        self.assertIn(r"{\1c&H48D5FF&}CARRO", events[1])
        self.assertTrue(all(event.count(r"{\1c&H48D5FF&}") == 1 for event in events))

    def test_legacy_study_uses_the_same_ass_implementation(self):
        from study import shorts_style

        self.assertIs(shorts_style.timed_captions, timed_captions)
        self.assertEqual(
            shorts_style.format_description("A clip", ["Shorts"]), "A clip\n\n#Shorts"
        )

    def test_style_scales_to_other_output_canvases(self):
        ass = timed_captions('[{"text":"A clip","times":[0,0.4,1]}]', 1, 1920, 1080)
        self.assertIn("PlayResX: 1920", ass)
        self.assertIn(r"\pos(960,893)", ass)

    def test_alignment_preserves_punctuation_and_handles_zero_duration_tokens(self):
        cue = SubtitleCue(0, 2, "Don't change this.")
        words = preserve_words(
            cue,
            [
                {"word": " Don't", "start": 0, "end": 0},
                {"word": " change", "start": 0, "end": 0.8},
                {"word": " this.", "start": 0.8, "end": 1.8},
            ],
            0,
        )
        self.assertEqual([word.text for word in words], ["Don't", "change", "this."])
        self.assertTrue(all(word.end_seconds > word.start_seconds for word in words))
        self.assertTrue(
            all(a.end_seconds <= b.start_seconds for a, b in zip(words, words[1:]))
        )
        with self.assertRaises(ValueError):
            preserve_words(cue, [{"word": " Different text", "start": 0, "end": 2}], 0)

    def test_short_groups_keep_every_approved_word(self):
        words = [
            TimedWord(word, index * 0.25, (index + 1) * 0.25)
            for index, word in enumerate(
                "This exact text is already approved. Keep every word!".split()
            )
        ]
        groups = highlight_cues(words, 4)
        self.assertEqual(
            " ".join(group["text"] for group in groups),
            "This exact text is already approved. Keep every word!",
        )
        self.assertTrue(all(len(group["text"].split()) <= 5 for group in groups))
        self.assertIn("APPROVED.", timed_captions(json.dumps(groups), 4))

    def test_invalid_highlight_times_and_control_text_are_rejected(self):
        for cue in (
            {"text": "A B", "times": [0, 0, 0.5]},
            {"text": "{danger}", "times": [0, 1]},
            {"text": "A", "times": [False, 1]},
        ):
            with self.subTest(cue=cue), self.assertRaises(ValueError):
                timed_captions(json.dumps([cue]), 1)

    def test_saved_service_preserves_approved_transcript_and_srt_bytes(self):
        class Aligner:
            def align(self, *args):
                return [TimedWord("Keep", 0, 0.4), TimedWord("this.", 0.4, 1)]

        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "source.mp4"
            source.touch()
            approved = {
                "inputMedia": str(source),
                "inputStartSeconds": 5,
                "inputEndSeconds": 7,
                "sourceLanguage": "en",
                "language": "en",
                "provider": "fixture",
                "model": "small",
                "task": "transcribe",
                "segments": [{"start": 0, "end": 1, "text": "Keep this."}],
            }
            transcript = folder / "approved.json"
            transcript.write_bytes(json.dumps(approved, indent=3).encode())
            srt = folder / "approved.srt"
            srt.write_bytes(b"1\r\n00:00:00,000 --> 00:00:01,000\r\nKeep this.\r\n")
            service = SavedCaptionService(
                transcript, srt, folder / "speech.wav", CaptionStyler(Aligner())
            )
            result = service.generate(source, 5, 7, folder / "new")
            self.assertEqual(
                Path(result["transcriptPath"]).read_bytes(), transcript.read_bytes()
            )
            self.assertEqual(Path(result["srtPath"]).read_bytes(), srt.read_bytes())
            self.assertEqual(
                result["approvedTranscriptSha256"],
                sha256(transcript.read_bytes()).hexdigest(),
            )
            self.assertTrue(result["transcriptReused"])
            self.assertEqual(result["style"], "word_highlight")
            with self.assertRaises(ValueError):
                service.generate(source, 0, 2, folder / "wrong-cut")


if __name__ == "__main__":
    unittest.main()
