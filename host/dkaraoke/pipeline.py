import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .audio_server import register_audio
from .cache import is_complete_file, read_json_cache, unlink_best_effort
from .constants import (
    DEFAULT_LYRICS_TIMING_METHOD,
    DEFAULT_LYRICS_TIMING_SOURCE,
    DEFAULT_TIMING_PIPELINE_SCHEDULE,
    FFMPEG_TIMEOUT_SECONDS,
    PROGRESS_RE,
    ROFORMER_TIMEOUT_SECONDS,
    STEM_WAIT_TIMEOUT_SECONDS,
    YTDLP_DOWNLOAD_TIMEOUT_SECONDS,
    TIMING_PIPELINE_SCHEDULES,
)
from .diagnostics import record_diagnostic
from .logging_setup import LOGGER
from .lyrics import (
    fetch_lrclib_lyrics,
    normalize_cached_lyrics,
    normalize_lyrics_timing_method,
    normalize_lyrics_timing_source,
    prepare_lyrics,
)
from .messaging import send_job
from .paths import app_download_dir, stem_job_active, stem_ready_event, timing_job_lock, validate_youtube_url, video_id_from_url
from .processes import (
    JobCanceled,
    format_remaining_time,
    raise_if_job_canceled,
    register_job_process,
    roformer_progress_from_line,
    stream_process_lines,
    subprocess_creationflags,
    terminate_process_tree,
    unregister_job_process,
)
from .stems import compress_stems, resolve_cached_stems, stem_paths
from .youtube import has_auth_error, require_tools, write_cookie_file, ytdlp_runtime_args

def send_stems_ready(job_id, video_id, instrumental_path, vocals_path, cache_hit=False):
    instrumental_url = register_audio(instrumental_path)
    vocals_url = register_audio(vocals_path)
    send_job(
        job_id,
        "stemsReady",
        "Cached stems ready. Loading synchronized audio..."
        if cache_hit else "Stems ready. Loading synchronized audio...",
        instrumentalPath=str(instrumental_path),
        vocalsPath=str(vocals_path),
        instrumentalUrl=instrumental_url,
        vocalsUrl=vocals_url,
        videoId=video_id,
        cacheHit=cache_hit,
    )


def complete_job(job_id, video_id, lyrics=None):
    payload = {"videoId": video_id}
    if lyrics is not None:
        payload["lyrics"] = lyrics
    send_job(job_id, "complete", "Stems ready.", **payload)


def check_cache(job_id, raw_url):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    legacy_audio_path = output_dir / "audio.mp3"
    stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
    instrumental_path, vocals_path = resolve_cached_stems(job_id, stem_dir)

    # Locally extracted timings are the authority. LRCLIB is the immediate
    # fallback when local timing has not run yet. Legacy Whisper-produced
    # caches remain readable so existing songs keep working after upgrades.
    lyrics = normalize_cached_lyrics(read_json_cache(output_dir / "lyrics.json"))
    has_local_timing = (
        (lyrics or {}).get("text")
        and (lyrics or {}).get("segments")
        and any(
            marker in ((lyrics or {}).get("source") or "")
            for marker in ("local-ctc", "local-silero-vad", "local-whisper")
        )
    )
    if not has_local_timing:
        lyrics = normalize_cached_lyrics(read_json_cache(output_dir / "lrclib_lyrics.json"))
    if not (lyrics or {}).get("text"):
        lyrics = {"text": "", "segments": [], "source": "none"}
    else:
        lyrics = {key: lyrics.get(key) for key in ("text", "segments", "source")}

    has_stems = all(is_complete_file(path) for path in (instrumental_path, vocals_path))
    if has_stems:
        unlink_best_effort(legacy_audio_path, "legacy source audio cleanup")
    payload = {
        "lyrics": lyrics,
        "videoId": video_id,
        "hasLyrics": bool(lyrics.get("text") and lyrics.get("segments")),
        "hasStems": has_stems,
    }
    if has_stems:
        payload.update({
            "instrumentalUrl": register_audio(instrumental_path),
            "vocalsUrl": register_audio(vocals_path),
        })
    send_job(job_id, "cacheCheck", "Checked saved karaoke results.", **payload)

