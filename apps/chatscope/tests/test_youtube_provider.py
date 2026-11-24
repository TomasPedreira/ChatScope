"""Boundary cases that must not be confused with missing public replay data."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers.youtube import extract


class ProviderTests(unittest.TestCase):
    def extract_info(self, info):
        client = MagicMock()
        client.__enter__.return_value.extract_info.return_value = info
        factory = MagicMock(return_value=client)
        with patch.dict(sys.modules, {
            "yt_dlp": SimpleNamespace(YoutubeDL=factory),
            "yt_dlp.version": SimpleNamespace(__version__="test"),
        }):
            result = extract("https://www.youtube.com/watch?v=YE7VzlLtp-4")
        self.assertTrue(factory.call_args.args[0]["skip_download"])
        self.assertFalse(client.__enter__.return_value.extract_info.call_args.kwargs["download"])
        return result

    def test_valid_video_can_have_no_heatmap(self):
        result = self.extract_info({"id": "YE7VzlLtp-4", "duration": 597, "channel": "Blender"})
        self.assertIsNone(result["heatmap"])
        self.assertEqual(result["duration"], 597)

    def test_unavailable_metadata_is_an_error(self):
        with self.assertRaises(ValueError):
            self.extract_info({"id": "BaW_jenozKc", "title": "Unavailable video"})

    def test_live_or_unprocessed_video_is_an_error(self):
        for state in ["is_live", "is_upcoming", "post_live"]:
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.extract_info({"id": "YE7VzlLtp-4", "duration": 597, "channel": "Blender", "live_status": state})


if __name__ == "__main__":
    unittest.main()
