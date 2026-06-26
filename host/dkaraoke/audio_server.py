import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .constants import ALLOWED_ORIGINS, RANGE_RE

AUDIO_FILES = {}
AUDIO_FILES_LOCK = threading.Lock()
AUDIO_SERVER = None
AUDIO_SERVER_THREAD = None

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