def roformer_paths():
    root = Path(__file__).resolve().parents[2]
    return (
        root / ".venv-roformer" / "Scripts" / "python.exe",
        root / ".stem-models" / "mel-band-roformer",
        root / ".stem-models" / "MelBandRoformer.ckpt",
        root / "host" / "roformer_runner.py",
    )


def run_roformer(job_id, source_path, output_dir):
    raise_if_job_canceled(job_id)
    python, repo, checkpoint, runner = roformer_paths()
    if any(not path.exists() for path in (python, repo, checkpoint, runner)):
        raise FileNotFoundError(
            "RoFormer is not installed. Run setup-roformer.ps1."
        )

    send_job(job_id, "status", "Separating instrumental and vocals with RoFormer...", phase="separate")
    command = [
        str(python), "-u", str(runner),
        "--repo", str(repo),
        "--checkpoint", str(checkpoint),
        "--output", str(output_dir),
        "--device", "auto",
        "--num-overlap", "2",
        "--chunk-size", "352800",
        str(source_path),
    ]
    LOGGER.info("job=%s starting RoFormer source=%s", job_id, source_path)
    stem_dir = output_dir / source_path.stem
    instrumental_path, vocals_path = stem_paths(stem_dir, ".wav")
    for path in (instrumental_path, vocals_path):
        unlink_best_effort(path, "stale RoFormer output cleanup")
    process = None
    roformer_completed = False
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess_creationflags(),
        )
        register_job_process(job_id, process, "RoFormer")
        last_line = ""
        roformer_total_seconds = None
        roformer_progress = 0.0
        for raw_line in stream_process_lines(process, "RoFormer", ROFORMER_TIMEOUT_SECONDS, job_id=job_id):
            line = raw_line.strip()
            if not line:
                continue
            LOGGER.info("job=%s RoFormer: %s", job_id, line)
            last_line = line
            roformer_total_seconds, progress_update = roformer_progress_from_line(
                line, roformer_total_seconds,
            )
            if "Normalizing" in line:
                send_job(job_id, "status", "Preparing audio for RoFormer...", phase="separate")
            elif "Separating vocals" in line:
                send_job(
                    job_id, "status", "RoFormer is separating vocals...",
                    progress=0, phase="separate",
                )
            elif progress_update:
                remaining_seconds, percent = progress_update
                roformer_progress = max(roformer_progress, percent)
                send_job(
                    job_id,
                    "progress",
                    (
                        f"RoFormer is separating vocals... "
                        f"{roformer_progress:.0f}% · about "
                        f"{format_remaining_time(remaining_seconds)} remaining"
                    ),
                    progress=roformer_progress,
                    phase="separate",
                )
        return_code = process.wait(timeout=30)
        LOGGER.info("job=%s RoFormer exited code=%s", job_id, return_code)
        if return_code != 0:
            raise RuntimeError(last_line or f"RoFormer exited with code {return_code}.")
        if not all(is_complete_file(path) for path in (instrumental_path, vocals_path)):
            raise FileNotFoundError("RoFormer finished, but both complete stem files were not found.")
        raise_if_job_canceled(job_id)
        roformer_completed = True
        return compress_stems(job_id, instrumental_path, vocals_path)
    except JobCanceled:
        if process is not None:
            terminate_process_tree(process, "RoFormer")
        for path in (instrumental_path, vocals_path):
            unlink_best_effort(path, "canceled RoFormer output cleanup")
        raise
    except Exception:
        if process is not None:
            terminate_process_tree(process, "RoFormer")
        if not roformer_completed:
            for path in (instrumental_path, vocals_path):
                unlink_best_effort(path, "failed RoFormer output cleanup")
        record_diagnostic(
            "error",
            "roformer_failed",
            "RoFormer separation failed.",
            job_id=job_id,
            phase="separate",
            details={"sourcePath": str(source_path), "outputDir": str(output_dir)},
            exc=sys.exc_info()[1],
        )
        raise
    finally:
        unregister_job_process(job_id, process)


