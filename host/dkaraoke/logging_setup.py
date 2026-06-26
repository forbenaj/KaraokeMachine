import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOGGER_NAME = "dkaraoke"
LOG_HANDLER_NAME = "dkaraoke-daily-file"
LOG_BACKUP_DAYS = 30
LOG_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(message)s"


def configure_logging():
    local_app_data = os.environ.get("LOCALAPPDATA")
    log_dir = Path(local_app_data) / "DKaraoKe" if local_app_data else Path.home() / ".dkaraoke"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dkaraoke.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    expected_path = str(log_path.resolve())
    for handler in logger.handlers:
        if (
            getattr(handler, "name", "") == LOG_HANDLER_NAME
            and getattr(handler, "baseFilename", "") == expected_path
        ):
            return logger, log_path

    for handler in list(logger.handlers):
        if getattr(handler, "name", "") == LOG_HANDLER_NAME:
            logger.removeHandler(handler)
            handler.close()

    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=LOG_BACKUP_DAYS,
        encoding="utf-8",
    )
    handler.name = LOG_HANDLER_NAME
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    return logger, log_path


LOGGER, LOG_PATH = configure_logging()
