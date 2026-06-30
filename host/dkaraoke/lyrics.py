import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cache import is_complete_file, read_json_cache, write_json_cache
from .constants import (
    DEFAULT_LYRICS_TIMING_METHOD,
    DEFAULT_LYRICS_TIMING_SOURCE,
    LEGACY_LYRICS_TIMING_SOURCE,
    LRCLIB_SEARCH_URL,
    LRC_TIMESTAMP_RE,
    LYRICS_TIMEOUT_SECONDS,
    LYRICS_TIMING_METHODS,
    LYRICS_TIMING_SOURCES,
    LYRICS_TIMING_VERSION,
)
from .logging_setup import LOGGER
from .messaging import send_job
from .processes import subprocess_creationflags

def split_words(text):
    return re.findall(r"\S+", text or "")


def normalize_lyrics_timing_method(value):
    return value if value in LYRICS_TIMING_METHODS else DEFAULT_LYRICS_TIMING_METHOD


def normalize_lyrics_timing_source(value):
    return value if value in LYRICS_TIMING_SOURCES else DEFAULT_LYRICS_TIMING_SOURCE


def clean_metadata_text(text):
    text = re.sub(
        r"\s*(?:\(|\[)(?:(?:official\s+)?(?:music\s+)?video|official\s+audio|lyrics?|visuali[sz]er|audio)(?:\)|\])\s*",
        " ", str(text or ""), flags=re.IGNORECASE,
    )
    return " ".join(text.split()).strip(" -|")


def parse_duration(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def song_metadata_from_title(title, duration=None):
    video_title = clean_metadata_text(re.sub(
        r"\s*-\s*YouTube\s*$", "", str(title or ""), flags=re.IGNORECASE,
    ))
    artist = ""
    if " - " in video_title:
        inferred_artist, inferred_title = video_title.split(" - ", 1)
        artist = clean_metadata_text(inferred_artist)
        video_title = clean_metadata_text(inferred_title)
    return {"title": video_title, "artist": artist, "duration": parse_duration(duration)}


def metadata_similarity(left, right):
    normalize = lambda value: re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE).strip()
    left_normalized = normalize(left)
    right_normalized = normalize(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized, autojunk=False).ratio()


def lrclib_candidate_score(candidate, metadata):
    title_score = metadata_similarity(metadata.get("title"), candidate.get("trackName"))
    artist_score = metadata_similarity(metadata.get("artist"), candidate.get("artistName"))
    requested_duration = metadata.get("duration")
    candidate_duration = candidate.get("duration")
    duration_score = 0.5
    if requested_duration and candidate_duration:
        try:
            difference = abs(float(requested_duration) - float(candidate_duration))
            duration_score = 1.0 if difference <= 3 else 0.7 if difference <= 8 else 0.2 if difference <= 20 else 0.0
        except (TypeError, ValueError):
            duration_score = 0.5
    synced_bonus = 0.05 if candidate.get("syncedLyrics") else 0.0
    score = title_score * 0.55 + artist_score * 0.30 + duration_score * 0.15 + synced_bonus
    valid = title_score >= 0.62 and (artist_score >= 0.45 or not metadata.get("artist"))
    return score if valid else -1.0


def parse_lrc_segments(synced_lyrics, duration=None):
    duration_value = parse_duration(duration)
    entries = []
    for raw_line in (synced_lyrics or "").splitlines():
        timestamps = LRC_TIMESTAMP_RE.findall(raw_line)
        if not timestamps:
            continue
        text = LRC_TIMESTAMP_RE.sub("", raw_line).strip()
        for minutes, seconds in timestamps:
            entries.append((float(minutes) * 60 + float(seconds), text))
    entries.sort(key=lambda item: item[0])

    segments = []
    for index, (start, text) in enumerate(entries):
        if not text:
            continue
        next_start = next((item[0] for item in entries[index + 1:] if item[0] > start), None)
        if next_start is not None:
            end = next_start
        elif duration_value and duration_value > start:
            end = min(duration_value, start + 8)
        else:
            end = start + 4
        end = max(start + 0.05, end)
        segments.append({
            "id": f"lrclib-segment-{len(segments)}",
            "text": text,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "words": [],
        })
    return segments


