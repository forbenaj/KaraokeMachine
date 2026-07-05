import unittest
import json
import os
import subprocess
import tempfile
import threading
import time
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from host import dkaraoke_host as host
from host.dkaraoke import diagnostics, paths
from host import lyrics_runner


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LyricsMetadataTests(unittest.TestCase):
    def test_extracts_artist_and_title_from_page_title(self):
        metadata = host.song_metadata_from_title(
            "Coldplay - Yellow (Official Video)",
            267,
        )

        self.assertEqual(metadata, {
            "title": "Yellow",
            "artist": "Coldplay",
            "duration": 267.0,
        })

    def test_removes_youtube_suffix_from_page_title(self):
        metadata = host.song_metadata_from_title(
            "New Order - Bizarre Love Triangle - YouTube",
            "262.5",
        )

        self.assertEqual(metadata["title"], "Bizarre Love Triangle")
        self.assertEqual(metadata["artist"], "New Order")
        self.assertEqual(metadata["duration"], 262.5)

    def test_accepts_unicode_title_separators(self):
        metadata = host.song_metadata_from_title(
            "A-ha – Take On Me [Official Music Video]",
            225,
        )

        self.assertEqual(metadata["title"], "Take On Me")
        self.assertEqual(metadata["artist"], "A-ha")
        self.assertEqual(metadata["duration"], 225.0)

    def test_removes_promotional_bracket_suffix_with_extra_words(self):
        metadata = host.song_metadata_from_title(
            "Michael Jackson - Don't Stop 'Til You Get Enough (Official Video - Upscaled)",
            253,
        )

        self.assertEqual(metadata["title"], "Don't Stop 'Til You Get Enough")
        self.assertEqual(metadata["artist"], "Michael Jackson")
        self.assertEqual(metadata["duration"], 253.0)

    def test_removes_live_bracket_and_trailing_year_suffix(self):
        metadata = host.song_metadata_from_title(
            "Michael Jackson - Billie Jean (Live) - 1983",
            299,
        )

        self.assertEqual(metadata["title"], "Billie Jean")
        self.assertEqual(metadata["artist"], "Michael Jackson")
        self.assertEqual(metadata["duration"], 299.0)

    def test_preserves_non_noise_parenthetical_title_text(self):
        metadata = host.song_metadata_from_title(
            "Eurythmics - Sweet Dreams (Are Made of This)",
            216,
        )

        self.assertEqual(metadata["title"], "Sweet Dreams (Are Made of This)")
        self.assertEqual(metadata["artist"], "Eurythmics")


class YoutubeHelperTests(unittest.TestCase):
    def test_http_403_download_error_can_retry_with_cookies(self):
        self.assertTrue(host.has_auth_error(
            "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        ))

    def test_cookie_file_writer_has_uuid_dependency(self):
        path = host.write_cookie_file([{
            "domain": ".youtube.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "expirationDate": 1893456000,
            "name": "SID",
            "value": "secret",
        }])

        try:
            self.assertIsNotNone(path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("# Netscape HTTP Cookie File", text)
            self.assertIn("SID", text)
        finally:
            if path:
                Path(path).unlink(missing_ok=True)


class PathsConfigTests(unittest.TestCase):
    def test_app_download_dir_uses_configured_downloads_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_appdata = root / "local"
            downloads = root / "custom-downloads"
            config_dir = local_appdata / "DKaraoKe"
            config_dir.mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({
                "downloadsDir": str(downloads),
            }), encoding="utf-8")

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_appdata)}):
                result = paths.app_download_dir("abcdefghijk")

            self.assertEqual(result, downloads / "abcdefghijk")
            self.assertTrue(result.exists())

    def test_app_download_dir_falls_back_when_config_is_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            local_appdata = Path(temporary) / "local"
            config_dir = local_appdata / "DKaraoKe"
            config_dir.mkdir(parents=True)
            (config_dir / "config.json").write_text("{not json", encoding="utf-8")

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_appdata)}):
                result = paths.app_download_dir("abcdefghijk")

            self.assertEqual(result, local_appdata / "DKaraoKe" / "downloads" / "abcdefghijk")
            self.assertTrue(result.exists())


