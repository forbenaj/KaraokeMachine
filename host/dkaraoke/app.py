import json
import os
import re
import sys
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .audio_server import stop_audio_server
from .diagnostics import record_diagnostic, record_external_diagnostic
from .logging_setup import DIAGNOSTICS_PATH, LOGGER, LOG_PATH
from .messaging import NativeMessagingDisconnected, read_message, send_job
from .paths import begin_stem_job, finish_stem_job, validate_youtube_url, video_id_from_url, app_download_dir
from .pipeline import check_cache, extract_lyrics_timings, run_download
from .lyrics import clean_metadata_text, fetch_lrclib_lyrics

YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"
YOUTUBE_METADATA_TIMEOUT_SECONDS = 5


def artist_from_youtube_channel_name(value):
    channel = " ".join(str(value or "").split())
    if not channel:
        return ""
    topic_match = re.match(r"^(.+?)\s*-\s*Topic$", channel, flags=re.IGNORECASE)
    if topic_match:
        return topic_match.group(1).strip()
    vevo_match = re.match(r"^(.+?)VEVO$", channel, flags=re.IGNORECASE)
    if vevo_match:
        return vevo_match.group(1).strip()
    return ""


def youtube_oembed_artist(url):
    request = Request(
        f"{YOUTUBE_OEMBED_URL}?{urlencode({'url': url, 'format': 'json'})}",
        headers={"User-Agent": "Karaoke Machine!/1.10 (local Chrome extension)"},
    )
    with urlopen(request, timeout=YOUTUBE_METADATA_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return ""
    return artist_from_youtube_channel_name(payload.get("author_name"))


def enrich_lrclib_search_info(url, title, artist, duration):
    info = {"title": title, "artist": artist, "duration": duration}
    if artist.strip() or len(clean_metadata_text(title).split()) > 2:
        return info
    try:
        inferred_artist = youtube_oembed_artist(url)
    except Exception as exc:
        LOGGER.info("could not infer YouTube author for LRCLIB search: %s", exc)
        return info
    if inferred_artist:
        info["artist"] = inferred_artist
    return info


def execute_message(message):
    if not isinstance(message, dict):
        raise ValueError("Native message must be a JSON object.")
    action = message.get("action")
    if action == "recordDiagnostic":
        record_external_diagnostic(message.get("diagnostic"))
        return
    job_id = str(message.get("jobId") or "")
    if not job_id:
        raise ValueError("Missing job ID.")
    LOGGER.info("job=%s action=%s received", job_id, action)
    if action == "checkCache":
        check_cache(job_id, str(message.get("url") or ""))
        return
    if action == "searchLrclib":
        url = validate_youtube_url(str(message.get("url") or ""))
        video_id = video_id_from_url(url)
        lyrics_info = enrich_lrclib_search_info(
            url,
            str(message.get("title") or ""),
            str(message.get("artist") or ""),
            message.get("duration"),
        )
        lyrics = fetch_lrclib_lyrics(
            lyrics_info,
            app_download_dir(video_id),
            force_refresh=message.get("forceRefresh") is True,
        )
        send_job(
            job_id, "lyrics", lyrics.get("message") or "LRCLIB search complete.",
            lyrics=lyrics, videoId=video_id,
        )
        return
    if action == "extractLyricsTimings":
        extract_lyrics_timings(
            job_id,
            str(message.get("url") or ""),
            str(message.get("lyricsText") or ""),
            str(message.get("timingMethod") or ""),
            str(message.get("timingSource") or ""),
            message.get("cookies") or [],
        )
        return
    if action != "prepareKaraoke":
        raise ValueError("Unsupported backend action.")
    run_download(
        job_id,
        str(message.get("url") or ""),
        message.get("cookies") or [],
        message.get("lyricsTiming") if isinstance(message.get("lyricsTiming"), dict) else None,
    )


def handle_message(message):
    if not isinstance(message, dict):
        raise ValueError("Native message must be a JSON object.")
    action = message.get("action")
    if action == "recordDiagnostic":
        execute_message(message)
        return
    job_id = str(message.get("jobId") or "")
    if not job_id:
        raise ValueError("Missing job ID.")
    supported = {
        "checkCache", "searchLrclib", "extractLyricsTimings",
        "prepareKaraoke",
    }
    if action not in supported:
        raise ValueError("Unsupported backend action.")

    stem_video_id = None
    if action == "prepareKaraoke":
        url = validate_youtube_url(str(message.get("url") or ""))
        stem_video_id = video_id_from_url(url)
        begin_stem_job(stem_video_id)

    def run():
        try:
            execute_message(message)
        except NativeMessagingDisconnected:
            return
        except Exception as exc:
            LOGGER.exception("job=%s failed", job_id)
            record_diagnostic(
                "error",
                "job_failed",
                str(exc),
                job_id=job_id,
                details={"action": action},
                exc=exc,
            )
            try:
                send_job(job_id, "error", str(exc))
            except NativeMessagingDisconnected:
                return
        finally:
            if stem_video_id:
                finish_stem_job(stem_video_id)

    threading.Thread(
        target=run,
        name=f"{str(action or 'job').lower()}-{job_id[:8]}",
        daemon=True,
    ).start()


def main():
    LOGGER.info("native host started pid=%s log=%s", os.getpid(), LOG_PATH)
    record_diagnostic(
        "info",
        "native_host_started",
        "Native host started.",
        details={"pid": os.getpid(), "logPath": str(LOG_PATH), "diagnosticsPath": str(DIAGNOSTICS_PATH)},
    )
    try:
        while True:
            message = read_message()
            if message is None:
                LOGGER.info("native messaging input closed")
                record_diagnostic("info", "native_input_closed", "Native messaging input closed.")
                break
            job_id = str(message.get("jobId") or "") if isinstance(message, dict) else ""
            try:
                handle_message(message)
            except NativeMessagingDisconnected:
                LOGGER.info("native messaging output closed")
                record_diagnostic("warning", "native_output_closed", "Native messaging output closed.")
                break
            except Exception as exc:
                LOGGER.exception("job=%s failed", job_id)
                record_diagnostic(
                    "error",
                    "message_failed",
                    str(exc),
                    job_id=job_id,
                    details={
                        "action": message.get("action") if isinstance(message, dict) else "",
                        "messageType": type(message).__name__,
                    },
                    exc=exc,
                )
                try:
                    send_job(job_id, "error", str(exc))
                except NativeMessagingDisconnected:
                    LOGGER.info("native messaging output closed while reporting job=%s failure", job_id)
                    record_diagnostic(
                        "warning",
                        "native_output_closed_reporting_failure",
                        "Native messaging output closed while reporting a job failure.",
                        job_id=job_id,
                    )
                    break
    except Exception:
        LOGGER.exception("native host stopped after an unhandled error")
        record_diagnostic(
            "error",
            "native_host_unhandled_error",
            "Native host stopped after an unhandled error.",
            exc=sys.exc_info()[1],
        )
        raise
    finally:
        stop_audio_server()
        LOGGER.info("native host stopped")
        record_diagnostic("info", "native_host_stopped", "Native host stopped.")