def line_only_lyrics(payload):
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    result["segments"] = [
        {**segment, "words": []}
        for segment in (payload.get("segments") or [])
        if isinstance(segment, dict)
    ]
    return result


def normalize_cached_lyrics(payload):
    if not isinstance(payload, dict):
        return payload
    source = payload.get("source") or ""
    timing_version = payload.get("timingVersion")
    if source == "lrclib":
        return line_only_lyrics(payload)
    if "local-silero-vad" in source:
        return line_only_lyrics(payload)
    if "local-ctc" in source and timing_version != LYRICS_TIMING_VERSION:
        return line_only_lyrics(payload)
    return payload


def fetch_lrclib_lyrics(info, output_dir):
    cache_path = output_dir / "lrclib_lyrics.json"
    cached = read_json_cache(cache_path)
    if cached and cached.get("source") == "lrclib" and cached.get("text"):
        normalized = normalize_cached_lyrics(cached)
        if normalized != cached:
            write_json_cache(cache_path, normalized)
        return normalized

    if isinstance(info, dict):
        metadata = song_metadata_from_title(info.get("title"), info.get("duration"))
    else:
        metadata = song_metadata_from_title(info)
    if not metadata["title"]:
        return {"text": "", "segments": [], "source": "none", "message": "Could not identify the song for LRCLIB."}
    params = {"track_name": metadata["title"]}
    if metadata["artist"]:
        params["artist_name"] = metadata["artist"]
    request = Request(
        f"{LRCLIB_SEARCH_URL}?{urlencode(params)}",
        headers={"User-Agent": "DKaraoKe/1.10 (local Chrome extension)"},
    )
    LOGGER.info("searching LRCLIB artist=%r title=%r", metadata["artist"], metadata["title"])
    with urlopen(request, timeout=20) as response:
        candidates = json.loads(response.read().decode("utf-8"))
    if not isinstance(candidates, list):
        return {"text": "", "segments": [], "source": "none", "message": "LRCLIB returned an invalid response."}
    usable_candidates = [
        candidate for candidate in candidates
        if candidate.get("syncedLyrics") or candidate.get("plainLyrics")
    ]
    ranked = sorted(
        ((lrclib_candidate_score(candidate, metadata), candidate) for candidate in usable_candidates),
        key=lambda item: item[0], reverse=True,
    )
    if not ranked or ranked[0][0] < 0:
        return {"text": "", "segments": [], "source": "none", "message": "LRCLIB found no reliable match."}

    score, candidate = ranked[0]
    synced = candidate.get("syncedLyrics") or ""
    plain = candidate.get("plainLyrics") or ""
    segments = parse_lrc_segments(synced, candidate.get("duration") or metadata.get("duration"))
    text = "\n".join(segment["text"] for segment in segments) if segments else plain.strip()
    if not text:
        return {"text": "", "segments": [], "source": "none", "message": "LRCLIB match has no lyrics."}
    result = {
        "text": text,
        "segments": segments,
        "source": "lrclib",
        "providerId": candidate.get("id"),
        "artist": candidate.get("artistName"),
        "title": candidate.get("trackName"),
        "duration": candidate.get("duration"),
        "matchScore": round(score, 3),
        "message": "Loaded synchronized lyrics from LRCLIB." if segments else "Loaded lyrics from LRCLIB.",
    }
    write_json_cache(cache_path, result)
    return result


def normalize_vad_windows(speech_timestamps, merge_gap=0.75):
    windows = []
    for item in speech_timestamps or []:
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (AttributeError, TypeError, ValueError):
            continue
        if end > start:
            windows.append({"start": max(0.0, start), "end": end})
    windows.sort(key=lambda window: (window["start"], window["end"]))
    merged = []
    for window in windows:
        if not merged or window["start"] - merged[-1]["end"] > merge_gap:
            merged.append(dict(window))
        else:
            merged[-1]["end"] = max(merged[-1]["end"], window["end"])
    return merged