class LrcParsingTests(unittest.TestCase):
    def test_builds_line_segments_without_fake_words(self):
        segments = host.parse_lrc_segments(
            "[00:10.00]Hello world\n[00:12.00]\n[00:14.00]Next line",
            duration=20,
        )

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start_time"], 10.0)
        self.assertEqual(segments[0]["end_time"], 12.0)
        self.assertEqual(segments[0]["text"], "Hello world")
        self.assertEqual(segments[0]["words"], [])
        self.assertEqual(segments[1]["start_time"], 14.0)

    def test_rejects_unrelated_lrclib_candidate(self):
        score = host.lrclib_candidate_score(
            {"trackName": "Shape of You", "artistName": "Ed Sheeran", "duration": 234},
            {"title": "Yellow", "artist": "Coldplay", "duration": 267},
        )

        self.assertEqual(score, -1.0)

    def test_lrclib_score_tolerates_feature_metadata(self):
        score = host.lrclib_candidate_score(
            {
                "trackName": "Save Your Tears",
                "artistName": "The Weeknd",
                "duration": 215,
                "syncedLyrics": "[00:01.00]Save your tears",
            },
            {
                "title": "Save Your Tears (feat. Ariana Grande)",
                "artist": "The Weeknd feat. Ariana Grande",
                "duration": 214,
            },
        )

        self.assertGreaterEqual(score, 0.88)

    def test_lrclib_rejects_short_title_embedded_in_venue_without_artist(self):
        score = host.lrclib_candidate_score(
            {
                "trackName": "Give You My Lovin' (FM Broadcast The Metro Chicago 12th November 1994)",
                "artistName": "Mazzy Star",
                "duration": 242,
                "plainLyrics": "Give you my lovin'",
            },
            {
                "title": "Chicago",
                "artist": "",
                "duration": 246,
            },
        )

        self.assertEqual(score, -1.0)

    def test_lrclib_explicit_artist_hint_ranks_single_word_song(self):
        variants = host.lyrics.lrclib_metadata_variants({
            "title": "Chicago",
            "artist": "Michael Jackson",
            "duration": 246,
        })
        queries = host.lyrics.lrclib_search_queries(variants)

        self.assertEqual(variants[0]["title"], "Chicago")
        self.assertEqual(variants[0]["artist"], "Michael Jackson")
        self.assertEqual(queries[0], {
            "track_name": "Chicago",
            "artist_name": "Michael Jackson",
        })

    def test_lrclib_query_strips_official_video_upscaled_suffix(self):
        variants = host.lyrics.lrclib_metadata_variants({
            "title": "Michael Jackson - Don't Stop 'Til You Get Enough (Official Video - Upscaled)",
            "artist": "",
            "duration": 253,
        })
        queries = host.lyrics.lrclib_search_queries(variants)

        self.assertEqual(variants[0]["title"], "Don't Stop 'Til You Get Enough")
        self.assertEqual(variants[0]["artist"], "Michael Jackson")
        self.assertEqual(queries[0], {
            "track_name": "Don't Stop 'Til You Get Enough",
            "artist_name": "Michael Jackson",
        })

    def test_lrclib_query_strips_live_year_suffix(self):
        variants = host.lyrics.lrclib_metadata_variants({
            "title": "Michael Jackson - Billie Jean (Live) - 1983",
            "artist": "",
            "duration": 299,
        })
        queries = host.lyrics.lrclib_search_queries(variants)

        self.assertEqual(variants[0]["title"], "Billie Jean")
        self.assertEqual(variants[0]["artist"], "Michael Jackson")
        self.assertEqual(queries[0], {
            "track_name": "Billie Jean",
            "artist_name": "Michael Jackson",
        })

    def test_lrclib_search_stops_after_confident_primary_match(self):
        candidate = {
            "id": 1,
            "trackName": "Yellow",
            "artistName": "Coldplay",
            "albumName": "Parachutes",
            "duration": 267,
            "syncedLyrics": "[00:01.00]Look at the stars",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(host.lyrics, "urlopen", return_value=JsonResponse([candidate])) as urlopen:
                result = host.fetch_lrclib_lyrics(
                    {"title": "Coldplay - Yellow", "duration": 267},
                    Path(temporary),
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result["text"], "Look at the stars")
        self.assertEqual(result["providerId"], 1)
        self.assertEqual(result["searchCount"], 1)
        self.assertIn("matchBreakdown", result)

    def test_lrclib_search_tries_swapped_title_artist_variant(self):
        candidate = {
            "id": 2,
            "trackName": "Yellow",
            "artistName": "Coldplay",
            "albumName": "Parachutes",
            "duration": 267,
            "plainLyrics": "Look at the stars",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                host.lyrics,
                "urlopen",
                side_effect=[JsonResponse([]), JsonResponse([candidate])],
            ) as urlopen:
                result = host.fetch_lrclib_lyrics(
                    {"title": "Yellow - Coldplay", "duration": 267},
                    Path(temporary),
                )

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["text"], "Look at the stars")
        self.assertEqual(result["artist"], "Coldplay")
        self.assertGreaterEqual(result["matchScore"], 0.88)

    def test_lrclib_search_continues_after_query_timeout(self):
        candidate = {
            "id": 4,
            "trackName": "Chicago",
            "artistName": "Michael Jackson",
            "albumName": "XSCAPE",
            "duration": 246,
            "plainLyrics": "I met her on my way to Chicago",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                host.lyrics,
                "urlopen",
                side_effect=[TimeoutError("timed out"), JsonResponse([candidate])],
            ) as urlopen:
                result = host.fetch_lrclib_lyrics(
                    {"title": "Chicago", "artist": "Michael Jackson", "duration": 246},
                    Path(temporary),
                    force_refresh=True,
                )

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["text"], "I met her on my way to Chicago")
        self.assertEqual(result["artist"], "Michael Jackson")

    def test_lrclib_force_refresh_ignores_and_replaces_cached_lyrics(self):
        candidate = {
            "id": 3,
            "trackName": "Chicago",
            "artistName": "Michael Jackson",
            "albumName": "Xscape",
            "duration": 246,
            "plainLyrics": "I met her on my way to Chicago",
        }
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "lrclib_lyrics.json").write_text(json.dumps({
                "text": "Wrong cached lyrics",
                "segments": [],
                "source": "lrclib",
                "title": "Give You My Lovin'",
                "artist": "Mazzy Star",
            }), encoding="utf-8")
            with patch.object(host.lyrics, "urlopen", return_value=JsonResponse([candidate])) as urlopen:
                result = host.fetch_lrclib_lyrics(
                    {"title": "Chicago", "artist": "Michael Jackson", "duration": 246},
                    output_dir,
                    force_refresh=True,
                )

            cached = json.loads((output_dir / "lrclib_lyrics.json").read_text(encoding="utf-8"))

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result["text"], "I met her on my way to Chicago")
        self.assertEqual(cached["artist"], "Michael Jackson")

    def test_silero_vad_segments_distribute_lines_over_vocal_activity(self):
        segments = host.lyrics.build_silero_vad_segments(
            "Hello world\nAgain",
            [{"start": 1.0, "end": 3.0}],
        )

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "Hello world")
        self.assertEqual(segments[0]["words"], [])
        self.assertEqual(segments[0]["start_time"], 1.0)
        self.assertEqual(segments[-1]["end_time"], 3.0)


