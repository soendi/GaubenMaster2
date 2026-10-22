"""Geometrie fuer Dreiecke und die gaubenspezifische Hoehenteilung.

Alle Laengen sind in Zentimetern, Winkel in Grad. Das Modul ist frei von
Tkinter und damit direkt testbar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal

Point = tuple[float, float]
HeightName = Literal["ha", "hb", "hc"]
SplitMode = Literal["count", "length"]

EPSILON = 1e-9
MIN_PARTS = 2
MAX_PARTS = 20
MAX_SPLIT_PARTS = 200
MIN_PART_LENGTH = 0.1
MAX_PART_LENGTH = 50.0


class GeometryError(ValueError):
    """Ungueltige Eingaben oder nicht teilbare Geometrie."""


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise GeometryError(f"Seite {name} muss eine endliche Zahl sein.")
    return number


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def distance(p1: Point, p2: Point) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def polygon_area(points: Iterable[Point]) -> float:
    values = list(points)
    if len(values) < 3:
        return 0.0
    total = 0.0
    for index, (x1, y1) in enumerate(values):
        x2, y2 = values[(index + 1) % len(values)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def polygon_centroid(points: Iterable[Point]) -> Point:
    values = list(points)
    if not values:
        raise GeometryError("Ein Teilstueck besitzt keine Punkte.")
    area = 0.0
    cx = 0.0
    cy = 0.0
    for index, (x1, y1) in enumerate(values):
        x2, y2 = values[(index + 1) % len(values)]
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < EPSILON:
        return (
            sum(point[0] for point in values) / len(values),
            sum(point[1] for point in values) / len(values),
        )
    area *= 0.5
    return (cx / (6.0 * area), cy / (6.0 * area))


def polygon_angles(points: Iterable[Point]) -> list[float]:
    values = list(points)
    result: list[float] = []
    for index, current in enumerate(values):
        previous = values[index - 1]
        following = values[(index + 1) % len(values)]
        v1 = (previous[0] - current[0], previous[1] - current[1])
        v2 = (following[0] - current[0], following[1] - current[1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < EPSILON or n2 < EPSILON:
            result.append(0.0)
            continue
        cosine = _clamp((v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2), -1.0, 1.0)
        result.append(math.degrees(math.acos(cosine)))
    return result


def _dedupe(points: Iterable[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if not result or distance(result[-1], point) > EPSILON:
            result.append(point)
    if len(result) > 1 and distance(result[0], result[-1]) <= EPSILON:
        result.pop()
    return result


@dataclass(frozen=True)
class Part:
    index: int
    points: tuple[Point, ...]
    height_cm: float
    area_cm2: float
    edges_cm: tuple[float, ...]
    angles_deg: tuple[float, ...]
    centroid: Point

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise GeometryError("Ein Teilstueck braucht mindestens drei Punkte.")
        if len(self.edges_cm) != len(self.points):
            raise GeometryError("Kanten und Punkte passen nicht zusammen.")
        if len(self.angles_deg) != len(self.points):
            raise GeometryError("Winkel und Punkte passen nicht zusammen.")

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class Triangle:
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    area: float
    perimeter: float
    semiperimeter: float
    inradius: float
    circumradius: float
    ha: float
    hb: float
    hc: float
    vertices: tuple[Point, Point, Point]

    def height(self, name: HeightName) -> float:
        return {"ha": self.ha, "hb": self.hb, "hc": self.hc}[name]

    def side(self, name: str) -> float:
        return {"a": self.a, "b": self.b, "c": self.c}[name]

    def height_segment(self, name: HeightName) -> tuple[Point, Point, Point]:
        """Liefert (Spitze, Basispunkt 1, Basispunkt 2) der gewaehlten Hoehe."""
        vertices = self.vertices
        if name == "ha":
            return vertices[0], vertices[1], vertices[2]
        if name == "hb":
            return vertices[1], vertices[2], vertices[0]
        return vertices[2], vertices[0], vertices[1]

    def height_foot(self, name: HeightName) -> Point:
        vertex, base1, base2 = self.height_segment(name)
        dx = base2[0] - base1[0]
        dy = base2[1] - base1[1]
        denominator = dx * dx + dy * dy
        if denominator < EPSILON:
            return base1
        t = ((vertex[0] - base1[0]) * dx + (vertex[1] - base1[1]) * dy) / denominator
        return (base1[0] + t * dx, base1[1] + t * dy)

    def split_height(
        self,
        name: HeightName,
        mode: SplitMode,
        value: float,
    ) -> list[Part]:
        height = self.height(name)
        if height < EPSILON:
            raise GeometryError("Die gewaehlte Hoehe ist zu klein zum Teilen.")
        number = float(value)
        if not math.isfinite(number):
            raise GeometryError("Der Teilungswert muss eine endliche Zahl sein.")

        fractions: list[float] = [0.0]
        if mode == "count":
            count = int(round(number))
            if abs(number - count) > EPSILON:
                raise GeometryError("Die Anzahl Teile muss eine ganze Zahl sein.")
            if not MIN_PARTS <= count <= MAX_PARTS:
                raise GeometryError(
                    f"Die Anzahl Teile muss zwischen {MIN_PARTS} und {MAX_PARTS} liegen."
                )
            fractions = [index / count for index in range(count + 1)]
        elif mode == "length":
            if not MIN_PART_LENGTH - EPSILON <= number <= MAX_PART_LENGTH + EPSILON:
                raise GeometryError(
                    f"Die Teillaenge muss zwischen {MIN_PART_LENGTH:g} und "
                    f"{MAX_PART_LENGTH:g} cm liegen."
                )
            count = max(1, math.ceil((height - EPSILON) / number))
            if count > MAX_SPLIT_PARTS:
                raise GeometryError(
                    f"Die Teilung ergibt mehr als {MAX_SPLIT_PARTS} Teile. "
                    "Bitte eine groessere Teillaenge waehlen."
                )
            position = 0.0
            while position < height - EPSILON:
                position = min(height, position + number)
                fractions.append(position / height)
        else:
            raise GeometryError("Unbekannter Teilungsmodus.")

        if fractions[-1] < 1.0 - EPSILON:
            fractions.append(1.0)
        fractions[-1] = 1.0

        vertex, base1, base2 = self.height_segment(name)
        parts: list[Part] = []
        for index, (start, end) in enumerate(zip(fractions, fractions[1:]), start=1):
            if end - start < EPSILON:
                continue
            p0 = (
                base1[0] + start * (vertex[0] - base1[0]),
                base1[1] + start * (vertex[1] - base1[1]),
            )
            q0 = (
                base2[0] + start * (vertex[0] - base2[0]),
                base2[1] + start * (vertex[1] - base2[1]),
            )
            p1 = (
                base1[0] + end * (vertex[0] - base1[0]),
                base1[1] + end * (vertex[1] - base1[1]),
            )
            q1 = (
                base2[0] + end * (vertex[0] - base2[0]),
                base2[1] + end * (vertex[1] - base2[1]),
            )
            points = _dedupe((p0, q0, q1, p1))
            edges = tuple(
                distance(points[pos], points[(pos + 1) % len(points)])
                for pos in range(len(points))
            )
            angles = tuple(polygon_angles(points))
            parts.append(
                Part(
                    index=index,
                    points=tuple(points),
                    height_cm=(end - start) * height,
                    area_cm2=polygon_area(points),
                    edges_cm=edges,
                    angles_deg=angles,
                    centroid=polygon_centroid(points),
                )
            )
        return parts


def calculate_triangle(a: float, b: float, c: float) -> Triangle:
    """Berechnet alle Dreiecksgroessen und validiert die Dreiecksungleichung."""
    a = _finite(a, "a")
    b = _finite(b, "b")
    c = _finite(c, "c")
    if a <= 0 or b <= 0 or c <= 0:
        raise GeometryError("Alle Seiten muessen groesser als 0 cm sein.")
    if a + b <= c + EPSILON:
        raise GeometryError("Ungueltig: a + b muss groesser als c sein.")
    if a + c <= b + EPSILON:
        raise GeometryError("Ungueltig: a + c muss groesser als b sein.")
    if b + c <= a + EPSILON:
        raise GeometryError("Ungueltig: b + c muss groesser als a sein.")

    alpha = math.degrees(
        math.acos(_clamp((b * b + c * c - a * a) / (2.0 * b * c), -1.0, 1.0))
    )
    beta = math.degrees(
        math.acos(_clamp((a * a + c * c - b * b) / (2.0 * a * c), -1.0, 1.0))
    )
    gamma = 180.0 - alpha - beta
    semiperimeter = (a + b + c) / 2.0
    area = math.sqrt(
        max(0.0, semiperimeter * (semiperimeter - a) * (semiperimeter - b) * (semiperimeter - c))
    )
    if area < EPSILON:
        raise GeometryError("Die Seiten bilden kein Dreieck mit einer Flaeche.")

    ax = (c * c + a * a - b * b) / (2.0 * a)
    ay_square = c * c - ax * ax
    if ay_square < -EPSILON:
        raise GeometryError("Die Seiten bilden kein gueltiges Dreieck.")
    ay = math.sqrt(max(0.0, ay_square))
    vertices = ((ax, ay), (0.0, 0.0), (a, 0.0))

    return Triangle(
        a=a,
        b=b,
        c=c,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        area=area,
        perimeter=a + b + c,
        semiperimeter=semiperimeter,
        inradius=area / semiperimeter,
        circumradius=(a * b * c) / (4.0 * area),
        ha=2.0 * area / a,
        hb=2.0 * area / b,
        hc=2.0 * area / c,
        vertices=vertices,
    )
