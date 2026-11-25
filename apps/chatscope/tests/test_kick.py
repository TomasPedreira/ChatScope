"""Kick adapter contracts: test acquisition timing without network availability assumptions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.providers import SourceRegistry
from pipeline.kick import KickSource
from pipeline.worker import analyze
from test_pipeline import synthetic


class KickTests(unittest.TestCase):
    def test_registry_reports_media_adapter_without_assuming_public_heatmap(self):
        provider, source = SourceRegistry().resolve("https://kick.com/xqc")
        self.assertEqual(provider, "kick")
        self.assertIsInstance(source, KickSource)

    def test_live_offsets_belong_to_the_recording(self):
        self.check_capture(live=True)

    def test_vod_offsets_remain_absolute(self):
        self.check_capture(live=False)

    def check_capture(self, live):
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="kick-contract-",dir=artifacts) as temporary:
            folder = Path(temporary)
            video = folder/"master.mp4"
            synthetic(video)
            info = {"id":"kick-fixture","title":"Fixture Kick","channel":"Example", "is_live":live,
                    "duration":None if live else 300}
            request = {"url":"https://kick.com/example","id":"fixture","root":str(folder/"cache"),
                       "captureSeconds":30,"start":None if live else 10,"end":None if live else 15,
                       "clipProfile":{"duration":5,"beforePeak":2,"maxMoments":2}}
            with patch.object(KickSource,"metadata",return_value=info), \
                 patch.object(KickSource,"acquire",return_value=(video,0 if live else 10)):
                result = analyze(request)
            self.assertEqual(result["source"]["kind"],"kick_live" if live else "kick")
            self.assertEqual(result["analysis"]["signal"],"audio_energy")
            self.assertEqual(result["analysis"]["timeOrigin"],"recording" if live else "source")
            self.assertEqual(result["source"]["start"],0 if live else 10)
            self.assertEqual(result["analysis"]["points"][0]["start_time"],0 if live else 10)
            self.assertEqual(Path(result["analysis"]["localMedia"]),video)


if __name__ == "__main__":
    unittest.main()
