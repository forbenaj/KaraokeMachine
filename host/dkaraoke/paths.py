import os
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .constants import YOUTUBE_HOSTS

STEM_JOB_LOCK = threading.Lock()
ACTIVE_STEM_JOBS = set()
STEM_READY_EVENTS = {}
TIMING_JOB_LOCK = threading.Lock()
TIMING_JOB_LOCKS = {}

def validate_youtube_url(raw_url):
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS:
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


def stem_ready_event(video_id):
    with STEM_JOB_LOCK:
        return STEM_READY_EVENTS.setdefault(video_id, threading.Event())


def begin_stem_job(video_id):
    event = stem_ready_event(video_id)
    with STEM_JOB_LOCK:
        event.clear()
        ACTIVE_STEM_JOBS.add(video_id)


def finish_stem_job(video_id):
    with STEM_JOB_LOCK:
        ACTIVE_STEM_JOBS.discard(video_id)
        event = STEM_READY_EVENTS.setdefault(video_id, threading.Event())
        event.set()


def stem_job_active(video_id):
    with STEM_JOB_LOCK:
        return video_id in ACTIVE_STEM_JOBS


def timing_job_lock(video_id):
    with TIMING_JOB_LOCK:
        return TIMING_JOB_LOCKS.setdefault(video_id, threading.Lock())
