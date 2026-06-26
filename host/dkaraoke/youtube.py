import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from .cache import unlink_best_effort, write_json_cache
from .constants import AUTH_ERROR_MARKERS, YTDLP_METADATA_ATTEMPTS, YTDLP_METADATA_TIMEOUT_SECONDS
from .logging_setup import LOGGER
from .processes import subprocess_creationflags

def cookie_line(cookie):
    domain = str(cookie.get("domain") or "")
    name = str(cookie.get("name") or "")
    if not domain or not name:
        return None
    domain_field = f"#HttpOnly_{domain}" if cookie.get("httpOnly") else domain
    return "\t".join([
        domain_field,
        "TRUE" if domain.startswith(".") else "FALSE",
        str(cookie.get("path") or "/"),
        "TRUE" if cookie.get("secure") else "FALSE",
        str(int(float(cookie.get("expirationDate") or 0))),
        name,
        str(cookie.get("value") or ""),
    ])


def write_cookie_file(cookies):
    lines = ["# Netscape HTTP Cookie File"]
    lines.extend(line for cookie in cookies if (line := cookie_line(cookie)))
    if len(lines) == 1:
        return None
    path = Path(tempfile.gettempdir()) / f"dkaraoke-cookies-{uuid.uuid4().hex}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def require_tools():
    missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe", "node") if not shutil.which(name)]
    if missing:
        raise FileNotFoundError(f"Missing required tool(s): {', '.join(missing)}. Run install.ps1, then restart Chrome.")
    return shutil.which("yt-dlp")


def ytdlp_runtime_args():
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("Node.js is required to resolve YouTube media formats. Run install.ps1, then restart Chrome.")
    return ["--js-runtimes", f"node:{node}"]


def has_auth_error(output_text):
    lowered = output_text.lower()
    return any(marker in lowered for marker in AUTH_ERROR_MARKERS)


def normalize_word(text):
    return re.sub(r"[^\w']+", "", text, flags=re.UNICODE).casefold()


def split_words(text):
    return re.findall(r"\S+", text or "")


def parse_youtube_json3(payload):
    segments = []
    for event_index, event in enumerate(payload.get("events") or []):
        fragments = event.get("segs") or []
        raw_text = "".join(str(fragment.get("utf8") or "") for fragment in fragments)
        line_text = " ".join(raw_text.replace("\n", " ").split())
        if not line_text:
            continue

        event_start = float(event.get("tStartMs") or 0) / 1000
        event_duration = max(0.05, float(event.get("dDurationMs") or 0) / 1000)
        event_end = event_start + event_duration
        words = []
        for fragment_index, fragment in enumerate(fragments):
            fragment_words = split_words(str(fragment.get("utf8") or ""))
            if not fragment_words:
                continue
            fragment_start = event_start + float(fragment.get("tOffsetMs") or 0) / 1000
            if fragment_index + 1 < len(fragments):
                next_offset = float(fragments[fragment_index + 1].get("tOffsetMs") or 0) / 1000
                fragment_end = max(fragment_start + 0.05, event_start + next_offset)
            else:
                fragment_end = max(fragment_start + 0.05, event_end)
            step = (fragment_end - fragment_start) / len(fragment_words)
            for word_index, word_text in enumerate(fragment_words):
                start = fragment_start + step * word_index
                words.append({
                    "id": f"yt-{event_index}-{fragment_index}-{word_index}",
                    "text": word_text,
                    "start_time": round(start, 3),
                    "end_time": round(start + step, 3),
                })
        if not words:
            fallback_words = split_words(line_text)
            step = event_duration / max(1, len(fallback_words))
            words = [{
                "id": f"yt-{event_index}-{word_index}",
                "text": word_text,
                "start_time": round(event_start + step * word_index, 3),
                "end_time": round(event_start + step * (word_index + 1), 3),
            } for word_index, word_text in enumerate(fallback_words)]
        segments.append({
            "id": f"yt-segment-{event_index}",
            "text": line_text,
            "start_time": words[0]["start_time"],
            "end_time": words[-1]["end_time"],
            "words": words,
        })
    return segments


def choose_caption_track(info):
    language = str(info.get("language") or "")
    # yt-dlp exposes creator-provided subtitles separately from YouTube's ASR
    # automatic_captions. There is no reliable "official song lyrics" flag, so
    # manual subtitles are the only conservative signal we accept.
    for source_name, tracks in (("youtube-manual", info.get("subtitles") or {}),):
        languages = list(tracks)
        if not languages:
            continue
        preferred = next((code for code in languages if code == language), None)
        preferred = preferred or next((code for code in languages if not code.endswith("-orig") and "-" not in code), None)
        preferred = preferred or languages[0]
        formats = tracks.get(preferred) or []
        caption = next((item for item in formats if item.get("ext") == "json3"), None)
        if caption and caption.get("url"):
            return source_name, preferred, caption["url"]
    return None


def run_ytdlp_json(url, cookie_path=None):
    yt_dlp = require_tools()
    command = [
        yt_dlp, "--ignore-config", *ytdlp_runtime_args(),
        "--socket-timeout", "20",
        "--no-playlist", "--skip-download", "--no-warnings", "--dump-single-json",
    ]
    if cookie_path:
        command.extend(["--cookies", str(cookie_path)])
    command.append(url)
    LOGGER.info("inspecting YouTube metadata cookies=%s", bool(cookie_path))
    for attempt in range(1, YTDLP_METADATA_ATTEMPTS + 1):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=YTDLP_METADATA_TIMEOUT_SECONDS,
                creationflags=subprocess_creationflags(),
            )
            break
        except subprocess.TimeoutExpired as exc:
            LOGGER.warning(
                "YouTube metadata inspection timed out attempt=%s/%s",
                attempt,
                YTDLP_METADATA_ATTEMPTS,
            )
            if attempt == YTDLP_METADATA_ATTEMPTS:
                raise RuntimeError(
                    f"YouTube metadata inspection timed out after {YTDLP_METADATA_ATTEMPTS} attempts."
                ) from exc
    LOGGER.info("YouTube metadata inspection exited code=%s", result.returncode)
    if result.returncode != 0:
        if result.stderr.strip():
            LOGGER.error("yt-dlp metadata: %s", result.stderr.strip())
        raise RuntimeError(result.stderr.strip() or "Could not inspect the YouTube video.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp returned invalid video metadata.") from exc


def load_youtube_info(url, cookies):
    cookie_path = None
    try:
        try:
            return run_ytdlp_json(url)
        except RuntimeError as exc:
            if not has_auth_error(str(exc)):
                raise
            cookie_path = write_cookie_file(cookies)
            if not cookie_path:
                raise
            return run_ytdlp_json(url, cookie_path)
    finally:
        if cookie_path and cookie_path.exists():
            unlink_best_effort(cookie_path, "metadata cookie cleanup")


def fetch_youtube_lyrics(url, cookies, output_dir, info=None):
    cache_path = output_dir / "youtube_lyrics.json"
    cached = read_json_cache(cache_path)
    if cached and cached.get("source") == "youtube-manual":
        return cached

    info = info or load_youtube_info(url, cookies)
    selected = choose_caption_track(info)
    if not selected:
        return {"text": "", "segments": [], "source": "none", "message": "YouTube has no manual captions for this video."}
    source, language, caption_url = selected
    request = Request(caption_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    segments = parse_youtube_json3(payload)
    result = {
        "text": "\n".join(segment["text"] for segment in segments),
        "segments": segments,
        "source": source,
        "language": language,
        "message": "Loaded creator-provided YouTube lyrics.",
    }
    if segments:
        write_json_cache(cache_path, result)
    return result

