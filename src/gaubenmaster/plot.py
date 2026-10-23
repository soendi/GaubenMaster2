"""Interaktive Tkinter-Zeichenflaeche fuer Dreieck und Hoehenteilung."""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from .formatting import format_area
from .geometry import Part, Point, Triangle

BACKGROUND = "#f6f8fb"
STEELBLUE = "#4682b4"
OUTLINE = "#1857a4"
VERTEX = "#d62728"
ANGLE = "#d62728"
HEIGHT = "#178a3a"
TEXT = "#12263f"

@dataclass(frozen=True)
class DisplayOptions:
    """Sichtbarkeit und Schriftgroesse der Zeichnungsbeschriftungen."""

    main_dimensions: bool = True
    main_angles: bool = True
    main_angle_arcs: bool = True
    part_dimensions: bool = True
    part_angles: bool = True
    part_areas: bool = True
    part_numbers: bool = True
    height: bool = True
    font_size: int = 9


TAB20 = (
    "#1f77b4",
    "#aec7e8",
    "#ff7f0e",
    "#ffbb78",
    "#2ca02c",
    "#98df8a",
    "#d62728",
    "#ff9896",
    "#9467bd",
    "#c5b0d5",
    "#8c564b",
    "#c49c94",
    "#e377c2",
    "#f7b6d2",
    "#7f7f7f",
    "#c7c7c7",
    "#bcbd22",
    "#dbdb8d",
    "#17becf",
    "#9edae5",
)


def blend(color: str, alpha: float, background: str = BACKGROUND) -> str:
    """Simuliert Alpha, weil Tkinter-Canvas keine transparenten Fuellungen kennt."""
    alpha = max(0.0, min(1.0, alpha))
    color = color.lstrip("#")
    background = background.lstrip("#")
    values = []
    for index in (0, 2, 4):
        foreground = int(color[index : index + 2], 16)
        behind = int(background[index : index + 2], 16)
        values.append(round(foreground * alpha + behind * (1.0 - alpha)))
    return "#" + "".join(f"{value:02x}" for value in values)


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    count = len(polygon)
    if count < 3:
        return False
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def _font_for(canvas: tk.Canvas, font: tuple) -> tkfont.Font:
    root = canvas.winfo_toplevel()
    cache = getattr(root, "_gm_font_cache", None)
    if cache is None:
        cache = {}
        setattr(root, "_gm_font_cache", cache)
    key = tuple(font)
    if key not in cache:
        cache[key] = tkfont.Font(root=root, font=font)
    return cache[key]


def _ray_polygon_distance(
    origin: Point,
    direction: Point,
    polygon: list[Point],
    skip_index: int,
) -> float:
    count = len(polygon)
    span = max(
        max(point[0] for point in polygon) - min(point[0] for point in polygon),
        max(point[1] for point in polygon) - min(point[1] for point in polygon),
        1.0,
    )
    ray_length = span * 4.0
    end = (
        origin[0] + direction[0] * ray_length,
        origin[1] + direction[1] * ray_length,
    )
    best = ray_length
    for index in range(count):
        if index == skip_index or (index + 1) % count == skip_index:
            continue
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        denominator = (end[0] - origin[0]) * (y2 - y1) - (end[1] - origin[1]) * (
            x2 - x1
        )
        if abs(denominator) < 1e-9:
            continue
        t = ((x1 - origin[0]) * (y2 - y1) - (y1 - origin[1]) * (x2 - x1)) / denominator
        u = ((x1 - origin[0]) * (end[1] - origin[1]) - (y1 - origin[1]) * (
            end[0] - origin[0]
        )) / denominator
        if t > 1e-6 and -1e-9 <= u <= 1.0 + 1e-9:
            best = min(best, ray_length * t)
    return best


