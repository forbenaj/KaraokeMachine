import hashlib
import json
import re
import subprocess
import unicodedata
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

LRCLIB_MAX_SEARCH_QUERIES = 4
LRCLIB_CONFIDENT_SCORE = 0.88
LRCLIB_MIN_ACCEPTED_SCORE = 0.58
LRCLIB_SEARCH_TIMEOUT_SECONDS = 12
DASH_TRANSLATION = str.maketrans({
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
})
APOSTROPHE_TRANSLATION = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u02bc": "'",
    "`": "'",
})
TITLE_SEPARATOR_RE = re.compile(r"\s+(?:-|:|\|)\s+")
BRACKETED_NOISE_RE = re.compile(
    r"\s*(?:\(|\[|\{)(?:"
    r"(?:official\s+)?(?:music\s+)?video|"
    r"official\s+audio|"
    r"lyrics?|"
    r"lyric\s+video|"
    r"visuali[sz]er|"
    r"audio|"
    r"hd|4k|"
    r"mv"
    r")(?:\)|\]|\})\s*",
    re.IGNORECASE,
)
INLINE_NOISE_RE = re.compile(
    r"\b(?:official|music\s+video|lyric\s+video|visuali[sz]er|official\s+audio|hd|4k|mv)\b",
    re.IGNORECASE,
)
FEATURE_RE = re.compile(
    r"(?:\s*(?:\(|\[)?\s*(?:feat\.?|ft\.?|featuring)\s+[^)\]\-:|]+(?:\)|\])?)",
    re.IGNORECASE,
)
PRIMARY_ARTIST_SPLIT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with|&|x|\+)\s+", re.IGNORECASE)
VERSION_TERMS = {
    "acoustic",
    "cover",
    "demo",
    "edit",
    "extended",
    "instrumental",
    "karaoke",
    "live",
    "mix",
    "remaster",
    "remastered",
    "remix",
    "sped",
    "slowed",
    "version",
}


def split_words(text):
    return re.findall(r"\S+", text or "")


def normalize_lyrics_timing_method(value):
    return value if value in LYRICS_TIMING_METHODS else DEFAULT_LYRICS_TIMING_METHOD


def normalize_lyrics_timing_source(value):
    return value if value in LYRICS_TIMING_SOURCES else DEFAULT_LYRICS_TIMING_SOURCE


def normalize_metadata_separators(text):
    return str(text or "").translate(DASH_TRANSLATION).translate(APOSTROPHE_TRANSLATION)


def clean_metadata_text(text):
    text = normalize_metadata_separators(text)
    text = BRACKETED_NOISE_RE.sub(" ", text)
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
    separator = TITLE_SEPARATOR_RE.search(video_title)
    if separator:
        inferred_artist = video_title[:separator.start()]
        inferred_title = video_title[separator.end():]
        artist = clean_metadata_text(inferred_artist)
        video_title = clean_metadata_text(inferred_title)
    return {"title": video_title, "artist": artist, "duration": parse_duration(duration)}


