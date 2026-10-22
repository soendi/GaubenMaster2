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
CARD_HEIGHT = 270


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
    *,
    tick: float = 4.0,
) -> None:
    canvas.create_line(x1, y1, x2, y2, fill=DIMENSION, width=1, tags=tags)
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return
    nx = -dy / length
    ny = dx / length
    for x, y in ((x1, y1), (x2, y2)):
        canvas.create_line(
            x - nx * tick,
            y - ny * tick,
            x + nx * tick,
            y + ny * tick,
            fill=DIMENSION,
            width=1,
            tags=tags,
        )


def _text_with_background(
    canvas: tk.Canvas,
    x: float,
    y: float,
    text: str,
    fill: str,
    font: tuple,
    *,
    angle: float,
    tags: tuple[str, ...],
    background: str,
    anchor: str = "center",
) -> None:
    canvas.create_text(
        x,
        y,
        text=text,
        fill=fill,
        font=font,
        angle=angle,
        anchor=anchor,
        justify="center",
        tags=tags,
    )


def _draw_side_dimensions(
    canvas: tk.Canvas,
    screen: list[Point],
    lengths: tuple[float, ...],
    *,
    compact: bool,
    tags: tuple[str, ...],
    background: str,
) -> None:
    if len(screen) < 3:
        return
    center = (
        sum(point[0] for point in screen) / len(screen),
        sum(point[1] for point in screen) / len(screen),
    )
    font = ("Segoe UI", 7 if compact else 10, "bold")
    offset = 15.0 if compact else 24.0
    label_gap = 7.0 if compact else 10.0
    tick = 3.0 if compact else 4.5
    for index, length in enumerate(lengths):
        point1 = screen[index]
        point2 = screen[(index + 1) % len(screen)]
        dx = point2[0] - point1[0]
        dy = point2[1] - point1[1]
        edge_length = math.hypot(dx, dy)
        if edge_length < 1e-9:
            continue
        normal_x = -dy / edge_length
        normal_y = dx / edge_length
        midpoint = (
            (point1[0] + point2[0]) / 2.0,
            (point1[1] + point2[1]) / 2.0,
        )
        if normal_x * (midpoint[0] - center[0]) + normal_y * (
            midpoint[1] - center[1]
        ) < 0.0:
            normal_x = -normal_x
            normal_y = -normal_y
        line_start = (
            point1[0] + normal_x * offset,
            point1[1] + normal_y * offset,
        )
        line_end = (
            point2[0] + normal_x * offset,
            point2[1] + normal_y * offset,
        )
        _draw_dimension_line(
            canvas,
            line_start[0],
            line_start[1],
            line_end[0],
            line_end[1],
            (*tags, f"side-dimension-{index}"),
            tick=tick,
        )
        text_angle = math.degrees(math.atan2(dy, dx))
        if text_angle > 90.0:
            text_angle -= 180.0
        elif text_angle <= -90.0:
            text_angle += 180.0
        _text_with_background(
            canvas,
            (line_start[0] + line_end[0]) / 2.0 + normal_x * label_gap,
            (line_start[1] + line_end[1]) / 2.0 + normal_y * label_gap,
            _format_length(length),
            DIMENSION,
            font,
            angle=-text_angle,
            tags=(*tags, f"side-label-{index}"),
            background=background,
        )


