import threading
import traceback
from datetime import datetime, timezone

from .logging_setup import DIAGNOSTICS_PATH, LOGGER

DIAGNOSTICS_LOCK = threading.Lock()
MAX_STRING_LENGTH = 2000
MAX_TRACEBACK_LENGTH = 6000
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "instrumentalurl",
    "password",
    "secret",
    "src",
    "token",
    "value",
    "vocalsurl",
)
URL_KEYS = {"href", "rawurl", "url"}
LOGGED_LEVELS = {"warning", "error"}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_string(value, limit=MAX_STRING_LENGTH):
    text = "" if value is None else str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def sanitize_value(value, key="", depth=0):
    lowered_key = str(key or "").replace("_", "").replace("-", "").casefold()
    if lowered_key in URL_KEYS or any(part in lowered_key for part in SENSITIVE_KEY_PARTS):
        return "[redacted]"
    if depth >= 5:
        return "[max-depth]"
    if isinstance(value, dict):
        return {
            clean_string(item_key, 120): sanitize_value(item_value, item_key, depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, key, depth + 1) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return clean_string(value)


def exception_diagnostic_details(exc):
    trace = traceback.format_exc()
    if trace == "NoneType: None\n":
        trace = "".join(traceback.format_exception_only(type(exc), exc))
    return {
        "errorType": type(exc).__name__,
        "traceback": clean_string(trace, MAX_TRACEBACK_LENGTH),
    }


def normalize_level(level):
    value = str(level or "info").casefold()
    return value if value in LOGGED_LEVELS else "info"


def format_value(value):
    if isinstance(value, dict):
        parts = [
            f"{clean_string(key, 120)}={format_value(item)}"
            for key, item in value.items()
        ]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return clean_string(value)


def format_details(details):
    if not isinstance(details, dict) or not details:
        return ""
    return "; ".join(
        f"{clean_string(key, 120)}={format_value(value)}"
        for key, value in details.items()
    )


def format_diagnostic_line(entry):
    parts = [
        entry["timestamp"],
        entry["level"].upper(),
        f"[{entry['source']}]",
        f"{entry['event']}:",
        entry["message"],
    ]
    context = []
    if entry.get("jobId"):
        context.append(f"job={entry['jobId']}")
    if entry.get("videoId"):
        context.append(f"video={entry['videoId']}")
    if entry.get("phase"):
        context.append(f"phase={entry['phase']}")
    if context:
        parts.append("| " + " ".join(context))
    details = format_details(entry.get("details"))
    if details:
        parts.append("| " + details)
    return " ".join(parts)


def record_diagnostic(
    level,
    event,
    message,
    *,
    source="host",
    job_id="",
    video_id="",
    phase="",
    details=None,
    exc=None,
):
    level = normalize_level(level)
    if level not in LOGGED_LEVELS:
        return None
    entry = {
        "timestamp": utc_timestamp(),
        "level": level,
        "source": clean_string(source, 80) or "host",
        "event": clean_string(event, 120) or "event",
        "message": clean_string(message),
    }
    if job_id:
        entry["jobId"] = clean_string(job_id, 120)
    if video_id:
        entry["videoId"] = clean_string(video_id, 120)
    if phase:
        entry["phase"] = clean_string(phase, 80)
    if details:
        entry["details"] = sanitize_value(details)
    if exc is not None:
        exception_details = exception_diagnostic_details(exc)
        if not isinstance(entry.get("details"), dict):
            entry["details"] = {}
        entry["details"].update(exception_details)

    try:
        DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = format_diagnostic_line(entry)
        with DIAGNOSTICS_LOCK:
            with DIAGNOSTICS_PATH.open("a", encoding="utf-8") as output:
                output.write(line + "\n")
    except OSError as write_error:
        LOGGER.warning("could not write diagnostics journal error=%s", write_error)
    return entry


def record_external_diagnostic(payload):
    if not isinstance(payload, dict):
        record_diagnostic(
            "warning",
            "invalid_external_diagnostic",
            "Ignored malformed external diagnostic payload.",
            details={"payloadType": type(payload).__name__},
        )
        return
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    record_diagnostic(
        payload.get("level") or "info",
        payload.get("event") or "external_event",
        payload.get("message") or "",
        source=payload.get("source") or "extension",
        job_id=payload.get("jobId") or "",
        video_id=payload.get("videoId") or "",
        phase=payload.get("phase") or "",
        details=details,
    )
