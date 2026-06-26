import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure_logging():
    local_app_data = os.environ.get("LOCALAPPDATA")
    log_dir = Path(local_app_data) / "DKaraoKe" if local_app_data else Path.home() / ".dkaraoke"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dkaraoke.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    logger = logging.getLogger("dkaraoke")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger, log_path


LOGGER, LOG_PATH = configure_logging()


LOGGER, LOG_PATH = configure_logging()