def normalize_match_text(value):
    text = normalize_metadata_separators(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = BRACKETED_NOISE_RE.sub(" ", text)
    text = FEATURE_RE.sub(" ", text)
    text = INLINE_NOISE_RE.sub(" ", text)
    text = re.sub(r"[^\w']+", " ", text.casefold(), flags=re.UNICODE)
    return " ".join(text.split())


def token_similarity(left, right):
    left_tokens = set(normalize_match_text(left).split())
    right_tokens = set(normalize_match_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    dice = 2 * overlap / (len(left_tokens) + len(right_tokens))
    containment = overlap / min(len(left_tokens), len(right_tokens))
    return max(dice, containment * 0.92)


def metadata_similarity(left, right):
    left_normalized = normalize_match_text(left)
    right_normalized = normalize_match_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence_score = SequenceMatcher(None, left_normalized, right_normalized, autojunk=False).ratio()
    sorted_score = SequenceMatcher(
        None,
        " ".join(sorted(left_normalized.split())),
        " ".join(sorted(right_normalized.split())),
        autojunk=False,
    ).ratio()
    return max(sequence_score, sorted_score, token_similarity(left, right))


def primary_artist_name(value):
    return clean_metadata_text(PRIMARY_ARTIST_SPLIT_RE.split(str(value or ""), maxsplit=1)[0])


def strip_feature_text(value):
    return clean_metadata_text(FEATURE_RE.sub(" ", str(value or "")))


def lyric_text_available(candidate):
    return bool(candidate.get("syncedLyrics") or candidate.get("plainLyrics"))


def duration_similarity(requested_duration, candidate_duration):
    if not requested_duration or not candidate_duration:
        return 0.55, None
    try:
        difference = abs(float(requested_duration) - float(candidate_duration))
    except (TypeError, ValueError):
        return 0.55, None
    if difference <= 3:
        return 1.0, difference
    if difference <= 8:
        return 0.82, difference
    if difference <= 20:
        return 0.45, difference
    if difference <= 45:
        return 0.18, difference
    return 0.0, difference


def version_terms(value):
    return set(normalize_match_text(value).split()) & VERSION_TERMS


def version_similarity(metadata, candidate):
    requested_terms = version_terms(metadata.get("rawTitle") or metadata.get("title"))
    candidate_terms = version_terms(" ".join([
        str(candidate.get("trackName") or ""),
        str(candidate.get("albumName") or ""),
    ]))
    if not requested_terms and not candidate_terms:
        return 1.0
    if requested_terms == candidate_terms:
        return 1.0
    if requested_terms & candidate_terms:
        return 0.78
    if requested_terms:
        return 0.48
    return 0.62


def lrclib_candidate_match(candidate, metadata):
    title_score = metadata_similarity(metadata.get("title"), candidate.get("trackName"))
    stripped_title = strip_feature_text(metadata.get("title"))
    if stripped_title and stripped_title != metadata.get("title"):
        title_score = max(title_score, metadata_similarity(stripped_title, candidate.get("trackName")))

    artist_score = metadata_similarity(metadata.get("artist"), candidate.get("artistName"))
    primary_artist = primary_artist_name(metadata.get("artist"))
    if primary_artist and primary_artist != metadata.get("artist"):
        artist_score = max(artist_score, metadata_similarity(primary_artist, candidate.get("artistName")))

    album_score = metadata_similarity(metadata.get("album"), candidate.get("albumName"))
    duration_score, duration_difference = duration_similarity(
        metadata.get("duration"),
        candidate.get("duration"),
    )
    version_score = version_similarity(metadata, candidate)
    lyrics_bonus = 0.04 if candidate.get("syncedLyrics") else 0.015 if candidate.get("plainLyrics") else 0.0
    instrumental_penalty = 0.35 if candidate.get("instrumental") and not lyric_text_available(candidate) else 0.0

    if metadata.get("artist"):
        score = (
            title_score * 0.46
            + artist_score * 0.25
            + duration_score * 0.17
            + version_score * 0.08
            + album_score * 0.04
            + lyrics_bonus
            - instrumental_penalty
        )
        valid = title_score >= 0.58 and artist_score >= 0.35
    else:
        score = (
            title_score * 0.62
            + duration_score * 0.23
            + version_score * 0.10
            + lyrics_bonus
            - instrumental_penalty
        )
        valid = title_score >= 0.68

    if candidate.get("instrumental") and not lyric_text_available(candidate):
        valid = False
    score = max(0.0, min(1.0, score))
    if not valid:
        score = -1.0
    return {
        "score": score,
        "title": round(title_score, 3),
        "artist": round(artist_score, 3),
        "album": round(album_score, 3),
        "duration": round(duration_score, 3),
        "durationDifference": None if duration_difference is None else round(duration_difference, 3),
        "version": round(version_score, 3),
        "synced": bool(candidate.get("syncedLyrics")),
    }


def lrclib_candidate_score(candidate, metadata):
    return lrclib_candidate_match(candidate, metadata)["score"]


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


def append_metadata_variant(variants, seen, title, artist, duration, raw_title):
    title = clean_metadata_text(title)
    artist = clean_metadata_text(artist)
    if not title:
        return
    key = (normalize_match_text(title), normalize_match_text(artist))
    if key in seen:
        return
    seen.add(key)
    variants.append({
        "title": title,
        "artist": artist,
        "duration": duration,
        "rawTitle": raw_title,
    })


def lrclib_metadata_variants(info):
    if isinstance(info, dict):
        raw_title = str(info.get("title") or "")
        duration = parse_duration(info.get("duration"))
    else:
        raw_title = str(info or "")
        duration = None
    raw_title = re.sub(r"\s*-\s*YouTube\s*$", "", raw_title, flags=re.IGNORECASE)
    cleaned = clean_metadata_text(raw_title)
    variants = []
    seen = set()

    primary = song_metadata_from_title(raw_title, duration)
    append_metadata_variant(variants, seen, primary["title"], primary["artist"], duration, cleaned)

    separator = TITLE_SEPARATOR_RE.search(cleaned)
    if separator:
        left = cleaned[:separator.start()]
        right = cleaned[separator.end():]
        append_metadata_variant(variants, seen, right, left, duration, cleaned)
        append_metadata_variant(variants, seen, left, right, duration, cleaned)

    if primary.get("artist"):
        append_metadata_variant(
            variants, seen,
            strip_feature_text(primary["title"]),
            primary_artist_name(primary["artist"]),
            duration,
            cleaned,
        )
        append_metadata_variant(variants, seen, primary["title"], "", duration, cleaned)
    else:
        append_metadata_variant(variants, seen, strip_feature_text(primary["title"]), "", duration, cleaned)

    return variants


def append_lrclib_query(queries, seen, params):
    cleaned = {
        key: value
        for key, value in params.items()
        if isinstance(value, (int, float)) or str(value or "").strip()
    }
    if not cleaned:
        return
    key = tuple(sorted((name, str(value).casefold()) for name, value in cleaned.items()))
    if key in seen:
        return
    seen.add(key)
    queries.append(cleaned)


def lrclib_search_queries(metadata_variants):
    queries = []
    seen = set()
    for metadata in metadata_variants:
        if metadata.get("artist"):
            append_lrclib_query(queries, seen, {
                "track_name": metadata["title"],
                "artist_name": metadata["artist"],
            })
    for metadata in metadata_variants:
        if metadata.get("artist"):
            append_lrclib_query(queries, seen, {
                "q": f"{metadata['artist']} {metadata['title']}",
            })
    for metadata in metadata_variants:
        append_lrclib_query(queries, seen, {"track_name": metadata["title"]})
    return queries[:LRCLIB_MAX_SEARCH_QUERIES]


def lrclib_candidate_key(candidate):
    provider_id = candidate.get("id")
    if provider_id is not None:
        return f"id:{provider_id}"
    return "|".join([
        normalize_match_text(candidate.get("trackName")),
        normalize_match_text(candidate.get("artistName")),
        str(candidate.get("duration") or ""),
    ])


def fetch_lrclib_candidates(params):
    request = Request(
        f"{LRCLIB_SEARCH_URL}?{urlencode(params)}",
        headers={"User-Agent": "DKaraoKe/1.10 (local Chrome extension)"},
    )
    with urlopen(request, timeout=LRCLIB_SEARCH_TIMEOUT_SECONDS) as response:
        candidates = json.loads(response.read().decode("utf-8"))
    if not isinstance(candidates, list):
        raise ValueError("LRCLIB returned an invalid response.")
    return candidates


def rank_lrclib_candidates(candidates, metadata_variants):
    ranked = []
    for candidate in candidates:
        if not lyric_text_available(candidate):
            continue
        matches = [
            (lrclib_candidate_match(candidate, metadata), metadata)
            for metadata in metadata_variants
        ]
        if not matches:
            continue
        match, metadata = max(matches, key=lambda item: item[0]["score"])
        ranked.append((match["score"], match, candidate, metadata))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def fetch_lrclib_lyrics(info, output_dir):
    cache_path = output_dir / "lrclib_lyrics.json"
    cached = read_json_cache(cache_path)
    if cached and cached.get("source") == "lrclib" and cached.get("text"):
        normalized = normalize_cached_lyrics(cached)
        if normalized != cached:
            write_json_cache(cache_path, normalized)
        return normalized

    metadata_variants = lrclib_metadata_variants(info)
    if not metadata_variants:
        return {"text": "", "segments": [], "source": "none", "message": "Could not identify the song for LRCLIB."}
    queries = lrclib_search_queries(metadata_variants)
    candidates_by_key = {}
    ranked = []
    searched_count = 0
    for params in queries:
        searched_count += 1
        LOGGER.info("searching LRCLIB params=%r", params)
        for candidate in fetch_lrclib_candidates(params):
            candidates_by_key.setdefault(lrclib_candidate_key(candidate), candidate)
        ranked = rank_lrclib_candidates(candidates_by_key.values(), metadata_variants)
        if ranked and ranked[0][0] >= LRCLIB_CONFIDENT_SCORE:
            break

    if not ranked or ranked[0][0] < LRCLIB_MIN_ACCEPTED_SCORE:
        return {"text": "", "segments": [], "source": "none", "message": "LRCLIB found no reliable match."}

    score, match, candidate, metadata = ranked[0]
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
        "album": candidate.get("albumName"),
        "duration": candidate.get("duration"),
        "matchScore": round(score, 3),
        "matchBreakdown": {key: value for key, value in match.items() if key != "score"},
        "searchCount": searched_count,
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