def _draw_part_angles(
    canvas: tk.Canvas,
    screen: list[Point],
    angles: tuple[float, ...],
    *,
    compact: bool,
    tags: tuple[str, ...],
) -> None:
    font = ("Segoe UI", 7 if compact else 10, "bold")
    for index, angle in enumerate(angles):
        if angle <= 1.0 or angle >= 179.0:
            continue
        create_angle_label(
            canvas,
            screen,
            index,
            f"{angle:.1f}°",
            font,
            ANGLE_TEXT,
            tags=(*tags, f"angle-{index}"),
        )


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
    background: str = BACKGROUND,
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
    fold_top = max(0.0, fold_front)
    fold_bottom = max(0.0, fold_back)
    center_y = (min_y + max_y) / 2.0

    center_x = sum(point[0] for point in points) / len(points)
    edge_offsets: list[Point] = []
    if len(points) == 3:
        base_index = next(
            (
                index
                for index in range(3)
                if abs(points[index][1] - points[(index + 1) % 3][1]) < 1e-9
            ),
            -1,
        )
        base_y = points[base_index][1] if base_index >= 0 else min_y
        if base_y > center_y:
            base_offset = (0.0, fold_top)
            side_offset_y = -fold_bottom
        else:
            base_offset = (0.0, -fold_bottom)
            side_offset_y = fold_top
        for index in range(3):
            if index == base_index:
                edge_offsets.append(base_offset)
                continue
            first = points[index]
            second = points[(index + 1) % 3]
            midpoint_x = (first[0] + second[0]) / 2.0
            edge_offsets.append(
                (-half_extra if midpoint_x < center_x else half_extra, side_offset_y)
            )
    else:
        for index, point in enumerate(points):
            following = points[(index + 1) % len(points)]
            if abs(point[1] - following[1]) < 1e-9:
                if point[1] >= max_y - 1e-9:
                    edge_offsets.append((0.0, fold_top))
                elif point[1] <= min_y + 1e-9:
                    edge_offsets.append((0.0, -fold_bottom))
                else:
                    edge_offsets.append((0.0, 0.0))
                continue
            midpoint_x = (point[0] + following[0]) / 2.0
            edge_offsets.append(
                (-half_extra if midpoint_x < center_x else half_extra, 0.0)
            )

    def shifted_intersection(
        first_start: Point,
        first_end: Point,
        first_offset: Point,
        second_start: Point,
        second_end: Point,
        second_offset: Point,
    ) -> Point:
        first_x = first_start[0] + first_offset[0]
        first_y = first_start[1] + first_offset[1]
        second_x = second_start[0] + second_offset[0]
        second_y = second_start[1] + second_offset[1]
        first_dx = first_end[0] - first_start[0]
        first_dy = first_end[1] - first_start[1]
        second_dx = second_end[0] - second_start[0]
        second_dy = second_end[1] - second_start[1]
        denominator = first_dx * second_dy - first_dy * second_dx
        if abs(denominator) < 1e-9:
            return (
                first_start[0] + first_offset[0] + second_offset[0],
                first_start[1] + first_offset[1] + second_offset[1],
            )
        offset_x = second_x - first_x
        offset_y = second_y - first_y
        factor = (offset_x * second_dy - offset_y * second_dx) / denominator
        return (first_x + first_dx * factor, first_y + first_dy * factor)

    extended_points: list[Point] = []
    for index, point in enumerate(points):
        previous = (index - 1) % len(points)
        following = (index + 1) % len(points)
        extended_points.append(
            shifted_intersection(
                points[previous],
                point,
                edge_offsets[previous],
                point,
                points[following],
                edge_offsets[index],
            )
        )

    cut_left = min(point[0] for point in extended_points)
    cut_right = max(point[0] for point in extended_points)
    cut_bottom = min(point[1] for point in extended_points)
    cut_top = max(point[1] for point in extended_points)

    if compact:
        pad_left = 58.0
        pad_right = 52.0
        pad_top = 58.0
        pad_bottom = 58.0
    else:
        pad_left = 84.0
        pad_right = 78.0
        pad_top = 90.0
        pad_bottom = 90.0
    available_width = max(1.0, x1 - x0 - pad_left - pad_right)
    available_height = max(1.0, y1 - y0 - pad_top - pad_bottom)
    span_x = max(1e-6, cut_right - cut_left)
    span_y = max(1e-6, cut_top - cut_bottom)
    scale = min(available_width / span_x, available_height / span_y)
    scale_center_x = (cut_left + cut_right) / 2.0
    scale_center_y = (cut_bottom + cut_top) / 2.0
    center_screen_x = x0 + pad_left + available_width / 2.0
    center_screen_y = y0 + pad_top + available_height / 2.0

    def to_screen(point: Point) -> Point:
        return (
            center_screen_x + (point[0] - scale_center_x) * scale,
            center_screen_y - (point[1] - scale_center_y) * scale,
        )

    screen = [to_screen(point) for point in points]
    extended_screen = [to_screen(point) for point in extended_points]
    cut_top_screen = to_screen((0.0, cut_top))[1]
    cut_bottom_screen = to_screen((0.0, cut_bottom))[1]
    original_top_screen = to_screen((0.0, max_y))[1]
    original_bottom_screen = to_screen((0.0, min_y))[1]

    color = TAB20[(part.index - 1) % len(TAB20)]
    extended_fill = blend(ALLOWANCE, 0.10 if compact else 0.12, background)
    canvas.create_polygon(
        *[coordinate for point in extended_screen for coordinate in point],
        fill=extended_fill,
        outline=ALLOWANCE,
        width=1,
        dash=(4, 3),
        joinstyle="round",
        tags=(*tags, "part-extended"),
    )
    fill = blend(color, 0.30 if compact else 0.36)
    canvas.create_polygon(
        *[coordinate for point in screen for coordinate in point],
        fill=fill,
        outline=color,
        width=2,
        joinstyle="round",
        tags=tags,
    )

    _draw_part_angles(canvas, screen, part.angles_deg, compact=compact, tags=tags)
    _draw_side_dimensions(
        canvas,
        screen,
        part.edges_cm,
        compact=compact,
        tags=tags,
        background=background,
    )

    dimension_x = x0 + 13.0
    _draw_dimension_line(
        canvas,
        dimension_x,
        cut_top_screen,
        dimension_x,
        cut_bottom_screen,
        (*tags, "cut-dimension"),
        tick=3.0 if compact else 4.0,
    )
    _text_with_background(
        canvas,
        dimension_x - (8.0 if compact else 10.0),
        (cut_top_screen + cut_bottom_screen) / 2.0,
        f"L {_format_length(part.height_cm + fold_top + fold_bottom)}",
        DIMENSION,
        ("Segoe UI", 7 if compact else 9, "bold"),
        angle=90,
        tags=(*tags, "cut-label"),
        background=background,
    )

    top_points = [point for point in points if abs(point[1] - max_y) < 1e-9]
    bottom_points = [point for point in points if abs(point[1] - min_y) < 1e-9]
    top_min_x = min(point[0] for point in top_points)
    top_max_x = max(point[0] for point in top_points)
    bottom_min_x = min(point[0] for point in bottom_points)
    bottom_max_x = max(point[0] for point in bottom_points)
    top_fold_x = top_min_x + (top_max_x - top_min_x) * 0.30
    bottom_fold_x = bottom_min_x + (bottom_max_x - bottom_min_x) * 0.70
    top_fold_screen = to_screen((top_fold_x, max_y))
    bottom_fold_screen = to_screen((bottom_fold_x, min_y))

    if fold_top > 0.0:
        _draw_dimension_line(
            canvas,
            top_fold_screen[0],
            original_top_screen,
            top_fold_screen[0],
            cut_top_screen,
            (*tags, "fold-dimension"),
            tick=3.0 if compact else 4.0,
        )
    if fold_bottom > 0.0:
        _draw_dimension_line(
            canvas,
            bottom_fold_screen[0],
            original_bottom_screen,
            bottom_fold_screen[0],
            cut_bottom_screen,
            (*tags, "fold-dimension"),
            tick=3.0 if compact else 4.0,
        )

    if half_extra > 0.0:
        def edge_x_at(start: Point, end: Point, y: float) -> float:
            if abs(end[1] - start[1]) < 1e-9:
                return (start[0] + end[0]) / 2.0
            factor = (y - start[1]) / (end[1] - start[1])
            return start[0] + factor * (end[0] - start[0])

        def draw_extra(
            original: Point,
            extended: Point,
            side: str,
            *,
            leader: bool = False,
        ) -> None:
            start = to_screen(original)
            end = to_screen(extended)
            if leader and abs(start[1] - end[1]) > 1.0:
                canvas.create_line(
                    start[0],
                    start[1],
                    start[0],
                    end[1],
                    fill=DIMENSION,
                    width=1,
                    dash=(2, 2),
                    tags=(*tags, f"extra-leader-{side}"),
                )
            _draw_dimension_line(
                canvas,
                start[0],
                end[1],
                end[0],
                end[1],
                (*tags, f"extra-dimension-{side}"),
                tick=3.0 if compact else 4.5,
            )
            anchor = "e" if side == "left" else "w"
            text_x = end[0] - 4 if side == "left" else end[0] + 4
            _text_with_background(
                canvas,
                text_x,
                end[1],
                f"+{_format_length(half_extra)}",
                ALLOWANCE,
                ("Segoe UI", 6 if compact else 8, "bold"),
                angle=0,
                tags=(*tags, "extra-label"),
                background=background,
                anchor=anchor,
            )

        base_edge = None
        if len(points) == 3:
            for index in range(3):
                first = points[index]
                second = points[(index + 1) % 3]
                if abs(first[1] - second[1]) < 1e-9:
                    base_edge = (first, second)
                    break

        if base_edge is not None:
            left, right = sorted(base_edge, key=lambda point: point[0])
            base_y = left[1]
            if base_y > center_y:
                extended_base_y = base_y + fold_top
            else:
                extended_base_y = base_y - fold_bottom
            draw_extra(left, (left[0] - half_extra, extended_base_y), "left", leader=True)
            draw_extra(right, (right[0] + half_extra, extended_base_y), "right", leader=True)
        else:
            for fraction, side in ((0.30, "left"), (0.70, "right")):
                y = min_y + (max_y - min_y) * fraction
                if side == "left":
                    original_x = edge_x_at(points[0], points[-1], y)
                    original = (original_x, y)
                    extended = (original_x - half_extra, y)
                else:
                    original_x = edge_x_at(points[1], points[2], y)
                    original = (original_x, y)
                    extended = (original_x + half_extra, y)
                draw_extra(original, extended, side)

    fold_font = ("Segoe UI", 6 if compact else 9, "bold")
    fold_gap = 38.0 if compact else 58.0
    _text_with_background(
        canvas,
        top_fold_screen[0],
        cut_top_screen - fold_gap,
        f"Fv {_format_length(fold_top)}",
        DIMENSION,
        fold_font,
        angle=90,
        tags=(*tags, "fold-label"),
        background=background,
    )
    _text_with_background(
        canvas,
        bottom_fold_screen[0],
        cut_bottom_screen + fold_gap,
        f"Fh {_format_length(fold_bottom)}",
        DIMENSION,
        fold_font,
        angle=90,
        tags=(*tags, "fold-label"),
        background=background,
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
        self.geometry("800x800")
        self.resizable(False, False)
        self.configure(background=BACKGROUND)
        self.transient(master.winfo_toplevel())
        self.canvas = tk.Canvas(
            self,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
            width=792,
            height=792,
        )
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind(
            "<Configure>", lambda _event: self._draw(part, axis, extras)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        root = master.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - 800) // 2
        y = root.winfo_rooty() + (root.winfo_height() - 800) // 2
        self.geometry(f"800x800+{max(0, x)}+{max(0, y)}")
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
                background=CARD_BACKGROUND,
            )
            top += card_height + 8.0

        self.canvas.configure(scrollregion=(0, 0, width, top))
