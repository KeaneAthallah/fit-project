"""Central logging setup for the application."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """Configure root logger with console + rotating file handlers."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)

    app_log = RotatingFileHandler(logs_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    app_log.setFormatter(fmt)

    proc_log = RotatingFileHandler(
        logs_dir / "processing.log", maxBytes=10_000_000, backupCount=3, encoding="utf-8"
    )
    proc_log.setFormatter(fmt)

    err_log = RotatingFileHandler(logs_dir / "errors.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    err_log.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    err_log.setLevel(logging.ERROR)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(app_log)
    root.addHandler(proc_log)
    root.addHandler(err_log)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