class CtcSegmentTests(unittest.TestCase):
    def test_ctc_words_use_character_spans_when_available(self):
        span = namedtuple("Span", "start end score")
        segments = lyrics_runner.build_segments(
            token_spans=[
                [span(0, 5, 0.9)],
                [
                    span(10, 20, 0.91),
                    span(20, 30, 0.92),
                    span(40, 50, 0.93),
                    span(50, 60, 0.94),
                    span(60, 70, 0.95),
                ],
                [span(70, 80, 0.9)],
            ],
            line_specs=[{"text": "Hi all", "word_indices": [0, 1]}],
            word_specs=[
                {"text": "Hi", "normalized": "hi"},
                {"text": "all", "normalized": "all"},
            ],
            alignment_entries=[
                {"kind": "gap"},
                {"kind": "line", "line_index": 0, "previous_gap": 0, "next_gap": 2},
                {"kind": "gap"},
            ],
            waveform_frames=1000,
            emission_frames=100,
            sample_rate=1000,
        )

        self.assertEqual(segments[0]["start_time"], 0.05)
        self.assertEqual(segments[0]["end_time"], 0.8)
        self.assertEqual([word["text"] for word in segments[0]["words"]], ["Hi", "all"])
        self.assertEqual(segments[0]["words"][0]["start_time"], 0.1)
        self.assertEqual(segments[0]["words"][1]["end_time"], 0.7)


