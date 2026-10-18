"""Logging configuration with rolling file + console + GUI tail handler."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Callable

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE = "%H:%M:%S"





def setup_logging(log_level: str = "INFO", log_dir: str | None = None, console: bool = True) -> str:
    level = getattr(logging, str(log_level).upper(), logging.INFO)
    root = logging.getLogger("opc_mitsu")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    log_path = ""
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "opc_mitsu.log")
        fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(fh)

    # make child loggers not propagate duplicates to root
    for name in ("pymcprotocol",):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        if not lg.handlers:
            lg.addHandler(logging.NullHandler())
        lg.propagate = root.getEffectiveLevel() <= level
    return log_path


class GTailHandler(logging.Handler):
    """Bridges log records to the GUI via a thread-safe callback."""

    def __init__(self, callback: Callable[[logging.LogRecord], None] | None = None) -> None:
        super().__init__()
        self._cb = callback
        self.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE))

    def set_callback(self, callback: Callable[[logging.LogRecord], None]) -> None:
        self._cb = callback

    def emit(self, record: logging.LogRecord) -> None:
        if self._cb is None:
            return
        try:
            self._cb(record)
        except Exception:
            self.handleError(record)