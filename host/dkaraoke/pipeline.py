import subprocess
import tempfile
from pathlib import Path

from .audio_server import register_audio
from .cache import is_complete_file, read_json_cache, unlink_best_effort
from .constants import PROGRESS_RE, ROFORMER_TIMEOUT_SECONDS, STEM_WAIT_TIMEOUT_SECONDS, YTDLP_DOWNLOAD_TIMEOUT_SECONDS
from .logging_setup import LOGGER
from .lyrics import prepare_lyrics
from .messaging import send_job
from .paths import app_download_dir, stem_job_active, stem_ready_event, timing_job_lock, validate_youtube_url, video_id_from_url
from .processes import format_remaining_time, roformer_progress_from_line, stream_process_lines, subprocess_creationflags
from .stems import resolve_cached_stems, stem_paths
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

    # Whisper-refined timings are the local authority. LRCLIB is the immediate
    # fallback when refinement has not run yet.
    lyrics = read_json_cache(output_dir / "lyrics.json")
    has_whisper_timing = (
        (lyrics or {}).get("text")
        and (lyrics or {}).get("segments")
        and "local-whisper" in ((lyrics or {}).get("source") or "")
    )
    if not has_whisper_timing:
        lyrics = read_json_cache(output_dir / "lrclib_lyrics.json")
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
        last_line = ""
        roformer_total_seconds = None
        roformer_progress = 0.0
        for raw_line in stream_process_lines(process, "RoFormer", ROFORMER_TIMEOUT_SECONDS):
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
        roformer_completed = True
        return compress_stems(job_id, instrumental_path, vocals_path)
    except Exception:
        if process is not None:
            terminate_process_tree(process, "RoFormer")
        if not roformer_completed:
            for path in (instrumental_path, vocals_path):
                unlink_best_effort(path, "failed RoFormer output cleanup")
        raise


def extract_lyrics_timings(job_id, raw_url, requested_text):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
    _, vocals_path = resolve_cached_stems(job_id, stem_dir)
    if not is_complete_file(vocals_path):
        if not stem_job_active(video_id):
            raise FileNotFoundError("Karaokize this song before extracting lyric timings.")
        send_job(
            job_id, "status",
            "Waiting for Karaokize to prepare the vocal stem...",
            phase="lyrics",
        )
        if not stem_ready_event(video_id).wait(STEM_WAIT_TIMEOUT_SECONDS):
            raise TimeoutError("Timed out waiting for Karaokize to prepare the vocal stem.")
        _, vocals_path = resolve_cached_stems(job_id, stem_dir)
        if not is_complete_file(vocals_path):
            raise FileNotFoundError(
                "Karaokize did not produce a usable vocal stem."
            )
    if not (requested_text or "").strip():
        raise ValueError("Enter lyrics before extracting lyric timings.")
    with timing_job_lock(video_id):
        lyrics = prepare_lyrics(
            job_id, output_dir, vocals_path, requested_text,
            {"text": "", "segments": [], "source": "manual"}, force=True,
        )
    send_job(job_id, "lyricsComplete", "Lyrics timings extracted.", lyrics=lyrics, videoId=video_id)


def publish_stems_and_complete(
    job_id, video_id, instrumental_path, vocals_path, cache_hit=False,
):
    send_stems_ready(
        job_id, video_id, instrumental_path, vocals_path, cache_hit=cache_hit,
    )
    complete_job(job_id, video_id)


def run_download(job_id, raw_url, cookies):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    legacy_audio_path = output_dir / "audio.mp3"
    separated_dir = output_dir / "separated" / "mel_band_roformer"
    stem_dir = separated_dir / "audio"
    instrumental_path, vocals_path = resolve_cached_stems(job_id, stem_dir)
    if all(is_complete_file(path) for path in (instrumental_path, vocals_path)):
        LOGGER.info("job=%s video=%s using cached stems", job_id, video_id)
        unlink_best_effort(legacy_audio_path, "legacy source audio cleanup")
        send_job(job_id, "status", "Found cached separated stems.", phase="cache")
        publish_stems_and_complete(
            job_id, video_id, instrumental_path, vocals_path, cache_hit=True,
        )
        return

    if is_complete_file(legacy_audio_path):
        LOGGER.info("job=%s video=%s using legacy cached MP3; stems missing", job_id, video_id)
        send_job(job_id, "status", "Legacy downloaded audio found. Extracting missing stems...", phase="separate")
        instrumental_path, vocals_path = run_roformer(job_id, legacy_audio_path, separated_dir)
        unlink_best_effort(legacy_audio_path, "processed legacy source audio cleanup")
        publish_stems_and_complete(job_id, video_id, instrumental_path, vocals_path)
        return

    yt_dlp = require_tools()
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
        with tempfile.TemporaryDirectory(prefix=f"dkaraoke-source-{video_id}-") as source_temp:
            output_template = str(Path(source_temp) / "audio.%(ext)s")
            for use_cookies in (False, True):
                if use_cookies:
                    cookie_path = write_cookie_file(cookies)
                    if not cookie_path:
                        break
                    send_job(job_id, "status", "YouTube requested sign-in; retrying with Chrome cookies...")

                command = [*base_command, "-o", output_template]
                if cookie_path:
                    command.extend(["--cookies", str(cookie_path)])
                command.append(url)

                source_path = None
                send_job(job_id, "status", "Downloading source audio...", progress=0, phase="download")
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

                for raw_line in stream_process_lines(
                    process, "yt-dlp audio download", YTDLP_DOWNLOAD_TIMEOUT_SECONDS,
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
                            f"Downloading source audio... {percent:.1f}%",
                            progress=percent,
                            phase="download",
                        )

                return_code = process.wait(timeout=30)
                LOGGER.info("job=%s yt-dlp exited code=%s", job_id, return_code)
                if return_code == 0:
                    if not source_path or not is_complete_file(source_path):
                        raise FileNotFoundError("yt-dlp finished, but the source audio file was not found.")
                    instrumental_path, vocals_path = run_roformer(job_id, source_path, separated_dir)
                    unlink_best_effort(source_path, "processed temporary source audio cleanup")
                    publish_stems_and_complete(job_id, video_id, instrumental_path, vocals_path)
                    return

                output_text = "\n".join(output_lines)
                if not use_cookies and has_auth_error(output_text):
                    continue
                raise RuntimeError(last_line or f"yt-dlp exited with code {return_code}.")

            raise RuntimeError(last_line or "yt-dlp could not download this audio.")
    finally:
        if cookie_path and cookie_path.exists():
            unlink_best_effort(cookie_path, "download cookie cleanup")
