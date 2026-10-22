"""Scrollbare, bemaszte Zeichnungen der einzelnen Teilstuecke."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from .geometry import Part, Point, Triangle
from .plot import BACKGROUND, TAB20, blend, create_angle_label

CARD_BACKGROUND = "#ffffff"
CARD_BORDER = "#d7e2ee"
DIMENSION = "#1857a4"
ALLOWANCE = "#a65b00"
ANGLE_TEXT = "#9b1c1c"
CARD_HEIGHT = 198


def _format_length(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def height_axis(triangle: Triangle, height_name: str) -> Point:
    vertex, _base1, _base2 = triangle.height_segment(height_name)  # type: ignore[arg-type]
    foot = triangle.height_foot(height_name)  # type: ignore[arg-type]
    dx = vertex[0] - foot[0]
    dy = vertex[1] - foot[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 1.0)
    return (dx / length, dy / length)


def _local_points(points: tuple[Point, ...], axis: Point) -> list[Point]:
    ux, uy = axis
    vx, vy = uy, -ux
    result: list[Point] = []
    for x, y in points:
        result.append((x * vx + y * vy, x * ux + y * uy))
    return result


def _draw_dimension_line(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    tags: tuple[str, ...],
) -> None:
    canvas.create_line(x1, y1, x2, y2, fill=DIMENSION, width=1, tags=tags)
    if abs(y2 - y1) >= abs(x2 - x1):
        canvas.create_line(x1 - 4, y1, x1 + 4, y1, fill=DIMENSION, tags=tags)
        canvas.create_line(x2 - 4, y2, x2 + 4, y2, fill=DIMENSION, tags=tags)
    else:
        canvas.create_line(x1, y1 - 4, x1, y1 + 4, fill=DIMENSION, tags=tags)
        canvas.create_line(x2, y2 - 4, x2, y2 + 4, fill=DIMENSION, tags=tags)


def draw_part(
    canvas: tk.Canvas,
    part: Part,
    bbox: tuple[float, float, float, float],
    axis: Point,
    extra_length: float,
    fold_front: float,
    fold_back: float,
    *,
    compact: bool,
    tags: tuple[str, ...] = (),
) -> None:
    x0, y0, x1, y1 = bbox
    if x1 - x0 < 40 or y1 - y0 < 40:
        return

    points = _local_points(part.points, axis)
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)

    half_extra = max(0.0, extra_length) / 2.0
    cut_left = min_x - max(0.0, fold_front)
    cut_right = max_x + max(0.0, fold_back)
    cut_bottom = min_y - half_extra
    cut_top = max_y + half_extra

    pad_left = 38.0
    pad_right = 18.0
    pad_top = 18.0
    pad_bottom = 30.0
    available_width = max(1.0, x1 - x0 - pad_left - pad_right)
    available_height = max(1.0, y1 - y0 - pad_top - pad_bottom)
    span_x = max(1e-6, cut_right - cut_left)
    span_y = max(1e-6, cut_top - cut_bottom)
    scale = min(available_width / span_x, available_height / span_y)
    center_x = (cut_left + cut_right) / 2.0
    center_y = (cut_bottom + cut_top) / 2.0
    center_screen_x = x0 + pad_left + available_width / 2.0
    center_screen_y = y0 + pad_top + available_height / 2.0

    def to_screen(point: Point) -> Point:
        return (
            center_screen_x + (point[0] - center_x) * scale,
            center_screen_y - (point[1] - center_y) * scale,
        )

    screen = [to_screen(point) for point in points]
    cut_left_screen = to_screen((cut_left, 0.0))[0]
    cut_right_screen = to_screen((cut_right, 0.0))[0]
    cut_top_screen = to_screen((0.0, cut_top))[1]
    cut_bottom_screen = to_screen((0.0, cut_bottom))[1]

    if half_extra > 0.0:
        for y in (cut_top_screen, cut_bottom_screen):
            canvas.create_line(
                cut_left_screen,
                y,
                cut_right_screen,
                y,
                fill=ALLOWANCE,
                dash=(3, 3),
                tags=tags,
            )
    if fold_front > 0.0:
        canvas.create_line(
            cut_left_screen,
            cut_top_screen,
            cut_left_screen,
            cut_bottom_screen,
            fill=ALLOWANCE,
            dash=(3, 3),
            tags=tags,
        )
    if fold_back > 0.0:
        canvas.create_line(
            cut_right_screen,
            cut_top_screen,
            cut_right_screen,
            cut_bottom_screen,
            fill=ALLOWANCE,
            dash=(3, 3),
            tags=tags,
        )

    color = TAB20[(part.index - 1) % len(TAB20)]
    fill = blend(color, 0.30 if compact else 0.36)
    canvas.create_polygon(
        *[coordinate for point in screen for coordinate in point],
        fill=fill,
        outline=color,
        width=2,
        joinstyle="round",
        tags=tags,
    )

    candidates = [
        (angle, index)
        for index, angle in enumerate(part.angles_deg)
        if 3.0 < angle < 177.0 and abs(angle - 90.0) >= 0.1
    ]
    if candidates:
        angle, index = min(candidates)
        create_angle_label(
            canvas,
            screen,
            index,
            f"{angle:.1f}°",
            ("Segoe UI", 8 if compact else 10, "bold"),
            ANGLE_TEXT,
            fill,
            tags,
        )

    y_top = cut_top_screen
    y_bottom = cut_bottom_screen
    dimension_x = x0 + 13.0
    _draw_dimension_line(canvas, dimension_x, y_top, dimension_x, y_bottom, tags)
    canvas.create_text(
        dimension_x - 3,
        (y_top + y_bottom) / 2.0,
        text=f"L {_format_length(part.height_cm + extra_length)}",
        fill=DIMENSION,
        font=("Segoe UI", 7 if compact else 9, "bold"),
        angle=90,
        tags=tags,
    )

    if half_extra > 0.0:
        for y, anchor in ((y_top - 2, "s"), (y_bottom + 2, "n")):
            canvas.create_text(
                (cut_left_screen + cut_right_screen) / 2.0,
                y,
                text=f"+{_format_length(half_extra)}",
                fill=ALLOWANCE,
                font=("Segoe UI", 6 if compact else 8),
                anchor=anchor,
                tags=tags,
            )

    fold_y = y1 - 6.0
    canvas.create_text(
        x0 + 4.0,
        fold_y,
        text=f"Fv {_format_length(max(0.0, fold_front))}",
        fill=DIMENSION,
        font=("Segoe UI", 6 if compact else 8, "bold"),
        anchor="sw",
        tags=tags,
    )
    canvas.create_text(
        x1 - 4.0,
        fold_y,
        text=f"Fh {_format_length(max(0.0, fold_back))}",
        fill=DIMENSION,
        font=("Segoe UI", 6 if compact else 8, "bold"),
        anchor="se",
        tags=tags,
    )


class PartPopup(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        part: Part,
        axis: Point,
        extras: tuple[float, float, float],
    ) -> None:
        super().__init__(master)
        self.title(f"Teil {part.index}")
        self.geometry("250x250")
        self.resizable(False, False)
        self.configure(background=BACKGROUND)
        self.transient(master.winfo_toplevel())
        self.canvas = tk.Canvas(
            self,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            width=242,
            height=242,
        )
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind(
            "<Configure>", lambda _event: self._draw(part, axis, extras)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        root = master.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - 250) // 2
        y = root.winfo_rooty() + (root.winfo_height() - 250) // 2
        self.geometry(f"250x250+{max(0, x)}+{max(0, y)}")
        self.update_idletasks()
        self._draw(part, axis, extras)

    def _draw(
        self,
        part: Part,
        axis: Point,
        extras: tuple[float, float, float],
    ) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if width <= 1:
            width = max(1, self.canvas.winfo_reqwidth())
        if height <= 1:
            height = max(1, self.canvas.winfo_reqheight())
        draw_part(
            self.canvas,
            part,
            (6.0, 6.0, width - 6.0, height - 6.0),
            axis,
            extras[0],
            extras[1],
            extras[2],
            compact=False,
            tags=("part",),
        )


class PartsList(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, background=BACKGROUND)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.triangle: Triangle | None = None
        self.parts: list[Part] = []
        self.height_name = "ha"
        self.extras: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.axis: Point = (0.0, 1.0)
        self._signature: tuple | None = None

        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _event: self._scroll(-3))
        self.canvas.bind("<Button-5>", lambda _event: self._scroll(3))
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.configure(cursor=""))

    def set_data(
        self,
        triangle: Triangle | None,
        parts: list[Part],
        height_name: str,
        extras: tuple[float, float, float],
    ) -> None:
        self.triangle = triangle
        self.parts = parts
        self.height_name = height_name
        self.extras = extras
        self.axis = height_axis(triangle, height_name) if triangle else (0.0, 1.0)
        signature = (len(parts), height_name)
        if signature != self._signature:
            self._signature = signature
            self.canvas.yview_moveto(0.0)
        self.redraw()

    def _on_wheel(self, event: tk.Event) -> str:
        self._scroll(-3 if event.delta > 0 else 3)
        return "break"

    def _scroll(self, units: int) -> str:
        self.canvas.yview_scroll(units, "units")
        return "break"

    def _part_from_current(self) -> Part | None:
        for tag in self.canvas.gettags("current"):
            if tag.startswith("part-"):
                try:
                    index = int(tag.split("-", 1)[1])
                except ValueError:
                    return None
                return next(
                    (part for part in self.parts if part.index == index), None
                )
        return None

    def _on_click(self, _event: tk.Event) -> None:
        self.canvas.focus_set()

    def _on_double_click(self, _event: tk.Event) -> str:
        part = self._part_from_current()
        if part is not None:
            PartPopup(self, part, self.axis, self.extras)
        return "break"

    def _on_motion(self, _event: tk.Event) -> None:
        self.canvas.configure(
            cursor="hand2" if self._part_from_current() is not None else ""
        )

    def redraw(self) -> None:
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if width < 40:
            return

        if not self.parts:
            message = (
                "Höhen-Teilung ist ausgeschaltet."
                if not self.triangle
                else "Keine Teile berechnet."
            )
            self.canvas.create_text(
                width / 2.0,
                height / 2.0,
                text=message,
                fill="#6b7a90",
                font=("Segoe UI", 9),
                width=max(40, width - 24),
                justify="center",
            )
            self.canvas.configure(scrollregion=(0, 0, width, height))
            return

        top = 8.0
        card_height = CARD_HEIGHT
        for part in self.parts:
            tags = (f"part-{part.index}",)
            self.canvas.create_rectangle(
                8,
                top,
                width - 8,
                top + card_height,
                fill=CARD_BACKGROUND,
                outline=CARD_BORDER,
                tags=tags,
            )
            color = TAB20[(part.index - 1) % len(TAB20)]
            self.canvas.create_text(
                18,
                top + 10,
                text=f"Teil {part.index}",
                fill=color,
                font=("Segoe UI", 9, "bold"),
                anchor="nw",
                tags=tags,
            )
            draw_part(
                self.canvas,
                part,
                (12.0, top + 26.0, width - 12.0, top + card_height - 8.0),
                self.axis,
                self.extras[0],
                self.extras[1],
                self.extras[2],
                compact=True,
                tags=tags,
            )
            top += card_height + 8.0

        self.canvas.configure(scrollregion=(0, 0, width, top))
