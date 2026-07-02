import os
import queue
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .constants import ROFORMER_REMAINING_TIME_RE, ROFORMER_TOTAL_TIME_RE
from .diagnostics import record_diagnostic
from .logging_setup import LOGGER

ACTIVE_JOB_PROCESSES = {}
CANCELED_JOBS = set()
JOB_PROCESS_LOCK = threading.Lock()
ML_PROCESS_LOCK = threading.Lock()


class JobCanceled(RuntimeError):
    pass


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


def subprocess_creationflags():
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


@contextmanager
def exclusive_ml_process(label, job_id=None):
    LOGGER.info("job=%s waiting for exclusive ML process slot label=%s", job_id, label)
    with ML_PROCESS_LOCK:
        LOGGER.info("job=%s acquired exclusive ML process slot label=%s", job_id, label)
        try:
            yield
        finally:
            LOGGER.info("job=%s released exclusive ML process slot label=%s", job_id, label)


def terminate_process_tree(process, label):
    if process.poll() is not None:
        return
    LOGGER.warning("terminating timed-out process label=%s pid=%s", label, process.pid)
    record_diagnostic(
        "warning",
        "process_tree_terminated",
        "Terminating a timed-out child process.",
        details={"label": label, "pid": process.pid},
    )
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


def terminate_all_job_processes(reason):
    with JOB_PROCESS_LOCK:
        active = list(ACTIVE_JOB_PROCESSES.items())
        ACTIVE_JOB_PROCESSES.clear()
        CANCELED_JOBS.clear()
    for job_id, (process, label) in active:
        LOGGER.warning("job=%s terminating active child on host shutdown label=%s reason=%s", job_id, label, reason)
        terminate_process_tree(process, label)


def terminate_stale_dkaraoke_runners(root):
    if os.name != "nt":
        return
    root_text = str(Path(root).resolve())
    runner_names = ("roformer_runner.py", "lyrics_runner.py", "silero_vad_runner.py")
    escaped_root = root_text.replace("'", "''")
    runner_filter = " -or ".join(
        f"$_.CommandLine.Contains('{name}')" for name in runner_names
    )
    script = (
        f"$root = '{escaped_root}'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($root) -and "
        f"({runner_filter}) }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        LOGGER.exception("could not terminate stale DKaraoKe runner processes")


def register_job_process(job_id, process, label):
    if not job_id or process is None:
        return
    with JOB_PROCESS_LOCK:
        ACTIVE_JOB_PROCESSES[job_id] = (process, label)
        canceled = job_id in CANCELED_JOBS
    if canceled:
        terminate_process_tree(process, label)


def unregister_job_process(job_id, process=None):
    if not job_id:
        return
    with JOB_PROCESS_LOCK:
        current = ACTIVE_JOB_PROCESSES.get(job_id)
        removed = False
        if current and (process is None or current[0] is process):
            ACTIVE_JOB_PROCESSES.pop(job_id, None)
            removed = True
        if (removed or not current) and job_id in CANCELED_JOBS:
            CANCELED_JOBS.discard(job_id)


def cancel_job(job_id):
    if not job_id:
        return False
    with JOB_PROCESS_LOCK:
        CANCELED_JOBS.add(job_id)
        current = ACTIVE_JOB_PROCESSES.get(job_id)
    if current:
        process, label = current
        LOGGER.info("job=%s cancellation requested; terminating %s", job_id, label)
        terminate_process_tree(process, label)
        return True
    LOGGER.info("job=%s cancellation requested; no active child process", job_id)
    return False


def is_job_canceled(job_id):
    if not job_id:
        return False
    with JOB_PROCESS_LOCK:
        return job_id in CANCELED_JOBS


def raise_if_job_canceled(job_id):
    if is_job_canceled(job_id):
        raise JobCanceled("Canceled.")


def run_registered_capture(job_id, label, command, *, input_text=None, stdin=None, timeout_seconds=None, **kwargs):
    raise_if_job_canceled(job_id)
    if input_text is not None:
        stdin = subprocess.PIPE
    elif stdin is None:
        stdin = subprocess.DEVNULL
    process = subprocess.Popen(
        command,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )
    register_job_process(job_id, process, label)
    try:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_process_tree(process, label)
            try:
                process.communicate(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            raise
        raise_if_job_canceled(job_id)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        unregister_job_process(job_id, process)


def stream_process_lines(process, label, timeout_seconds, job_id=None):
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
        raise_if_job_canceled(job_id)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record_diagnostic(
                "error",
                "process_timeout",
                f"{label} timed out after {timeout_seconds // 60} minutes.",
                details={"label": label, "timeoutSeconds": timeout_seconds},
            )
            terminate_process_tree(process, label)
            raise TimeoutError(f"{label} timed out after {timeout_seconds // 60} minutes.")
        try:
            item = lines.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if item is finished:
            return
        yield item
