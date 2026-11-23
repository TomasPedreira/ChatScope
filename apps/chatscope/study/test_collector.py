"""Offline regression checks for the limits and the review handoff."""

import asyncio
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from collector import LISBON, Study, Window, evaluate, session_deadline
from chat_signals import Activity, chat_flow, emote_ids
from twitch import CHANNELS, clip_segments, media_segments


class PreviewChecks(unittest.TestCase):
    def test_deadline_cannot_roll_into_night(self):
        evening = datetime(2026, 11, 18, 18, tzinfo=LISBON).timestamp()
        cutoff = datetime.fromtimestamp(session_deadline(evening, 8), LISBON)
        self.assertEqual((cutoff.day, cutoff.hour), (18, 22))

    def test_requested_evening_run_still_obeys_its_duration(self):
        start = datetime(2026, 11, 21, 23, 10, tzinfo=LISBON).timestamp()
        self.assertEqual(session_deadline(start, 0.75, outside_hours=True), start + 45 * 60)

    def test_reject_preview_with_missing_start(self):
        segments = list(media_segments(
            "https://test.hls.ttvnw.net/live.m3u8",
            "#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:2026-11-18T10:00:00Z\n"
            "#EXTINF:2.0,\na.ts\n#EXTINF:2.0,\nb.ts\n",
        ))
        start = segments[0].utc + 0.5
        self.assertEqual(len(clip_segments(segments, start, start + 3)), 2)
        with self.assertRaises(ValueError):
            clip_segments(segments[1:], start, start + 3)

    def test_fragmented_mp4_preserves_init_and_skips_ad_ranges(self):
        media_url = "https://test.hls.ttvnw.net/live.m3u8"
        playlist = """#EXTM3U
#EXT-X-DATERANGE:ID="ad",CLASS="twitch-stitched-ad",START-DATE="2026-11-18T10:00:00Z",DURATION=2.0
#EXT-X-MAP:URI="ad-init.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-11-18T10:00:00Z
#EXTINF:2.0,
ad.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="game-init.mp4"
#EXT-X-PROGRAM-DATE-TIME:2026-11-18T10:00:02Z
#EXTINF:2.0,
game-1.mp4
#EXTINF:2.0,
game-2.mp4
"""
        segments = list(media_segments(media_url, playlist))
        self.assertEqual(len(segments), 2)
        self.assertTrue(all(segment.init_url.endswith("/game-init.mp4") for segment in segments))
        self.assertTrue(all("/game-" in segment.url for segment in segments))
        self.assertEqual(len(clip_segments(segments, segments[0].utc, segments[-1].end)), 2)