def _fit_angle_label(
    canvas: tk.Canvas,
    polygon: list[Point],
    index: int,
    text: str,
    font: tuple,
) -> tuple[float, float, float]:
    current = polygon[index]
    previous = polygon[index - 1]
    following = polygon[(index + 1) % len(polygon)]
    v1 = (previous[0] - current[0], previous[1] - current[1])
    v2 = (following[0] - current[0], following[1] - current[1])
    angle1 = math.atan2(v1[1], v1[0])
    angle2 = math.atan2(v2[1], v2[0])
    delta = (angle2 - angle1 + math.pi) % (2.0 * math.pi) - math.pi
    middle = angle1 + delta / 2.0
    direction = (math.cos(middle), math.sin(middle))
    ray_length = _ray_polygon_distance(current, direction, polygon, index)

    measured = _font_for(canvas, font)
    text_width = max(1, measured.measure(text))
    text_height = max(1, measured.metrics("linespace"))
    text_angle = math.degrees(middle)
    if text_angle > 90.0:
        text_angle -= 180.0
    elif text_angle <= -90.0:
        text_angle += 180.0
    radians = math.radians(text_angle)
    box_width = abs(text_width * math.cos(radians)) + abs(
        text_height * math.sin(radians)
    )
    box_height = abs(text_width * math.sin(radians)) + abs(
        text_height * math.cos(radians)
    )

    def fits(distance_along: float) -> bool:
        center_x = current[0] + direction[0] * distance_along
        center_y = current[1] + direction[1] * distance_along
        half_width = max(0.5, box_width / 2.0 - 1.0)
        half_height = max(0.5, box_height / 2.0 - 1.0)
        corners = (
            (center_x - half_width, center_y - half_height),
            (center_x + half_width, center_y - half_height),
            (center_x + half_width, center_y + half_height),
            (center_x - half_width, center_y + half_height),
        )
        return all(point_in_polygon(corner, polygon) for corner in corners)

    best = 0.0
    steps = 48
    previous = 0.0
    for step in range(1, steps + 1):
        distance_along = ray_length * step / steps
        if fits(distance_along):
            low = previous
            high = distance_along
            for _ in range(18):
                middle_distance = (low + high) / 2.0
                if fits(middle_distance):
                    high = middle_distance
                else:
                    low = middle_distance
            best = high
            break
        previous = distance_along
    else:
        best = min(ray_length * 0.55, max(10.0, text_width * 0.6))

    center_x = current[0] + direction[0] * best
    center_y = current[1] + direction[1] * best
    return center_x, center_y, -text_angle


def create_angle_label(
    canvas: tk.Canvas,
    polygon: list[Point],
    index: int,
    text: str,
    font: tuple,
    fill: str,
    background: str | None = None,
    tags: tuple[str, ...] = (),
) -> None:
    x, y, angle = _fit_angle_label(canvas, polygon, index, text, font)
    identifier = canvas.create_text(
        x,
        y,
        text=text,
        fill=fill,
        font=font,
        angle=angle,
        justify="center",
        tags=tags,
    )
    if background is None:
        return
    box = canvas.bbox(identifier)
    if not box:
        return
    rectangle = canvas.create_rectangle(
        box[0] - 1,
        box[1] - 1,
        box[2] + 1,
        box[3] + 1,
        fill=background,
        outline="",
        tags=tags,
    )
    canvas.tag_lower(rectangle, identifier)