def download_source_audio(job_id, url, video_id, cookies, output_template, phase="download"):
    raise_if_job_canceled(job_id)
    yt_dlp = require_tools()
    download_label = "Downloading original audio for lyric timing" if phase == "lyrics" else "Downloading source audio"
    base_command = [
        yt_dlp,
        "--ignore-config",
        *ytdlp_runtime_args(),
        "--newline",
        "--socket-timeout", "30",
        "--retries", "3",
        "--fragment-retries", "3",
        "--no-playlist",
        "--force-overwrites",
        "-f", "bestaudio/best",
        "--print", "after_move:__DKARAOKE_FILE__:%(filepath)s",
    ]
    cookie_path = None
    last_line = ""
    try:
        for use_cookies in (False, True):
            if use_cookies:
                cookie_path = write_cookie_file(cookies)
                if not cookie_path:
                    break
                record_diagnostic(
                    "warning",
                    "youtube_auth_retry",
                    "YouTube requested sign-in; retrying the audio download with Chrome cookies.",
                    job_id=job_id,
                    video_id=video_id,
                    phase=phase,
                )
                send_job(
                    job_id, "status",
                    "YouTube requested sign-in; retrying with Chrome cookies...",
                    phase=phase,
                )

            command = [*base_command, "-o", str(output_template)]
            if cookie_path:
                command.extend(["--cookies", str(cookie_path)])
            command.append(url)

            source_path = None
            send_job(job_id, "status", f"{download_label}...", progress=0, phase=phase)
            LOGGER.info("job=%s video=%s starting yt-dlp cookies=%s", job_id, video_id, bool(cookie_path))
            output_lines = []
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess_creationflags(),
            )
            register_job_process(job_id, process, "yt-dlp audio download")

            for raw_line in stream_process_lines(
                process, "yt-dlp audio download", YTDLP_DOWNLOAD_TIMEOUT_SECONDS, job_id=job_id,
            ):
                line = raw_line.strip()
                if not line:
                    continue
                LOGGER.info("job=%s yt-dlp: %s", job_id, line)
                last_line = line
                output_lines.append(line)

                if line.startswith("__DKARAOKE_FILE__:"):
                    source_path = Path(line.split(":", 1)[1])
                    continue

                progress = PROGRESS_RE.search(line)
                if progress:
                    percent = float(progress.group(1))
                    send_job(
                        job_id,
                        "progress",
                        f"{download_label}... {percent:.1f}%",
                        progress=percent,
                        phase=phase,
                    )

            return_code = process.wait(timeout=30)
            LOGGER.info("job=%s yt-dlp exited code=%s", job_id, return_code)
            if return_code == 0:
                if not source_path or not is_complete_file(source_path):
                    record_diagnostic(
                        "error",
                        "download_missing_source",
                        "yt-dlp finished, but the source audio file was not found.",
                        job_id=job_id,
                        video_id=video_id,
                        phase=phase,
                    )
                    raise FileNotFoundError("yt-dlp finished, but the source audio file was not found.")
                raise_if_job_canceled(job_id)
                return source_path

            output_text = "\n".join(output_lines)
            if not use_cookies and has_auth_error(output_text):
                record_diagnostic(
                    "warning",
                    "youtube_auth_required",
                    "Anonymous YouTube audio download failed with an auth-related response.",
                    job_id=job_id,
                    video_id=video_id,
                    phase=phase,
                    details={"lastLine": last_line},
                )
                continue
            record_diagnostic(
                "error",
                "download_process_failed",
                last_line or f"yt-dlp exited with code {return_code}.",
                job_id=job_id,
                video_id=video_id,
                phase=phase,
                details={"returnCode": return_code},
            )
            raise RuntimeError(last_line or f"yt-dlp exited with code {return_code}.")

        record_diagnostic(
            "error",
            "download_failed",
            last_line or "yt-dlp could not download this audio.",
            job_id=job_id,
            video_id=video_id,
            phase=phase,
        )
        raise RuntimeError(last_line or "yt-dlp could not download this audio.")
    except JobCanceled:
        if "process" in locals():
            terminate_process_tree(process, "yt-dlp audio download")
        if "source_path" in locals() and source_path:
            unlink_best_effort(source_path, "canceled source audio cleanup")
        raise
    finally:
        if "process" in locals():
            unregister_job_process(job_id, process)
        if cookie_path and cookie_path.exists():
            unlink_best_effort(cookie_path, "download cookie cleanup")


