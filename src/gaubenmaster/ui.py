"""Benutzeroberflaeche: Eingaben, Zeichnung, Hoehenteilung und Updates."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .formatting import format_area, format_number
from .geometry import (
    GeometryError,
    HeightName,
    Part,
    SplitMode,
    Triangle,
    calculate_triangle,
)
from .partdraw import PartsList
from .paths import (
    cache_file,
    data_dir,
    installed_exe,
    is_frozen,
    load_settings,
    save_settings,
    update_dir,
)
from .pdfexport import export_pdf
from .plot import DisplayOptions, TriangleView
from .updater import (
    REPO,
    UpdateError,
    UpdateInfo,
    cache_is_fresh,
    download_and_verify,
    fetch_latest_release,
    is_newer,
    launch_update_helper,
    normalize_repo,
    read_cache,
    save_cache,
)
from .version import __version__

log = logging.getLogger(__name__)

DEFAULT_REPO_URL = f"https://github.com/{REPO}"
DEFAULT_INTERVAL_HOURS = 6.0
VALID_COLOR = "#137333"
INVALID_COLOR = "#b3261e"


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def _parse_number(value: str) -> float:
    text = value.strip()
    if not text:
        raise GeometryError("Bitte alle Zahlenfelder ausfüllen.")
    try:
        return float(text.replace(",", "."))
    except ValueError:
        raise GeometryError(f"„{text}“ ist keine gültige Zahl.") from None


class UpdateToast(tk.Toplevel):
    """Kleine Benachrichtigung unten rechts, die sich nach 30 s schliesst."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        message: str,
        on_install,
        timeout_ms: int = 30_000,
    ) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self._on_install = on_install
        self._closed = False
        self._after_id: str | None = None

        border = tk.Frame(self, background="#17324d", padx=1, pady=1)
        border.pack(fill="both", expand=True)
        body = tk.Frame(border, background="#ffffff", padx=14, pady=12)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text=title,
            background="#ffffff",
            foreground="#12263f",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            body,
            text=message,
            background="#ffffff",
            foreground="#3d4b5c",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
            wraplength=330,
        ).pack(fill="x", pady=(5, 10))
        buttons = tk.Frame(body, background="#ffffff")
        buttons.pack(fill="x")
        tk.Button(
            buttons,
            text="Installieren",
            command=self._install,
            background="#1857a4",
            foreground="#ffffff",
            activebackground="#12457f",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2",
        ).pack(side="right")
        tk.Button(
            buttons,
            text="Später",
            command=self.close,
            background="#eef2f7",
            foreground="#12263f",
            activebackground="#dfe7f1",
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2",
        ).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _event: self.close())
        self._after_id = self.after(timeout_ms, self.close)
        self.update_idletasks()
        self._place()

    def _place(self) -> None:
        try:
            root = self.master.winfo_toplevel()
            width = self.winfo_reqwidth()
            height = self.winfo_reqheight()
            x = root.winfo_rootx() + root.winfo_width() - width - 24
            y = root.winfo_rooty() + root.winfo_height() - height - 24
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

    def _install(self) -> None:
        self.close()
        self._on_install()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        try:
            self.destroy()
        except tk.TclError:
            pass


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Einstellungen")
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

        self.auto_var = tk.BooleanVar(value=app.auto_update)
        self.interval_var = tk.StringVar(value=format_number(app.interval_hours, 1))
        self.repo_var = tk.StringVar(value=f"https://github.com/{app.repo}")

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Updates", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Checkbutton(
            outer,
            text="Beim Start automatisch nach Updates suchen",
            variable=self.auto_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(outer, text="Prüfintervall (Stunden)").grid(
            row=2, column=0, sticky="w", pady=3
        )
        ttk.Spinbox(
            outer,
            from_=1,
            to=168,
            increment=1,
            width=8,
            textvariable=self.interval_var,
        ).grid(row=2, column=1, sticky="e", pady=3)
        ttk.Label(outer, text="Repository-URL").grid(
            row=3, column=0, sticky="w", pady=(10, 3)
        )
        ttk.Entry(outer, width=44, textvariable=self.repo_var).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=3
        )
        ttk.Label(
            outer,
            text="Unterstützt owner/repo oder https://github.com/owner/repo",
            foreground="#5b6878",
        ).grid(row=5, column=0, columnspan=2, sticky="w")

        buttons = ttk.Frame(outer)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(buttons, text="Speichern", command=self._save).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _save(self) -> None:
        try:
            interval = _parse_number(self.interval_var.get())
            if not 1 <= interval <= 168:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Einstellungen",
                "Das Prüfintervall muss zwischen 1 und 168 Stunden liegen.",
                parent=self,
            )
            return
        try:
            repo = normalize_repo(self.repo_var.get())
        except UpdateError as exc:
            messagebox.showerror("Einstellungen", str(exc), parent=self)
            return
        self.app.apply_settings(
            auto_update=self.auto_var.get(),
            interval_hours=interval,
            repo=repo,
        )
        self.destroy()


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple] = queue.Queue()
        self.info: UpdateInfo | None = None
        self.installer: Path | None = None
        self.checking = False
        self.downloading = False
        self.toast: UpdateToast | None = None
        self.triangle: Triangle | None = None
        self.parts: list[Part] = []
        self.display_options = DisplayOptions()
        self._syncing_zoom = False

        settings = load_settings()
        self.auto_update = bool(settings.get("auto_update", True))
        try:
            self.interval_hours = float(settings.get("interval_hours", DEFAULT_INTERVAL_HOURS))
        except (TypeError, ValueError):
            self.interval_hours = DEFAULT_INTERVAL_HOURS
        self.interval_hours = max(1.0, min(168.0, self.interval_hours))
        try:
            self.repo = normalize_repo(str(settings.get("repo", DEFAULT_REPO_URL)))
        except UpdateError:
            self.repo = REPO

        root.title("GaubenMaster2 – Gaubenberechnung")
        root.geometry("1400x900")
        root.minsize(1100, 700)
        root.protocol("WM_DELETE_WINDOW", self._close)

        self._build_menu()
        self._build_layout()
        self._apply_display()
        self._bind_keys()
        root.after(120, self._poll_events)
        root.after(2000, self._startup_check)
        root.after(200, self._calculate)

    # ------------------------------------------------------------------ UI
    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(
            label="Neu", accelerator="Strg+N", command=self._reset
        )
        file_menu.add_command(
            label="Datenordner öffnen", command=self._open_data_dir
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Beenden", accelerator="Alt+F4", command=self._close
        )
        menu.add_cascade(label="Datei", menu=file_menu)

        export_menu = tk.Menu(menu, tearoff=False)
        export_menu.add_command(
            label="Als PDF exportieren...", command=self._export_pdf
        )
        menu.add_cascade(label="Export", menu=export_menu)

        extras_menu = tk.Menu(menu, tearoff=False)
        extras_menu.add_command(
            label="Nach Updates suchen", command=self._manual_check
        )
        extras_menu.add_command(
            label="Repository öffnen", command=self._open_repository
        )
        extras_menu.add_separator()
        extras_menu.add_command(
            label="Einstellungen", command=self._open_settings
        )
        menu.add_cascade(label="Extras", menu=extras_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Über GaubenMaster2", command=self._about)
        help_menu.add_command(label="Hilfe", command=self._help)
        menu.add_cascade(label="Hilfe", menu=help_menu)
        self.root.config(menu=menu)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, minsize=240)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        self.left = ttk.Frame(outer, width=240)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left.grid_propagate(False)
        self.left.pack_propagate(False)
        self.left_body = ttk.Frame(self.left)
        self.left_body.pack(side="top", fill="both", expand=True)
        self.left_canvas = tk.Canvas(
            self.left_body,
            width=240,
            highlightthickness=0,
            borderwidth=0,
            background=self.root.cget("background"),
        )
        self.left_scrollbar = ttk.Scrollbar(
            self.left_body, orient="vertical", command=self.left_canvas.yview
        )
        self.left_scrollbar.pack(side="right", fill="y")
        self.left_canvas.pack(side="left", fill="both", expand=True)
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        self.left_content = ttk.Frame(self.left_canvas)
        self.left_window = self.left_canvas.create_window(
            (0, 0), window=self.left_content, anchor="nw"
        )
        self.left_content.bind(
            "<Configure>",
            lambda _event: self.left_canvas.configure(
                scrollregion=self.left_canvas.bbox("all")
            ),
        )
        self.left_canvas.bind(
            "<Configure>",
            lambda event: self.left_canvas.itemconfigure(
                self.left_window, width=event.width
            ),
        )
        self.left_canvas.bind("<MouseWheel>", self._scroll_left)
        self.left_content.bind("<MouseWheel>", self._scroll_left)

        center = ttk.Frame(outer)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)
        ttk.Label(
            center,
            text="Ziehen = verschieben   ·   Strg+Ziehen = drehen   ·   Mausrad = zoomen",
            foreground="#5b6878",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.view = TriangleView(center)
        self.view.grid(row=1, column=0, sticky="nsew")
        self.view.on_hover = self._on_part_hover
        self.view.on_zoom = self._on_view_zoom

        self.parts_panel = ttk.LabelFrame(outer, text="Einzelteile", padding=8)
        self.parts_panel.grid(row=0, column=2, sticky="nsew", padx=(12, 0))
        self.parts_panel.columnconfigure(0, weight=1)
        self.parts_panel.rowconfigure(1, weight=1)
        self.hover_label = ttk.Label(
            self.parts_panel,
            text="Mausrad = scrollen · Doppelklick = Großansicht",
            foreground="#5b6878",
            wraplength=340,
        )
        self.hover_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.parts_list = PartsList(self.parts_panel)
        self.parts_list.grid(row=1, column=0, sticky="nsew")
        self.parts_panel.grid_remove()

        self._build_left_panel()
        self._bind_left_scroll(self.left_content)
        self._build_footer()

    def _build_left_panel(self) -> None:
        header = ttk.Frame(self.left_content)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(
            header, text="GaubenMaster2", font=("Segoe UI", 19, "bold")
        ).pack(anchor="w")
        ttk.Label(
            header, text=f"Version {__version__}", foreground="#5b6878"
        ).pack(anchor="w")

        input_frame = ttk.LabelFrame(
            self.left_content, text="Seitenlängen (cm)", padding=8
        )
        input_frame.pack(fill="x", pady=(0, 6))
        self.side_vars: dict[str, tk.StringVar] = {}
        for index, (name, value) in enumerate((("a", "3,0"), ("b", "4,0"), ("c", "5,0"))):
            ttk.Label(input_frame, text=f"Seite {name}").grid(
                row=index, column=0, sticky="w", pady=2
            )
            variable = tk.StringVar(value=value)
            self.side_vars[name] = variable
            entry = ttk.Entry(
                input_frame,
                textvariable=variable,
                width=12,
                justify="right",
            )
            entry.grid(row=index, column=1, sticky="e", padx=(10, 6), pady=2)
            ttk.Label(input_frame, text="cm").grid(row=index, column=2, sticky="w")
            variable.trace_add("write", lambda *_args: self._live_validate())
            if name == "a":
                self.first_entry = entry
        input_frame.columnconfigure(1, weight=1)

        self.validation = ttk.Label(
            input_frame, text="", wraplength=170, justify="left"
        )
        self.validation.grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 2)
        )

        buttons = ttk.Frame(input_frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Berechnen", command=self._calculate).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(buttons, text="Zurücksetzen", command=self._reset).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )
        ttk.Button(
            input_frame, text="Ansicht zurücksetzen", command=self.view.reset_view
        ).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        height_frame = ttk.LabelFrame(
            self.left_content, text="Höhen-Teilung", padding=8
        )
        height_frame.pack(fill="x", pady=(0, 6))
        self.height_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            height_frame,
            text="Höhen-Teilung anzeigen",
            variable=self.height_var,
            command=self._height_toggle,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        ttk.Label(height_frame, text="Höhe").grid(row=1, column=0, sticky="w", pady=2)
        self.height_choice = tk.StringVar(value="ha (Seite a)")
        self.height_combo = ttk.Combobox(
            height_frame,
            textvariable=self.height_choice,
            values=("ha (Seite a)", "hb (Seite b)", "hc (Seite c)"),
            state="readonly",
            width=15,
        )
        self.height_combo.grid(row=1, column=1, sticky="e", pady=2)
        self.height_combo.bind("<<ComboboxSelected>>", lambda _event: self._height_changed())

        self.mode_var = tk.StringVar(value="count")
        modes = ttk.Frame(height_frame)
        modes.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        ttk.Radiobutton(
            modes,
            text="In n Teile teilen",
            variable=self.mode_var,
            value="count",
            command=self._mode_changed,
        ).pack(anchor="w")
        ttk.Radiobutton(
            modes,
            text="Teile à n cm",
            variable=self.mode_var,
            value="length",
            command=self._mode_changed,
        ).pack(anchor="w")

        self.param_label = ttk.Label(height_frame, text="Anzahl Teile")
        self.param_label.grid(row=3, column=0, sticky="w", pady=2)
        self.param_var = tk.StringVar(value="4")
        self.param_spin = ttk.Spinbox(
            height_frame,
            from_=2,
            to=20,
            increment=1,
            width=8,
            textvariable=self.param_var,
            command=self._height_changed,
        )
        self.param_spin.grid(row=3, column=1, sticky="e", pady=2)
        self.param_var.trace_add("write", lambda *_args: self._schedule_height())

        ttk.Label(
            height_frame, text="Einzelteil-Zuschnitt", font=("Segoe UI", 9, "bold")
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.extra_vars: dict[str, tk.StringVar] = {}
        for index, (key, label) in enumerate(
            (
                ("length_extra", "Länge + (cm)"),
                ("fold_front", "Falz vorne (cm)"),
                ("fold_back", "Falz hinten (cm)"),
            ),
            start=5,
        ):
            ttk.Label(height_frame, text=label).grid(
                row=index, column=0, sticky="w", pady=1
            )
            variable = tk.StringVar(value="0,0")
            self.extra_vars[key] = variable
            ttk.Spinbox(
                height_frame,
                from_=0,
                to=50,
                increment=0.1,
                width=8,
                textvariable=variable,
                command=self._height_changed,
            ).grid(row=index, column=1, sticky="e", pady=1)
            variable.trace_add("write", lambda *_args: self._schedule_height())
        self.height_status = ttk.Label(
            height_frame, text="", foreground="#5b6878", wraplength=170
        )
        self.height_status.grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        display_frame = ttk.LabelFrame(
            self.left_content, text="Anzeige", padding=6
        )
        display_frame.pack(fill="x", pady=(0, 4))
        display_frame.columnconfigure(1, weight=1)

        ttk.Label(display_frame, text="Zoomfaktor").grid(
            row=0, column=0, sticky="w", pady=1
        )
        self.zoom_var = tk.StringVar(value="1,00")
        self.zoom_var.trace_add("write", lambda *_args: self._zoom_field_changed())
        ttk.Spinbox(
            display_frame,
            from_=0.25,
            to=8.0,
            increment=0.25,
            width=7,
            textvariable=self.zoom_var,
        ).grid(row=0, column=1, sticky="e", pady=1)

        ttk.Label(display_frame, text="Schriftgrösse").grid(
            row=1, column=0, sticky="w", pady=1
        )
        self.font_var = tk.StringVar(value="9")
        self.font_var.trace_add("write", lambda *_args: self._display_changed())
        ttk.Spinbox(
            display_frame,
            from_=4,
            to=40,
            increment=1,
            width=7,
            textvariable=self.font_var,
        ).grid(row=1, column=1, sticky="e", pady=1)

        self.option_vars: dict[str, tk.BooleanVar] = {}
        options = (
            ("main_dimensions", "Hauptdreieck Aussenmass"),
            ("main_angles", "Hauptdreieck Winkelmass"),
            ("main_angle_arcs", "Hauptdreieck Winkelkreise"),
            ("part_dimensions", "Einzelteile Aussenmass"),
            ("part_angles", "Einzelteile Winkelmass"),
            ("part_areas", "Einzelteile Fläche"),
            ("part_numbers", "Einzelteile Teil-Nr."),
            ("height", "Höhe"),
        )
        for index, (key, label) in enumerate(options, start=2):
            variable = tk.BooleanVar(value=True)
            self.option_vars[key] = variable
            ttk.Checkbutton(
                display_frame,
                text=label,
                variable=variable,
                command=self._display_changed,
            ).grid(row=index, column=0, columnspan=2, sticky="w")

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root, padding=(14, 6, 14, 8))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, minsize=110)
        self.status = ttk.Label(footer, text="Bereit.")
        self.status.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(
            footer, mode="determinate", maximum=100, length=96
        )
        self.progress.grid(row=0, column=1, padx=6, sticky="e")
        self.progress.grid_remove()
        self.activity = ttk.Label(
            footer, text=f"Version {__version__}", foreground="#5b6878"
        )
        self.activity.grid(row=0, column=2, sticky="e")

    def _bind_keys(self) -> None:
        self.root.bind("<Control-n>", lambda _event: self._reset())
        self.root.bind("<Control-N>", lambda _event: self._reset())
        self.root.bind("<F5>", lambda _event: self._calculate())
        self.root.bind("<Return>", lambda _event: self._calculate())

    # --------------------------------------------------------------- Anzeige
    def _scroll_left(self, event: tk.Event) -> str:
        self.left_canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"

    def _bind_left_scroll(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll_left)
        for child in widget.winfo_children():
            self._bind_left_scroll(child)

    def _zoom_field_changed(self) -> None:
        if self._syncing_zoom:
            return
        self._apply_display()

    def _on_view_zoom(self, zoom: float) -> None:
        self._syncing_zoom = True
        try:
            self.zoom_var.set(format_number(zoom))
        finally:
            self._syncing_zoom = False

    def _display_changed(self) -> None:
        self._apply_display()

    def _apply_display(self) -> None:
        try:
            zoom = max(0.25, min(8.0, float(self.zoom_var.get().replace(",", "."))))
        except ValueError:
            zoom = self.view.zoom
        try:
            font_size = int(round(float(self.font_var.get().replace(",", "."))))
        except ValueError:
            font_size = self.display_options.font_size
        font_size = max(4, min(40, font_size))
        self.display_options = DisplayOptions(
            **{
                key: variable.get()
                for key, variable in self.option_vars.items()
            },
            font_size=font_size,
        )
        self.view.set_zoom(zoom)
        self.view.set_display_options(self.display_options)
        self.parts_list.set_display_options(self.display_options)

    # ------------------------------------------------------------ Berechnung
    def _read_sides(self) -> tuple[float, float, float]:
        return (
            _parse_number(self.side_vars["a"].get()),
            _parse_number(self.side_vars["b"].get()),
            _parse_number(self.side_vars["c"].get()),
        )

    def _live_validate(self) -> None:
        try:
            triangle = calculate_triangle(*self._read_sides())
        except (ValueError, GeometryError) as exc:
            self._set_validation(False, str(exc))
            return
        self._set_validation(
            True,
            f"Gültiges Dreieck\nFläche {format_area(triangle.area)}",
        )

    def _set_validation(self, valid: bool, message: str) -> None:
        self.validation.configure(
            text=("✓ " if valid else "✗ ") + message,
            foreground=VALID_COLOR if valid else INVALID_COLOR,
        )

    def _calculate(self) -> None:
        try:
            triangle = calculate_triangle(*self._read_sides())
        except (ValueError, GeometryError) as exc:
            self._set_validation(False, str(exc))
            self.first_entry.focus_set()
            return
        self.triangle = triangle
        self._set_validation(
            True,
            f"Gültiges Dreieck\nFläche {format_area(triangle.area)}",
        )
        self.status.configure(
            text=(
                f"a={format_number(triangle.a)} cm   "
                f"b={format_number(triangle.b)} cm   "
                f"c={format_number(triangle.c)} cm   |   "
                f"α={format_number(triangle.alpha)}°   "
                f"β={format_number(triangle.beta)}°   "
                f"γ={format_number(triangle.gamma)}°   |   "
                f"A={format_area(triangle.area)}"
            )
        )
        self._rebuild_view()

    def _height_name(self) -> HeightName:
        text = self.height_choice.get().strip().lower()
        name = text[:2]
        return name if name in ("ha", "hb", "hc") else "ha"  # type: ignore[return-value]

    def _split_mode(self) -> SplitMode:
        return "length" if self.mode_var.get() == "length" else "count"

    def _split_value(self) -> float:
        return _parse_number(self.param_var.get())

    def _extras(self) -> tuple[float, float, float]:
        try:
            return (
                max(0.0, _parse_number(self.extra_vars["length_extra"].get())),
                max(0.0, _parse_number(self.extra_vars["fold_front"].get())),
                max(0.0, _parse_number(self.extra_vars["fold_back"].get())),
            )
        except ValueError:
            return 0.0, 0.0, 0.0

    def _build_parts(self) -> list[Part]:
        self.parts = []
        if not self.triangle or not self.height_var.get():
            self.height_status.configure(text="", foreground="#5b6878")
            return []
        try:
            self.parts = self.triangle.split_height(
                self._height_name(), self._split_mode(), self._split_value()
            )
        except (ValueError, GeometryError) as exc:
            self.height_status.configure(text=f"✗ {exc}", foreground=INVALID_COLOR)
            return []
        self.height_status.configure(
            text=f"✓ {len(self.parts)} Teile berechnet", foreground=VALID_COLOR
        )
        return self.parts

    def _rebuild_view(self) -> None:
        if not self.height_var.get():
            self.parts = []
            self.height_status.configure(text="", foreground="#5b6878")
        else:
            self._build_parts()
        self.view.set_data(
            self.triangle,
            self.parts,
            self._height_name(),
            bool(self.height_var.get()),
        )
        self._show_parts_panel(bool(self.height_var.get()))
        self.parts_list.set_data(
            self.triangle,
            self.parts,
            self._height_name(),
            self._extras(),
        )

    def _height_toggle(self) -> None:
        self._rebuild_view()

    def _height_changed(self) -> None:
        if self.triangle:
            self._rebuild_view()

    def _schedule_height(self) -> None:
        if not self.triangle:
            return
        if hasattr(self, "_height_job"):
            try:
                self.root.after_cancel(self._height_job)
            except tk.TclError:
                pass
        self._height_job = self.root.after(220, self._height_changed)

    def _mode_changed(self) -> None:
        if self._split_mode() == "count":
            self.param_label.configure(text="Anzahl Teile")
            self.param_spin.configure(from_=2, to=20, increment=1)
            self.param_var.set("4")
        else:
            self.param_label.configure(text="Teil-Länge (cm)")
            self.param_spin.configure(from_=0.1, to=50, increment=0.1)
            self.param_var.set("2,0")
        self._height_changed()

    def _show_parts_panel(self, visible: bool) -> None:
        if visible:
            self.parts_panel.grid()
            outer = self.parts_panel.master
            if isinstance(outer, ttk.Frame):
                outer.columnconfigure(2, weight=0, minsize=380)
        else:
            self.parts_panel.grid_remove()
            outer = self.parts_panel.master
            if isinstance(outer, ttk.Frame):
                outer.columnconfigure(2, weight=0, minsize=0)
            self.hover_label.configure(
                text="Mausrad = scrollen · Doppelklick = Großansicht"
            )

    def _on_part_hover(self, part: Part | None) -> None:
        if part is None:
            self.hover_label.configure(
                text="Mausrad = scrollen · Doppelklick = Großansicht"
            )
            return
        self.hover_label.configure(
            text=f"Teil {part.index} · Doppelklick für Großansicht"
        )

    # ------------------------------------------------------------------ Reset
    def _reset(self) -> None:
        for name, value in (("a", "3,0"), ("b", "4,0"), ("c", "5,0")):
            self.side_vars[name].set(value)
        self.height_var.set(False)
        self.height_choice.set("ha (Seite a)")
        self.mode_var.set("count")
        self.param_var.set("4")
        for variable in self.extra_vars.values():
            variable.set("0,0")
        self.triangle = None
        self.parts = []
        self.view.reset_view()
        self.view.set_data(None)
        self._show_parts_panel(False)
        self.status.configure(text="Bereit.")
        self._calculate()

    # -------------------------------------------------------------- Einstellungen
    def apply_settings(self, auto_update: bool, interval_hours: float, repo: str) -> None:
        old_repo = self.repo
        self.auto_update = bool(auto_update)
        self.interval_hours = max(1.0, min(168.0, float(interval_hours)))
        self.repo = normalize_repo(repo)
        settings = load_settings()
        settings.update(
            {
                "auto_update": self.auto_update,
                "interval_hours": self.interval_hours,
                "repo": self.repo,
            }
        )
        save_settings(settings)
        if old_repo != self.repo:
            try:
                cache_file().unlink(missing_ok=True)
            except OSError:
                pass
        self.activity.configure(text="Einstellungen gespeichert.")
        if self.auto_update:
            self._set_activity(f"Auto-Update aktiv · alle {self.interval_hours:g} h")
        else:
            self._set_activity("Auto-Update deaktiviert.")

    def _open_settings(self) -> None:
        SettingsDialog(self)

    # ------------------------------------------------------------------ Update
    def _startup_check(self) -> None:
        if not self.auto_update:
            self._set_activity("Auto-Update ist deaktiviert.")
            return
        checked, info = read_cache(cache_file(), self.repo)
        if cache_is_fresh(checked, interval=self.interval_hours * 3600):
            if info and is_newer(info.version, __version__):
                self._on_update_found(info)
            else:
                self._set_activity("Version ist aktuell.")
            return
        self._start_check(silent=True)

    def _manual_check(self) -> None:
        if self.checking or self.downloading:
            return
        if self.info:
            self._update_action()
            return
        self._start_check(silent=False)

    def _update_action(self) -> None:
        if self.downloading or self.checking:
            return
        if self.info:
            if self.installer and self.installer.is_file():
                self._install()
            else:
                self._download(self.info)
            return
        self._start_check(silent=False)

    def _start_check(self, silent: bool) -> None:
        self.checking = True
        self._set_activity("Suche nach Updates …")
        threading.Thread(
            target=self._check_worker,
            args=(silent,),
            daemon=True,
            name="update-check",
        ).start()

    def _check_worker(self, silent: bool) -> None:
        try:
            info = fetch_latest_release(__version__, repo=self.repo)
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
        if error:
            self._set_activity("Update-Prüfung nicht möglich (offline?).")
            if not silent:
                messagebox.showwarning(
                    "Update-Prüfung",
                    f"Es konnte keine Verbindung zu GitHub hergestellt werden.\n\n{error}\n\n"
                    "Die Anwendung läuft unverändert weiter.",
                    parent=self.root,
                )
            return
        if info:
            self._on_update_found(info)
            return
        self.info = None
        self.installer = None
        self._set_activity("Version ist aktuell.")
        if not silent:
            messagebox.showinfo(
                "Update-Prüfung",
                f"Sie verwenden bereits die neueste Version ({__version__}).",
                parent=self.root,
            )

    def _on_update_found(self, info: UpdateInfo) -> None:
        if self.info is None or self.info.version != info.version:
            self.installer = None
        self.info = info
        self._set_activity(f"Update {info.version} ist verfügbar.")
        if self.toast:
            self.toast.close()
        notes = info.notes.strip()
        if len(notes) > 320:
            notes = notes[:320] + " …"
        message = (
            f"Installiert: {__version__}\n"
            f"Verfügbar: {info.version}\n\n{notes}"
        ).strip()
        self.toast = UpdateToast(
            self.root,
            "Update verfügbar",
            message,
            on_install=lambda: self._download(info),
        )

    def _download(self, info: UpdateInfo) -> None:
        if self.downloading:
            return
        self.downloading = True
        self.info = info
        self.progress.configure(mode="determinate", value=0)
        self.progress.grid()
        self._set_activity(f"Lade Update {info.version} herunter …")
        threading.Thread(
            target=self._download_worker,
            args=(info,),
            daemon=True,
            name="update-download",
        ).start()

    def _download_worker(self, info: UpdateInfo) -> None:
        last = [0.0]

        def progress(done: int, total: int) -> None:
            import time

            now = time.monotonic()
            if done == total or now - last[0] >= 0.15:
                last[0] = now
                self.events.put(("progress", done, total))

        try:
            path = download_and_verify(
                info,
                update_dir(),
                progress=progress,
                timeout=30.0,
                repo=self.repo,
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
        self.progress.configure(value=max(0, min(100, percent)))

    def _on_download_done(self, path: Path) -> None:
        self.downloading = False
        self.installer = Path(path)
        self.progress.grid_remove()
        self._set_activity(
            f"Update {self.info.version if self.info else ''} geprüft."
        )
        if not is_frozen():
            messagebox.showinfo(
                "Update heruntergeladen",
                "Das Update wurde heruntergeladen und die Prüfsumme stimmt.\n\n"
                "Die automatische Installation ist nur in der installierten "
                "Version aktiv.",
                parent=self.root,
            )
            return
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
            save_settings(
                {
                    **load_settings(),
                    "auto_update": self.auto_update,
                    "interval_hours": self.interval_hours,
                    "repo": self.repo,
                }
            )
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
        self._set_activity("Update wird installiert, die Anwendung startet neu …")
        self.root.after(250, self.root.destroy)

    def _on_download_error(self, message: str) -> None:
        self.downloading = False
        self.progress.grid_remove()
        self._set_activity("Update-Download fehlgeschlagen.")
        messagebox.showerror(
            "Update",
            f"Das Update konnte nicht geladen werden.\n\n{message}\n\n"
            "Die aktuelle Version bleibt unverändert.",
            parent=self.root,
        )

    def _set_activity(self, text: str) -> None:
        self.activity.configure(text=text)

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "check_result":
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

    # ------------------------------------------------------------------ Dialoge
    def _export_pdf(self) -> None:
        if self.triangle is None:
            messagebox.showwarning(
                "PDF-Export",
                "Bitte zuerst ein gültiges Dreieck berechnen.",
                parent=self.root,
            )
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Als PDF exportieren",
            defaultextension=".pdf",
            filetypes=(("PDF-Datei", "*.pdf"), ("Alle Dateien", "*.*")),
            initialfile="GaubenMaster2.pdf",
        )
        if not path:
            return
        try:
            export_pdf(
                Path(path),
                self.triangle,
                self.parts,
                self._height_name(),
                self._extras(),
                self.display_options,
                rotation=self.view.rotation,
                master=self.root,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "PDF-Export",
                f"Die PDF-Datei konnte nicht geschrieben werden.\n\n{exc}",
                parent=self.root,
            )
            return
        self._set_activity(f"PDF gespeichert: {path}")

    def _open_repository(self) -> None:
        webbrowser.open(f"https://github.com/{self.repo}")

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
            "Berechnung und Visualisierung von Dreiecken für den Gaubenbau.\n\n"
            f"Ausführung: {state}\n"
            f"Repository: {self.repo}\n"
            f"Datenordner: {data_dir()}",
            parent=self.root,
        )

    def _help(self) -> None:
        messagebox.showinfo(
            "Hilfe",
            "Seiten a, b und c in cm eingeben und „Berechnen“ drücken.\n\n"
            "Maus: Linke Taste ziehen = verschieben, Strg+Ziehen = drehen, "
            "Mausrad = zoomen.\n"
            "Tastatur: Enter oder F5 = berechnen, Strg+N = zurücksetzen.\n\n"
            "Höhen-Teilung: Höhe wählen, Modus festlegen und die Teilung "
            "einschalten. Die rechte Spalte zeigt jedes Einzelteil bemaßt "
            "mit Länge und Winkel. Mausrad scrollt, Doppelklick öffnet die "
            "Großansicht. Im Plot werden Seiten, Hauptwinkel, Kanten und "
            "Flächen beschriftet.",
            parent=self.root,
        )

    def _close(self) -> None:
        if self.toast:
            self.toast.close()
        try:
            settings = load_settings()
            settings.update(
                {
                    "auto_update": self.auto_update,
                    "interval_hours": self.interval_hours,
                    "repo": self.repo,
                }
            )
            save_settings(settings)
        finally:
            self.root.destroy()


def run() -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()
