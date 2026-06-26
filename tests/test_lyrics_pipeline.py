import unittest
import json
import subprocess
import tempfile
import threading
import time
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


class YtdlpMetadataTests(unittest.TestCase):
    def test_retries_once_after_metadata_timeout(self):
        completed = host.subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout='{"title":"Recovered"}',
            stderr="",
        )
        with (
            patch.object(host, "require_tools", return_value="yt-dlp"),
            patch.object(host, "ytdlp_runtime_args", return_value=[]),
            patch.object(
                host.subprocess,
                "run",
                side_effect=[
                    host.subprocess.TimeoutExpired(["yt-dlp"], host.YTDLP_METADATA_TIMEOUT_SECONDS),
                    completed,
                ],
            ) as run,
        ):
            info = host.run_ytdlp_json("https://www.youtube.com/watch?v=abcdefghijk")

        self.assertEqual(info["title"], "Recovered")
        self.assertEqual(run.call_count, 2)
        self.assertIn("--socket-timeout", run.call_args.args[0])


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

    def test_cache_check_prefers_whisper_over_lrclib(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
            stem_dir.mkdir(parents=True)
            for path in (stem_dir / "instrumental.mp3", stem_dir / "vocals.mp3"):
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
                patch.object(host, "validate_stem_mp3"),
                patch.object(host, "register_audio", side_effect=lambda path: f"audio://{path.name}"),
                patch.object(host, "send_job") as send_job,
            ):
                host.check_cache("job", "https://www.youtube.com/watch?v=abcdefghijk")

            payload = send_job.call_args.kwargs
            self.assertEqual(payload["lyrics"]["text"], "Whisper words")
            self.assertTrue(payload["hasLyrics"])
            self.assertTrue(payload["hasStems"])

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

            def fake_publish(*_args, **_kwargs):
                self.assertFalse(observed["source"].exists())

            with (
                patch.object(host, "app_download_dir", return_value=output_dir),
                patch.object(host, "require_tools", return_value="yt-dlp"),
                patch.object(host, "ytdlp_runtime_args", return_value=[]),
                patch.object(host, "run_roformer", side_effect=fake_roformer),
                patch.object(host, "publish_stems_and_complete", side_effect=fake_publish),
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
                        "source": "manual+local-whisper",
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


class NativeMessagingTests(unittest.TestCase):
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

    def test_lyrics_subprocess_failure_reaches_caller(self):
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
                patch.object(host.subprocess, "run", return_value=failed),
                patch.object(host, "send_job"),
            ):
                with self.assertRaisesRegex(RuntimeError, "CUDA out of memory"):
                    host.transcribe_lyrics("job", vocals)

    def test_lyrics_invalid_json_is_reported(self):
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
                patch.object(host.subprocess, "run", return_value=completed),
                patch.object(host, "send_job"),
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid result"):
                    host.transcribe_lyrics("job", vocals)


if __name__ == "__main__":
    unittest.main()