def normalize_timing_audio(job_id, source_path, output_path):
    send_job(job_id, "status", "Preparing source audio for lyric timing...", phase="lyrics")
    LOGGER.info("job=%s normalizing lyric timing audio source=%s", job_id, source_path)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source_path), "-vn", "-map", "0:a:0",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        creationflags=subprocess_creationflags(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFmpeg could not prepare source audio for lyric timing.")
    if not is_complete_file(output_path):
        raise FileNotFoundError("FFmpeg did not produce usable timing audio.")
    return output_path


def normalize_timing_pipeline_schedule(value):
    return value if value in TIMING_PIPELINE_SCHEDULES else DEFAULT_TIMING_PIPELINE_SCHEDULE


def normalized_original_timing_request(lyrics_timing):
    if not isinstance(lyrics_timing, dict):
        return None
    timing_job_id = str(lyrics_timing.get("jobId") or "")
    requested_text = str(lyrics_timing.get("lyricsText") or "")
    timing_source = normalize_lyrics_timing_source(lyrics_timing.get("timingSource"))
    if not timing_job_id or timing_source != "original":
        return None
    return {
        "jobId": timing_job_id,
        "lyricsText": requested_text,
        "timingMethod": normalize_lyrics_timing_method(lyrics_timing.get("timingMethod")),
        "timingSource": timing_source,
        "timingSchedule": normalize_timing_pipeline_schedule(lyrics_timing.get("timingSchedule")),
        "title": str(lyrics_timing.get("title") or ""),
        "artist": str(lyrics_timing.get("artist") or ""),
        "duration": lyrics_timing.get("duration"),
    }


def run_original_audio_timing_job(video_id, output_dir, timing_audio_path, timing_request):
    timing_job_id = timing_request["jobId"]
    requested_text = timing_request["lyricsText"]
    timing_method = timing_request["timingMethod"]
    timing_source = timing_request["timingSource"]
    try:
        provider_lyrics = read_json_cache(output_dir / "lrclib_lyrics.json")
        if not isinstance(provider_lyrics, dict):
            provider_lyrics = {"text": "", "segments": [], "source": "none"}
        if not requested_text.strip() and not provider_lyrics.get("text"):
            send_job(timing_job_id, "status", "Searching LRCLIB for lyrics...", phase="lyrics")
            provider_lyrics = fetch_lrclib_lyrics({
                "title": timing_request["title"],
                "artist": timing_request.get("artist") or "",
                "duration": timing_request["duration"],
            }, output_dir)
        final_text = requested_text.strip() or str((provider_lyrics or {}).get("text") or "").strip()
        if not final_text:
            raise ValueError((provider_lyrics or {}).get("message") or "No lyrics were available for timing extraction.")
        with timing_job_lock(video_id):
            lyrics = prepare_lyrics(
                timing_job_id, output_dir, timing_audio_path, final_text,
                provider_lyrics, force=True, timing_method=timing_method,
                timing_source=timing_source,
            )
        method_label = "Silero VAD" if timing_method == "silero-vad" else "CTC forced alignment"
        send_job(
            timing_job_id,
            "lyricsComplete",
            f"Lyrics timings extracted with {method_label} from original audio.",
            lyrics=lyrics,
            videoId=video_id,
        )
    except Exception as exc:
        LOGGER.exception("job=%s source timing failed", timing_job_id)
        record_diagnostic(
            "error",
            "lyrics_timing_failed",
            str(exc),
            job_id=timing_job_id,
            video_id=video_id,
            phase="lyrics",
            exc=exc,
        )
        send_job(timing_job_id, "error", str(exc), videoId=video_id)


def run_original_audio_timing_inline(video_id, output_dir, source_path, timing_request):
    timing_temp = tempfile.TemporaryDirectory(prefix=f"dkaraoke-lyrics-shared-{video_id}-")
    try:
        timing_audio_path = Path(timing_temp.name) / "timing-audio.wav"
        normalize_timing_audio(timing_request["jobId"], source_path, timing_audio_path)
        run_original_audio_timing_job(video_id, output_dir, timing_audio_path, timing_request)
    except Exception as exc:
        LOGGER.exception("job=%s could not prepare source timing", timing_request["jobId"])
        record_diagnostic(
            "error",
            "lyrics_source_prepare_failed",
            str(exc),
            job_id=timing_request["jobId"],
            video_id=video_id,
            phase="lyrics",
            exc=exc,
        )
        send_job(timing_request["jobId"], "error", str(exc), videoId=video_id)
    finally:
        timing_temp.cleanup()


def start_original_audio_timing_thread(video_id, output_dir, source_path, timing_request):
    timing_temp = tempfile.TemporaryDirectory(prefix=f"dkaraoke-lyrics-shared-{video_id}-")
    timing_audio_path = Path(timing_temp.name) / "timing-audio.wav"
    try:
        normalize_timing_audio(timing_request["jobId"], source_path, timing_audio_path)
    except Exception as exc:
        LOGGER.exception("job=%s could not prepare parallel source timing", timing_request["jobId"])
        record_diagnostic(
            "error",
            "parallel_lyrics_source_prepare_failed",
            str(exc),
            job_id=timing_request["jobId"],
            video_id=video_id,
            phase="lyrics",
            exc=exc,
        )
        send_job(timing_request["jobId"], "error", str(exc), videoId=video_id)
        timing_temp.cleanup()
        return None

    def run_timing():
        try:
            run_original_audio_timing_job(video_id, output_dir, timing_audio_path, timing_request)
        finally:
            timing_temp.cleanup()

    thread = threading.Thread(
        target=run_timing,
        name=f"lyrics-original-{timing_request['jobId'][:8]}",
        daemon=True,
    )
    thread.start()
    return thread


def extract_lyrics_timings(
    job_id, raw_url, requested_text, timing_method=DEFAULT_LYRICS_TIMING_METHOD,
    timing_source=DEFAULT_LYRICS_TIMING_SOURCE, cookies=None,
):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    timing_method = normalize_lyrics_timing_method(timing_method)
    timing_source = normalize_lyrics_timing_source(timing_source)
    output_dir = app_download_dir(video_id)
    stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
    legacy_audio_path = output_dir / "audio.mp3"
    if not (requested_text or "").strip():
        raise ValueError("Enter lyrics before extracting lyric timings.")
    provider_lyrics = read_json_cache(output_dir / "lrclib_lyrics.json")
    if not isinstance(provider_lyrics, dict):
        provider_lyrics = {"text": "", "segments": [], "source": "manual"}
    with timing_job_lock(video_id):
        if timing_source == "original":
            with tempfile.TemporaryDirectory(prefix=f"dkaraoke-lyrics-source-{video_id}-") as source_temp:
                if is_complete_file(legacy_audio_path):
                    send_job(
                        job_id,
                        "status",
                        "Using saved source audio for lyric timing...",
                        phase="lyrics",
                    )
                    source_path = legacy_audio_path
                else:
                    source_path = download_source_audio(
                        job_id, url, video_id, cookies or [],
                        Path(source_temp) / "audio.%(ext)s",
                        phase="lyrics",
                    )
                timing_audio_path = normalize_timing_audio(
                    job_id, source_path, Path(source_temp) / "timing-audio.wav",
                )
                lyrics = prepare_lyrics(
                    job_id, output_dir, timing_audio_path, requested_text,
                    provider_lyrics, force=True, timing_method=timing_method,
                    timing_source=timing_source,
                )
                if source_path != legacy_audio_path:
                    unlink_best_effort(source_path, "processed lyrics source audio cleanup")
        else:
            _, vocals_path = resolve_cached_stems(job_id, stem_dir)
            if not is_complete_file(vocals_path):
                if not stem_job_active(video_id):
                    raise FileNotFoundError("Prepare this song before extracting lyric timings.")
                send_job(
                    job_id, "status",
                    "Waiting for Karaoke Machine! to prepare the vocal stem...",
                    phase="lyrics",
                )
                if not stem_ready_event(video_id).wait(STEM_WAIT_TIMEOUT_SECONDS):
                    raise TimeoutError("Timed out waiting for Karaoke Machine! to prepare the vocal stem.")
                _, vocals_path = resolve_cached_stems(job_id, stem_dir)
                if not is_complete_file(vocals_path):
                    raise FileNotFoundError(
                        "Karaoke Machine! did not produce a usable vocal stem."
                    )
            else:
                send_job(
                    job_id,
                    "status",
                    "Using cached vocal stem for lyric timing...",
                    phase="lyrics",
                )
            lyrics = prepare_lyrics(
                job_id, output_dir, vocals_path, requested_text,
                provider_lyrics, force=True, timing_method=timing_method,
                timing_source=timing_source,
            )
    method_label = "Silero VAD" if timing_method == "silero-vad" else "CTC forced alignment"
    source_label = "original audio" if timing_source == "original" else "vocal stem"
    send_job(
        job_id,
        "lyricsComplete",
        f"Lyrics timings extracted with {method_label} from {source_label}.",
        lyrics=lyrics,
        videoId=video_id,
    )


def publish_stems_and_complete(
    job_id, video_id, instrumental_path, vocals_path, cache_hit=False,
):
    send_stems_ready(
        job_id, video_id, instrumental_path, vocals_path, cache_hit=cache_hit,
    )
    complete_job(job_id, video_id)


def run_download(job_id, raw_url, cookies, lyrics_timing=None):
    raise_if_job_canceled(job_id)
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    timing_request = normalized_original_timing_request(lyrics_timing)
    legacy_audio_path = output_dir / "audio.mp3"
    separated_dir = output_dir / "separated" / "mel_band_roformer"
    stem_dir = separated_dir / "audio"
    instrumental_path, vocals_path = resolve_cached_stems(job_id, stem_dir)
    if all(is_complete_file(path) for path in (instrumental_path, vocals_path)):
        LOGGER.info("job=%s video=%s using cached stems", job_id, video_id)
        unlink_best_effort(legacy_audio_path, "legacy source audio cleanup")
        send_job(job_id, "status", "Found cached separated stems.", phase="cache")
        raise_if_job_canceled(job_id)
        publish_stems_and_complete(
            job_id, video_id, instrumental_path, vocals_path, cache_hit=True,
        )
        return

    if is_complete_file(legacy_audio_path):
        LOGGER.info("job=%s video=%s using legacy cached MP3; stems missing", job_id, video_id)
        send_job(job_id, "status", "Legacy downloaded audio found. Extracting missing stems...", phase="separate")
        if timing_request and timing_request["timingSchedule"] == "lyrics-first":
            run_original_audio_timing_inline(video_id, output_dir, legacy_audio_path, timing_request)
            raise_if_job_canceled(job_id)
            timing_request = None
        if timing_request and timing_request["timingSchedule"] == "parallel":
            start_original_audio_timing_thread(video_id, output_dir, legacy_audio_path, timing_request)
            timing_request = None
        raise_if_job_canceled(job_id)
        instrumental_path, vocals_path = run_roformer(job_id, legacy_audio_path, separated_dir)
        raise_if_job_canceled(job_id)
        publish_stems_and_complete(job_id, video_id, instrumental_path, vocals_path)
        if timing_request:
            run_original_audio_timing_inline(video_id, output_dir, legacy_audio_path, timing_request)
        unlink_best_effort(legacy_audio_path, "processed legacy source audio cleanup")
        return

    with tempfile.TemporaryDirectory(prefix=f"dkaraoke-source-{video_id}-") as source_temp:
        source_path = download_source_audio(
            job_id, url, video_id, cookies, Path(source_temp) / "audio.%(ext)s",
        )
        if timing_request and timing_request["timingSchedule"] == "lyrics-first":
            run_original_audio_timing_inline(video_id, output_dir, source_path, timing_request)
            raise_if_job_canceled(job_id)
            timing_request = None
        if timing_request and timing_request["timingSchedule"] == "parallel":
            start_original_audio_timing_thread(video_id, output_dir, source_path, timing_request)
            timing_request = None
        raise_if_job_canceled(job_id)
        instrumental_path, vocals_path = run_roformer(job_id, source_path, separated_dir)
        raise_if_job_canceled(job_id)
        publish_stems_and_complete(job_id, video_id, instrumental_path, vocals_path)
        if timing_request:
            run_original_audio_timing_inline(video_id, output_dir, source_path, timing_request)
        unlink_best_effort(source_path, "processed temporary source audio cleanup")
