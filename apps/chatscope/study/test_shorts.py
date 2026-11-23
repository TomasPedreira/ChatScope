"""Offline checks for private uploads and review alerts."""

from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import shorts
import drafts
import shorts_style as style
import shorts_youtube as youtube


VIDEO_ID = "ABC123abcDE"
SESSION_URL = youtube.UPLOAD + "?uploadType=resumable&upload_id=fixture"


class ShortStyleTests(unittest.TestCase):
    def test_template_keeps_credits_and_deduplicates_hashtags(self):
        description = style.format_description(
            "Momento do direto. #GTA6", ["gta6", "TwitchClips", "shorts"],
            "https://www.twitch.tv/ricfazeres", "https://www.youtube.com/@RicFazeres",
        )
        self.assertEqual(description, (
            "Momento do direto. #GTA6\n\n"
            "Twitch: https://www.twitch.tv/ricfazeres\n"
            "YouTube: https://www.youtube.com/@RicFazeres\n\n#TwitchClips #shorts"
        ))

    def test_template_highlights_only_the_timed_word(self):
        ass = style.timed_captions('[{"text":"O carro","times":[1,1.2,1.5]}]', 2)
        lines = [line for line in ass.splitlines() if line.startswith("Dialogue")]
        self.assertEqual(len(lines), 2)
        self.assertIn("0:00:01.00,0:00:01.20", lines[0])
        self.assertIn(r"{\1c&H48D5FF&}CARRO", lines[1])

    def test_draft_captions_fit_the_trim_and_keep_word_timing(self):
        words = [(0.20, 0.42, "Outside"), (1.20, 1.40, "Good"), (1.40, 1.55, "shot."),
                 (2.60, 3.40, "Wow!")]
        cues = drafts.caption_cues(words, 1.0, 3.006)
        self.assertEqual(cues[0]["text"], "Good shot.")
        self.assertEqual(cues[0]["times"][:2], [0.2, 0.4])
        self.assertEqual(cues[-1]["times"][-1], 2.0)
        self.assertIn("WOW!", style.timed_captions(json.dumps(cues), 2.006))

    def test_editor_can_remove_multiple_pauses_from_one_source(self):
        self.assertEqual(drafts.kept_spans(6, 50, [(12, 14), (28, 37)]), [(6, 12), (14, 28), (37, 50)])
        with self.assertRaises(ValueError):
            drafts.kept_spans(6, 50, [(12, 28), (25, 37)])


def response(status, headers=None, body=None):
    return SimpleNamespace(status_code=status, headers=headers or {}, json=lambda: body or {})


