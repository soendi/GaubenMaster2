from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

_START = time.perf_counter()


def _option(name: str) -> str | None:
    argv = sys.argv
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def _write_json(path: str, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_probe(path: str) -> int:
    from .paths import setup_logging
    from .ui import _enable_dpi_awareness
    from .version import __version__

    setup_logging()
    _enable_dpi_awareness()
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    elapsed = (time.perf_counter() - _START) * 1000
    root.destroy()
    _write_json(path, {"ok": True, "version": __version__, "startup_ms": round(elapsed, 1)})
    return 0


def _check_payload(info: Any, error: str | None = None) -> dict[str, Any]:
    from .version import __version__

    payload: dict[str, Any] = {
        "ok": error is None,
        "current": __version__,
        "available": bool(info),
    }
    if error:
        payload["error"] = error
    if info:
        payload.update(
            {
                "version": info.version,
                "tag": info.tag,
                "notes": info.notes,
                "installer": info.installer_name,
                "size": info.installer_size,
            }
        )
    return payload


def _run_check(path: str) -> int:
    from .paths import setup_logging
    from .updater import UpdateError, fetch_latest_release

    setup_logging()
    try:
        info = fetch_latest_release()
    except UpdateError as exc:
        logging.getLogger(__name__).warning("Update-Prüfung: %s", exc)
        _write_json(path, _check_payload(None, str(exc)))
        return 0
    _write_json(path, _check_payload(info))
    return 0


def _run_install(path: str, restart: bool) -> int:
    from .paths import data_dir, installed_exe, is_frozen, setup_logging, update_dir
    from .updater import (
        UpdateError,
        download_and_verify,
        fetch_latest_release,
        launch_update_helper,
    )

    setup_logging()
    log = logging.getLogger(__name__)
    try:
        info = fetch_latest_release()
        if not info:
            _write_json(path, _check_payload(None))
            return 0
        if not is_frozen():
            raise UpdateError("Die automatische Installation ist nur installiert möglich.")
        installer = download_and_verify(info, update_dir())
        launch_update_helper(
            installer,
            installed_exe(),
            os.getpid(),
            data_dir(),
            restart=restart,
        )
        payload = _check_payload(info)
        payload["downloaded"] = str(installer)
        payload["restart"] = restart
        _write_json(path, payload)
        log.info("Update %s vorbereitet.", info.version)
        return 0
    except UpdateError as exc:
        log.warning("Update-Installation: %s", exc)
        _write_json(path, _check_payload(None, str(exc)))
        return 2
    except Exception as exc:
        log.exception("Unerwarteter Fehler bei der Update-Installation")
        _write_json(path, _check_payload(None, f"Unerwarteter Fehler: {exc}"))
        return 3


def _run_gui() -> int:
    from .paths import acquire_single_instance, log_file, setup_logging
    from .version import __version__

    setup_logging()
    logging.getLogger(__name__).info("Start Version %s", __version__)
    if not acquire_single_instance():
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("GaubenMaster2", "GaubenMaster2 läuft bereits.")
            root.destroy()
        except Exception:
            pass
        return 0
    try:
        from .ui import run

        run()
        return 0
    except Exception:
        logging.getLogger(__name__).exception("Start der Oberfläche fehlgeschlagen")
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "GaubenMaster2",
                "Die Anwendung konnte nicht gestartet werden.\n\n"
                f"Details stehen in der Protokolldatei:\n{log_file()}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


def main() -> int:
    version_path = _option("--version-out")
    if version_path:
        from .version import __version__

        _write_json(version_path, {"ok": True, "version": __version__})
        return 0

    probe_path = _option("--probe-out")
    if probe_path:
        return _run_probe(probe_path)

    check_path = _option("--check-update-out")
    if check_path:
        return _run_check(check_path)

    install_path = _option("--install-update-out")
    if install_path:
        return _run_install(install_path, restart="--no-restart" not in sys.argv)

    return _run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
