import re

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
ALLOWED_ORIGINS = {"https://www.youtube.com", "https://m.youtube.com", "https://music.youtube.com"}
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
ROFORMER_TOTAL_TIME_RE = re.compile(
    r"Estimated total processing time for this track:\s*([\d.]+)\s*seconds",
    re.IGNORECASE,
)
ROFORMER_REMAINING_TIME_RE = re.compile(
    r"Estimated time remaining:\s*([\d.]+)\s*seconds",
    re.IGNORECASE,
)
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
AUTH_ERROR_MARKERS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
    "private video",
    "age-restricted",
    "members-only",
)
STEM_MP3_BITRATE = "192k"
LYRICS_TIMING_VERSION = 3
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRC_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d{2}(?:\.\d{1,3})?)\]")
YTDLP_METADATA_TIMEOUT_SECONDS = 90
YTDLP_METADATA_ATTEMPTS = 2
MAX_NATIVE_MESSAGE_BYTES = 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = 60
FFMPEG_TIMEOUT_SECONDS = 30 * 60
YTDLP_DOWNLOAD_TIMEOUT_SECONDS = 2 * 60 * 60
ROFORMER_TIMEOUT_SECONDS = 6 * 60 * 60
LYRICS_TIMEOUT_SECONDS = 2 * 60 * 60
STEM_WAIT_TIMEOUT_SECONDS = (
    YTDLP_DOWNLOAD_TIMEOUT_SECONDS + ROFORMER_TIMEOUT_SECONDS + 10 * 60
)
