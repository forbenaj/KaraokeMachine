import os
import queue
import subprocess
import threading
import time

from .constants import ROFORMER_REMAINING_TIME_RE, ROFORMER_TOTAL_TIME_RE
from .logging_setup import LOGGER

def format_remaining_time(seconds):
    seconds = max(0, int(round(seconds)))
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def roformer_progress_from_line(line, total_seconds=None):
    total_match = ROFORMER_TOTAL_TIME_RE.search(line)
    if total_match:
        return float(total_match.group(1)), None

    remaining_match = ROFORMER_REMAINING_TIME_RE.search(line)
    if not remaining_match:
        return total_seconds, None

    remaining_seconds = max(0.0, float(remaining_match.group(1)))
    if not total_seconds or total_seconds <= 0:
        total_seconds = remaining_seconds
    if total_seconds <= 0:
        percent = 99.0
    else:
        percent = 100.0 * (1.0 - min(remaining_seconds, total_seconds) / total_seconds)
        percent = max(0.0, min(99.0, percent))
    return total_seconds, (remaining_seconds, percent)


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


def subprocess_creationflags():
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def terminate_process_tree(process, label):
    if process.poll() is not None:
        return
    LOGGER.warning("terminating timed-out process label=%s pid=%s", label, process.pid)
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except (OSError, subprocess.SubprocessError):
            LOGGER.exception("could not terminate process tree label=%s pid=%s", label, process.pid)
    try:
        process.kill()
    except OSError:
        pass


def stream_process_lines(process, label, timeout_seconds):
    """Yield merged process output without allowing a silent child to hang forever."""
    if process.stdout is None:
        raise RuntimeError(f"{label} did not expose its output stream.")

    # Lightweight test doubles commonly expose an iterator rather than a pipe.
    if not hasattr(process.stdout, "readline"):
        yield from process.stdout
        return

    lines = queue.Queue()
    finished = object()

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(finished)

    threading.Thread(
        target=read_output,
        name=f"{label.lower().replace(' ', '-')}-output",
        daemon=True,
    ).start()
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate_process_tree(process, label)
            raise TimeoutError(f"{label} timed out after {timeout_seconds // 60} minutes.")
        try:
            item = lines.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if item is finished:
            return
        yield item
