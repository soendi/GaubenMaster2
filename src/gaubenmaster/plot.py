"""Interaktive Tkinter-Zeichenflaeche fuer Dreieck und Hoehenteilung."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

from .geometry import Part, Point, Triangle

BACKGROUND = "#f6f8fb"
STEELBLUE = "#4682b4"
OUTLINE = "#1857a4"
VERTEX = "#d62728"
ANGLE = "#d62728"
HEIGHT = "#178a3a"
TEXT = "#12263f"

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
        self.hovered: int | None = None
        self.on_hover: Callable[[Part | None], None] | None = None
        self._drag_x: int | None = None
        self._screen_parts: list[tuple[Part, list[Point]]] = []
        self._transform: tuple[float, float, float, float, float] | None = None
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

    def reset_view(self) -> None:
        self.rotation = 0.0
        self.zoom = 1.0
        self.redraw()

    def _on_press(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self.configure(cursor="fleur")

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_x is None:
            return
        delta = event.x - self._drag_x
        self._drag_x = event.x
        self.rotation = (self.rotation + delta * 0.45) % 360.0
        self.redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_x = None
        self.configure(cursor="")

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag_x is not None or not self._screen_parts:
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
        if self._drag_x is None:
            self.configure(cursor="")

    def _on_wheel(self, event: tk.Event) -> None:
        delta = 1.0 if event.delta > 0 else -1.0
        self._zoom_at(event.x, event.y, delta)

    def _zoom_at(self, _x: int, _y: int, direction: float) -> None:
        factor = 1.12 if direction > 0 else 1 / 1.12
        self.zoom = max(0.25, min(8.0, self.zoom * factor))
        self.redraw()

    def _find_part(self, index: int | None) -> Part | None:
        if index is None:
            return None
        return next((part for part in self.parts if part.index == index), None)

    def _build_transform(self) -> tuple[float, float, float, float, float] | None:
        if not self.triangle:
            return None
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
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
        scale = min(width * 0.80 / span_x, height * 0.80 / span_y) * self.zoom
        return center_x, center_y, cosine, sine, scale

    def _to_screen(self, point: Point) -> Point:
        if not self._transform:
            return point
        center_x, center_y, cosine, sine, scale = self._transform
        x, y = point
        dx = x - center_x
        dy = y - center_y
        rotated_x = dx * cosine - dy * sine
        rotated_y = dx * sine + dy * cosine
        return (
            self.winfo_width() / 2.0 + rotated_x * scale,
            self.winfo_height() / 2.0 - rotated_y * scale,
        )

    def _line(self, point1: Point, point2: Point) -> list[float]:
        x1, y1 = self._to_screen(point1)
        x2, y2 = self._to_screen(point2)
        return [x1, y1, x2, y2]

    def redraw(self) -> None:
        self.delete("all")
        self._screen_parts = []
        self._transform = self._build_transform()
        if not self.triangle:
            self.create_text(
                max(1, self.winfo_width()) / 2,
                max(1, self.winfo_height()) / 2,
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

        if self.height_active:
            self._draw_height()

        self._draw_triangle_outline(screen_vertices)
        self._draw_sides()
        self._draw_vertices()
        self._draw_angles()

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
            alpha = 1.0 if self.hovered in (None, part.index) else 0.5
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
        font_size = 8 if len(self.parts) <= 10 else 6
        self.create_text(
            centroid[0],
            centroid[1] - 4,
            text=f"Teil {part.index}\n{part.area_cm2:.2f} cm²",
            fill=label_color,
            font=("Segoe UI", font_size, "bold"),
            justify="center",
        )

        for index, edge in enumerate(part.edges_cm):
            p1 = screen[index]
            p2 = screen[(index + 1) % len(screen)]
            midpoint = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
            dx = midpoint[0] - centroid[0]
            dy = midpoint[1] - centroid[1]
            length = math.hypot(dx, dy) or 1.0
            offset = 8.0
            self.create_text(
                midpoint[0] + dx / length * offset,
                midpoint[1] + dy / length * offset,
                text=f"{edge:.2f}",
                fill=label_color,
                font=("Segoe UI", font_size - 1),
            )

        if len(part.points) <= 4:
            for index, angle in enumerate(part.angles_deg):
                vertex = screen[index]
                dx = centroid[0] - vertex[0]
                dy = centroid[1] - vertex[1]
                length = math.hypot(dx, dy) or 1.0
                distance = 15.0 if len(self.parts) <= 8 else 11.0
                self.create_text(
                    vertex[0] + dx / length * distance,
                    vertex[1] + dy / length * distance,
                    text=f"{angle:.0f}°",
                    fill=label_color,
                    font=("Segoe UI", max(5, font_size - 2)),
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
        self._text_with_background(
            midpoint[0] + 10,
            midpoint[1],
            label,
            HEIGHT,
            ("Segoe UI", 8, "bold"),
            anchor="w",
        )

    def _draw_sides(self) -> None:
        if not self.triangle:
            return
        vertices = self.triangle.vertices
        centroid = (
            sum(point[0] for point in vertices) / 3.0,
            sum(point[1] for point in vertices) / 3.0,
        )
        sides = (
            ("a", vertices[1], vertices[2], self.triangle.a),
            ("b", vertices[2], vertices[0], self.triangle.b),
            ("c", vertices[0], vertices[1], self.triangle.c),
        )
        for name, point1, point2, value in sides:
            midpoint = ((point1[0] + point2[0]) / 2.0, (point1[1] + point2[1]) / 2.0)
            screen = self._to_screen(midpoint)
            center = self._to_screen(centroid)
            dx = screen[0] - center[0]
            dy = screen[1] - center[1]
            length = math.hypot(dx, dy) or 1.0
            offset = 22.0
            self._text_with_background(
                screen[0] + dx / length * offset,
                screen[1] + dy / length * offset,
                f"{name} = {value:.2f} cm",
                "#0b2a55",
                ("Segoe UI", 10, "bold"),
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
            self._text_with_background(
                screen[0] + dx / length * 17,
                screen[1] + dy / length * 17,
                name,
                VERTEX,
                ("Segoe UI", 11, "bold"),
            )

    def _draw_angles(self) -> None:
        if not self.triangle:
            return
        vertices = self.triangle.vertices
        angles = (self.triangle.alpha, self.triangle.beta, self.triangle.gamma)
        names = ("α", "β", "γ")
        for index, (name, angle) in enumerate(zip(names, angles)):
            current = self._to_screen(vertices[index])
            previous = self._to_screen(vertices[index - 1])
            following = self._to_screen(vertices[(index + 1) % 3])
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
                    (current[0] + math.cos(sample) * radius, current[1] + math.sin(sample) * radius)
                )
            self.create_line(*points, fill=ANGLE, width=1.6)
            middle = angle1 + delta / 2.0
            label_radius = radius + 13.0
            self._text_with_background(
                current[0] + math.cos(middle) * label_radius,
                current[1] + math.sin(middle) * label_radius,
                f"{name} {angle:.1f}°",
                ANGLE,
                ("Segoe UI", 8, "bold"),
            )

    def _text_with_background(
        self,
        x: float,
        y: float,
        text: str,
        color: str,
        font: tuple,
        anchor: str = "center",
    ) -> None:
        identifier = self.create_text(
            x,
            y,
            text=text,
            fill=color,
            font=font,
            anchor=anchor,
            justify="center",
        )
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
        )
        self.tag_lower(background, identifier)
