"""Plattenplanung mit Polygon-Nesting, Live-Ansicht und Top-5-Loesungen.

Die eigentliche Optimierung liegt in :mod:`gaubenmaster.nesting`. Dieses Modul
stellt das Fenster bereit, startet die Suche in einem Worker-Thread und zeigt
waehrend der Berechnung die aktuell getestete und die beste gefundene
Anordnung. Saemtliche Masse werden in Zentimetern angezeigt.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from gaubenmaster.formatting import format_number
from gaubenmaster.cutmodel import CutModelError
from gaubenmaster.geometry import Part, Triangle, polygon_centroid
from gaubenmaster.nesting import (
    SCORING_BALANCED,
    SCORING_CUTS,
    SCORING_LABELS,
    SCORING_MODES,
    SCORING_WASTE,
    STRIP_WIDTH_CM,
    TARGET_LAYOUTS,
    Layout,
    NestingError,
    NestingOptions,
    NestingProgress,
    NestingResult,
    nest_shapes_detailed,
    shapes_from_parts,
    validate_layout,
)
from gaubenmaster.plot import BACKGROUND, TAB20, blend

try:
    from gaubenmaster.spyrrow_solver import is_spyrrow_available
except Exception:  # pragma: no cover
    def is_spyrrow_available() -> bool:
        return False

PLATE_FILL = "#ffffff"
PLATE_OUTLINE = "#12263f"
GRID = "#e4e8ee"
PART_OUTLINE = "#12324f"
TEXT = "#12263f"
MUTED = "#5b6878"
VALID = "#137333"
INVALID = "#b3261e"
ATTENTION = "#a65b00"
CUT_LINE = "#d93025"

LIVE_UPDATE_MS = 50
CANVAS_LEFT = 70
CANVAS_TOP = 64


class PlatePlanningWindow(tk.Toplevel):
    """Fenster fuer die Plattenplanung mit Live-Optimierung."""

    def __init__(
        self,
        master: tk.Misc,
        triangle: Triangle | None,
        parts: list[Part],
        height_name: str,
        extras: tuple[float, float, float],
    ) -> None:
        super().__init__(master)
        self.triangle = triangle
        self.parts = parts
        self.height_name = height_name
        self.extras = extras

        self.live_var = tk.BooleanVar(value=True)
        self.budget_var = tk.StringVar(value="60")
        self.angle_step_var = tk.StringVar(value="5")
        self.scoring_var = tk.StringVar(value=SCORING_LABELS[SCORING_BALANCED])
        self.solver_var = tk.StringVar(value="Eigen (Heuristik)")

        self._results: list[Layout] = []
        self._pareto: list[Layout] = []
        self._result: NestingResult | None = None
        self._live_best: Layout | None = None
        self._live_layout: Layout | None = None
        self._selected_index = 0
        self._progress: NestingProgress | None = None
        self._search_duration = 0.0

        self._queue: queue.Queue = queue.Queue(maxsize=80)
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._poll_job: str | None = None
        self._closing = False
        self._suppress_dialogs = False
        self.update_interval_ms = LIVE_UPDATE_MS

        self.title("Plattenplanung")
        self.geometry("1400x1000")
        self.minsize(980, 640)
        self.configure(background=BACKGROUND)
        self.transient(master.winfo_toplevel())

        self._build_ui()
        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<Return>", lambda _event: self._start_search())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.update_idletasks()
        self._center_on_parent(master)
        self.after(120, self._start_search)

    # ------------------------------------------------------------------
    # Aufbau der Oberflaeche
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        controls = ttk.LabelFrame(outer, text="Material und Optimierung", padding=8)
        controls.grid(row=0, column=0, sticky="ew", columnspan=2)
        controls.columnconfigure(4, weight=1)

        ttk.Label(
            controls,
            text=f"Breite: {format_number(STRIP_WIDTH_CM)} cm (fest)",
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Label(controls, text="Länge: aus der Platzierung").grid(
            row=0, column=1, sticky="w", padx=(0, 16)
        )
        ttk.Checkbutton(
            controls,
            text="Live-Ansicht während der Berechnung anzeigen",
            variable=self.live_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 16))
        budget_frame = ttk.Frame(controls)
        budget_frame.grid(row=0, column=3, sticky="w", padx=(0, 16))
        ttk.Label(budget_frame, text="Zeitbudget:").pack(side="left")
        ttk.Spinbox(
            budget_frame,
            from_=3,
            to=60,
            increment=1,
            width=4,
            textvariable=self.budget_var,
        ).pack(side="left", padx=(4, 2))
        ttk.Label(budget_frame, text="s").pack(side="left")
        ttk.Label(budget_frame, text="Winkelschritt:").pack(
            side="left", padx=(10, 0)
        )
        ttk.Spinbox(
            budget_frame,
            from_=5,
            to=30,
            increment=5,
            width=4,
            textvariable=self.angle_step_var,
        ).pack(side="left", padx=(4, 2))
        ttk.Label(budget_frame, text="°").pack(side="left")
        ttk.Label(budget_frame, text="Ziel:").pack(side="left", padx=(10, 0))
        self._scoring_box = ttk.Combobox(
            budget_frame,
            textvariable=self.scoring_var,
            values=[SCORING_LABELS[mode] for mode in SCORING_MODES],
            state="readonly",
            width=26,
        )
        self._scoring_box.pack(side="left", padx=(4, 0))
        self._scoring_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._start_search()
        )
        ttk.Label(budget_frame, text="Solver:").pack(side="left", padx=(10, 0))
        solver_values = ["Eigen (Heuristik)"]
        if is_spyrrow_available():
            solver_values.append("Sparrow (extern)")
        self._solver_box = ttk.Combobox(
            budget_frame,
            textvariable=self.solver_var,
            values=solver_values,
            state="readonly",
            width=18,
        )
        self._solver_box.pack(side="left", padx=(4, 0))
        self._solver_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._start_search()
        )
        self._start_button = ttk.Button(
            controls, text="Berechnen", command=self._start_search
        )
        self._start_button.grid(row=0, column=5, sticky="e", padx=(0, 8))
        self._cancel_button = ttk.Button(
            controls,
            text="Abbrechen",
            command=self._cancel_search,
            state="disabled",
        )
        self._cancel_button.grid(row=0, column=6, sticky="e")

        info = ttk.Label(
            outer,
            text=(
                f"Zuschnitt: Länge+ {format_number(self.extras[0])} cm · "
                f"Fv {format_number(self.extras[1])} cm · "
                f"Fh {format_number(self.extras[2])} cm   |   "
                "Vier Drehungsphasen (A 0°/180°, B 90°/270°, C alternative "
                "Winkel, D gemischt) konkurrieren über die gewählte Bewertung. "
                "Die Schnittanzahl zählt jede gerade Innenlinie einmal "
                "(Fugenbreite 0 cm, fluchtende Kanten zusammengefasst) und "
                "ist keine gemessene Werkzeugzahl. Heuristik, kein "
                "nachgewiesenes Optimum."
            ),
            foreground=MUTED,
            justify="left",
            wraplength=1220,
        )
        info.grid(row=1, column=0, sticky="w", pady=(6, 6), columnspan=2)

        canvas_frame = ttk.Frame(outer)
        canvas_frame.grid(row=2, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=self.canvas.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", lambda _event: self._draw_strip())
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda _event: self._on_mousewheel_linux(-1))
        self.canvas.bind("<Button-5>", lambda _event: self._on_mousewheel_linux(1))

        self._build_result_panel(outer)

        self.status = ttk.Label(outer, text="Bereit.", foreground=MUTED)
        self.status.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.live_info = ttk.Label(outer, text="", foreground=MUTED)
        self.live_info.grid(row=4, column=0, sticky="w", pady=(2, 0))

    def _build_result_panel(self, outer: ttk.Frame) -> None:
        panel = ttk.LabelFrame(
            outer, text="Lösungen (bis zu 5, nach Bewertung)", padding=8
        )
        panel.grid(row=2, column=1, sticky="nsew", padx=(10, 0))
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        columns = ("rank", "length", "cuts", "waste", "score")
        self.result_tree = ttk.Treeview(
            panel,
            columns=columns,
            show="headings",
            height=5,
            selectmode="browse",
        )
        headings = {
            "rank": ("Rang", 46),
            "length": ("Länge", 68),
            "cuts": ("Schnitte", 62),
            "waste": ("Verschnitt", 76),
            "score": ("Bewertung", 68),
        }
        for key, (label, width) in headings.items():
            self.result_tree.heading(key, text=label)
            self.result_tree.column(key, width=width, anchor="center")
        self.result_tree.grid(row=0, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self._on_result_selected)

        details_frame = ttk.Frame(panel)
        details_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.result_details = tk.Text(
            details_frame,
            height=15,
            width=44,
            wrap="word",
            relief="flat",
            background="#f7f9fc",
            foreground=TEXT,
            font=("Segoe UI", 9),
            padx=6,
            pady=6,
        )
        self.result_details.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(
            details_frame, orient="vertical", command=self.result_details.yview
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.result_details.configure(yscrollcommand=detail_scroll.set)
        self.result_details.configure(state="disabled")
        self._set_details("Noch keine Lösung berechnet.")

        pareto_label = ttk.Label(
            panel,
            text="Zielkonflikt (Pareto: Länge ↔ Schnitte)",
            foreground=TEXT,
        )
        pareto_label.grid(row=2, column=0, sticky="w", pady=(10, 2))
        pareto_columns = ("length", "cuts", "waste")
        self.pareto_tree = ttk.Treeview(
            panel,
            columns=pareto_columns,
            show="headings",
            height=4,
            selectmode="none",
        )
        pareto_headings = {
            "length": ("Länge", 90),
            "cuts": ("Schnitte", 70),
            "waste": ("Verschnitt", 90),
        }
        for key, (label, width) in pareto_headings.items():
            self.pareto_tree.heading(key, text=label)
            self.pareto_tree.column(key, width=width, anchor="center")
        self.pareto_tree.grid(row=3, column=0, sticky="ew")

        legend = ttk.Label(
            panel,
            text=(
                "Farben kennzeichnen die Teilnummern.\n"
                "Während der Suche: gestrichelt = getesteter Kandidat,\n"
                "grün = gültig, rot = verworfen (Kollision oder Rand)."
            ),
            foreground=MUTED,
            justify="left",
            wraplength=330,
        )
        legend.grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _set_details(self, text: str) -> None:
        widget = getattr(self, "result_details", None)
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # Fenster-Hilfen
    # ------------------------------------------------------------------

    def _center_on_parent(self, master: tk.Misc) -> None:
        try:
            root = master.winfo_toplevel()
            x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
            y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

    def _on_mousewheel(self, event: tk.Event) -> str:
        steps = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(steps, "units")
        return "break"

    def _on_mousewheel_linux(self, direction: int) -> str:
        self.canvas.yview_scroll(direction, "units")
        return "break"

    def _close(self) -> None:
        self._closing = True
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        self.destroy()

    # ------------------------------------------------------------------
    # Start, Abbruch und Worker
    # ------------------------------------------------------------------

    def _budget_seconds(self) -> float:
        try:
            value = float(self.budget_var.get().replace(",", "."))
        except ValueError:
            raise NestingError("Das Zeitbudget muss eine Zahl zwischen 3 und 60 sein.")
        if not 3.0 <= value <= 60.0:
            raise NestingError("Das Zeitbudget muss zwischen 3 und 60 Sekunden liegen.")
        return value

    def _angle_step_degrees(self) -> float:
        try:
            value = float(self.angle_step_var.get().replace(",", "."))
        except ValueError:
            raise NestingError(
                "Der Winkelschritt muss eine Zahl zwischen 5 und 30 sein."
            )
        if not 1.0 <= value <= 90.0:
            raise NestingError(
                "Der Winkelschritt muss zwischen 5 und 30 Grad liegen."
            )
        return value

    def _scoring_mode(self) -> str:
        label = self.scoring_var.get()
        for mode in SCORING_MODES:
            if SCORING_LABELS[mode] == label:
                return mode
        return SCORING_BALANCED

    def _solver_mode(self) -> str:
        return "sparrow" if self.solver_var.get().startswith("Sparrow") else "own"

    def _build_shapes(self) -> list:
        return shapes_from_parts(
            self.triangle, self.parts, self.height_name, self.extras
        )

    def _start_search(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        if not self.parts:
            self.status.configure(
                text=(
                    "Keine Einzelteile vorhanden. Bitte zuerst die "
                    "Höhen-Teilung aktivieren."
                ),
                foreground=ATTENTION,
            )
            self._live_info("")
            return
        self._suppress_dialogs = False
        try:
            shapes = self._build_shapes()
            budget = self._budget_seconds()
            angle_step = self._angle_step_degrees()
        except NestingError as error:
            self._report_error(str(error))
            return

        options = NestingOptions(
            width=STRIP_WIDTH_CM,
            time_budget_s=budget,
            max_candidates=2000,
            coarse_angle_step_deg=angle_step,
            allow_free_rotation=True,
            scoring=self._scoring_mode(),
            solver=self._solver_mode(),
        )
        live = bool(self.live_var.get())
        self._results = []
        self._pareto = []
        self._result = None
        self._live_best = None
        self._live_layout = None
        self._progress = None
        self._selected_index = 0
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        for item in self.pareto_tree.get_children():
            self.pareto_tree.delete(item)
        self._set_details("Berechnung läuft ...")

        self._cancel_event = threading.Event()
        self._start_button.configure(state="disabled")
        self._cancel_button.configure(state="normal")
        self.status.configure(
            text=(
                "Berechne Platzierung (Phasen A–D, Ziel: "
                f"{SCORING_LABELS[self._scoring_mode()]}) ..."
            ),
            foreground=MUTED,
        )
        self._live_info(
            "Suche startet ..." if live else "Live-Ansicht aus – Berechnung läuft."
        )
        self._draw_strip()

        worker = threading.Thread(
            target=self._run_worker,
            args=(shapes, options, live),
            daemon=True,
        )
        self._worker = worker
        worker.start()
        self._schedule_poll()

    def _run_worker(self, shapes, options: NestingOptions, live: bool) -> None:
        started = time.monotonic()
        try:
            result = nest_shapes_detailed(
                shapes,
                options,
                progress_cb=self._enqueue if live else None,
                cancel_event=self._cancel_event,
            )
            payload = ("done", result, None, time.monotonic() - started)
        except NestingError as error:
            payload = ("error", None, str(error), time.monotonic() - started)
        except Exception as error:  # pragma: no cover - defensive
            payload = (
                "error",
                None,
                f"Unerwarteter Fehler bei der Berechnung: {error}",
                time.monotonic() - started,
            )
        self._put_final(payload)

    def _enqueue(self, progress: NestingProgress) -> None:
        try:
            self._queue.put_nowait(progress)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(progress)
            except queue.Full:
                pass

    def _put_final(self, payload: tuple) -> None:
        while True:
            try:
                self._queue.put_nowait(payload)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    return

    def _schedule_poll(self) -> None:
        if self._closing:
            return
        self._poll_job = self.after(self.update_interval_ms, self._poll_queue)

    def _poll_queue(self) -> None:
        self._poll_job = None
        if self._closing:
            return
        latest: NestingProgress | None = None
        final: tuple | None = None
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, tuple):
                final = message
            else:
                latest = message
        if latest is not None:
            self._apply_progress(latest)
        if final is not None:
            self._finish(final)
            return
        self._schedule_poll()

    def _cancel_search(self) -> None:
        if self._cancel_event is not None and self._worker is not None:
            self._cancel_event.set()
            self._cancel_button.configure(state="disabled")
            self.status.configure(
                text=(
                    "Abbruch angefordert – die beste bisherige gültige "
                    "Lösung bleibt erhalten."
                ),
                foreground=ATTENTION,
            )

    # ------------------------------------------------------------------
    # Status und Fortschritt
    # ------------------------------------------------------------------

    def _live_info(self, text: str) -> None:
        self.live_info.configure(text=text)

    def _apply_progress(self, progress: NestingProgress) -> None:
        self._progress = progress
        if progress.layout is not None:
            self._live_layout = progress.layout
            if progress.layout.complete:
                if (
                    self._live_best is None
                    or progress.layout.length < self._live_best.length
                ):
                    self._live_best = progress.layout
        self._draw_strip()
        self.status.configure(
            text=progress.phase_label,
            foreground=TEXT,
        )
        parts = [progress.phase_label]
        parts.append(f"Kandidaten: {progress.layouts}")
        parts.append(f"geprüfte Positionen: {progress.attempts}")
        if progress.strategy:
            parts.append(f"Strategie: {progress.strategy}")
        if progress.groups:
            groups = " · ".join(
                "(" + ",".join(str(index) for index in group) + ")"
                for group in progress.groups
            )
            parts.append(f"Gruppen: {groups}")
        if progress.cuts is not None:
            parts.append(f"Schnitte: {progress.cuts}")
        if progress.waste_percent is not None:
            parts.append(
                f"Verschnitt: {format_number(progress.waste_percent, 1)} %"
            )
        if progress.score is not None:
            parts.append(
                f"Bewertung ({SCORING_LABELS[self._scoring_mode()]}): "
                f"{format_number(progress.score, 3)}"
            )
        if progress.best_length is not None:
            parts.append(f"beste Länge: {format_number(progress.best_length)} cm")
        parts.append(f"Zeit: {progress.elapsed_s:.1f} s")
        if progress.event == "attempt" and progress.part_index is not None:
            validity = "gültig" if progress.attempt_valid else "verworfen"
            angle = progress.angle if progress.angle is not None else 0.0
            x = progress.x if progress.x is not None else 0.0
            y = progress.y if progress.y is not None else 0.0
            parts.append(
                f"Test: Teil {progress.part_index} · "
                f"{format_number(angle)}° · x={format_number(x)} cm · "
                f"y={format_number(y)} cm · {validity}"
            )
        self._live_info(" · ".join(parts))

    def _finish(self, payload: tuple) -> None:
        kind, result, error, duration = payload
        self._worker = None
        self._search_duration = duration
        self._start_button.configure(state="normal")
        self._cancel_button.configure(state="disabled")
        self._queue = queue.Queue(maxsize=80)
        if self._closing:
            return
        if kind == "error" or error:
            self._results = []
            self._pareto = []
            self._result = None
            self.status.configure(text="Berechnung fehlgeschlagen.", foreground=INVALID)
            self._set_details(str(error))
            self._live_info("")
            self._draw_message(str(error), INVALID)
            self._report_error(str(error))
            return
        if not isinstance(result, NestingResult) or not result.layouts:
            self._results = []
            self._pareto = []
            self._result = result if isinstance(result, NestingResult) else None
            message = (
                "Keine gültige Anordnung gefunden. Bitte Zeitbudget erhöhen "
                "oder die Zuschnitt-Zugaben prüfen."
            )
            self.status.configure(text=message, foreground=INVALID)
            self._set_details(message)
            self._live_info(
                f"Fertig nach {duration:.1f} s – keine gültige Lösung."
            )
            self._draw_message(message, INVALID)
            return

        self._result = result
        self._results = list(result.layouts)
        self._pareto = list(result.pareto)
        self._live_best = self._results[0]
        self._live_layout = self._results[0]
        self._populate_results()
        self._populate_pareto()
        self._show_result(0)
        best = self._results[0]
        cancelled = result.cancelled
        timed_out = result.timed_out
        shortfall = result.complete_shortfall
        status_text = (
            f"{len(self._results)} Lösung(en) · beste Länge "
            f"{format_number(best.length)} cm · Verschnitt "
            f"{format_number(best.waste_area, 1)} cm² "
            f"({format_number(best.waste_percent, 1)} %) · "
            f"Schnitte {best.cut_operations} · "
            f"{duration:.1f} s · Heuristik, kein nachgewiesenes Optimum"
        )
        if cancelled:
            status_text = "Abgebrochen – " + status_text
        elif timed_out:
            status_text = "Zeitbudget erreicht – " + status_text
        if shortfall:
            status_text = (
                status_text
                + f" · weniger als {TARGET_LAYOUTS} unterschiedliche Lösungen gefunden"
            )
        self.status.configure(text=status_text, foreground=VALID)
        checked = sum(1 for layout in self._results if validate_layout(layout))
        if checked:
            self.status.configure(
                text="Interne Prüfung meldet ungültige Lösung.", foreground=INVALID
            )
        self._live_info(
            f"Fertig nach {duration:.1f} s · "
            f"{result.candidates} Kandidaten geprüft · "
            f"Phasen: " + ", ".join(
                f"{name}={count}" for name, count in result.phase_counts
            )
        )

    def _report_error(self, message: str) -> None:
        if self._suppress_dialogs:
            return
        try:
            messagebox.showerror("Plattenplanung", message, parent=self)
        except tk.TclError:
            pass

    def _populate_results(self) -> None:
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        for index, layout in enumerate(self._results):
            rank = f"{index + 1}."
            label = rank + (" ★" if index == 0 else "")
            score = layout.score(
                self._scoring_mode(),
                self._weight_pair()[0],
                self._weight_pair()[1],
            )
            self.result_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    label,
                    f"{format_number(layout.length)} cm",
                    str(layout.cut_operations),
                    f"{format_number(layout.waste_percent, 1)} %",
                    format_number(score, 3),
                ),
            )

    def _weight_pair(self) -> tuple[float, float]:
        return 0.5, 0.5

    def _populate_pareto(self) -> None:
        for item in self.pareto_tree.get_children():
            self.pareto_tree.delete(item)
        for layout in self._pareto:
            self.pareto_tree.insert(
                "",
                "end",
                values=(
                    f"{format_number(layout.length)} cm",
                    str(layout.cut_operations),
                    f"{format_number(layout.waste_percent, 1)} %",
                ),
            )

    def _on_result_selected(self, _event=None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        try:
            index = int(selection[0])
        except ValueError:
            return
        self._show_result(index)

    def _show_result(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return
        self._selected_index = index
        layout = self._results[index]
        if str(index) not in self.result_tree.selection():
            self.result_tree.selection_set(str(index))
        angles = ", ".join(
            f"{format_number(value)}°" for value in layout.angles
        )
        phase = (
            "Phase A (nur 0°/180°)"
            if not layout.free_rotation
            else "Phasen B–D (freie/gemischte Drehungen)"
        )
        plan = layout.cut_plan
        lines: list[str] = []
        lines.append(f"Rang {index + 1} von {len(self._results)}")
        lines.append(f"Verfahren: {layout.strategy or '–'}")
        lines.append(
            f"Bewertung ({SCORING_LABELS[self._scoring_mode()]}): "
            f"{format_number(layout.score(self._scoring_mode()), 4)}"
        )
        lines.append(
            f"Materiallänge: {format_number(layout.length)} cm "
            f"(Mindestlänge {format_number(layout.min_length)} cm)"
        )
        lines.append(
            f"Verschnittfläche: {format_number(layout.waste_area, 1)} cm² "
            f"({format_number(layout.waste_percent, 1)} %)"
        )
        lines.append(
            f"Schnitte: {plan.operations} gerade Linie(n) "
            f"({plan.separating_operations} Trennschnitt(e), "
            f"{plan.trim_operations} Schnitt(e) zum Abfall)"
        )
        lines.append(
            f"Schnittlänge: {format_number(plan.total_length, 1)} cm, "
            f"davon {format_number(plan.shared_length, 1)} cm gemeinsam "
            f"({plan.shared_edges} gemeinsame Linie(n))"
        )
        lines.append(f"Schnittmodell: {plan.assumptions.describe()}")
        lines.append(
            f"Drehungen: {angles} · Vierteldrehungen: "
            f"{layout.quarter_turn_count} · alternative Winkel: "
            f"{layout.alternative_angle_count}"
        )
        if layout.groups:
            groups = "; ".join(
                "(" + ", ".join(str(value) for value in group) + ")"
                for group in layout.groups
            )
            lines.append(
                f"Gruppen: {groups} · {layout.group_count} Gruppe(n), "
                f"{layout.single_count} Einzelteil(e)"
            )
        else:
            lines.append(f"Gruppen: keine · {len(layout.items)} Einzelteile")
        lines.append("")
        lines.append("Positionen:")
        for item in layout.items:
            lines.append(
                f"  Teil {item.part_index} · {format_number(item.angle)}° · "
                f"x={format_number(item.bounds[0])} cm · "
                f"y={format_number(item.bounds[1])} cm · "
                f"{format_number(item.width)}×{format_number(item.height)} cm"
            )
        lines.append("")
        lines.append(
            f"Gefunden nach: {layout.elapsed_s:.2f} s · Phase: {layout.phase}"
        )
        lines.append(
            "Heuristische Lösung – kein mathematischer Optimalitätsnachweis."
        )
        self._set_details("\n".join(lines))
        self._live_layout = layout
        self._live_best = layout
        self._draw_strip()

    # ------------------------------------------------------------------
    # Zeichnung
    # ------------------------------------------------------------------

    def _strip_to_draw(self) -> Layout | None:
        if (
            self._progress is not None
            and self._live_layout is not None
            and not self._live_layout.complete
        ):
            return self._live_layout
        if self._results and self._selected_index < len(self._results):
            return self._results[self._selected_index]
        return self._live_layout or self._live_best

    def _draw_message(self, text: str, color: str = MUTED) -> None:
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.create_text(
            width / 2.0,
            height / 2.0,
            text=text,
            fill=color,
            font=("Segoe UI", 10),
            width=max(240, width - 80),
            justify="center",
        )
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _draw_strip(self) -> None:
        layout = self._strip_to_draw()
        progress = self._progress
        attempt_only = (
            layout is None
            and progress is not None
            and progress.attempt_polygon is not None
        )
        if layout is None and not attempt_only:
            if not self.parts:
                self._draw_message("Keine Einzelteile vorhanden.")
            elif self._results:
                self._draw_message("Lösung auswählen.")
            else:
                self._draw_message("Noch keine Anordnung berechnet.")
            return

        width_px = max(1, self.canvas.winfo_width())
        height_px = max(1, self.canvas.winfo_height())
        if width_px < 120:
            return

        length = max(
            layout.length if layout is not None else 0.0,
            (
                progress.layout.length
                if progress and progress.layout and self._worker is not None
                else 0.0
            ),
        )
        attempt = progress if (progress and progress.attempt_polygon and self._worker is not None) else None
        if attempt is not None and attempt.attempt_polygon:
            length = max(
                length,
                max(y for _x, y in attempt.attempt_polygon),
            )
        length = max(10.0, length)

        scale = (width_px - CANVAS_LEFT - 110.0) / STRIP_WIDTH_CM
        scale = max(0.25, min(scale, 10.0))
        strip_w = STRIP_WIDTH_CM * scale
        strip_h = max(1.0, length * scale)
        left = CANVAS_LEFT
        top = CANVAS_TOP

        self.canvas.delete("all")
        self.canvas.create_text(
            left,
            20.0,
            text=(
                f"Material · {format_number(STRIP_WIDTH_CM)} cm breit · "
                f"{format_number(length)} cm lang"
            ),
            fill=TEXT,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        if layout is not None:
            caption = (
                f"Angezeigt: {'beste / gewählte' if layout.complete else 'laufender Kandidat'}"
                f" · {len(layout.items)} Teile · {format_number(layout.length)} cm"
            )
            if (
                not layout.complete
                and self._live_best is not None
                and self._live_best is not layout
            ):
                caption += " · grau gestrichelt = beste Lösung"
            if layout.complete:
                caption += " · rot gepunktet = Schnittlinien"
            self.canvas.create_text(
                left,
                38.0,
                text=caption,
                fill=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
            )

        self.canvas.create_rectangle(
            left,
            top,
            left + strip_w,
            top + strip_h,
            fill=PLATE_FILL,
            outline="",
        )
        grid_step = 10.0 * scale
        x = left + grid_step
        while x < left + strip_w - 1e-6:
            self.canvas.create_line(x, top, x, top + strip_h, fill=GRID)
            x += grid_step
        y = top + grid_step
        while y < top + strip_h - 1e-6:
            self.canvas.create_line(left, y, left + strip_w, y, fill=GRID)
            y += grid_step

        if layout is not None:
            if self._live_best is not None and layout is not self._live_best:
                for item in self._live_best.items:
                    ghost = [
                        (left + x * scale, top + y * scale)
                        for x, y in item.polygon
                    ]
                    self.canvas.create_polygon(
                        *[coordinate for point in ghost for coordinate in point],
                        fill="",
                        outline="#9aa7b8",
                        width=1,
                        dash=(2, 2),
                    )
            for item in layout.items:
                self._draw_item(item, left, top, scale)
            if layout.complete:
                self._draw_cuts(layout, left, top, scale)

        if attempt is not None:
            self._draw_attempt(attempt, left, top, scale)

        if (
            progress is not None
            and progress.best_length is not None
            and progress.best_length < length - 0.5
        ):
            best_y = top + progress.best_length * scale
            self.canvas.create_line(
                left,
                best_y,
                left + strip_w,
                best_y,
                fill=VALID,
                dash=(5, 3),
            )
            self.canvas.create_text(
                left + strip_w - 4.0,
                best_y - 7.0,
                text=f"beste {format_number(progress.best_length)} cm",
                fill=VALID,
                font=("Segoe UI", 8, "bold"),
                anchor="e",
            )

        self.canvas.create_rectangle(
            left,
            top,
            left + strip_w,
            top + strip_h,
            fill="",
            outline=PLATE_OUTLINE,
            width=2,
        )
        self._draw_width_dimension(left, top, strip_w, self.canvas.winfo_width() < 560)
        self._draw_length_dimension(left, top, strip_h, length)

        total_height = max(top + strip_h + 60.0, height_px)
        self.canvas.configure(scrollregion=(0, 0, width_px, total_height))

    def _draw_cuts(self, layout: Layout, left: float, top: float, scale: float) -> None:
        """Zeichnet die modellierten Schnittlinien rot gepunktet ueber die Teile."""
        try:
            plan = layout.cut_plan
        except (CutModelError, ZeroDivisionError):
            return
        for segment in plan.segments:
            start_x, start_y = segment.start
            end_x, end_y = segment.end
            self.canvas.create_line(
                left + start_x * scale,
                top + start_y * scale,
                left + end_x * scale,
                top + end_y * scale,
                fill=CUT_LINE,
                width=2,
                dash=(6, 4),
                capstyle="round",
            )

    def _draw_item(self, item, left: float, top: float, scale: float) -> None:
        color = TAB20[(item.part_index - 1) % len(TAB20)]
        fill = blend(color, 0.30, PLATE_FILL)
        screen = [
            (left + x * scale, top + y * scale) for x, y in item.polygon
        ]
        self.canvas.create_polygon(
            *[coordinate for point in screen for coordinate in point],
            fill=fill,
            outline=color,
            width=2,
            joinstyle="round",
        )
        centroid_x = left + polygon_centroid(item.polygon)[0] * scale
        centroid_y = top + polygon_centroid(item.polygon)[1] * scale
        label = f"{item.part_index}\n{format_number(item.angle % 360.0)}°"
        self.canvas.create_text(
            centroid_x,
            centroid_y,
            text=label,
            fill=PART_OUTLINE,
            font=("Segoe UI", 8, "bold"),
            justify="center",
        )
        if min(item.width, item.height) * scale >= 34.0:
            self.canvas.create_text(
                centroid_x,
                centroid_y + 15.0,
                text=(
                    f"x {format_number(item.bounds[0])} · "
                    f"y {format_number(item.bounds[1])}"
                ),
                fill=MUTED,
                font=("Segoe UI", 7),
            )

    def _draw_attempt(
        self, progress: NestingProgress, left: float, top: float, scale: float
    ) -> None:
        polygon = progress.attempt_polygon
        if not polygon:
            return
        valid = bool(progress.attempt_valid)
        color = VALID if valid else INVALID
        screen = [(left + x * scale, top + y * scale) for x, y in polygon]
        self.canvas.create_polygon(
            *[coordinate for point in screen for coordinate in point],
            fill="",
            outline=color,
            width=2,
            dash=() if valid else (4, 3),
        )
        centroid = polygon_centroid(polygon)
        label = (
            f"Test: Teil {progress.part_index} · "
            f"{format_number(progress.angle or 0.0)}° · "
            f"{'gültig' if valid else 'verworfen'}"
        )
        self.canvas.create_text(
            left + centroid[0] * scale,
            top + centroid[1] * scale,
            text=label,
            fill=color,
            font=("Segoe UI", 8, "bold"),
        )
        if progress.x is not None and progress.y is not None:
            self.canvas.create_text(
                left + progress.x * scale,
                top + progress.y * scale,
                text="●",
                fill=color,
                font=("Segoe UI", 8),
            )

    def _draw_width_dimension(
        self, x: float, top: float, strip_w: float, compact: bool
    ) -> None:
        y = top - 16.0
        self.canvas.create_line(x, y, x + strip_w, y, fill=MUTED)
        for tick_x in (x, x + strip_w):
            self.canvas.create_line(tick_x, y - 5.0, tick_x, y + 5.0, fill=MUTED)
        self.canvas.create_text(
            x + strip_w / 2.0,
            y - 9.0,
            text=(
                f"{format_number(STRIP_WIDTH_CM)} cm"
                if not compact
                else f"{format_number(STRIP_WIDTH_CM)} cm (fest)"
            ),
            fill=TEXT,
            font=("Segoe UI", 9),
        )

    def _draw_length_dimension(
        self, margin_x: float, top: float, strip_h: float, length: float
    ) -> None:
        x = margin_x - 18.0
        self.canvas.create_line(x, top, x, top + strip_h, fill=MUTED)
        for tick_y in (top, top + strip_h):
            self.canvas.create_line(x - 5.0, tick_y, x + 5.0, tick_y, fill=MUTED)
        self.canvas.create_text(
            x - 10.0,
            top + strip_h / 2.0,
            text=f"{format_number(length)} cm",
            fill=TEXT,
            font=("Segoe UI", 9),
            angle=90,
        )

    # ------------------------------------------------------------------
    # Synchroner Pfad (Tests, Skripte, Enter-Taste)
    # ------------------------------------------------------------------

    def _recalculate(self) -> list[Layout]:
        """Berechnet synchron ohne Live-Ansicht (gut testbar)."""
        if self._worker is not None and self._worker.is_alive():
            return list(self._results)
        if not self.parts:
            self._results = []
            self.status.configure(
                text=(
                    "Keine Einzelteile vorhanden. Bitte zuerst die "
                    "Höhen-Teilung aktivieren."
                ),
                foreground=ATTENTION,
            )
            self._draw_strip()
            return []
        self._suppress_dialogs = True
        try:
            shapes = self._build_shapes()
            options = NestingOptions(
                width=STRIP_WIDTH_CM,
                time_budget_s=5.0,
                max_candidates=200,
                coarse_angle_step_deg=self._angle_step_degrees(),
                allow_free_rotation=True,
                scoring=self._scoring_mode(),
                solver=self._solver_mode(),
            )
            started = time.monotonic()
            result = nest_shapes_detailed(shapes, options)
            duration = time.monotonic() - started
        except NestingError as error:
            self._results = []
            self._pareto = []
            self._result = None
            self.status.configure(text=str(error), foreground=INVALID)
            self._set_details(str(error))
            self._draw_message(str(error), INVALID)
            return []
        finally:
            self._suppress_dialogs = False
        self._result = result
        self._results = list(result.layouts)
        self._pareto = list(result.pareto)
        self._live_best = self._results[0] if self._results else None
        self._live_layout = self._live_best
        self._finish(("done", result, None, duration))
        return list(self._results)
