import json
import hashlib
import logging
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import uuid
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
ALLOWED_ORIGINS = {"https://www.youtube.com", "https://m.youtube.com", "https://music.youtube.com"}
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
AUTH_ERROR_MARKERS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
    "private video",
    "age-restricted",
    "members-only",
)

AUDIO_FILES = {}
AUDIO_FILES_LOCK = threading.Lock()
SEND_MESSAGE_LOCK = threading.Lock()
STEM_TRANSCODE_LOCK = threading.Lock()
AUDIO_SERVER = None
AUDIO_SERVER_THREAD = None
STEM_MP3_BITRATE = "192k"
LYRICS_TIMING_VERSION = 3
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRC_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d{2}(?:\.\d{1,3})?)\]")


def configure_logging():
    local_app_data = os.environ.get("LOCALAPPDATA")
    log_dir = Path(local_app_data) / "DKaraoKe" if local_app_data else Path.home() / ".dkaraoke"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dkaraoke.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    logger = logging.getLogger("dkaraoke")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger, log_path


LOGGER, LOG_PATH = configure_logging()


def send_message(payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    with SEND_MESSAGE_LOCK:
        sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()


def send_job(job_id, message_type, message, **extra):
    send_message({"jobId": job_id, "type": message_type, "message": message, **extra})


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    length = struct.unpack("<I", raw_length)[0]
    payload = sys.stdin.buffer.read(length)
    if len(payload) != length:
        raise ValueError("Received a truncated native message.")
    return json.loads(payload.decode("utf-8"))


class AudioRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def add_access_headers(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self.add_access_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.serve_audio(head_only=True)

    def do_GET(self):
        self.serve_audio(head_only=False)

    def serve_audio(self, head_only):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "audio":
            self.send_error(404)
            return

        with AUDIO_FILES_LOCK:
            audio_path = AUDIO_FILES.get(parts[1])
        if not audio_path or not audio_path.is_file():
            self.send_error(404)
            return

        file_size = audio_path.stat().st_size
        start = 0
        end = file_size - 1
        status = 200
        range_header = self.headers.get("Range")

        if range_header:
            match = RANGE_RE.fullmatch(range_header.strip())
            if not match:
                self.send_error(416)
                return
            start_text, end_text = match.groups()
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else end
            elif end_text:
                suffix_length = int(end_text)
                start = max(0, file_size - suffix_length)
            if start >= file_size or start > end:
                self.send_response(416)
                self.add_access_headers()
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(end, file_size - 1)
            status = 206

        content_length = end - start + 1
        self.send_response(status)
        self.add_access_headers()
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        content_type = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if head_only:
            return

        try:
            with audio_path.open("rb") as source:
                source.seek(start)
                remaining = content_length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return


def ensure_audio_server():
    global AUDIO_SERVER, AUDIO_SERVER_THREAD
    if AUDIO_SERVER:
        return AUDIO_SERVER
    AUDIO_SERVER = ThreadingHTTPServer(("127.0.0.1", 0), AudioRequestHandler)
    AUDIO_SERVER_THREAD = threading.Thread(target=AUDIO_SERVER.serve_forever, daemon=True)
    AUDIO_SERVER_THREAD.start()
    return AUDIO_SERVER


def register_audio(audio_path):
    server = ensure_audio_server()
    token = secrets.token_urlsafe(32)
    with AUDIO_FILES_LOCK:
        AUDIO_FILES[token] = audio_path.resolve()
    return f"http://127.0.0.1:{server.server_port}/audio/{token}"


def is_complete_file(path):
    return path.is_file() and path.stat().st_size > 0


def stem_paths(stem_dir, suffix=".mp3"):
    return stem_dir / f"instrumental{suffix}", stem_dir / f"vocals{suffix}"


def validate_stem_mp3(path):
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=creationflags,
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
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with STEM_TRANSCODE_LOCK:
        if all(is_complete_file(path) for path in mp3_paths):
            for path in wav_paths:
                path.unlink(missing_ok=True)
            return mp3_paths
        if not all(is_complete_file(path) for path in wav_paths):
            raise FileNotFoundError("Both WAV stems are required before MP3 compression.")

        send_job(job_id, "status", "Compressing separated stems to MP3...", phase="convert")
        try:
            for source, temporary in zip(wav_paths, temporary_paths):
                result = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(source), "-vn", "-map", "0:a:0",
                        "-c:a", "libmp3lame", "-b:a", STEM_MP3_BITRATE,
                        "-ar", "44100", "-ac", "2", "-write_xing", "1",
                        str(temporary),
                    ],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    creationflags=creationflags,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"FFmpeg could not compress {source.name}.")
                validate_stem_mp3(temporary)

            for temporary, destination in zip(temporary_paths, mp3_paths):
                os.replace(temporary, destination)
            for path in wav_paths:
                path.unlink(missing_ok=True)
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    LOGGER.info("job=%s compressed stems bitrate=%s directory=%s", job_id, STEM_MP3_BITRATE, instrumental_wav.parent)
    return mp3_paths


