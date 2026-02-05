import datetime
import logging
import sys
from logging.handlers import BaseRotatingHandler, TimedRotatingFileHandler
from pathlib import Path


# ==================================================================================================
def get_handler(path_logs: str | Path) -> BaseRotatingHandler:
    handler = TimedRotatingFileHandler(
        path_logs,
        when="midnight",
        interval=1,
        backupCount=7,
        atTime=datetime.time.fromisoformat("04:00:00"),
        encoding="utf-8",  # Ensure file handler uses UTF-8
    )
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    return handler


# ==================================================================================================
def get_handlers(path_logs: str | Path) -> tuple[BaseRotatingHandler, logging.StreamHandler]:
    """
    Create a file handler (rotates at 4:00 AM, keeps 7 backups)
    and a colored console handler with readable delimiters.
    """
    # ---------------- File Handler ----------------
    file_handler = TimedRotatingFileHandler(
        path_logs,
        when="midnight",
        interval=1,
        backupCount=7,
        atTime=datetime.time.fromisoformat("04:00:00"),
        encoding="utf-8",  # Ensure file handler uses UTF-8
    )
    file_formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    # ---------------- Console Handler ----------------
    class ColoredFormatter(logging.Formatter):
        COLORS = {  # noqa: RUF012
            "DEBUG": "\033[36m",  # cyan
            "INFO": "\033[38;5;233m",  # light-black
            "WARNING": "\033[33m",  # Yellow
            "ERROR": "\033[31m",  # Red
            "CRITICAL": "\033[1;91m",  # Red background
        }
        RESET = "\033[0m"

        def format(self, record, min_width_name=85):
            color = self.COLORS.get(record.levelname, self.RESET)
            record.asctime = self.formatTime(record, datefmt="%H:%M:%S")
            name_aligned = f"{record.name:<{min_width_name}}"
            log_msg = (
                f"[{record.levelname}] | {record.asctime} | {name_aligned} | {record.getMessage()}"
            )
            return f"{color}{log_msg}{self.RESET}"

    console_handler = logging.StreamHandler(sys.stdout)  # Use sys.stdout explicitly
    console_formatter = ColoredFormatter()
    console_handler.setFormatter(console_formatter)

    return file_handler, console_handler


# ==================================================================================================
def install_logging_excepthook(logger: logging.Logger):
    def _hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("KeyboardInterrupt received, shutting down gracefully...")
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


# ==================================================================================================
def get_logs_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "logs"


# ==================================================================================================
def setup_logging(
    logs_path: Path, debug: bool = False, show_console: bool = True
) -> logging.Logger:
    """Set up root logger with file and console handlers."""
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler, console_handler = get_handlers(logs_path)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    if show_console:
        root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    install_logging_excepthook(root_logger)
    return root_logger
