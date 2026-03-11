import logging
import sys
from typing import Optional

__all__ = ["logger", "setup_logger", "progress"]

COLORS = {
    "DEBUG": "\033[0;36m",
    "INFO": "\033[0;32m",
    "WARNING": "\033[0;33m",
    "ERROR": "\033[0;31m",
    "CRITICAL": "\033[0;35m",
    "RESET": "\033[0m",
}


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        formatted = super().format(record)
        color = COLORS.get(record.levelname)
        if color:
            return f"{color}{formatted}{COLORS['RESET']}"
        return formatted


def setup_logger(
    name: str = "youtu-graphrag",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    formatter = ColoredFormatter(
        fmt="[%(asctime)s] %(levelname)-8s %(module)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="[%(asctime)s] %(levelname)-8s %(module)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()


def progress(stage: str, message: str, *, done: bool | None = None):
    suffix = ""
    if done is True:
        suffix = " ✅"
    elif done is False:
        suffix = " ❌"
    logger.info(f"[{stage}] {message}{suffix}")