class TriangleView(tk.Canvas):
    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(
            master,
            background=BACKGROUND,
            highlightthickness=1,
            highlightbackground="#d7deea",
            **kwargs,
        )
        self.triangle: Triangle | None = None
        self.parts: list[Part] = []
        self.height_name = "ha"
        self.height_active = False
        self.rotation = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.options = DisplayOptions()
        self.fit_fraction = 0.80
        self.render_size: tuple[int, int] | None = None
        self.hovered: int | None = None
        self.on_hover: Callable[[Part | None], None] | None = None
        self.on_zoom: Callable[[float], None] | None = None
        self._drag_mode: str | None = None
        self._drag_last: Point | None = None
        self._drag_center: Point | None = None
        self._drag_angle: float | None = None
        self._screen_parts: list[tuple[Part, list[Point]]] = []
        self._labeled_edges: set[
            tuple[tuple[float, float], tuple[float, float]]
        ] = set()
        self._transform: (
            tuple[float, float, float, float, float, float, float] | None
        ) = None
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda event: self._zoom_at(event.x, event.y, 1.0))
        self.bind("<Button-5>", lambda event: self._zoom_at(event.x, event.y, -1.0))

    def set_data(
        self,
        triangle: Triangle | None,
        parts: list[Part] | None = None,
        height_name: str = "ha",
        height_active: bool = False,
    ) -> None:
        self.triangle = triangle
        self.parts = parts or []
        self.height_name = height_name
        self.height_active = height_active
        if not self.parts:
            self.hovered = None
        self.redraw()

    def set_display_options(self, options: DisplayOptions) -> None:
        self.options = options
        self.redraw()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(8.0, zoom))
        self.redraw()

    def _width(self) -> float:
        if self.render_size is not None:
            return float(self.render_size[0])
        return float(max(1, self.winfo_width()))

    def _height(self) -> float:
        if self.render_size is not None:
            return float(self.render_size[1])
        return float(max(1, self.winfo_height()))

    def _label_font(self, *, bold: bool = False) -> tuple[str, int, str]:
        size = max(4, min(72, int(round(self.options.font_size * self.zoom))))
        return ("Segoe UI", size, "bold") if bold else ("Segoe UI", size)

    def reset_view(self) -> None:
        self.rotation = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.redraw()
        if self.on_zoom:
            self.on_zoom(self.zoom)

    def _on_press(self, event: tk.Event) -> None:
        self._drag_last = (event.x, event.y)
        if event.state & 0x0004:
            self._drag_mode = "rotate"
            center = self._screen_center()
            self._drag_center = center
            self._drag_angle = math.atan2(event.y - center[1], event.x - center[0])
            self.configure(cursor="crosshair")
        else:
            self._drag_mode = "pan"
            self.configure(cursor="fleur")

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_mode is None or self._drag_last is None:
            return
        if self._drag_mode == "pan":
            self.pan_x += event.x - self._drag_last[0]
            self.pan_y += event.y - self._drag_last[1]
            self._drag_last = (event.x, event.y)
        elif self._drag_center is not None:
            angle = math.atan2(
                event.y - self._drag_center[1], event.x - self._drag_center[0]
            )
            if self._drag_angle is not None:
                delta = math.degrees(angle - self._drag_angle)
                delta = (delta + 180.0) % 360.0 - 180.0
                self.rotation = (self.rotation + delta) % 360.0
            self._drag_angle = angle
        self.redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self._drag_last = None
        self._drag_center = None
        self._drag_angle = None
        self.configure(cursor="")

    def _screen_center(self) -> Point:
        return (
            self._width() / 2.0 + self.pan_x,
            self._height() / 2.0 + self.pan_y,
        )

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag_mode is not None or not self._screen_parts:
            return
        found: int | None = None
        for part, polygon in reversed(self._screen_parts):
            if point_in_polygon((event.x, event.y), polygon):
                found = part.index
                break
        if found != self.hovered:
            self.hovered = found
            self.configure(cursor="hand2" if found is not None else "")
            part = self._find_part(found)
            if self.on_hover:
                self.on_hover(part)
            self.redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        if self.hovered is not None:
            self.hovered = None
            if self.on_hover:
                self.on_hover(None)
            self.redraw()
        if self._drag_mode is None:
            self.configure(cursor="")

    def _on_wheel(self, event: tk.Event) -> None:
        delta = 1.0 if event.delta > 0 else -1.0
        self._zoom_at(event.x, event.y, delta)

    def _zoom_at(self, _x: int, _y: int, direction: float) -> None:
        factor = 1.12 if direction > 0 else 1 / 1.12
        self.zoom = max(0.25, min(8.0, self.zoom * factor))
        self.redraw()
        if self.on_zoom:
            self.on_zoom(self.zoom)

    def _find_part(self, index: int | None) -> Part | None:
        if index is None:
            return None
        return next((part for part in self.parts if part.index == index), None)

    def _build_transform(self) -> tuple[float, float, float, float, float] | None:
        if not self.triangle:
            return None
        width = self._width()
        height = self._height()
        vertices = self.triangle.vertices
        center_x = sum(point[0] for point in vertices) / 3.0
        center_y = sum(point[1] for point in vertices) / 3.0
        angle = math.radians(self.rotation)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        rotated = []
        for x, y in vertices:
            dx = x - center_x
            dy = y - center_y
            rotated.append((dx * cosine - dy * sine, dx * sine + dy * cosine))
        min_x = min(point[0] for point in rotated)
        max_x = max(point[0] for point in rotated)
        min_y = min(point[1] for point in rotated)
        max_y = max(point[1] for point in rotated)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        scale = min(
            width * self.fit_fraction / span_x,
            height * self.fit_fraction / span_y,
        ) * self.zoom
        bbox_center_x = (min_x + max_x) / 2.0
        bbox_center_y = (min_y + max_y) / 2.0
        return (
            center_x,
            center_y,
            cosine,
            sine,
            scale,
            bbox_center_x,
            bbox_center_y,
        )

    def _to_screen(self, point: Point) -> Point:
        if not self._transform:
            return point
        (
            center_x,
            center_y,
            cosine,
            sine,
            scale,
            bbox_center_x,
            bbox_center_y,
        ) = self._transform
        x, y = point
        dx = x - center_x
        dy = y - center_y
        rotated_x = dx * cosine - dy * sine - bbox_center_x
        rotated_y = dx * sine + dy * cosine - bbox_center_y
        return (
            self._width() / 2.0 + self.pan_x + rotated_x * scale,
            self._height() / 2.0 + self.pan_y - rotated_y * scale,
        )

    def _line(self, point1: Point, point2: Point) -> list[float]:
        x1, y1 = self._to_screen(point1)
        x2, y2 = self._to_screen(point2)
        return [x1, y1, x2, y2]

    def redraw(self) -> None:
        self.delete("all")
        self.create_rectangle(
            0,
            0,
            self._width(),
            self._height(),
            fill=BACKGROUND,
            outline="",
            tags=("canvas-background",),
        )
        self._screen_parts = []
        self._labeled_edges = set()
        self._transform = self._build_transform()
        if not self.triangle:
            self.create_text(
                self._width() / 2,
                self._height() / 2,
                text="Seiten eingeben und „Berechnen“ drücken.",
                fill="#6b7a90",
                font=("Segoe UI", 12),
            )
            return

        screen_vertices = [self._to_screen(point) for point in self.triangle.vertices]
        self.create_polygon(
            *[coordinate for point in screen_vertices for coordinate in point],
            fill=STEELBLUE if not self.parts else "#dbe8f5",
            outline=OUTLINE,
            width=3,
            joinstyle="round",
        )

        if self.height_active and self.parts:
            self._draw_parts()

        if self.height_active and self.options.height:
            self._draw_height()

        self._draw_triangle_outline(screen_vertices)
        if self.options.main_dimensions:
            self._draw_sides()
        self._draw_vertices()
        self._draw_angles(
            show_labels=self.options.main_angles,
            show_arcs=self.options.main_angle_arcs,
        )

    def _draw_triangle_outline(self, screen_vertices: list[Point]) -> None:
        self.create_polygon(
            *[coordinate for point in screen_vertices for coordinate in point],
            fill="",
            outline=OUTLINE,
            width=3,
            joinstyle="round",
        )

    def _draw_parts(self) -> None:
        for part in self.parts:
            screen = [self._to_screen(point) for point in part.points]
            self._screen_parts.append((part, screen))
            alpha = 0.70 if self.hovered == part.index else 0.30
            color = TAB20[(part.index - 1) % len(TAB20)]
            fill = blend(color, alpha)
            outline = blend(color, alpha, "#12324f")
            self.create_polygon(
                *[coordinate for point in screen for coordinate in point],
                fill=fill,
                outline=outline,
                width=2 if self.hovered == part.index else 1,
                joinstyle="round",
            )
            self._draw_part_bounds(part, alpha, color)
            self._draw_part_labels(part, screen, alpha, color)

    def _draw_part_bounds(self, part: Part, alpha: float, color: str) -> None:
        min_x, min_y, max_x, max_y = part.bounds
        corners = [
            self._to_screen((min_x, min_y)),
            self._to_screen((max_x, min_y)),
            self._to_screen((max_x, max_y)),
            self._to_screen((min_x, max_y)),
        ]
        self.create_polygon(
            *[coordinate for point in corners for coordinate in point],
            fill="",
            outline=blend(color, alpha, "#ffffff"),
            width=1,
            dash=(2, 4),
        )

    def _draw_part_labels(
        self, part: Part, screen: list[Point], alpha: float, color: str
    ) -> None:
        centroid = self._to_screen(part.centroid)
        label_color = blend(color, alpha, "#0d1b2a")
        lines: list[str] = []
        if self.options.part_numbers:
            lines.append(f"Teil {part.index}")
        if self.options.part_areas:
            lines.append(format_area(part.area_cm2))
        if lines:
            self.create_text(
                centroid[0],
                centroid[1] - 4,
                text="\n".join(lines),
                fill=label_color,
                font=self._label_font(bold=True),
                justify="center",
            )

        if self.options.part_dimensions:
            for index, edge in enumerate(part.edges_cm):
                p1 = screen[index]
                p2 = screen[(index + 1) % len(screen)]
                key = tuple(
                    sorted(
                        (
                            (round(p1[0], 1), round(p1[1], 1)),
                            (round(p2[0], 1), round(p2[1], 1)),
                        )
                    )
                )
                if key in self._labeled_edges:
                    continue
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                length = math.hypot(dx, dy)
                if length < 1.0:
                    continue
                self._labeled_edges.add(key)
                midpoint = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
                normal_x = -dy / length
                normal_y = dx / length
                toward_x = centroid[0] - midpoint[0]
                toward_y = centroid[1] - midpoint[1]
                if normal_x * toward_x + normal_y * toward_y < 0:
                    normal_x = -normal_x
                    normal_y = -normal_y
                offset = max(8.0, self.options.font_size * self.zoom * 0.95)
                text_angle = math.degrees(math.atan2(dy, dx))
                if text_angle > 90.0:
                    text_angle -= 180.0
                elif text_angle <= -90.0:
                    text_angle += 180.0
                self.create_text(
                    midpoint[0] + normal_x * offset,
                    midpoint[1] + normal_y * offset,
                    text=f"{edge:.2f}",
                    fill=label_color,
                    font=self._label_font(),
                    angle=-text_angle,
                    tags=("part-dimension-label", f"part-dimension-label-{part.index}"),
                )

        if self.options.part_angles:
            for index, angle in enumerate(part.angles_deg):
                if angle <= 1.0 or angle >= 179.0:
                    continue
                create_angle_label(
                    self,
                    screen,
                    index,
                    f"{angle:.1f}°",
                    self._label_font(bold=True),
                    ANGLE,
                    tags=("part-angle-label", f"part-angle-label-{part.index}"),
                )

    def _draw_height(self) -> None:
        if not self.triangle:
            return
        vertex, _base1, _base2 = self.triangle.height_segment(self.height_name)  # type: ignore[arg-type]
        foot = self.triangle.height_foot(self.height_name)  # type: ignore[arg-type]
        start = self._to_screen(vertex)
        end = self._to_screen(foot)
        self.create_line(
            *start,
            *end,
            fill=HEIGHT,
            width=2,
            dash=(7, 4),
        )
        radius = 4
        self.create_oval(
            end[0] - radius,
            end[1] - radius,
            end[0] + radius,
            end[1] + radius,
            fill=HEIGHT,
            outline="#0b5e26",
        )
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        label = f"{self.height_name} = {self.triangle.height(self.height_name):.2f} cm"  # type: ignore[arg-type]
        text_angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
        if text_angle > 90.0:
            text_angle -= 180.0
        elif text_angle <= -90.0:
            text_angle += 180.0

        vertex, base1, base2 = self.triangle.height_segment(self.height_name)  # type: ignore[arg-type]
        base1_screen = self._to_screen(base1)
        base2_screen = self._to_screen(base2)
        foot_distance = min(
            math.hypot(end[0] - base1_screen[0], end[1] - base1_screen[1]),
            math.hypot(end[0] - base2_screen[0], end[1] - base2_screen[1]),
        )
        label_x, label_y = midpoint
        if foot_distance < 8.0:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                normal_x = -dy / length
                normal_y = dx / length
                screen_vertices = [
                    self._to_screen(point) for point in self.triangle.vertices
                ]
                centroid = (
                    sum(point[0] for point in screen_vertices) / 3.0,
                    sum(point[1] for point in screen_vertices) / 3.0,
                )
                if normal_x * (centroid[0] - midpoint[0]) + normal_y * (
                    centroid[1] - midpoint[1]
                ) > 0.0:
                    normal_x = -normal_x
                    normal_y = -normal_y
                label_x += normal_x * 74.0
                label_y += normal_y * 74.0

        self._text_with_background(
            label_x,
            label_y,
            label,
            HEIGHT,
            self._label_font(bold=True),
            angle=-text_angle,
            tags=("height-label",),
        )

    def _draw_sides(self) -> None:
        if not self.triangle:
            return
        vertices = self.triangle.vertices
        screen_vertices = [self._to_screen(point) for point in vertices]
        centroid = (
            sum(point[0] for point in screen_vertices) / 3.0,
            sum(point[1] for point in screen_vertices) / 3.0,
        )
        sides = (
            ("a", 1, 2, self.triangle.a),
            ("b", 2, 0, self.triangle.b),
            ("c", 0, 1, self.triangle.c),
        )
        for name, index1, index2, value in sides:
            point1 = screen_vertices[index1]
            point2 = screen_vertices[index2]
            dx = point2[0] - point1[0]
            dy = point2[1] - point1[1]
            length = math.hypot(dx, dy)
            if length < 1.0:
                continue
            normal_x = -dy / length
            normal_y = dx / length
            midpoint = (
                (point1[0] + point2[0]) / 2.0,
                (point1[1] + point2[1]) / 2.0,
            )
            if normal_x * (midpoint[0] - centroid[0]) + normal_y * (
                midpoint[1] - centroid[1]
            ) < 0.0:
                normal_x = -normal_x
                normal_y = -normal_y

            offset = 54.0
            line_start = (
                point1[0] + normal_x * offset,
                point1[1] + normal_y * offset,
            )
            line_end = (
                point2[0] + normal_x * offset,
                point2[1] + normal_y * offset,
            )
            self.create_line(
                *line_start,
                *line_end,
                fill="#0b2a55",
                width=1,
                tags=("side-dimension", f"side-dimension-{name}"),
            )
            for endpoint in (line_start, line_end):
                self.create_line(
                    endpoint[0] - normal_x * 3.0,
                    endpoint[1] - normal_y * 3.0,
                    endpoint[0] + normal_x * 3.0,
                    endpoint[1] + normal_y * 3.0,
                    fill="#0b2a55",
                    width=1,
                    tags=("side-tick", f"side-tick-{name}"),
                )

            text_angle = math.degrees(math.atan2(dy, dx))
            if text_angle > 90.0:
                text_angle -= 180.0
            elif text_angle <= -90.0:
                text_angle += 180.0
            self._text_with_background(
                (line_start[0] + line_end[0]) / 2.0,
                (line_start[1] + line_end[1]) / 2.0,
                f"{name} = {value:.2f} cm",
                "#0b2a55",
                self._label_font(bold=True),
                angle=-text_angle,
                tags=("side-label", f"side-label-{name}"),
                background=False,
            )

    def _draw_vertices(self) -> None:
        if not self.triangle:
            return
        vertices = self.triangle.vertices
        centroid = (
            sum(point[0] for point in vertices) / 3.0,
            sum(point[1] for point in vertices) / 3.0,
        )
        for name, point in zip(("A", "B", "C"), vertices):
            screen = self._to_screen(point)
            center = self._to_screen(centroid)
            radius = 6
            self.create_oval(
                screen[0] - radius,
                screen[1] - radius,
                screen[0] + radius,
                screen[1] + radius,
                fill=VERTEX,
                outline="#8f1111",
            )
            dx = screen[0] - center[0]
            dy = screen[1] - center[1]
            length = math.hypot(dx, dy) or 1.0
            self.create_text(
                screen[0] + dx / length * 17,
                screen[1] + dy / length * 17,
                text=name,
                fill=VERTEX,
                font=self._label_font(bold=True),
                justify="center",
                tags=("vertex-label",),
            )

    def _draw_angles(
        self, *, show_labels: bool = True, show_arcs: bool = True
    ) -> None:
        if not self.triangle or not (show_labels or show_arcs):
            return
        vertices = self.triangle.vertices
        screen_vertices = [self._to_screen(point) for point in vertices]
        angles = (self.triangle.alpha, self.triangle.beta, self.triangle.gamma)
        for index, angle in enumerate(angles):
            current = screen_vertices[index]
            previous = screen_vertices[index - 1]
            following = screen_vertices[(index + 1) % 3]
            v1 = (previous[0] - current[0], previous[1] - current[1])
            v2 = (following[0] - current[0], following[1] - current[1])
            length1 = math.hypot(*v1) or 1.0
            length2 = math.hypot(*v2) or 1.0
            radius = max(16.0, min(34.0, min(length1, length2) * 0.20))
            angle1 = math.atan2(v1[1], v1[0])
            angle2 = math.atan2(v2[1], v2[0])
            delta = (angle2 - angle1 + math.pi) % (2.0 * math.pi) - math.pi
            points: list[float] = []
            for step in range(17):
                sample = angle1 + delta * step / 16.0
                points.extend(
                    (
                        current[0] + math.cos(sample) * radius,
                        current[1] + math.sin(sample) * radius,
                    )
                )
            if show_arcs:
                self.create_line(
                    *points, fill=ANGLE, width=1.6, tags=("angle-arc",)
                )
            if not show_labels:
                continue
            create_angle_label(
                self,
                screen_vertices,
                index,
                f"{angle:.1f}°",
                self._label_font(bold=True),
                "#ffffff",
                tags=("angle-label",),
            )

    def _text_with_background(
        self,
        x: float,
        y: float,
        text: str,
        color: str,
        font: tuple,
        anchor: str = "center",
        angle: float = 0.0,
        tags: tuple[str, ...] = (),
        background: bool = True,
    ) -> None:
        identifier = self.create_text(
            x,
            y,
            text=text,
            fill=color,
            font=font,
            anchor=anchor,
            justify="center",
            angle=angle,
            tags=tags,
        )
        if not background:
            return
        box = self.bbox(identifier)
        if not box:
            return
        background = self.create_rectangle(
            box[0] - 2,
            box[1] - 1,
            box[2] + 2,
            box[3] + 1,
            fill=BACKGROUND,
            outline="",
            tags=tags,
        )
        self.tag_lower(background, identifier)
