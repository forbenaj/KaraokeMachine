import json
import struct
import sys
import threading

from .constants import MAX_NATIVE_MESSAGE_BYTES

SEND_MESSAGE_LOCK = threading.Lock()

class NativeMessagingDisconnected(Exception):
    pass


def send_message(payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        with SEND_MESSAGE_LOCK:
            sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()
    except (BrokenPipeError, OSError) as exc:
        raise NativeMessagingDisconnected("Native messaging output closed.") from exc


def send_job(job_id, message_type, message, **extra):
    send_message({"jobId": job_id, "type": message_type, "message": message, **extra})


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    length = struct.unpack("<I", raw_length)[0]
    if length > MAX_NATIVE_MESSAGE_BYTES:
        raise ValueError("Native message exceeds the 1 MiB size limit.")
    payload = sys.stdin.buffer.read(length)
    if len(payload) != length:
        raise ValueError("Received a truncated native message.")
    return json.loads(payload.decode("utf-8"))

