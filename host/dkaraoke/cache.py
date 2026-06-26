import json
import os
import uuid

from .logging_setup import LOGGER

def is_complete_file(path):
    return path.is_file() and path.stat().st_size > 0


def unlink_best_effort(path, context="cleanup"):
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        LOGGER.warning("%s skipped locked file path=%s error=%s", context, path, exc)
        return False


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
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        unlink_best_effort(temporary, "JSON cache temporary cleanup")