class StudyChecks(unittest.IsolatedAsyncioTestCase):
    def test_chat_flow_uses_people_and_rejects_repetition(self):
        reference = [Activity(messages=28, people=20)] * 12
        spike = chat_flow(Activity(messages=80, people=73), reference, 3_000)
        self.assertEqual(spike["rule"], "pico de participantes")
        self.assertEqual(spike["excessPeople"], 53)
        flood = chat_flow(Activity(messages=80, people=21), reference, 3_000)
        self.assertIsNone(flood["rule"])
        self.assertIsNone(chat_flow(Activity(messages=80, people=73), reference[:5], 3_000))

    def test_chat_flow_accepts_two_broad_windows_without_one_big_peak(self):
        reference = [Activity(messages=24, people=20)] * 10
        sustained = chat_flow(Activity(messages=40, people=33),
                              [*reference, Activity(messages=37, people=32)], 3_000)
        self.assertEqual(sustained["rule"], "fluxo sustentado")

    def test_experimental_emotes_and_phrases_count_people(self):
        window = Window()
        ids = emote_ids("emotesv2_abc:0-7,9-16/25:18-22/emotesv2_abc:24-31")
        self.assertEqual(ids, ("emotesv2_abc", "25"))
        for user, text in (("one", "NO WAY!"), ("two", "no way"), ("three", "no way??")):
            window.add(user, text, ids)
        for _ in range(6):
            window.add("one", "NO WAY", ids)
        self.assertEqual(window.extra_signals.top(), {
            "emotes": {"25": 3, "emotesv2_abc": 3}, "text": {"no way": 3},
        })
        self.assertEqual(window.extra_signals.top(
            participants=3, baseline=[(window.extra_signals, 3)] * 6,
        ), {"emotes": {}, "text": {}})
        self.assertEqual(len(window.reactors), 0)

    async def test_rotation_keeps_six_candidate_hourly_cap(self):
        now = datetime(2026, 11, 18, 18, tzinfo=LISBON).timestamp()
        with TemporaryDirectory() as temp:
            study = Study(Path(temp), now, now + 3600)

            async def capture(*_):
                pass

            for group, channels in CHANNELS.items():
                feed = SimpleNamespace(name=channels[0], group=group, stream_id=group, capture=capture)
                for offset in (1830, 1950):
                    study.selected(feed, now + offset, {"rule": "ritmo+reações"})
            await asyncio.gather(*study.jobs)
            kinds = [sample["kind"] for sample in study.candidates.values()]
            self.assertEqual(kinds.count("candidate"), 6)
            self.assertLessEqual(kinds.count("control"), 2)

    def test_audience_threshold_scales_and_requires_an_audience_sample(self):
        baseline = [Window(messages=40) for _ in range(6)]
        window = Window()
        for index in range(16):
            window.add(str(index), "MONKAS")
        self.assertIsNotNone(evaluate(window, baseline, 2500)["rule"])
        self.assertIsNone(evaluate(window, baseline, None)["rule"])
        large_stream = evaluate(window, baseline, 27_001)
        self.assertEqual(large_stream["minReactors"], 55)
        self.assertIsNone(large_stream["rule"])
        for index in range(16, 54):
            window.add(str(index), "MONKAS")
        self.assertIsNone(evaluate(window, baseline, 27_001)["rule"])
        window.add("54", "MONKAS")
        self.assertIsNotNone(evaluate(window, baseline, 27_001)["rule"])

    def test_strong_burst_can_pass_on_a_large_stream(self):
        baseline = [Window(messages=40, reactors=set(range(4))) for _ in range(18)]
        window = Window(messages=122, participants=set(range(115)), reactors=set(range(50)))
        score = evaluate(window, baseline, 96_216)
        self.assertEqual(score["rule"], "pico acima da rotina do canal")
        self.assertEqual(score["minReactors"], 37)
        self.assertEqual(score["reactionBaseline"], 4)
        self.assertIsNone(evaluate(window, baseline[:5], 96_216)["rule"])

    def test_sixteen_reactors_cannot_pass_on_a_large_stream(self):
        baseline = [Window(messages=20, reactors=set(range(3))) for _ in range(18)]
        window = Window(messages=60, participants=set(range(48)), reactors=set(range(16)))
        score = evaluate(window, baseline, 49_175)
        self.assertEqual(score["burstMinReactors"], 27)
        self.assertIsNone(score["rule"])

    async def test_capped_selection_reaches_report_without_double_counting_reactions(self):
        now = datetime(2026, 11, 18, 18, tzinfo=LISBON).timestamp()
        baseline = [Window(messages=12) for _ in range(6)]
        window = Window()
        for index in range(8):
            window.add(str(index), "MONKAS")
        for _ in range(20):
            window.add("0", "MONKAS")
        metrics = evaluate(window, baseline, 99)
        self.assertEqual(metrics["reactors"], 8)
        self.assertIsNotNone(metrics["rule"])

        with TemporaryDirectory() as temp:
            study = Study(Path(temp), now, now + 3600)

            async def capture(clip_id, start, end):
                peak = study.candidates[clip_id]["peakTimestamp"]
                self.assertEqual((peak - start, end - peak), (55, 18))
                study.candidates[clip_id]["status"] = "ready"

            feed = SimpleNamespace(name="example_channel", group="conversa", stream_id="123", capture=capture)
            study.audience[("example_channel", "123")] = [(now, 99)]
            for offset in (120, 130, 220, 1850, 1960):
                study.selected(feed, now + offset, metrics)
            await asyncio.gather(*study.jobs)
            self.assertEqual(len(study.candidates), 2)
            study.update_report("teste")
            self.assertEqual([sample["peakTimestamp"]-now for sample in study.candidates.values()], [120, 1850])
            self.assertIn("| example_channel | 0 | 1 |", (Path(temp) / "resultado.md").read_text(encoding="utf-8"))
            self.assertEqual((Path(temp) / "revisao.md").read_text(encoding="utf-8").count("[MP4]"), 2)


if __name__ == "__main__":
    unittest.main()
