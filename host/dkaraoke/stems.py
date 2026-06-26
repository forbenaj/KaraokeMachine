import json
import os
import subprocess
import threading
import uuid

from .cache import is_complete_file, unlink_best_effort
from .constants import FFMPEG_TIMEOUT_SECONDS, FFPROBE_TIMEOUT_SECONDS, STEM_MP3_BITRATE
from .logging_setup import LOGGER
from .messaging import send_job
from .processes import subprocess_creationflags

STEM_TRANSCODE_LOCK = threading.Lock()

def stem_paths(stem_dir, suffix=".mp3"):
    return stem_dir / f"instrumental{suffix}", stem_dir / f"vocals{suffix}"


def validate_stem_mp3(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=FFPROBE_TIMEOUT_SECONDS,
        creationflags=subprocess_creationflags(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe could not validate {path.name}.")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ffprobe returned invalid metadata for {path.name}.") from exc
    if (
        stream.get("codec_name") != "mp3"
        or int(stream.get("sample_rate", 0)) != 44100
        or int(stream.get("channels", 0)) != 2
        or duration <= 0
    ):
        raise RuntimeError(f"Compressed stem has invalid audio metadata: {path.name}.")


def compress_stems(job_id, instrumental_wav, vocals_wav):
    """Encode both WAV stems, publish them atomically, then remove the WAV pair."""
    mp3_paths = stem_paths(instrumental_wav.parent)
    wav_paths = (instrumental_wav, vocals_wav)
    temporary_paths = tuple(
        path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp.mp3") for path in mp3_paths
    )

    with STEM_TRANSCODE_LOCK:
        if all(is_complete_file(path) for path in mp3_paths):
            for path in wav_paths:
                unlink_best_effort(path, "cached WAV cleanup")
            return mp3_paths
        if not all(is_complete_file(path) for path in wav_paths):
            raise FileNotFoundError("Both WAV stems are required before MP3 compression.")

        send_job(job_id, "status", "Compressing separated stems to MP3...", phase="convert")
        try:
            for source, temporary in zip(wav_paths, temporary_paths):
                LOGGER.info("job=%s compressing cached stem source=%s", job_id, source)
                result = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(source), "-vn", "-map", "0:a:0",
                        "-c:a", "libmp3lame", "-b:a", STEM_MP3_BITRATE,
                        "-ar", "44100", "-ac", "2", "-write_xing", "1",
                        str(temporary),
                    ],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=FFMPEG_TIMEOUT_SECONDS,
                    creationflags=subprocess_creationflags(),
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"FFmpeg could not compress {source.name}.")
                validate_stem_mp3(temporary)

            for temporary, destination in zip(temporary_paths, mp3_paths):
                os.replace(temporary, destination)
            for path in wav_paths:
                unlink_best_effort(path, "post-transcode WAV cleanup")
        finally:
            for path in temporary_paths:
                unlink_best_effort(path, "temporary MP3 cleanup")

    LOGGER.info("job=%s compressed stems bitrate=%s directory=%s", job_id, STEM_MP3_BITRATE, instrumental_wav.parent)
    return mp3_paths


def resolve_cached_stems(job_id, stem_dir):
    mp3_paths = stem_paths(stem_dir)
    wav_paths = stem_paths(stem_dir, ".wav")
    if all(is_complete_file(path) for path in mp3_paths):
        try:
            for path in mp3_paths:
                validate_stem_mp3(path)
        except RuntimeError:
            LOGGER.exception("job=%s cached MP3 stems are invalid; rebuilding", job_id)
            for path in mp3_paths:
                unlink_best_effort(path, "invalid cached MP3 cleanup")
            if any(is_complete_file(path) for path in mp3_paths):
                raise RuntimeError(
                    "Cached stems are invalid but locked by another process. "
                    "Close media players using them, then retry."
                )
        else:
            for path in wav_paths:
                unlink_best_effort(path, "cached WAV cleanup")
            return mp3_paths
    if all(is_complete_file(path) for path in wav_paths):
        return compress_stems(job_id, *wav_paths)
    return mp3_paths