def active_offset_to_time(offset, windows):
    remaining = max(0.0, float(offset))
    for window in windows:
        duration = max(0.0, window["end"] - window["start"])
        if remaining <= duration:
            return window["start"] + remaining
        remaining -= duration
    return windows[-1]["end"]


def build_silero_vad_segments(lyrics_text, speech_timestamps):
    line_specs = []
    total_weight = 0
    for raw_line in (lyrics_text or "").splitlines():
        text = raw_line.strip()
        words = split_words(text)
        if not words:
            continue
        weight = sum(max(1, len(word.strip())) for word in words)
        line_specs.append({"text": text, "weight": weight})
        total_weight += weight
    if not line_specs:
        raise RuntimeError("lyrics text does not contain any timing words")

    windows = normalize_vad_windows(speech_timestamps)
    if not windows:
        raise RuntimeError("Silero VAD did not detect vocal activity in the stem.")
    total_active_duration = sum(window["end"] - window["start"] for window in windows)
    if total_active_duration <= 0:
        raise RuntimeError("Silero VAD returned unusable vocal activity timings.")

    cursor_weight = 0
    segments = []
    for line_index, spec in enumerate(line_specs):
        start_offset = total_active_duration * cursor_weight / total_weight
        cursor_weight += spec["weight"]
        end_offset = total_active_duration * cursor_weight / total_weight
        start_time = active_offset_to_time(start_offset, windows)
        end_time = active_offset_to_time(end_offset, windows)
        segments.append({
            "id": f"silero-vad-segment-{line_index}",
            "text": spec["text"],
            "words": [],
            "start_time": round(start_time, 3),
            "end_time": round(max(start_time + 0.02, end_time), 3),
        })
    return segments


def lyrics_runner_path():
    root = Path(__file__).resolve().parents[2]
    return root / ".venv-roformer" / "Scripts" / "python.exe", root / "host" / "lyrics_runner.py"


def silero_vad_runner_path():
    root = Path(__file__).resolve().parents[2]
    return root / ".venv-roformer" / "Scripts" / "python.exe", root / "host" / "silero_vad_runner.py"


def parse_runner_json(job_id, stdout, label):
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                LOGGER.warning("job=%s %s prefixed its JSON output", job_id, label)
                return payload
        LOGGER.error(
            "job=%s %s returned invalid JSON stdout=%r",
            job_id,
            label,
            stdout[:1000],
        )
        raise RuntimeError("Lyrics extraction returned an invalid result.")