class PipelineOrderingTests(unittest.TestCase):
    def test_parses_roformer_eta_into_progress(self):
        total, update = host.roformer_progress_from_line(
            "Estimated total processing time for this track: 60.00 seconds",
        )
        self.assertEqual(total, 60.0)
        self.assertIsNone(update)

        total, update = host.roformer_progress_from_line(
            "Estimated time remaining: 45.00 seconds", total,
        )
        self.assertEqual(total, 60.0)
        self.assertEqual(update, (45.0, 25.0))
        self.assertEqual(host.format_remaining_time(update[0]), "45s")

    def test_roformer_eta_without_total_starts_at_zero_percent(self):
        total, update = host.roformer_progress_from_line(
            "Estimated time remaining: 80.00 seconds",
        )

        self.assertEqual(total, 80.0)
        self.assertEqual(update, (80.0, 0.0))
        self.assertEqual(host.format_remaining_time(80), "1m 20s")

    def test_stem_publish_does_not_run_lyrics_processes(self):
        events = []

        with (
            patch.object(host, "send_stems_ready", side_effect=lambda *args, **kwargs: events.append("stems-ready")),
            patch.object(host, "prepare_lyrics") as prepare_lyrics,
            patch.object(host, "complete_job", side_effect=lambda *args, **kwargs: events.append("complete")),
        ):
            host.publish_stems_and_complete(
                "job", "video", Path("instrumental.mp3"), Path("vocals.mp3"),
            )

        self.assertEqual(events, ["stems-ready", "complete"])
        prepare_lyrics.assert_not_called()

    def test_lrclib_search_uses_provided_page_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "fetch_lrclib_lyrics", return_value={
                    "text": "Yellow",
                    "segments": [],
                    "source": "lrclib",
                    "message": "Loaded lyrics from LRCLIB.",
                }) as fetch_lrclib_lyrics,
                patch.object(host, "send_job") as send_job,
            ):
                host.execute_message({
                    "action": "searchLrclib",
                    "jobId": "lyrics-job",
                    "url": "https://www.youtube.com/watch?v=abcdefghijk",
                    "title": "Coldplay - Yellow",
                    "artist": "",
                    "duration": 267,
                })

            fetch_lrclib_lyrics.assert_called_once_with(
                {"title": "Coldplay - Yellow", "artist": "", "duration": 267},
                output_dir,
                force_refresh=False,
            )
            self.assertEqual(send_job.call_args.args[1], "lyrics")

    def test_lrclib_search_infers_topic_channel_artist_for_short_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.app, "urlopen", return_value=JsonResponse({
                    "title": "Chicago",
                    "author_name": "Michael Jackson - Topic",
                })),
                patch.object(host, "fetch_lrclib_lyrics", return_value={
                    "text": "I met her on my way to Chicago",
                    "segments": [],
                    "source": "lrclib",
                    "message": "Loaded lyrics from LRCLIB.",
                }) as fetch_lrclib_lyrics,
                patch.object(host, "send_job"),
            ):
                host.execute_message({
                    "action": "searchLrclib",
                    "jobId": "lyrics-job",
                    "url": "https://www.youtube.com/watch?v=wAoq__SQpwk",
                    "title": "Chicago",
                    "artist": "",
                    "duration": 246,
                    "forceRefresh": True,
                })

            fetch_lrclib_lyrics.assert_called_once_with(
                {"title": "Chicago", "artist": "Michael Jackson", "duration": 246},
                output_dir,
                force_refresh=True,
            )

    def test_cache_check_prefers_local_ctc_over_lrclib(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            for path in (stem_dir / "instrumental.mp3", stem_dir / "vocals.mp3"):
                path.write_bytes(b"audio")
            (output_dir / "lyrics.json").write_text(json.dumps({
                "text": "Aligned words", "segments": [{"start_time": 0}],
                "source": "lrclib+local-ctc",
            }), encoding="utf-8")
            (output_dir / "lrclib_lyrics.json").write_text(json.dumps({
                "text": "LRCLIB words", "segments": [{"start_time": 1}], "source": "lrclib",
            }), encoding="utf-8")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            payload = send_job.call_args.kwargs
            self.assertEqual(payload["lyrics"]["text"], "Aligned words")
            self.assertTrue(payload["hasLyrics"])
            self.assertTrue(payload["hasStems"])

    def test_cache_check_prefers_local_silero_vad_over_lrclib(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            for path in (stem_dir / "instrumental.mp3", stem_dir / "vocals.mp3"):
                path.write_bytes(b"audio")
            (output_dir / "lyrics.json").write_text(json.dumps({
                "text": "VAD words", "segments": [{"start_time": 0}],
                "source": "local-silero-vad",
            }), encoding="utf-8")
            (output_dir / "lrclib_lyrics.json").write_text(json.dumps({
                "text": "LRCLIB words", "segments": [{"start_time": 1}], "source": "lrclib",
            }), encoding="utf-8")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(send_job.call_args.kwargs["lyrics"]["text"], "VAD words")

    def test_prepare_lyrics_uses_silero_vad_backend_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vocals = output_dir / "vocals.mp3"
            vocals.write_bytes(b"audio")
            segments = [{
                "id": "silero-vad-segment-0",
                "text": "Hello world",
                "start_time": 0.0,
                "end_time": 1.0,
                "words": [],
            }]

            with (
                patch.object(host.lyrics, "align_lyrics_with_silero_vad", return_value=segments) as silero,
                patch.object(host.lyrics, "align_lyrics") as ctc,
            ):
                lyrics = host.lyrics.prepare_lyrics(
                    "job",
                    output_dir,
                    vocals,
                    "Hello world",
                    {"text": "", "segments": [], "source": "none"},
                    force=True,
                    timing_method="silero-vad",
                )

            silero.assert_called_once_with("job", vocals, "Hello world")
            ctc.assert_not_called()
            self.assertEqual(lyrics["source"], "local-silero-vad-original")
            self.assertEqual(lyrics["timingMethod"], "silero-vad")
            self.assertEqual(lyrics["timingSource"], "original")
            cached = json.loads((output_dir / "lyrics.json").read_text(encoding="utf-8"))
            self.assertEqual(cached["timingMethod"], "silero-vad")
            self.assertEqual(cached["timingSource"], "original")

    def test_cache_check_accepts_legacy_whisper_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            for path in (stem_dir / "instrumental.mp3", stem_dir / "vocals.mp3"):
                path.write_bytes(b"audio")
            (output_dir / "lyrics.json").write_text(json.dumps({
                "text": "Legacy words", "segments": [{"start_time": 0}],
                "source": "manual+local-whisper",
            }), encoding="utf-8")
            (output_dir / "lrclib_lyrics.json").write_text(json.dumps({
                "text": "LRCLIB words", "segments": [{"start_time": 1}], "source": "lrclib",
            }), encoding="utf-8")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(send_job.call_args.kwargs["lyrics"]["text"], "Legacy words")

    def test_cache_check_removes_legacy_source_when_stems_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            legacy_audio = output_dir / "audio.mp3"
            legacy_audio.write_bytes(b"legacy")
            for path in host.stem_paths(stem_dir):
                path.write_bytes(b"stem")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            self.assertFalse(legacy_audio.exists())
            self.assertTrue(send_job.call_args.kwargs["hasStems"])

    def test_legacy_wav_stems_are_migrated_during_cache_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            wav_paths = host.stem_paths(stem_dir, ".wav")
            for path in wav_paths:
                path.write_bytes(b"wave")
            mp3_paths = host.stem_paths(stem_dir)

            def migrate(_job_id, *_paths):
                for path in mp3_paths:
                    path.write_bytes(b"mp3")
                return mp3_paths

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "compress_stems", side_effect=migrate) as compress_stems,
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            compress_stems.assert_called_once_with("job", *wav_paths)
            payload = send_job.call_args.kwargs
            self.assertTrue(payload["hasStems"])
            self.assertEqual(payload["instrumentalUrl"], "audio://instrumental.mp3")

    def test_locked_legacy_wav_cleanup_does_not_break_cached_mp3_stems(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem_dir = Path(temporary)
            for path in (*host.stem_paths(stem_dir), *host.stem_paths(stem_dir, ".wav")):
                path.write_bytes(b"audio")
            mp3_paths = host.stem_paths(stem_dir)

            with (
                patch.object(host, "unlink_best_effort", return_value=False) as unlink_best_effort,
                patch.object(host, "validate_stem_mp3"),
            ):
                resolved = host.resolve_cached_stems("job", stem_dir)

            self.assertEqual(resolved, mp3_paths)
            self.assertEqual(unlink_best_effort.call_count, 2)

    def test_karaokize_with_cached_stems_does_not_start_lyrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            stems = host.stem_paths(stem_dir)
            for path in stems:
                path.write_bytes(b"stem")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "prepare_lyrics") as prepare_lyrics,
                patch.object(host, "publish_stems_and_complete") as publish,
                patch.object(host, "send_job"),
            ):
                host.run_download(
                    "job", "https://www.youtube.com/watch?v=abcdefghijk", [],
                )

            publish.assert_called_once_with("job", "abcdefghijk", *stems, cache_hit=True)
            prepare_lyrics.assert_not_called()

    def test_download_keeps_source_format_and_deletes_it_before_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "cache"
            output_dir.mkdir()
            observed = {}

            class FakeProcess:
                def __init__(self, command, **_kwargs):
                    observed["command"] = command
                    template = Path(command[command.index("-o") + 1])
                    source = Path(str(template).replace("%(ext)s", "webm"))
                    source.write_bytes(b"source")
                    observed["source"] = source
                    self.stdout = iter([f"__DKARAOKE_FILE__:{source}\n"])

                def wait(self, timeout=None):
                    return 0

            def fake_roformer(_job_id, source, separated_dir):
                self.assertEqual(source.suffix, ".webm")
                stem_dir = separated_dir / "audio"
                stem_dir.mkdir(parents=True)
                stems = host.stem_paths(stem_dir)
                for path in stems:
                    path.write_bytes(b"stem")
                return stems

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "require_tools", return_value="yt-dlp"),
                patch.object(host, "ytdlp_runtime_args", return_value=[]),
                patch.object(host, "run_roformer", side_effect=fake_roformer),
                patch.object(host, "publish_stems_and_complete"),
                patch.object(host, "send_job"),
                patch.object(host.subprocess, "Popen", side_effect=FakeProcess),
            ):
                host.run_download(
                    "job", "https://www.youtube.com/watch?v=abcdefghijk", [],
                )

            command = observed["command"]
            self.assertNotIn("-x", command)
            self.assertNotIn("--audio-format", command)
            self.assertIn("bestaudio/best", command)
            self.assertFalse(observed["source"].exists())

    def test_karaokize_default_original_timing_runs_after_roformer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "cache"
            output_dir.mkdir()
            source = output_dir / "source.webm"
            source.write_bytes(b"source")
            events = []

            def normalize(_job_id, _source, output_path):
                events.append("normalize")
                output_path.write_bytes(b"wav")
                return output_path

            def run_roformer(_job_id, _source, separated_dir):
                events.append("roformer")
                stem_dir = separated_dir / "audio"
                stem_dir.mkdir(parents=True)
                stems = host.stem_paths(stem_dir)
                for path in stems:
                    path.write_bytes(b"stem")
                return stems

            def prepare(*_args, **_kwargs):
                events.append("timing")
                return {
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio", return_value=source),
                patch.object(host.pipeline, "normalize_timing_audio", side_effect=normalize),
                patch.object(host, "run_roformer", side_effect=run_roformer),
                patch.object(host, "prepare_lyrics", side_effect=prepare),
                patch.object(host, "publish_stems_and_complete", side_effect=lambda *_args, **_kwargs: events.append("publish")),
                patch.object(host, "send_job"),
            ):
                host.run_download(
                    "stem-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    [],
                    {
                        "jobId": "timing-job",
                        "lyricsText": "Hello world",
                        "timingMethod": "ctc",
                        "timingSource": "original",
                    },
                )

            self.assertEqual(events, ["roformer", "publish", "normalize", "timing"])

    def test_karaokize_lyrics_first_original_timing_runs_before_roformer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "cache"
            output_dir.mkdir()
            source = output_dir / "source.webm"
            source.write_bytes(b"source")
            events = []

            def normalize(_job_id, _source, output_path):
                events.append("normalize")
                output_path.write_bytes(b"wav")
                return output_path

            def run_roformer(_job_id, _source, separated_dir):
                events.append("roformer")
                stem_dir = separated_dir / "audio"
                stem_dir.mkdir(parents=True)
                stems = host.stem_paths(stem_dir)
                for path in stems:
                    path.write_bytes(b"stem")
                return stems

            def prepare(*_args, **_kwargs):
                events.append("timing")
                return {
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio", return_value=source),
                patch.object(host.pipeline, "normalize_timing_audio", side_effect=normalize),
                patch.object(host, "run_roformer", side_effect=run_roformer),
                patch.object(host, "prepare_lyrics", side_effect=prepare),
                patch.object(host, "publish_stems_and_complete", side_effect=lambda *_args, **_kwargs: events.append("publish")),
                patch.object(host, "send_job"),
            ):
                host.run_download(
                    "stem-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    [],
                    {
                        "jobId": "timing-job",
                        "lyricsText": "Hello world",
                        "timingMethod": "ctc",
                        "timingSource": "original",
                        "timingSchedule": "lyrics-first",
                    },
                )

            self.assertEqual(events, ["normalize", "timing", "roformer", "publish"])

    def test_karaokize_parallel_original_timing_starts_before_roformer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "cache"
            output_dir.mkdir()
            source = output_dir / "source.webm"
            source.write_bytes(b"source")
            events = []
            timing_complete = threading.Event()

            def normalize(_job_id, _source, output_path):
                events.append("normalize")
                output_path.write_bytes(b"wav")
                return output_path

            def run_roformer(_job_id, _source, separated_dir):
                events.append("roformer")
                stem_dir = separated_dir / "audio"
                stem_dir.mkdir(parents=True)
                stems = host.stem_paths(stem_dir)
                for path in stems:
                    path.write_bytes(b"stem")
                return stems

            def prepare(*_args, **_kwargs):
                events.append("timing")
                timing_complete.set()
                return {
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio", return_value=source),
                patch.object(host.pipeline, "normalize_timing_audio", side_effect=normalize),
                patch.object(host, "run_roformer", side_effect=run_roformer),
                patch.object(host, "prepare_lyrics", side_effect=prepare),
                patch.object(host, "publish_stems_and_complete"),
                patch.object(host, "send_job"),
            ):
                host.run_download(
                    "stem-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    [],
                    {
                        "jobId": "timing-job",
                        "lyricsText": "Hello world",
                        "timingMethod": "ctc",
                        "timingSource": "original",
                        "timingSchedule": "parallel",
                    },
                )

            self.assertEqual(events[0], "normalize")
            self.assertIn("roformer", events)
            self.assertTrue(timing_complete.wait(2))
            self.assertIn("timing", events)

    def test_karaokize_original_timing_can_fetch_lrclib_before_alignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "cache"
            output_dir.mkdir()
            source = output_dir / "source.webm"
            source.write_bytes(b"source")
            timing_complete = threading.Event()

            def normalize(_job_id, _source, output_path):
                output_path.write_bytes(b"wav")
                return output_path

            def run_roformer(_job_id, _source, separated_dir):
                stem_dir = separated_dir / "audio"
                stem_dir.mkdir(parents=True)
                stems = host.stem_paths(stem_dir)
                for path in stems:
                    path.write_bytes(b"stem")
                return stems

            def prepare(_job_id, _output_dir, _audio_path, requested_text, *_args, **_kwargs):
                self.assertEqual(requested_text, "Hello world")
                timing_complete.set()
                return {
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "lrclib+local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }

            messages = []

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio", return_value=source),
                patch.object(host.pipeline, "normalize_timing_audio", side_effect=normalize),
                patch.object(host, "fetch_lrclib_lyrics", return_value={
                    "text": "Hello world",
                    "segments": [{"text": "Hello world", "start_time": 1.0, "end_time": 2.0, "words": [{"text": "Hello"}]}],
                    "source": "lrclib",
                }) as fetch_lrclib,
                patch.object(host, "run_roformer", side_effect=run_roformer),
                patch.object(host, "prepare_lyrics", side_effect=prepare),
                patch.object(host, "publish_stems_and_complete"),
                patch.object(host, "send_job", side_effect=lambda *args, **kwargs: messages.append((args, kwargs))),
            ):
                host.run_download(
                    "stem-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    [],
                    {
                        "jobId": "timing-job",
                        "lyricsText": "",
                        "timingMethod": "ctc",
                        "timingSource": "original",
                        "title": "Artist - Song",
                        "artist": "Artist",
                        "duration": 123,
                    },
                )

            self.assertTrue(timing_complete.wait(2))
            fetch_lrclib.assert_called_once_with(
                {"title": "Artist - Song", "artist": "Artist", "duration": 123},
                output_dir,
            )
            message_types = [args[1] for args, _kwargs in messages]
            self.assertLess(message_types.index("lyricsPreview"), message_types.index("lyricsComplete"))
            preview = next(kwargs for args, kwargs in messages if args[1] == "lyricsPreview")
            self.assertEqual(preview["lyrics"]["text"], "Hello world")
            self.assertEqual(preview["lyrics"]["segments"][0]["words"], [])
            self.assertEqual(preview["activeLyricsFileId"], "lrclib")


