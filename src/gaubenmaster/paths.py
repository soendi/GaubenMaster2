"""Dateipfade, Logging, Einstellungen und Einzelinstanz-Sperre."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_NAME = "GaubenMaster2"
EXE_NAME = "GaubenMaster2.exe"
MUTEX_NAME = "Local\\GaubenMaster2.SingleInstance"

_LOGGER_READY = False
_MUTEX_HANDLE: int | None = None


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


def data_dir() -> Path:
    override = os.environ.get("GAUBENMASTER_DATA_DIR")
    return Path(override) if override else _local_appdata() / APP_NAME


def update_dir() -> Path:
    return data_dir() / "update"


def logs_dir() -> Path:
    return data_dir() / "logs"


def cache_file() -> Path:
    return data_dir() / "update_cache.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def log_file() -> Path:
    return logs_dir() / "app.log"


def ensure_runtime_dirs() -> None:
    for path in (data_dir(), update_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """Schreibt JSON atomar, damit ein Abbruch keine halbe Datei hinterlaesst."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_settings() -> dict[str, Any]:
    try:
        value = json.loads(settings_file().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    try:
        atomic_write_json(settings_file(), settings)
    except OSError:
        logging.getLogger(__name__).warning("Einstellungen konnten nicht gespeichert werden.")


def setup_logging() -> logging.Logger:
    global _LOGGER_READY
    logger = logging.getLogger()
    if _LOGGER_READY:
        return logger
    ensure_runtime_dirs()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_file(), maxBytes=256 * 1024, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    _LOGGER_READY = True
    return logger


def acquire_single_instance() -> bool:
    """Verhindert zwei gleichzeitig laufende Hauptfenster (Windows-Mutex)."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


def installed_exe() -> Path:
    return Path(sys.executable).resolve()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
