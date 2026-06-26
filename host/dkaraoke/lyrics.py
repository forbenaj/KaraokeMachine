import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cache import is_complete_file, read_json_cache, write_json_cache
from .constants import LRCLIB_SEARCH_URL, LRC_TIMESTAMP_RE, LYRICS_TIMEOUT_SECONDS, LYRICS_TIMING_VERSION
from .logging_setup import LOGGER
from .messaging import send_job
from .processes import subprocess_creationflags

def normalize_word(text):
    return re.sub(r"[^\w']+", "", text, flags=re.UNICODE).casefold()


def split_words(text):
    return re.findall(r"\S+", text or "")

def clean_metadata_text(text):
    text = re.sub(
        r"\s*(?:\(|\[)(?:(?:official\s+)?(?:music\s+)?video|official\s+audio|lyrics?|visuali[sz]er|audio)(?:\)|\])\s*",
        " ", str(text or ""), flags=re.IGNORECASE,
    )
    return " ".join(text.split()).strip(" -|")


def youtube_music_metadata(info):
    title = clean_metadata_text(info.get("track") or info.get("alt_title") or "")
    artist = clean_metadata_text(info.get("artist") or info.get("creator") or "")
    video_title = clean_metadata_text(info.get("title") or "")
    uploader = clean_metadata_text(info.get("uploader") or info.get("channel") or "")
    uploader = re.sub(r"\s+-\s+Topic$", "", uploader, flags=re.IGNORECASE)
    uploader = re.sub(r"VEVO$", "", uploader, flags=re.IGNORECASE).strip()

    if not title and " - " in video_title:
        inferred_artist, inferred_title = video_title.split(" - ", 1)
        title = clean_metadata_text(inferred_title)
        artist = artist or clean_metadata_text(inferred_artist)
    title = title or video_title
    artist = artist or uploader
    try:
        duration = float(info.get("duration")) if info.get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None
    return {"title": title, "artist": artist, "duration": duration}


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
        elif duration and float(duration) > start:
            end = min(float(duration), start + 8)
        else:
            end = start + 4
        end = max(start + 0.05, end)
        word_texts = split_words(text)
        step = (end - start) / max(1, len(word_texts))
        words = [{
            "id": f"lrclib-{len(segments)}-{word_index}",
            "text": word_text,
            "start_time": round(start + step * word_index, 3),
            "end_time": round(start + step * (word_index + 1), 3),
        } for word_index, word_text in enumerate(word_texts)]
        if words:
            segments.append({
                "id": f"lrclib-segment-{len(segments)}",
                "text": text,
                "start_time": words[0]["start_time"],
                "end_time": words[-1]["end_time"],
                "words": words,
            })
    return segments


def fetch_lrclib_lyrics(info, output_dir):
    cache_path = output_dir / "lrclib_lyrics.json"
    cached = read_json_cache(cache_path)
    if cached and cached.get("source") == "lrclib" and cached.get("text"):
        return cached

    metadata = youtube_music_metadata(info)
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


def interpolate_word_timing(index, mapped, reference_words):
    before_item = next(((position, mapped[position]) for position in range(index - 1, -1, -1) if position in mapped), None)
    after_item = next(((position, mapped[position]) for position in range(index + 1, max(mapped.keys(), default=-1) + 1) if position in mapped), None)
    before = before_item[1] if before_item else None
    after = after_item[1] if after_item else None
    if before and after:
        slots = after_item[0] - before_item[0]
        available = after["start_time"] - before["end_time"]
        if available <= 0.05:
            boundary = (before["end_time"] + after["start_time"]) / 2
            return max(0, boundary - 0.06), boundary + 0.06
        step = available / slots
        start = before["end_time"] + step * (index - before_item[0] - 1)
        return start, start + step
    if before:
        start = before["end_time"] + 0.3 * (index - before_item[0] - 1)
        return start, start + 0.3
    if after:
        end = after["start_time"] - 0.3 * (after_item[0] - index - 1)
        return max(0, end - 0.3), end
    if reference_words:
        return reference_words[0]["start_time"], reference_words[-1]["end_time"]
    return index * 0.4, (index + 1) * 0.4