class PipelineConcurrencyTests(unittest.TestCase):
    def test_message_dispatch_does_not_block_on_long_job(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_job(_message):
            started.set()
            release.wait(2)

        with patch.object(host, "execute_message", side_effect=blocking_job):
            before = time.monotonic()
            host.handle_message({
                "action": "checkCache",
                "jobId": "cache-job",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
            })
            elapsed = time.monotonic() - before
            self.assertTrue(started.wait(1))
            self.assertLess(elapsed, 0.25)
            release.set()

    def test_timing_extraction_waits_for_active_karaokize_stems(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            stems = host.stem_paths(stem_dir)
            waiting = threading.Event()
            completed = threading.Event()
            errors = []

            def resolve(_job_id, _stem_dir):
                return stems

            def observe_message(_job_id, message_type, _message, **_extra):
                if message_type == "status":
                    waiting.set()
                if message_type == "lyricsComplete":
                    completed.set()

            def extract():
                try:
                    host.extract_lyrics_timings(
                        "timing-job",
                        "https://www.youtube.com/watch?v=abcdefghijk",
                        "Hello world",
                        "ctc",
                        "vocal-stem",
                    )
                except Exception as exc:
                    errors.append(exc)

            host.begin_stem_job("abcdefghijk")
            try:
                with (
                    patch.object(host, "app_download_dir", return_value=output_dir),
                    patch.object(host, "resolve_cached_stems", side_effect=resolve),
                    patch.object(host, "prepare_lyrics", return_value={
                        "text": "Hello world", "segments": [{"words": []}],
                        "source": "manual+local-ctc",
                    }),
                    patch.object(host, "send_job", side_effect=observe_message),
                ):
                    thread = threading.Thread(target=extract)
                    thread.start()
                    self.assertTrue(waiting.wait(1))
                    for path in stems:
                        path.write_bytes(b"stem")
                    host.finish_stem_job("abcdefghijk")
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(errors)
                    self.assertTrue(completed.is_set())
            finally:
                host.finish_stem_job("abcdefghijk")

    def test_timing_extraction_passes_selected_method_to_prepare_lyrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            stems = host.stem_paths(stem_dir)
            for path in stems:
                path.write_bytes(b"stem")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "resolve_cached_stems", return_value=stems),
                patch.object(host, "prepare_lyrics", return_value={
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-silero-vad",
                    "timingMethod": "silero-vad",
                }) as prepare_lyrics,
                patch.object(host, "send_job") as send_job,
            ):
                host.extract_lyrics_timings(
                    "timing-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    "Hello world",
                    "silero-vad",
                    "vocal-stem",
                )

            self.assertEqual(prepare_lyrics.call_args.kwargs["timing_method"], "silero-vad")
            self.assertIn("Silero VAD", send_job.call_args.args[2])

    def test_original_audio_timing_does_not_wait_for_stems(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            stems = host.stem_paths(stem_dir)
            source = output_dir / "source.webm"
            timing_audio = output_dir / "timing-audio.wav"
            source.write_bytes(b"source")
            timing_audio.write_bytes(b"wav")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio", return_value=source) as download_source,
                patch.object(host.pipeline, "normalize_timing_audio", return_value=timing_audio) as normalize_audio,
                patch.object(host, "resolve_cached_stems", return_value=stems) as resolve_cached_stems,
                patch.object(host, "prepare_lyrics", return_value={
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }) as prepare_lyrics,
                patch.object(host, "send_job"),
            ):
                host.extract_lyrics_timings(
                    "timing-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    "Hello world",
                )

            resolve_cached_stems.assert_called_once()
            normalize_audio.assert_called_once()
            self.assertEqual(prepare_lyrics.call_args.args[2], timing_audio)
            self.assertEqual(prepare_lyrics.call_args.kwargs["timing_source"], "original")
            self.assertEqual(download_source.call_args.kwargs["phase"], "lyrics")

    def test_original_audio_timing_reuses_cached_vocal_stem(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            stems = host.stem_paths(stem_dir)
            for path in stems:
                path.write_bytes(b"stem")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "resolve_cached_stems", return_value=stems),
                patch.object(host.pipeline, "download_source_audio") as download_source,
                patch.object(host.pipeline, "normalize_timing_audio") as normalize_audio,
                patch.object(host, "prepare_lyrics", return_value={
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc",
                    "timingMethod": "ctc",
                    "timingSource": "vocal-stem",
                }) as prepare_lyrics,
                patch.object(host, "send_job") as send_job,
            ):
                host.extract_lyrics_timings(
                    "timing-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    "Hello world",
                    "ctc",
                    "original",
                )

            download_source.assert_not_called()
            normalize_audio.assert_not_called()
            self.assertEqual(prepare_lyrics.call_args.args[2], stems[1])
            self.assertEqual(prepare_lyrics.call_args.kwargs["timing_source"], "vocal-stem")
            self.assertIn("vocal stem", send_job.call_args.args[2])

    def test_original_audio_timing_reuses_legacy_source_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            legacy_audio = output_dir / "audio.mp3"
            timing_audio = output_dir / "timing-audio.wav"
            legacy_audio.write_bytes(b"source")
            timing_audio.write_bytes(b"wav")

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host.pipeline, "download_source_audio") as download_source,
                patch.object(host.pipeline, "normalize_timing_audio", return_value=timing_audio) as normalize_audio,
                patch.object(host, "prepare_lyrics", return_value={
                    "text": "Hello world",
                    "segments": [{"words": []}],
                    "source": "local-ctc-original",
                    "timingMethod": "ctc",
                    "timingSource": "original",
                }) as prepare_lyrics,
                patch.object(host, "send_job"),
            ):
                host.extract_lyrics_timings(
                    "timing-job",
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    "Hello world",
                    "ctc",
                    "original",
                )

            download_source.assert_not_called()
            self.assertEqual(normalize_audio.call_args.args[1], legacy_audio)
            self.assertEqual(prepare_lyrics.call_args.args[2], timing_audio)
            self.assertTrue(legacy_audio.exists())

    def test_prepare_lyrics_cache_is_split_by_timing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            audio = output_dir / "audio.webm"
            audio.write_bytes(b"audio")
            cached = {
                "text": "Hello world",
                "segments": [{"words": []}],
                "source": "local-ctc",
                "timingMethod": "ctc",
                "timingSource": "vocal-stem",
                "timingVersion": host.constants.LYRICS_TIMING_VERSION,
                "textHash": "64ec88ca00b268e5ba1a35678a1b5316d212f4f366b2477232534a8aeca37f3c",
            }
            (output_dir / "lyrics.json").write_text(json.dumps(cached), encoding="utf-8")

            with patch.object(host.lyrics, "align_lyrics", return_value=[{"words": []}]) as align:
                lyrics = host.lyrics.prepare_lyrics(
                    "job",
                    output_dir,
                    audio,
                    "Hello world",
                    {"text": "", "segments": [], "source": "none"},
                    timing_method="ctc",
                    timing_source="original",
                )

            align.assert_called_once()
            self.assertEqual(lyrics["timingSource"], "original")

    def test_prepare_lyrics_treats_missing_cached_timing_source_as_legacy_vocal_stem(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vocals = output_dir / "vocals.mp3"
            vocals.write_bytes(b"audio")
            cached = {
                "text": "Hello world",
                "segments": [{"words": []}],
                "source": "local-ctc",
                "timingMethod": "ctc",
                "timingVersion": host.constants.LYRICS_TIMING_VERSION,
                "textHash": "64ec88ca00b268e5ba1a35678a1b5316d212f4f366b2477232534a8aeca37f3c",
            }
            (output_dir / "lyrics.json").write_text(json.dumps(cached), encoding="utf-8")

            with patch.object(host.lyrics, "align_lyrics") as align:
                lyrics = host.lyrics.prepare_lyrics(
                    "job",
                    output_dir,
                    vocals,
                    "Hello world",
                    {"text": "", "segments": [], "source": "none"},
                    timing_method="ctc",
                    timing_source="vocal-stem",
                )

            align.assert_not_called()
            self.assertEqual(lyrics["segments"], cached["segments"])


class NativeMessagingTests(unittest.TestCase):
    def test_diagnostic_action_does_not_require_processing_job_id(self):
        with patch.object(host.app, "record_external_diagnostic") as record:
            host.handle_message({
                "action": "recordDiagnostic",
                "diagnostic": {"event": "content_warning"},
            })

        record.assert_called_once_with({"event": "content_warning"})

    def test_send_message_translates_closed_pipe(self):
        class ClosedBuffer:
            def write(self, _data):
                raise BrokenPipeError(32, "Broken pipe")

            def flush(self):
                pass

        class ClosedStdout:
            buffer = ClosedBuffer()

        with patch.object(host.sys, "stdout", ClosedStdout()):
            with self.assertRaises(host.NativeMessagingDisconnected):
                host.send_message({"type": "complete"})

    def test_main_stops_if_pipe_closes_while_reporting_job_error(self):
        with (
            patch.object(host, "read_message", return_value={"jobId": "job"}),
            patch.object(host, "handle_message", side_effect=ValueError("failed")),
            patch.object(host, "send_job", side_effect=host.NativeMessagingDisconnected),
            patch.object(host, "stop_audio_server") as stop_audio_server,
        ):
            host.main()

        stop_audio_server.assert_called_once()


class DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_journal_appends_readable_warning_and_redacts_sensitive_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dkaraoke-diagnostics.log"
            with patch.object(diagnostics, "DIAGNOSTICS_PATH", path):
                entry = diagnostics.record_diagnostic(
                    "warning",
                    "browser_audio_weirdness",
                    "A recoverable audio issue happened.",
                    source="content",
                    job_id="job",
                    video_id="abcdefghijk",
                    phase="audio",
                    details={
                        "token": "secret-token",
                        "url": "http://127.0.0.1/audio/secret-token",
                        "readyState": 2,
                    },
                )

            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        self.assertIn("WARNING [content] browser_audio_weirdness:", lines[0])
        self.assertIn("job=job", lines[0])
        self.assertIn("video=abcdefghijk", lines[0])
        self.assertIn("token=[redacted]", lines[0])
        self.assertIn("url=[redacted]", lines[0])
        self.assertIn("readyState=2", lines[0])
        self.assertNotIn("{\"", lines[0])
        self.assertEqual(entry["event"], "browser_audio_weirdness")

    def test_diagnostics_journal_ignores_info_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dkaraoke-diagnostics.log"
            with patch.object(diagnostics, "DIAGNOSTICS_PATH", path):
                entry = diagnostics.record_diagnostic(
                    "info",
                    "native_host_started",
                    "Native host started.",
                )

            self.assertIsNone(entry)
            self.assertFalse(path.exists())


class FailureHandlingTests(unittest.TestCase):
    def test_ffprobe_cannot_read_native_messaging_stdin(self):
        completed = subprocess.CompletedProcess(
            args=["ffprobe"],
            returncode=0,
            stdout=json.dumps({
                "streams": [{
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "channels": 2,
                }],
                "format": {"duration": "1.0"},
            }),
            stderr="",
        )
        with patch.object(host.subprocess, "run", return_value=completed) as run:
            host.validate_stem_mp3(Path("stem.mp3"))

        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_ffmpeg_cannot_read_native_messaging_stdin(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem_dir = Path(temporary)
            wavs = host.stem_paths(stem_dir, ".wav")
            for path in wavs:
                path.write_bytes(b"wave")

            def complete(command, **_kwargs):
                Path(command[-1]).write_bytes(b"mp3")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(host.subprocess, "run", side_effect=complete) as run,
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "send_job"),
            ):
                host.compress_stems("job", *wavs)

        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertIs(call.kwargs["stdin"], subprocess.DEVNULL)

    def test_invalid_cached_mp3_pair_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem_dir = Path(temporary)
            stems = host.stem_paths(stem_dir)
            for path in stems:
                path.write_bytes(b"corrupt")

            with patch.object(host, "validate_stem_mp3", side_effect=RuntimeError("invalid")):
                resolved = host.resolve_cached_stems("job", stem_dir)

            self.assertEqual(resolved, stems)
            self.assertFalse(any(path.exists() for path in stems))

    def test_wav_migration_failure_is_not_silently_served(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem_dir = Path(temporary)
            wavs = host.stem_paths(stem_dir, ".wav")
            for path in wavs:
                path.write_bytes(b"wave")

            with patch.object(host, "compress_stems", side_effect=RuntimeError("ffmpeg failed")):
                with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                    host.resolve_cached_stems("job", stem_dir)

    def test_locked_invalid_mp3_pair_is_not_served(self):
        with tempfile.TemporaryDirectory() as temporary:
            stem_dir = Path(temporary)
            for path in host.stem_paths(stem_dir):
                path.write_bytes(b"corrupt")

            with (
                patch.object(host, "validate_stem_mp3", side_effect=RuntimeError("invalid")),
                patch.object(host, "unlink_best_effort", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "locked"):
                    host.resolve_cached_stems("job", stem_dir)

    def test_alignment_subprocess_failure_reaches_caller(self):
        failed = subprocess.CompletedProcess(
            args=["python", "lyrics_runner.py"],
            returncode=1,
            stdout="",
            stderr="RuntimeError: CUDA out of memory\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python.exe"
            runner = root / "lyrics_runner.py"
            vocals = root / "vocals.mp3"
            for path in (python, runner, vocals):
                path.write_bytes(b"x")
            with (
                patch.object(host, "lyrics_runner_path", return_value=(python, runner)),
                patch.object(host.lyrics, "run_registered_capture", return_value=failed),
                patch.object(host, "send_job"),
            ):
                with self.assertRaisesRegex(RuntimeError, "CUDA out of memory"):
                    host.align_lyrics("job", vocals, "Hello world")

    def test_alignment_invalid_json_is_reported(self):
        completed = subprocess.CompletedProcess(
            args=["python", "lyrics_runner.py"],
            returncode=0,
            stdout="not-json",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python.exe"
            runner = root / "lyrics_runner.py"
            vocals = root / "vocals.mp3"
            for path in (python, runner, vocals):
                path.write_bytes(b"x")
            with (
                patch.object(host, "lyrics_runner_path", return_value=(python, runner)),
                patch.object(host.lyrics, "run_registered_capture", return_value=completed),
                patch.object(host, "send_job"),
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid result"):
                    host.align_lyrics("job", vocals, "Hello world")


if __name__ == "__main__":
    unittest.main()