def align_lyrics(job_id, vocals_path, lyrics_text):
    python, runner = lyrics_runner_path()
    if not python.exists() or not runner.exists():
        raise FileNotFoundError(
            "Lyrics runtime is not installed. Run setup-roformer.ps1."
        )
    if not is_complete_file(vocals_path):
        raise FileNotFoundError("The vocals stem is missing or empty.")
    lyrics_text = (lyrics_text or "").strip()
    if not lyrics_text:
        raise ValueError("Enter lyrics before extracting lyric timings.")
    send_job(job_id, "status", "Aligning provided lyrics to the vocals...", phase="lyrics")
    LOGGER.info("job=%s starting CTC lyric alignment", job_id)
    try:
        result = subprocess.run(
            [str(python), str(runner), str(vocals_path)],
            input=lyrics_text,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace", timeout=LYRICS_TIMEOUT_SECONDS,
            creationflags=subprocess_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Lyrics extraction timed out after {LYRICS_TIMEOUT_SECONDS // 60} minutes."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start lyrics extraction: {exc}") from exc
    LOGGER.info("job=%s CTC lyric alignment exited code=%s", job_id, result.returncode)
    if result.stderr.strip():
        LOGGER.info("job=%s CTC lyric alignment output: %s", job_id, result.stderr.strip())
    if result.returncode != 0:
        detail = next(
            (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
            "",
        )
        raise RuntimeError(detail or f"Lyrics extraction exited with code {result.returncode}.")
    payload = parse_runner_json(job_id, result.stdout, "CTC lyric alignment")
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise RuntimeError("Lyrics extraction returned an invalid segment list.")
    if not segments:
        raise RuntimeError("CTC forced alignment found no aligned lyric words.")
    return segments


def align_lyrics_with_silero_vad(job_id, vocals_path, lyrics_text):
    python, runner = silero_vad_runner_path()
    if not python.exists() or not runner.exists():
        raise FileNotFoundError(
            "Silero VAD runtime is not installed. Run setup-roformer.ps1."
        )
    if not is_complete_file(vocals_path):
        raise FileNotFoundError("The vocals stem is missing or empty.")
    lyrics_text = (lyrics_text or "").strip()
    if not lyrics_text:
        raise ValueError("Enter lyrics before extracting lyric timings.")
    send_job(job_id, "status", "Detecting vocal activity with Silero VAD...", phase="lyrics")
    LOGGER.info("job=%s starting Silero VAD lyric timing", job_id)
    try:
        result = subprocess.run(
            [str(python), str(runner), str(vocals_path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace", timeout=LYRICS_TIMEOUT_SECONDS,
            creationflags=subprocess_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Silero VAD timing timed out after {LYRICS_TIMEOUT_SECONDS // 60} minutes."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start Silero VAD timing: {exc}") from exc
    LOGGER.info("job=%s Silero VAD exited code=%s", job_id, result.returncode)
    if result.stderr.strip():
        LOGGER.info("job=%s Silero VAD output: %s", job_id, result.stderr.strip())
    if result.returncode != 0:
        detail = next(
            (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
            "",
        )
        raise RuntimeError(detail or f"Silero VAD exited with code {result.returncode}.")
    payload = parse_runner_json(job_id, result.stdout, "Silero VAD")
    speech_timestamps = payload.get("speech_timestamps") if isinstance(payload, dict) else None
    if not isinstance(speech_timestamps, list):
        raise RuntimeError("Silero VAD returned an invalid timestamp list.")
    return build_silero_vad_segments(lyrics_text, speech_timestamps)


def prepare_lyrics(
    job_id, output_dir, vocals_path, requested_text, provider_lyrics, force=False,
    timing_method=DEFAULT_LYRICS_TIMING_METHOD,
    timing_source=DEFAULT_LYRICS_TIMING_SOURCE,
):
    requested_text = (requested_text or "").strip()
    provider_text = ((provider_lyrics or {}).get("text") or "").strip()
    final_text = requested_text or provider_text
    if not final_text:
        return {"text": "", "segments": [], "source": "none"}
    timing_method = normalize_lyrics_timing_method(timing_method)
    timing_source = normalize_lyrics_timing_source(timing_source)
    local_source = "local-silero-vad" if timing_method == "silero-vad" else "local-ctc"
    if timing_source == "original":
        local_source = f"{local_source}-original"

    cached_path = output_dir / "lyrics.json"
    cached = read_json_cache(cached_path) if not force else None
    if cached:
        cache_matches_text = (
            requested_text and cached.get("textHash") == hashlib.sha256(requested_text.encode("utf-8")).hexdigest()
        ) or (not requested_text and cached.get("segments"))
        cached_method = cached.get("timingMethod")
        if not cached_method and local_source in (cached.get("source") or ""):
            cached_method = timing_method
        if (
            cached.get("timingVersion") == LYRICS_TIMING_VERSION
            and cache_matches_text
            and cached_method == timing_method
            and (cached.get("timingSource") or LEGACY_LYRICS_TIMING_SOURCE) == timing_source
        ):
            return {key: cached.get(key) for key in ("text", "segments", "source", "timingMethod", "timingSource")}
    provider_source = (provider_lyrics or {}).get("source") or "none"
    source = f"{provider_source}+{local_source}" if provider_source != "none" else local_source
    if timing_method == "silero-vad":
        segments = align_lyrics_with_silero_vad(job_id, vocals_path, final_text)
    else:
        segments = align_lyrics(job_id, vocals_path, final_text)
    result = {
        "text": final_text,
        "segments": segments,
        "source": source,
        "timingMethod": timing_method,
        "timingSource": timing_source,
    }
    digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    write_json_cache(cached_path, {
        **result, "textHash": digest, "timingVersion": LYRICS_TIMING_VERSION
    })
    return result