class PrivateUploadTests(unittest.TestCase):
    def test_authorization_survives_a_disabled_youtube_api(self):
        channel = "UC" + "a" * 22
        args = SimpleNamespace(channel=channel, resume=False, client=Path("client.json"), account=None)
        credentials = Mock(refresh_token="fixture")
        credentials.to_json.return_value = '{"refresh_token":"fixture","client_id":"fixture","client_secret":"fixture"}'
        with (
            TemporaryDirectory() as folder,
            patch.object(shorts, "CONFIG", Path(folder)),
            patch.object(youtube, "connect", return_value=credentials) as consent,
            patch.object(youtube, "authorized_session", return_value=MagicMock()),
            patch.object(youtube, "selected_channel",
                         side_effect=[youtube.UploadError("API desativada"), (channel, "Clips")]),
        ):
            with self.assertRaises(youtube.UploadError):
                shorts.connect(args)
            pending = Path(folder) / "youtube-pendente.json"
            self.assertTrue(pending.is_file())
            self.assertFalse((Path(folder) / "youtube.json").exists())
            args.resume = True
            shorts.connect(args)
            consent.assert_called_once()
            self.assertFalse(pending.exists())
            self.assertEqual(shorts.load_config(Path(folder) / "youtube.json", "ligar")["channel"], channel)

    def test_rejects_an_ambiguous_destination_channel(self):
        session = Mock()
        session.get.return_value = response(200, body={"items": [{"id": "review"}, {"id": "personal"}]})
        with self.assertRaises(youtube.UploadError):
            youtube.verify_channel(session, "review")

    def test_initiation_requests_private_video(self):
        session = Mock()
        session.post.return_value = response(200, {"Location": SESSION_URL})
        self.assertEqual(youtube.begin_upload(session, 5, "Short", "", False), SESSION_URL)
        metadata = session.post.call_args.kwargs["json"]
        self.assertEqual(metadata["status"]["privacyStatus"], "private")
        self.assertNotIn("publishAt", metadata["status"])

    def test_resumes_the_same_upload_from_confirmed_offset(self):
        session = Mock()
        session.put.side_effect = [response(308, {"Range": "bytes=0-2"}), response(201, body={"id": VIDEO_ID})]
        self.assertEqual(youtube.send_media(session, SESSION_URL, BytesIO(b"12345"), 5), VIDEO_ID)
        self.assertEqual(session.put.call_args_list[0].kwargs["headers"]["Content-Range"], "bytes */5")
        self.assertEqual(session.put.call_args.kwargs["headers"]["Content-Range"], "bytes 3-4/5")
        self.assertEqual(session.put.call_args.kwargs["data"], b"45")

    def test_video_must_be_private_in_the_expected_channel(self):
        session = Mock()
        video = {"snippet": {"channelId": "review"}, "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"}}
        session.get.return_value = response(200, body={"items": [video]})
        with self.assertRaises(youtube.UploadError):
            youtube.video_status(session, VIDEO_ID, "review")

    def test_title_update_keeps_other_metadata_and_privacy(self):
        session = Mock()
        snippet = {"title": "Original", "categoryId": "20", "description": "Credits",
                   "tags": ["Shorts"], "defaultLanguage": "en", "channelId": "review"}
        video = {"snippet": snippet, "status": {"privacyStatus": "private"}}
        session.get.return_value = response(200, body={"items": [video]})
        session.put.return_value = response(200, body={"snippet": {"title": "New title"}})
        youtube.update_title(session, VIDEO_ID, "review", "New title")
        self.assertEqual(session.put.call_args.kwargs["params"], {"part": "snippet"})
        self.assertEqual(session.put.call_args.kwargs["json"], {
            "id": VIDEO_ID,
            "snippet": {key: value for key, value in (snippet | {"title": "New title"}).items()
                        if key != "channelId"},
        })
        video["status"]["privacyStatus"] = "public"
        session.put.reset_mock()
        with self.assertRaises(youtube.UploadError):
            youtube.update_title(session, VIDEO_ID, "review", "New title")
        session.put.assert_not_called()
        youtube.update_title(session, VIDEO_ID, "review", "New title", allow_public=True)
        self.assertEqual(session.put.call_args.kwargs["params"], {"part": "snippet"})
        video["status"]["privacyStatus"] = "unlisted"
        session.put.reset_mock()
        with self.assertRaises(youtube.UploadError):
            youtube.update_title(session, VIDEO_ID, "review", "New title", allow_public=True)
        session.put.assert_not_called()

    def test_publish_only_when_processed_and_never_republishes_existing_id(self):
        session = Mock()
        video = {"id": VIDEO_ID, "snippet": {"channelId": "review"},
                 "status": {"uploadStatus": "uploaded", "privacyStatus": "private",
                            "selfDeclaredMadeForKids": False}}
        with self.assertRaises(youtube.UploadError):
            youtube.publish_video(session, video, "review")
        session.put.assert_not_called()
        video["status"]["uploadStatus"] = "processed"
        session.put.return_value = response(200, body={"status": {"privacyStatus": "public"}})
        youtube.publish_video(session, video, "review")
        self.assertEqual(session.put.call_args.kwargs["params"], {"part": "status"})
        self.assertEqual(session.put.call_args.kwargs["json"], {
            "id": VIDEO_ID, "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        })
        video["status"]["privacyStatus"] = "public"
        youtube.publish_video(session, video, "review")
        session.put.assert_called_once()

    def test_editorial_publish_resumes_without_uploading_a_duplicate(self):
        with TemporaryDirectory() as folder, patch.object(shorts, "CONFIG", Path(folder)):
            root = Path(folder)
            source = root / "drafts" / "0001-creator.mp4"
            source.parent.mkdir()
            source.write_bytes(b"reviewed draft")
            shorts.save_config(root / "youtube.json", {
                "channel": "review",
                "credentials": {"refresh_token": "fixture", "client_id": "fixture",
                                "client_secret": "fixture", "scopes": [youtube.EDIT_SCOPE]},
            })
            args = SimpleNamespace(source=source, title="Strong title", reason="Setup and reaction",
                                   action_evidence=("4.5", "He pulls the parking brake"),
                                   outcome_evidence=("14", "The car rolls into the sea"),
                                   description="", youtube_url=None, hashtags=())
            candidate = {"id": source.stem, "channel": "creator"}
            video = {"id": VIDEO_ID, "snippet": {"title": args.title, "channelId": "review"},
                     "status": {"uploadStatus": "processed", "privacyStatus": "private"}}
            with (
                patch.object(drafts, "verified_draft", return_value=(root, candidate, source)),
                patch.object(shorts, "probe", return_value=(1080, 1920, 20)),
                patch.object(youtube, "authorized_session", return_value=MagicMock()),
                patch.object(youtube, "verify_channel"),
                patch.object(youtube, "begin_upload", return_value=SESSION_URL),
                patch.object(youtube, "send_media", return_value=VIDEO_ID) as sent,
                patch.object(youtube, "lookup_video", return_value=video),
                patch.object(youtube, "publish_video") as published,
                patch.object(shorts, "collect_metrics", return_value=("fixture", 1)) as feedback,
            ):
                approved_outcome = args.outcome_evidence
                args.outcome_evidence = ("21", "The car rolls into the sea")
                with self.assertRaisesRegex(ValueError, "dentro do corte"):
                    shorts.publish_draft(args)
                sent.assert_not_called()
                published.assert_not_called()
                args.outcome_evidence = approved_outcome
                shorts.publish_draft(args)
                video["status"]["privacyStatus"] = "public"
                shorts.publish_draft(args)
                video["status"]["privacyStatus"] = "private"
                with self.assertRaisesRegex(ValueError, "retirado"):
                    shorts.publish_draft(args)
                with self.assertRaisesRegex(ValueError, "retirado"):
                    shorts.publish_draft(args)
                sent.assert_called_once()
                self.assertEqual(published.call_count, 2)
                feedback.assert_called_once()
            with closing(shorts.queue()) as db:
                row = db.execute("SELECT reason,published_at FROM short_publications").fetchone()
                self.assertEqual(row["reason"], "Setup and reaction")
                self.assertIsNotNone(row["published_at"])
                self.assertIsNotNone(db.execute("SELECT withdrawn_at FROM short_withdrawals").fetchone())
                review = db.execute("SELECT action_at,outcome_at FROM short_reviews").fetchone()
                self.assertEqual(tuple(review), (4.5, 14))

    def test_publication_gap_survives_reopening_the_queue(self):
        with TemporaryDirectory() as folder, patch.object(shorts, "CONFIG", Path(folder)):
            with closing(shorts.queue()) as db:
                self.assertIsNone(shorts.reserve_publication(db, 1000))
            with closing(shorts.queue()) as db:
                self.assertEqual(shorts.reserve_publication(db, 1001), 2830)
                self.assertEqual(shorts.reserve_publication(db, 2799), 2830)
                self.assertIsNone(shorts.reserve_publication(db, 2830))

    def test_feedback_keeps_public_metrics_and_distinguishes_zero_from_missing(self):
        with TemporaryDirectory() as folder, patch.object(shorts, "CONFIG", Path(folder)), closing(shorts.queue()) as db:
            with db:
                db.execute(
                    """INSERT INTO shorts(id,path,digest,title,description,made_for_kids,video_id)
                       VALUES(?,?,?,?,?,?,?)""",
                    ("id", "clip.mp4", "hash", "Public clip", "", 0, VIDEO_ID),
                )
            api = Mock()
            api.get.return_value = response(200, body={"items": [
                {"id": VIDEO_ID, "snippet": {"channelId": "review", "publishedAt": "2026-11-22T00:00:00Z"},
                 "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "0", "likeCount": "1"},
                 "contentDetails": {"duration": "PT18S"}},
                {"id": "other", "snippet": {"channelId": "review"}, "status": {"privacyStatus": "private"}},
            ]})
            stamp, count = shorts.collect_metrics(db, api, "review")
            self.assertEqual(count, 1)
            row = db.execute("SELECT measured_at,views,likes,comments,duration FROM short_metrics").fetchone()
            self.assertEqual(tuple(row), (stamp, 0, 1, None, "PT18S"))

    def test_title_queue_applies_before_upload_or_updates_the_existing_id(self):
        with TemporaryDirectory() as folder, patch.object(shorts, "CONFIG", Path(folder)):
            fresh, uploaded = (Path(folder) / name for name in ("new.mp4", "uploaded.mp4"))
            with closing(shorts.queue()) as db, db:
                db.executemany(
                    """INSERT INTO shorts(id,path,digest,title,description,made_for_kids,video_id,notified)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    [("new", str(fresh), "new", "Original", "", 0, None, 0),
                     ("uploaded", str(uploaded), "uploaded", "Original", "", 0, VIDEO_ID, 1)],
                )
            shorts.stage_title(fresh, "Final title")
            shorts.stage_title(uploaded, "Initial edit")
            shorts.stage_title(uploaded, "Latest edit")
            with closing(shorts.queue()) as db:
                shorts.apply_titles_before_upload(db)
                self.assertEqual(db.execute("SELECT title FROM shorts WHERE id='new'").fetchone()[0], "Final title")
                self.assertEqual(db.execute("SELECT title FROM short_titles").fetchone()[0], "Latest edit")
                with patch.object(youtube, "update_title") as update:
                    shorts.apply_uploaded_titles(db, None, "review")
                update.assert_called_once_with(None, VIDEO_ID, "review", "Latest edit", allow_public=False)
                row = db.execute("SELECT title,video_id,notified FROM shorts WHERE id='uploaded'").fetchone()
                self.assertEqual(tuple(row), ("Latest edit", VIDEO_ID, 1))
                self.assertIsNone(db.execute("SELECT 1 FROM short_titles").fetchone())

    def test_notifies_only_after_processing_and_keeps_uploaded_id(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(shorts, "CONFIG", Path(folder)),
            closing(shorts.queue()) as db,
        ):
            file = Path(folder) / "test.mp4"
            file.write_bytes(b"fixture")
            with db:
                db.execute(
                    "INSERT INTO shorts(id,path,digest,title,description,made_for_kids) VALUES(?,?,?,?,?,?)",
                    ("test", str(file), shorts.digest(file), "A clip", "", 0),
                )
            with (
                patch.object(youtube, "begin_upload", return_value=SESSION_URL) as begin,
                patch.object(youtube, "send_media", return_value=VIDEO_ID),
                patch.object(youtube, "video_status", side_effect=[False, True]),
                patch.object(shorts, "notify") as send,
            ):
                row = db.execute("SELECT * FROM shorts WHERE notified=0").fetchone()
                shorts.process_job(db, None, "review", {}, row)
                send.assert_not_called()
                row = db.execute("SELECT * FROM shorts WHERE notified=0").fetchone()
                self.assertEqual(row["video_id"], VIDEO_ID)
                shorts.process_job(db, None, "review", {}, row)
                begin.assert_called_once()
                send.assert_called_once_with({}, VIDEO_ID, "A clip")
                self.assertIsNone(db.execute("SELECT id FROM shorts WHERE notified=0").fetchone())


if __name__ == "__main__":
    unittest.main()