def align_edited_lyrics(text, reference_segments):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    edited_words = [word for line in lines for word in split_words(line)]
    reference_words = [word for segment in reference_segments for word in segment.get("words", [])]
    matcher = SequenceMatcher(
        None,
        [normalize_word(word.get("text", "")) for word in reference_words],
        [normalize_word(word) for word in edited_words],
        autojunk=False,
    )
    mapped = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapped[block.b + offset] = reference_words[block.a + offset]

    timed_words = []
    for index, word_text in enumerate(edited_words):
        timing = mapped.get(index)
        if timing:
            start, end = timing["start_time"], timing["end_time"]
        else:
            start, end = interpolate_word_timing(index, mapped, reference_words)
        timed_words.append({
            "id": f"edited-word-{index}", "text": word_text,
            "start_time": round(float(start), 3), "end_time": round(float(end), 3),
        })

    segments = []
    cursor = 0
    for line_index, line in enumerate(lines):
        count = len(split_words(line))
        words = timed_words[cursor:cursor + count]
        cursor += count
        if words:
            segments.append({
                "id": f"edited-segment-{line_index}", "text": line, "words": words,
                "start_time": words[0]["start_time"], "end_time": words[-1]["end_time"],
            })
    return segments


def lyrics_runner_path():
    root = Path(__file__).resolve().parents[2]
    return root / ".venv-roformer" / "Scripts" / "python.exe", root / "host" / "lyrics_runner.py"


def transcribe_lyrics(job_id, vocals_path):
    python, runner = lyrics_runner_path()
    if not python.exists() or not runner.exists():
        raise FileNotFoundError(
            "Lyrics runtime is not installed. Run setup-roformer.ps1."
        )
    if not is_complete_file(vocals_path):
        raise FileNotFoundError("The vocals stem is missing or empty.")
    send_job(job_id, "status", "Finding word timings in the vocals...", phase="lyrics")
    LOGGER.info("job=%s starting lyric transcription", job_id)
    try:
        result = subprocess.run(
            [str(python), str(runner), str(vocals_path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=LYRICS_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Lyrics extraction timed out after {LYRICS_TIMEOUT_SECONDS // 60} minutes."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start lyrics extraction: {exc}") from exc
    LOGGER.info("job=%s lyric transcription exited code=%s", job_id, result.returncode)
    if result.stderr.strip():
        LOGGER.info("job=%s lyric transcription output: %s", job_id, result.stderr.strip())
    if result.returncode != 0:
        detail = next(
            (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
            "",
        )
        raise RuntimeError(detail or f"Lyrics extraction exited with code {result.returncode}.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Older/cached runners or third-party code may still prefix stdout.
        # Accept the final JSON line, but retain the full diagnostic excerpt.
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                LOGGER.warning("job=%s lyric transcription prefixed its JSON output", job_id)
                break
        else:
            LOGGER.error(
                "job=%s lyric transcription returned invalid JSON stdout=%r",
                job_id,
                result.stdout[:1000],
            )
            raise RuntimeError("Lyrics extraction returned an invalid result.")
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise RuntimeError("Lyrics extraction returned an invalid segment list.")
    if not segments:
        raise RuntimeError("Whisper found no words in the vocals stem.")
    return segments


def prepare_lyrics(job_id, output_dir, vocals_path, requested_text, youtube_lyrics, force=False):
    requested_text = (requested_text or "").strip()
    youtube_text = ((youtube_lyrics or {}).get("text") or "").strip()
    final_text = requested_text or youtube_text
    if not final_text:
        return {"text": "", "segments": [], "source": "none"}

    cached_path = output_dir / "lyrics.json"
    cached = read_json_cache(cached_path) if not force else None
    if cached:
        cache_matches_text = (
            requested_text and cached.get("textHash") == hashlib.sha256(requested_text.encode("utf-8")).hexdigest()
        ) or (not requested_text and cached.get("segments"))
        if cached.get("timingVersion") == LYRICS_TIMING_VERSION and cache_matches_text:
            return {key: cached.get(key) for key in ("text", "segments", "source")}
    provider_segments = (youtube_lyrics or {}).get("segments") or []
    provider_source = (youtube_lyrics or {}).get("source") or "none"

    # YouTube JSON3 is excellent as a text source but automatic captions often
    # expose rolling cue windows rather than true word ends. Karaoke-gen uses a
    # word-timestamped vocal transcription as the timing authority, then maps
    # corrected/reference lyric text onto those timestamps. Do the same here.
    whisper_segments = transcribe_lyrics(job_id, vocals_path)
    reference_segments = whisper_segments
    source = f"{provider_source}+local-whisper" if provider_source != "none" else "local-whisper"

    segments = align_edited_lyrics(final_text, reference_segments) if final_text else []
    result = {"text": final_text, "segments": segments, "source": source}
    digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    write_json_cache(cached_path, {
        **result, "textHash": digest, "timingVersion": LYRICS_TIMING_VERSION
    })
    return result
