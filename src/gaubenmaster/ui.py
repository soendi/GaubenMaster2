"""Benutzeroberflaeche. Alle Netzwerk- und Installationsarbeit laeuft im Thread."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .paths import (
    cache_file,
    data_dir,
    installed_exe,
    is_frozen,
    load_settings,
    save_settings,
    update_dir,
)
from .updater import (
    UpdateError,
    UpdateInfo,
    cache_is_fresh,
    download_and_verify,
    fetch_latest_release,
    is_newer,
    launch_update_helper,
    read_cache,
    save_cache,
)
from .version import __version__

log = logging.getLogger(__name__)


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple] = queue.Queue()
        self.info: UpdateInfo | None = None
        self.installer: Path | None = None
        self.checking = False
        self.downloading = False
        self.prompted_version: str | None = None

        root.title("GaubenMaster2")
        root.minsize(620, 400)
        root.geometry(str(load_settings().get("geometry", "820x520")))
        root.protocol("WM_DELETE_WINDOW", self._close)

        self._build_menu()
        self._build_layout()
        root.after(120, self._poll_events)
        root.after(500, self._startup_check)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Datenordner öffnen", command=self._open_data_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self._close)
        menu.add_cascade(label="Datei", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Nach Updates suchen", command=self._manual_check)
        help_menu.add_command(label="Über GaubenMaster2", command=self._about)
        menu.add_cascade(label="Hilfe", menu=help_menu)
        self.root.config(menu=menu)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="GaubenMaster2", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text=f"Version {__version__}", foreground="#555").grid(
            row=1, column=0, sticky="w"
        )

        content = ttk.LabelFrame(outer, text="Fachfunktionen", padding=16)
        content.grid(row=1, column=0, sticky="nsew")
        ttk.Label(
            content,
            text=(
                "Das Grundgerüst, die Versionsverwaltung und das automatische "
                "Update über GitHub sind einsatzbereit.\n\n"
                "Die Gauben-Berechnung und -Zeichnung wird hier ergänzt."
            ),
            justify="left",
            wraplength=680,
        ).pack(anchor="w")
        ttk.Button(content, text="Über diese Anwendung", command=self._about).pack(
            anchor="w", pady=(16, 0)
        )

        footer = ttk.Frame(outer)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, text=f"Version {__version__}")
        self.status.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100, length=170)
        self.progress.grid(row=0, column=1, padx=10, sticky="e")
        self.progress.grid_remove()
        self.update_button = ttk.Button(
            footer, text="Nach Updates suchen", command=self._manual_check
        )
        self.update_button.grid(row=0, column=2, sticky="e")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    self._set_status(event[1])
                elif kind == "check_result":
                    self._on_check_result(event[1], event[2], event[3])
                elif kind == "progress":
                    self._on_progress(event[1], event[2])
                elif kind == "download_done":
                    self._on_download_done(event[1])
                elif kind == "download_error":
                    self._on_download_error(event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)

    def _startup_check(self) -> None:
        checked, info = read_cache(cache_file())
        if cache_is_fresh(checked):
            if info and is_newer(info.version, __version__):
                self._on_update_found(info, startup=True)
            else:
                self._set_status(f"Version {__version__} ist aktuell.")
            return
        self._start_check(silent=True)

    def _manual_check(self) -> None:
        if self.checking or self.downloading:
            return
        self._start_check(silent=False)

    def _start_check(self, silent: bool) -> None:
        self.checking = True
        self.update_button.state(["disabled"])
        self._set_status("Suche nach Updates …")
        threading.Thread(
            target=self._check_worker, args=(silent,), daemon=True, name="update-check"
        ).start()

    def _check_worker(self, silent: bool) -> None:
        try:
            info = fetch_latest_release(__version__)
            save_cache(cache_file(), info)
            self.events.put(("check_result", info, None, silent))
        except UpdateError as exc:
            log.warning("Update-Prüfung fehlgeschlagen: %s", exc)
            self.events.put(("check_result", None, str(exc), silent))
        except Exception:
            log.exception("Unerwarteter Fehler bei der Update-Prüfung")
            self.events.put(
                ("check_result", None, "Die Update-Prüfung ist fehlgeschlagen.", silent)
            )

    def _on_check_result(
        self, info: UpdateInfo | None, error: str | None, silent: bool
    ) -> None:
        self.checking = False
        self.update_button.state(["!disabled"])
        if error:
            self._set_status("Update-Prüfung nicht möglich (offline?).")
            if not silent:
                messagebox.showwarning(
                    "Update-Prüfung",
                    f"Es konnte keine Verbindung zu GitHub hergestellt werden.\n\n{error}\n\n"
                    "Die Anwendung läuft unverändert weiter.",
                    parent=self.root,
                )
            return
        if info:
            self._on_update_found(info, startup=silent)
            return
        self.info = None
        self.installer = None
        self._set_status(f"Version {__version__} ist aktuell.")
        if not silent:
            messagebox.showinfo(
                "Update-Prüfung",
                f"Sie verwenden bereits die neueste Version ({__version__}).",
                parent=self.root,
            )

    def _on_update_found(self, info: UpdateInfo, startup: bool) -> None:
        self.info = info
        self._set_status(f"Update {info.version} ist verfügbar.")
        self.update_button.config(text=f"Update {info.version} installieren")
        if self.prompted_version == info.version:
            return
        self.prompted_version = info.version
        notes = info.notes.strip()
        if len(notes) > 700:
            notes = notes[:700] + " …"
        text = (
            f"Version {info.version} ist verfügbar (installiert: {__version__}).\n\n"
            f"{notes}\n\nJetzt herunterladen und installieren?"
        ).strip()
        if messagebox.askyesno("Update verfügbar", text, parent=self.root):
            self._download(info)

    def _download(self, info: UpdateInfo) -> None:
        if self.downloading:
            return
        self.downloading = True
        self.info = info
        self.update_button.state(["disabled"])
        self.progress.config(mode="determinate", value=0)
        self.progress.grid()
        self._set_status(f"Lade Update {info.version} herunter …")
        threading.Thread(
            target=self._download_worker, args=(info,), daemon=True, name="update-download"
        ).start()

    def _download_worker(self, info: UpdateInfo) -> None:
        last = [0.0]
        import time

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if done == total or now - last[0] >= 0.15:
                last[0] = now
                self.events.put(("progress", done, total))

        try:
            path = download_and_verify(
                info, update_dir(), progress=progress, timeout=30.0
            )
            self.events.put(("download_done", path))
        except UpdateError as exc:
            log.warning("Update-Download fehlgeschlagen: %s", exc)
            self.events.put(("download_error", str(exc)))
        except Exception:
            log.exception("Unerwarteter Fehler beim Update-Download")
            self.events.put(
                ("download_error", "Der Download ist unerwartet fehlgeschlagen.")
            )

    def _on_progress(self, done: int, total: int) -> None:
        percent = (done * 100 / total) if total else 0
        self.progress.config(value=max(0, min(100, percent)))

    def _on_download_done(self, path: Path) -> None:
        self.downloading = False
        self.installer = Path(path)
        self.progress.grid_remove()
        self.update_button.state(["!disabled"])
        self._set_status(f"Update {self.info.version if self.info else ''} ist geprüft.")
        if not is_frozen():
            messagebox.showinfo(
                "Update heruntergeladen",
                "Das Update wurde heruntergeladen und die Prüfsumme stimmt.\n\n"
                "Die automatische Installation ist nur in der installierten "
                "Version aktiv.",
                parent=self.root,
            )
            return
        if messagebox.askyesno(
            "Update installieren",
            "Das Update ist heruntergeladen und geprüft.\n\n"
            "Die Anwendung wird jetzt beendet, das Update installiert und "
            "anschließend neu gestartet. Benutzerdaten bleiben erhalten.\n\n"
            "Jetzt installieren?",
            parent=self.root,
        ):
            self._install()

    def _install(self) -> None:
        if not self.installer or not self.info:
            return
        if not is_frozen():
            messagebox.showinfo(
                "Update",
                "Die automatische Installation ist nur in der installierten Version möglich.",
                parent=self.root,
            )
            return
        try:
            save_settings({"geometry": self.root.geometry()})
            launch_update_helper(
                self.installer,
                installed_exe(),
                os.getpid(),
                data_dir(),
                restart=True,
            )
        except (UpdateError, OSError) as exc:
            log.error("Update-Helfer konnte nicht gestartet werden: %s", exc)
            messagebox.showerror(
                "Update",
                f"Das Update konnte nicht vorbereitet werden.\n\n{exc}\n\n"
                "Die aktuelle Version bleibt unverändert.",
                parent=self.root,
            )
            return
        self._set_status("Update wird installiert, die Anwendung startet neu …")
        self.root.after(250, self.root.destroy)

    def _on_download_error(self, message: str) -> None:
        self.downloading = False
        self.progress.grid_remove()
        self.update_button.state(["!disabled"])
        self._set_status("Update-Download fehlgeschlagen.")
        messagebox.showerror(
            "Update",
            f"Das Update konnte nicht geladen werden.\n\n{message}\n\n"
            "Die aktuelle Version bleibt unverändert.",
            parent=self.root,
        )

    def _open_data_dir(self) -> None:
        path = data_dir()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError:
            messagebox.showinfo("Datenordner", str(path), parent=self.root)

    def _about(self) -> None:
        state = "installiert" if is_frozen() else "Entwicklung"
        messagebox.showinfo(
            "Über GaubenMaster2",
            f"GaubenMaster2\nVersion {__version__}\n\n"
            f"Ausführung: {state}\nDatenordner: {data_dir()}",
            parent=self.root,
        )

    def _close(self) -> None:
        try:
            save_settings({"geometry": self.root.geometry()})
        finally:
            self.root.destroy()


def run() -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()