def resolve_cached_stems(job_id, stem_dir):
    mp3_paths = stem_paths(stem_dir)
    wav_paths = stem_paths(stem_dir, ".wav")
    if all(is_complete_file(path) for path in mp3_paths):
        for path in wav_paths:
            path.unlink(missing_ok=True)
        return mp3_paths
    if all(is_complete_file(path) for path in wav_paths):
        try:
            return compress_stems(job_id, *wav_paths)
        except Exception:
            LOGGER.exception("job=%s could not migrate cached WAV stems", job_id)
            return wav_paths
    return mp3_paths


def read_json_cache(path):
    if not is_complete_file(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("ignoring invalid cache file path=%s", path)
        return None


def write_json_cache(path, payload):
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def send_stems_ready(job_id, video_id, final_path, instrumental_path, vocals_path, cache_hit=False):
    instrumental_url = register_audio(instrumental_path)
    vocals_url = register_audio(vocals_path)
    send_job(
        job_id,
        "stemsReady",
        "Cached stems ready. Loading synchronized audio..."
        if cache_hit else "Stems ready. Loading synchronized audio...",
        filePath=str(final_path),
        instrumentalPath=str(instrumental_path),
        vocalsPath=str(vocals_path),
        instrumentalUrl=instrumental_url,
        vocalsUrl=vocals_url,
        videoId=video_id,
        cacheHit=cache_hit,
    )


def complete_job(job_id, video_id, lyrics=None):
    send_job(
        job_id,
        "complete",
        "Stems ready and lyric timing refined."
        if (lyrics or {}).get("segments") else "Stems ready. No synchronized lyrics found.",
        lyrics=lyrics or {"text": "", "segments": [], "source": "none"},
        videoId=video_id,
    )


def check_cache(job_id, raw_url):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    final_path = output_dir / "audio.mp3"
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

    has_stems = all(is_complete_file(path) for path in (final_path, instrumental_path, vocals_path))
    payload = {
        "lyrics": lyrics,
        "videoId": video_id,
        "hasLyrics": bool(lyrics.get("text") and lyrics.get("segments")),
        "hasStems": has_stems,
    }
    if has_stems:
        payload.update({
            "filePath": str(final_path),
            "instrumentalUrl": register_audio(instrumental_path),
            "vocalsUrl": register_audio(vocals_path),
        })
    send_job(job_id, "cacheCheck", "Checked saved karaoke results.", **payload)


def roformer_paths():
    root = Path(__file__).resolve().parent.parent
    return (
        root / ".venv-roformer" / "Scripts" / "python.exe",
        root / ".stem-models" / "mel-band-roformer",
        root / ".stem-models" / "MelBandRoformer.ckpt",
        Path(__file__).resolve().with_name("roformer_runner.py"),
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
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    assert process.stdout is not None
    last_line = ""
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        LOGGER.info("job=%s RoFormer: %s", job_id, line)
        last_line = line
        if "Normalizing" in line:
            send_job(job_id, "status", "Preparing audio for RoFormer...", phase="separate")
        elif "Separating vocals" in line:
            send_job(job_id, "status", "RoFormer is separating vocals...", phase="separate")
    return_code = process.wait()
    LOGGER.info("job=%s RoFormer exited code=%s", job_id, return_code)
    if return_code != 0:
        raise RuntimeError(last_line or f"RoFormer exited with code {return_code}.")

    stem_dir = output_dir / source_path.stem
    instrumental_path, vocals_path = stem_paths(stem_dir, ".wav")
    if not instrumental_path.is_file() or not vocals_path.is_file():
        raise FileNotFoundError("RoFormer finished, but its stem files were not found.")
    return compress_stems(job_id, instrumental_path, vocals_path)


def stop_audio_server():
    global AUDIO_SERVER, AUDIO_SERVER_THREAD
    if AUDIO_SERVER:
        AUDIO_SERVER.shutdown()
        AUDIO_SERVER.server_close()
    if AUDIO_SERVER_THREAD:
        AUDIO_SERVER_THREAD.join(timeout=2)
    AUDIO_SERVER = None
    AUDIO_SERVER_THREAD = None
    with AUDIO_FILES_LOCK:
        AUDIO_FILES.clear()


def validate_youtube_url(raw_url):
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise ValueError("Only YouTube video URLs are supported.")
    return raw_url


def video_id_from_url(raw_url):
    parsed = urlparse(raw_url)
    if parsed.hostname == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    else:
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    candidate = re.sub(r"[^A-Za-z0-9_-]", "", candidate)
    if not candidate:
        raise ValueError("The YouTube URL has no video ID.")
    return candidate[:32]


def app_download_dir(video_id):
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    path = root / "DKaraoKe" / "downloads" / video_id
    path.mkdir(parents=True, exist_ok=True)
    return path


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
        "--no-playlist", "--skip-download", "--no-warnings", "--dump-single-json",
    ]
    if cookie_path:
        command.extend(["--cookies", str(cookie_path)])
    command.append(url)
    LOGGER.info("inspecting YouTube metadata cookies=%s", bool(cookie_path))
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("YouTube metadata inspection timed out.") from exc
    LOGGER.info("YouTube metadata inspection exited code=%s", result.returncode)
    if result.returncode != 0:
        if result.stderr.strip():
            LOGGER.error("yt-dlp metadata: %s", result.stderr.strip())
        raise RuntimeError(result.stderr.strip() or "Could not inspect the YouTube video.")
    return json.loads(result.stdout)


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
            cookie_path.unlink()


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


def fetch_best_available_lyrics(url, cookies, output_dir, requested_text="", supplied_lyrics=None):
    requested_text = (requested_text or "").strip()
    if requested_text:
        return {"text": requested_text, "segments": [], "source": "manual", "message": "Using edited lyrics."}
    if (supplied_lyrics or {}).get("text"):
        return supplied_lyrics

    info = load_youtube_info(url, cookies)
    youtube_lyrics = fetch_youtube_lyrics(url, cookies, output_dir, info=info)
    if youtube_lyrics.get("text"):
        return youtube_lyrics
    return fetch_lrclib_lyrics(info, output_dir)


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
    root = Path(__file__).resolve().parent.parent
    return root / ".venv-roformer" / "Scripts" / "python.exe", Path(__file__).resolve().with_name("lyrics_runner.py")


def transcribe_lyrics(job_id, vocals_path):
    python, runner = lyrics_runner_path()
    if not python.exists() or not runner.exists():
        LOGGER.warning("job=%s lyrics runtime is unavailable", job_id)
        return []
    send_job(job_id, "status", "Finding word timings in the vocals...", phase="lyrics")
    LOGGER.info("job=%s starting lyric transcription", job_id)
    result = subprocess.run(
        [str(python), str(runner), str(vocals_path)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    LOGGER.info("job=%s lyric transcription exited code=%s", job_id, result.returncode)
    if result.stderr.strip():
        LOGGER.info("job=%s lyric transcription output: %s", job_id, result.stderr.strip())
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get("segments", [])
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
                return payload.get("segments", [])
        LOGGER.exception(
            "job=%s lyric transcription returned invalid JSON stdout=%r",
            job_id,
            result.stdout[:1000],
        )
        return []


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
    if whisper_segments:
        reference_segments = whisper_segments
        source = f"{provider_source}+local-whisper" if provider_source != "none" else "local-whisper"
    else:
        reference_segments = provider_segments
        source = provider_source

    segments = align_edited_lyrics(final_text, reference_segments) if final_text else []
    result = {"text": final_text, "segments": segments, "source": source}
    digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    write_json_cache(cached_path, {
        **result, "textHash": digest, "timingVersion": LYRICS_TIMING_VERSION
    })
    return result


def refresh_lyrics(job_id, raw_url, requested_text):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    stem_dir = output_dir / "separated" / "mel_band_roformer" / "audio"
    _, vocals_path = resolve_cached_stems(job_id, stem_dir)
    if not is_complete_file(vocals_path):
        raise FileNotFoundError("Karaokize this song before refreshing lyric timing.")
    if not (requested_text or "").strip():
        raise ValueError("Enter lyrics before refreshing lyric timing.")
    lyrics = prepare_lyrics(
        job_id, output_dir, vocals_path, requested_text,
        {"text": "", "segments": [], "source": "manual"}, force=True,
    )
    send_job(job_id, "lyricsComplete", "Lyrics timing refreshed.", lyrics=lyrics, videoId=video_id)


def start_lyrics_lookup(job_id, url, cookies, output_dir, requested_text, supplied_lyrics):
    state = {"lyrics": {"text": "", "segments": [], "source": "none"}}

    def lookup():
        searching = not (requested_text or "").strip() and not (supplied_lyrics or {}).get("text")
        if searching:
            send_job(job_id, "monitorStart", "Searching lyrics...", phase="lyricsLookup")
        try:
            if (requested_text or "").strip():
                lyrics = {
                    "text": requested_text.strip(), "segments": [], "source": "manual",
                    "message": "Using edited lyrics.",
                }
            elif (supplied_lyrics or {}).get("text"):
                lyrics = supplied_lyrics
            else:
                info = load_youtube_info(url, cookies)
                lyrics = fetch_lrclib_lyrics(info, output_dir)
            state["lyrics"] = lyrics
            if lyrics.get("text"):
                send_job(
                    job_id,
                    "lyricsPreview",
                    lyrics.get("message") or "Lyrics available; word timing will be refined after separation.",
                    lyrics=lyrics,
                    phase="lyricsLookup",
                )
        except Exception as exc:
            state["error"] = str(exc)
            LOGGER.exception("job=%s concurrent lyric lookup failed", job_id)
        finally:
            if searching:
                send_job(job_id, "monitorEnd", "", phase="lyricsLookup")

    thread = threading.Thread(target=lookup, name=f"lyrics-{job_id[:8]}", daemon=True)
    thread.start()
    return thread, state


def publish_stems_then_refine_lyrics(
    job_id, video_id, final_path, instrumental_path, vocals_path,
    output_dir, requested_text, lyrics_thread, lyrics_state, cache_hit=False,
):
    send_stems_ready(
        job_id, video_id, final_path, instrumental_path, vocals_path, cache_hit=cache_hit,
    )
    lyrics_thread.join()
    provider_lyrics = lyrics_state.get("lyrics") or {"text": "", "segments": [], "source": "none"}
    lyrics = prepare_lyrics(
        job_id, output_dir, vocals_path, requested_text, provider_lyrics,
    )
    complete_job(job_id, video_id, lyrics=lyrics)


def run_download(job_id, raw_url, cookies, requested_text="", supplied_lyrics=None):
    url = validate_youtube_url(raw_url)
    video_id = video_id_from_url(url)
    output_dir = app_download_dir(video_id)
    final_path = output_dir / "audio.mp3"
    separated_dir = output_dir / "separated" / "mel_band_roformer"
    stem_dir = separated_dir / final_path.stem
    instrumental_path, vocals_path = resolve_cached_stems(job_id, stem_dir)
    lyrics_thread, lyrics_state = start_lyrics_lookup(
        job_id, url, cookies, output_dir, requested_text, supplied_lyrics,
    )

    if all(is_complete_file(path) for path in (final_path, instrumental_path, vocals_path)):
        LOGGER.info("job=%s video=%s using cached audio and stems", job_id, video_id)
        send_job(job_id, "status", "Found cached audio and separated stems.", phase="cache")
        publish_stems_then_refine_lyrics(
            job_id, video_id, final_path, instrumental_path, vocals_path,
            output_dir, requested_text, lyrics_thread, lyrics_state, cache_hit=True,
        )
        return

    if is_complete_file(final_path):
        LOGGER.info("job=%s video=%s using cached audio; stems missing", job_id, video_id)
        send_job(job_id, "status", "Downloaded audio found. Extracting missing stems...", phase="separate")
        instrumental_path, vocals_path = run_roformer(job_id, final_path, separated_dir)
        publish_stems_then_refine_lyrics(
            job_id, video_id, final_path, instrumental_path, vocals_path,
            output_dir, requested_text, lyrics_thread, lyrics_state,
        )
        return

    yt_dlp = require_tools()
    output_template = str(output_dir / "audio.%(ext)s")
    base_command = [
        yt_dlp,
        "--ignore-config",
        *ytdlp_runtime_args(),
        "--newline",
        "--no-playlist",
        "--force-overwrites",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--print", "after_move:__DKARAOKE_FILE__:%(filepath)s",
        "-o", output_template,
    ]
    cookie_path = None
    last_line = ""

    try:
        for use_cookies in (False, True):
            if use_cookies:
                cookie_path = write_cookie_file(cookies)
                if not cookie_path:
                    break
                send_job(job_id, "status", "YouTube requested sign-in; retrying with Chrome cookies...")

            command = list(base_command)
            if cookie_path:
                command.extend(["--cookies", str(cookie_path)])
            command.append(url)

            send_job(job_id, "status", "Downloading audio...", progress=0, phase="download")
            LOGGER.info("job=%s video=%s starting yt-dlp cookies=%s", job_id, video_id, bool(cookie_path))
            output_lines = []
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                LOGGER.info("job=%s yt-dlp: %s", job_id, line)
                last_line = line
                output_lines.append(line)

                if line.startswith("__DKARAOKE_FILE__:"):
                    final_path = Path(line.split(":", 1)[1])
                    continue

                progress = PROGRESS_RE.search(line)
                if progress:
                    percent = float(progress.group(1))
                    send_job(
                        job_id,
                        "progress",
                        f"Downloading audio... {percent:.1f}%",
                        progress=percent,
                        phase="download",
                    )
                elif "[ExtractAudio]" in line:
                    send_job(job_id, "status", "Converting audio to MP3...", phase="convert")

            return_code = process.wait()
            LOGGER.info("job=%s yt-dlp exited code=%s", job_id, return_code)
            if return_code == 0:
                if not final_path.exists():
                    raise FileNotFoundError("yt-dlp finished, but the MP3 file was not found.")
                instrumental_path, vocals_path = run_roformer(job_id, final_path, separated_dir)
                publish_stems_then_refine_lyrics(
                    job_id, video_id, final_path, instrumental_path, vocals_path,
                    output_dir, requested_text, lyrics_thread, lyrics_state,
                )
                return

            output_text = "\n".join(output_lines)
            if not use_cookies and has_auth_error(output_text):
                continue
            raise RuntimeError(last_line or f"yt-dlp exited with code {return_code}.")

        raise RuntimeError(last_line or "yt-dlp could not download this audio.")
    finally:
        if cookie_path and cookie_path.exists():
            cookie_path.unlink()


def handle_message(message):
    job_id = str(message.get("jobId") or "")
    if not job_id:
        raise ValueError("Missing job ID.")
    action = message.get("action")
    LOGGER.info("job=%s action=%s received", job_id, action)
    if action == "checkCache":
        check_cache(job_id, str(message.get("url") or ""))
        return
    if action == "fetchLyrics":
        url = validate_youtube_url(str(message.get("url") or ""))
        video_id = video_id_from_url(url)
        cookies = message.get("cookies") or []

        def fetch_and_send():
            try:
                lyrics = fetch_best_available_lyrics(
                    url, cookies, app_download_dir(video_id),
                )
                send_job(
                    job_id, "lyrics", lyrics.get("message") or "Lyrics lookup complete.",
                    lyrics=lyrics, videoId=video_id,
                )
            except Exception as exc:
                LOGGER.exception("job=%s standalone lyric lookup failed", job_id)
                send_job(job_id, "error", str(exc))

        threading.Thread(
            target=fetch_and_send, name=f"lyrics-fetch-{job_id[:8]}", daemon=True,
        ).start()
        return
    if action == "refreshLyrics":
        refresh_lyrics(job_id, str(message.get("url") or ""), str(message.get("lyricsText") or ""))
        return
    if action != "downloadMp3":
        raise ValueError("Unsupported backend action.")
    run_download(
        job_id, str(message.get("url") or ""), message.get("cookies") or [],
        str(message.get("lyricsText") or ""), message.get("youtubeLyrics") or {},
    )


def main():
    LOGGER.info("native host started pid=%s log=%s", os.getpid(), LOG_PATH)
    try:
        while True:
            message = read_message()
            if message is None:
                LOGGER.info("native messaging input closed")
                break
            job_id = str(message.get("jobId") or "")
            try:
                handle_message(message)
            except Exception as exc:
                LOGGER.exception("job=%s failed", job_id)
                send_job(job_id, "error", str(exc))
    except Exception:
        LOGGER.exception("native host stopped after an unhandled error")
        raise
    finally:
        stop_audio_server()
        LOGGER.info("native host stopped")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
