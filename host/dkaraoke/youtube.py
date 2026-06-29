import shutil
import tempfile
import uuid
from pathlib import Path

from .constants import AUTH_ERROR_MARKERS

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
