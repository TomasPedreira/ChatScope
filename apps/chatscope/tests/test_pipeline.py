"""Real local acquisition/rendering plus boundary tests. No network or channel credentials."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.media_sources import MediaSourceRegistry, YtDlpSource
from pipeline.video_renderer import FFmpegRenderer
from pipeline.caption_service import CaptionService
from pipeline.caption_styling import CaptionStyler
from pipeline.word_alignment import TimedWord
from pipeline.request_validation import validate_render_profile
from pipeline.audio_signals import extract_audio_energy_signal
from pipeline.request_validation import validate_clip_profile
from pipeline.media_tools import (
    resolve_ffmpeg_executable,
    probe_video,
    run_media_command,
)
from pipeline.source_analysis import analyze_media_request
from pipeline.clip_production import render_clip_batch
from pipeline.request_validation import validate_heatmap_points


def synthetic(path, audio=True):
    inputs = ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24"]
    if audio:
        inputs += [
            "-f",
            "lavfi",
            "-i",
            r"aevalsrc=if(between(t\,5\,7)\,0.8\,0.01)*sin(2*PI*440*t):s=16000",
        ]
    run_media_command(
        [
            resolve_ffmpeg_executable(),
            "-v",
            "error",
            "-nostdin",
            "-n",
            *inputs,
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )


class Boundaries(unittest.TestCase):
    def test_ffmpeg_applies_network_timeout_to_video_and_audio_inputs(self):
        from yt_dlp import YoutubeDL
        from yt_dlp.downloader.external import FFmpegFD

        options = YtDlpSource(
            "https://www.youtube.com/watch?v=bsTxc6iwPb4", "youtube"
        ).options()
        with YoutubeDL(options) as client:
            downloader = FFmpegFD(client, options)
            for input_key in ("_i1", "_i2"):
                self.assertEqual(
                    downloader._configuration_args((input_key, "_i")),
                    ["-rw_timeout", "20000000"],
                )

    def test_untrusted_sources_and_profiles_are_rejected(self):
        for url in (
            "https://youtube.com.evil.org/watch?v=YE7VzlLtp-4",
            "https://user@youtube.com/a",
            "http://twitch.tv/a",
            "file://server/share/a.mp4",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                MediaSourceRegistry().resolve(url)
        for profile in (
            {"duration": 0, "beforePeak": 0, "maxMoments": 1},
            {"duration": 30, "beforePeak": 31, "maxMoments": 1},
            {"duration": 30, "beforePeak": 20, "maxMoments": True},
        ):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_clip_profile(profile)
        with self.assertRaises(ValueError):
            validate_render_profile({"aspect": "9:16", "fit": "arbitrary"})

    def test_invalid_replay_signals_are_not_treated_as_missing(self):
        for points in (
            [{"start_time": 0, "end_time": 10, "value": float("nan")}],
            [{"start_time": 0, "end_time": 10, "value": 1.1}],
            [
                {"start_time": 0, "end_time": 10, "value": 0.5},
                {"start_time": 9, "end_time": 11, "value": 0.8},
            ],
        ):
            with self.subTest(points=points), self.assertRaises(ValueError):
                validate_heatmap_points(points, 20)


class LocalProduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        cls.temp = TemporaryDirectory(prefix="pipeline-", dir=artifacts)
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "vídeo com espaços.mp4"
        synthetic(cls.source)
        cls.profile = {"duration": 5, "beforePeak": 2, "maxMoments": 2}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_audio_fallback_and_absolute_offsets(self):
        points = extract_audio_energy_signal(self.source, 3, 10)
        loud = [p["value"] for p in points if 5 <= p["start_time"] < 7]
        quiet = [p["value"] for p in points if p["start_time"] < 5]
        self.assertGreater(min(loud), max(quiet) + 0.3)
        result = analyze_media_request(
            {
                "url": self.source.as_uri(),
                "id": "local-analysis",
                "root": str(self.folder / "cache-test"),
                "clipProfile": self.profile,
                "start": 3,
                "end": 10,
            }
        )
        self.assertEqual(result["source"]["start"], 3)
        self.assertEqual(result["analysis"]["signal"], "audio_energy")
        self.assertEqual(result["analysis"]["points"][0]["start_time"], 3)
        self.assertEqual(Path(result["analysis"]["localMedia"]), self.source)

    def test_render_profiles_preserve_duration_and_support_silent_video(self):
        for aspect, fit, size in (
            ("1:1", "crop", (1080, 1080)),
            ("16:9", "pad", (1920, 1080)),
        ):
            output = self.folder / f"render-{fit}.mp4"
            info = FFmpegRenderer().render(
                self.source,
                output,
                2,
                7,
                {"aspect": aspect, "fit": fit, "captions": False},
            )
            self.assertEqual((info["width"], info["height"]), size)
            self.assertAlmostEqual(info["duration"], 5, delta=0.15)
            self.assertTrue(info["audio"])
        silent = self.folder / "silent.mp4"
        synthetic(silent, audio=False)
        info = FFmpegRenderer().render(
            silent,
            self.folder / "silent-draft.mp4",
            0,
            5,
            {"aspect": "9:16", "captions": True},
        )
        self.assertFalse(info["audio"])
        self.assertEqual(info["captions"]["status"], "no_audio")

    def test_batch_preserves_success_when_another_clip_fails(self):
        root = self.folder / "production"
        source = {
            "url": self.source.as_uri(),
            "id": "fixture",
            "title": "Vídeo de teste",
            "channel": "local",
            "kind": "local",
            "start": 0,
            "end": 12,
            "duration": 12,
        }
        moment = {
            "start": 2,
            "end": 7,
            "peak": 6,
            "signal": "manual",
            "reason": "Teste real",
            "strength": 1,
        }
        request = {
            "id": "batch-test",
            "root": str(root),
            "source": source,
            "clipProfile": self.profile,
            "renderProfile": {"aspect": "9:16", "fit": "pad", "captions": False},
            "topic": "testes",
            "moments": [moment, {**moment, "start": 11, "end": 17}],
            "localMedia": str(self.source),
            "mediaOrigin": 0,
        }
        result = render_clip_batch(request)
        self.assertEqual(result["status"], "partial")
        ready, error = result["clips"]
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(error["status"], "error")
        self.assertTrue(Path(ready["path"]).is_file())
        self.assertEqual(len(ready["sha256"]), 64)
        self.assertEqual(
            json.loads((root / "current.json").read_text(encoding="utf-8"))["status"],
            "partial",
        )
        self.assertTrue(list(root.glob("*/clips-index.md")))
        with self.assertRaises(FileExistsError):
            render_clip_batch(request)

    def test_caption_renderer_with_transcriber_boundary(self):
        folder = self.folder / "caption-test"
        folder.mkdir()

        class Speech:
            def transcribe(self, source, **options):
                assert options == {
                    "language": None,
                    "task": "translate",
                    "vad_filter": True,
                }
                return iter(
                    [SimpleNamespace(start=-0.1, end=8, text="This is a caption test.")]
                ), SimpleNamespace(language="pt")

        class FixedWordAligner:
            def align(self, audio, cues, source_language, task, model_name):
                return [
                    TimedWord(word, index, index + 1)
                    for index, word in enumerate("This is a caption test.".split())
                ]

        with patch(
            "pipeline.speech_transcriber.load_whisper_model", return_value=Speech()
        ):
            service = CaptionService(caption_styler=CaptionStyler(FixedWordAligner()))
            info = FFmpegRenderer(caption_service=service).render(
                self.source,
                folder / "captioned.mp4",
                2,
                7,
                {"aspect": "1:1", "fit": "pad", "captions": True},
            )
        self.assertAlmostEqual(info["duration"], 5, delta=0.15)
        captions = (folder / "captions.srt").read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:05,000", captions)
        self.assertIn("This is a caption test.", captions)
        self.assertEqual(
            json.loads((folder / "transcript.json").read_text(encoding="utf-8"))[
                "language"
            ],
            "en",
        )
        transcript = json.loads(
            (folder / "transcript.json").read_text(encoding="utf-8")
        )
        self.assertEqual(transcript["sourceLanguage"], "pt")
        self.assertEqual(info["captions"]["language"], "en")
        self.assertEqual(info["captions"]["task"], "translate")
        self.assertEqual(info["captions"]["style"], "word_highlight")
        self.assertIn(
            r"{\1c&H48D5FF&}", (folder / "captions.ass").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
