import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from host import dkaraoke_host as host


class LyricsMetadataTests(unittest.TestCase):
    def test_extracts_artist_and_title_from_youtube_title(self):
        metadata = host.youtube_music_metadata({
            "title": "Coldplay - Yellow (Official Video)",
            "uploader": "ColdplayVEVO",
            "duration": 267,
        })

        self.assertEqual(metadata, {
            "title": "Yellow",
            "artist": "Coldplay",
            "duration": 267.0,
        })

    def test_prefers_structured_track_metadata(self):
        metadata = host.youtube_music_metadata({
            "track": "Bizarre Love Triangle",
            "artist": "New Order",
            "title": "unhelpful upload title",
            "duration": "262.5",
        })

        self.assertEqual(metadata["title"], "Bizarre Love Triangle")
        self.assertEqual(metadata["artist"], "New Order")
        self.assertEqual(metadata["duration"], 262.5)


class LrcParsingTests(unittest.TestCase):
    def test_builds_line_segments_and_interpolated_words(self):
        segments = host.parse_lrc_segments(
            "[00:10.00]Hello world\n[00:12.00]\n[00:14.00]Next line",
            duration=20,
        )

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start_time"], 10.0)
        self.assertEqual(segments[0]["end_time"], 12.0)
        self.assertEqual([word["text"] for word in segments[0]["words"]], ["Hello", "world"])
        self.assertEqual(segments[0]["words"][0]["end_time"], 11.0)
        self.assertEqual(segments[1]["start_time"], 14.0)

    def test_rejects_unrelated_lrclib_candidate(self):
        score = host.lrclib_candidate_score(
            {"trackName": "Shape of You", "artistName": "Ed Sheeran", "duration": 234},
            {"title": "Yellow", "artist": "Coldplay", "duration": 267},
        )

        self.assertEqual(score, -1.0)


class PipelineOrderingTests(unittest.TestCase):
    def test_stems_are_published_before_waiting_for_lyrics_and_whisper(self):
        events = []

        class FakeThread:
            def join(self):
                events.append("lyrics-joined")

        with (
            patch.object(host, "send_stems_ready", side_effect=lambda *args, **kwargs: events.append("stems-ready")),
            patch.object(host, "prepare_lyrics", side_effect=lambda *args, **kwargs: events.append("whisper") or {"text": "x", "segments": []}),
            patch.object(host, "complete_job", side_effect=lambda *args, **kwargs: events.append("complete")),
        ):
            host.publish_stems_then_refine_lyrics(
                "job", "video", Path("audio.mp3"), Path("instrumental.wav"), Path("vocals.wav"),
                Path("output"), "", FakeThread(), {"lyrics": {"text": "x", "segments": [], "source": "lrclib"}},
            )

        self.assertEqual(events, ["stems-ready", "lyrics-joined", "whisper", "complete"])

    def test_cache_check_prefers_whisper_over_lrclib(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            for path in (output_dir / "audio.mp3", stem_dir / "instrumental.wav", stem_dir / "vocals.wav"):
                path.write_bytes(b"audio")
            (output_dir / "lyrics.json").write_text(json.dumps({
                "text": "Whisper words", "segments": [{"start_time": 0}],
                "source": "lrclib+local-whisper",
            }), encoding="utf-8")
            (output_dir / "lrclib_lyrics.json").write_text(json.dumps({
                "text": "LRCLIB words", "segments": [{"start_time": 1}], "source": "lrclib",
            }), encoding="utf-8")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            payload = send_job.call_args.kwargs
            self.assertEqual(payload["lyrics"]["text"], "Whisper words")
            self.assertTrue(payload["hasLyrics"])
            self.assertTrue(payload["hasStems"])

    def test_karaokize_lookup_uses_lrclib_directly(self):
        expected = {"text": "LRCLIB words", "segments": [], "source": "lrclib"}
        with (
            patch.object(host, "load_youtube_info", return_value={"title": "Song"}),
            patch.object(host, "fetch_lrclib_lyrics", return_value=expected) as fetch_lrclib,
            patch.object(host, "fetch_best_available_lyrics") as fetch_best,
            patch.object(host, "send_job"),
        ):
            thread, state = host.start_lyrics_lookup(
                "job", "https://www.youtube.com/watch?v=abcdefghijk", [], Path("output"), "", {},
            )
            thread.join()

        self.assertEqual(state["lyrics"], expected)
        fetch_lrclib.assert_called_once()
        fetch_best.assert_not_called()


if __name__ == "__main__":
    unittest.main()
