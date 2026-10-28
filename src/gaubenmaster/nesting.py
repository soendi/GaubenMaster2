"""2D-Polygon-Nesting fuer GaubenMaster2.

Der Algorithmus platziert bis zu 20 Polygone (Vierecke, Dreiecke und andere
Formen) auf einem Materialband mit fester Breite (100 cm). Bewertet werden
zwei Ziele gemeinsam: die benoetigte Materiallaenge (Verschnitt) und die
modellierte Zahl manueller Schnittvorgaenge. Alle Masse sind Zentimeter; das
Koordinatensystem hat den Ursprung oben links, X zeigt nach rechts, Y nach
unten.

Das Modul ist frei von Tkinter und damit direkt testbar. Die Suche laeuft in
vier Drehungsphasen, die reine Suchprioritaeten sind:

* Phase A: 0 und 180 Grad (paarweise Passung gerader/ungerader Teile).
* Phase B: 0, 90, 180 und 270 Grad (Vierteldrehungen).
* Phase C: zusaetzliche Winkel mit grober, danach feiner Schrittweite.
* Phase D: gemischte Drehungen innerhalb einer Anordnung.

Keine Phase schliesst eine spaeter gefundene bessere Gesamtloesung aus: alle
vollstaendigen Anordnungen konkurrieren am Ende ueber die gewaehlte
Bewertungsregel (Verschnitt, Schnittanzahl oder ausgewogen).

Die Geometriepruefung arbeitet auf den tatsaechlichen Polygonkonturen.
Konvexe Polygone werden per Separating-Axis-Theorem geprueft, konkave
Polygone vorher per Ohrenschneiden trianguliert. Beruehrungen an Kanten und
Punkten sind zulaessig (idealisierte Konturen ohne Schnittfuge).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from gaubenmaster.cutmodel import (
    CutAssumptions,
    CutModelError,
    CutPlan,
    compute_cut_plan,
)

Point = tuple[float, float]
Polygon = tuple[Point, ...]

STRIP_WIDTH_CM = 100.0
GEOMETRY_TOLERANCE = 1e-7
ANGLE_TOLERANCE = 1e-6
MIN_ANGLE_STEP_DEG = 0.5

COARSE_ANGLE_STEP_DEG = 10.0
FINE_ANGLE_STEP_DEG = 1.0

MAX_LAYOUTS_KEPT = 24
MAX_PARETO_KEPT = 8
PROGRESS_EMIT_INTERVAL_S = 0.02
PROGRESS_ATTEMPT_INTERVAL = 41

SCORING_WASTE = "waste"
SCORING_CUTS = "cuts"
SCORING_BALANCED = "balanced"
SCORING_MODES = (SCORING_BALANCED, SCORING_WASTE, SCORING_CUTS)
SCORING_LABELS = {
    SCORING_BALANCED: "Ausgewogen (Verschnitt + Schnitte)",
    SCORING_WASTE: "Verschnitt priorisieren",
    SCORING_CUTS: "Schnittanzahl priorisieren",
}

PLACEMENT_COMPACT = "compact"
PLACEMENT_COLUMN = "column"
PLACEMENT_ROW = "row"
PLACEMENT_MODES = (PLACEMENT_COMPACT, PLACEMENT_COLUMN, PLACEMENT_ROW)


class NestingError(ValueError):
    """Ungueltige Eingabepolygone oder nicht platzierbare Teile."""


class _StopSearch(Exception):
    """Interner Abbruch (Zeitbudget, Abbruchknopf oder Kandidatenlimit)."""


class _Unplaceable(Exception):
    def __init__(self, part_index: int, angle_hint: str) -> None:
        super().__init__(part_index)
        self.part_index = part_index
        self.angle_hint = angle_hint


# ---------------------------------------------------------------------------
# Grundlegende Geometrie
# ---------------------------------------------------------------------------


def _signed_area(points: Sequence[Point]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_area(points: Sequence[Point]) -> float:
    return abs(_signed_area(points))


def polygon_perimeter(points: Sequence[Point]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def polygon_bounds(points: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_centroid(points: Sequence[Point]) -> Point:
    area = _signed_area(points)
    if abs(area) < GEOMETRY_TOLERANCE:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    cx = 0.0
    cy = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * area), cy / (6.0 * area))


def dedupe_points(points: Iterable[Point]) -> list[Point]:
    """Entfernt aufeinanderfolgende Duplikate (ohne die Kontur zu veraendern)."""
    result: list[Point] = []
    for x, y in points:
        point = (float(x), float(y))
        if not result or math.hypot(point[0] - result[-1][0], point[1] - result[-1][1]) > 1e-9:
            result.append(point)
    if len(result) > 1:
        first, last = result[0], result[-1]
        if math.hypot(first[0] - last[0], first[1] - last[1]) <= 1e-9:
            result.pop()
    return result


def rotate_points(points: Sequence[Point], angle_deg: float) -> list[Point]:
    if abs(angle_deg % 360.0) < ANGLE_TOLERANCE:
        return [(float(x), float(y)) for x, y in points]
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return [
        (x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in points
    ]


def translate_points(points: Sequence[Point], dx: float, dy: float) -> Polygon:
    return tuple((x + dx, y + dy) for x, y in points)


def normalize_points(points: Sequence[Point]) -> list[Point]:
    min_x, min_y, _max_x, _max_y = polygon_bounds(points)
    return [(x - min_x, y - min_y) for x, y in points]


def _cross(origin: Point, first: Point, second: Point) -> float:
    return (first[0] - origin[0]) * (second[1] - origin[1]) - (
        first[1] - origin[1]
    ) * (second[0] - origin[0])


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    if abs(_cross(start, end, point)) > 1e-9:
        return False
    return (
        min(start[0], end[0]) - 1e-9 <= point[0] <= max(start[0], end[0]) + 1e-9
        and min(start[1], end[1]) - 1e-9 <= point[1] <= max(start[1], end[1]) + 1e-9
    )


def _segments_intersect(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    d1 = _cross(first_start, first_end, second_start)
    d2 = _cross(first_start, first_end, second_end)
    d3 = _cross(second_start, second_end, first_start)
    d4 = _cross(second_start, second_end, first_end)

    if ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and (
        (d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9)
    ):
        return True
    if abs(d1) <= 1e-9 and _point_on_segment(second_start, first_start, first_end):
        return True
    if abs(d2) <= 1e-9 and _point_on_segment(second_end, first_start, first_end):
        return True
    if abs(d3) <= 1e-9 and _point_on_segment(first_start, second_start, second_end):
        return True
    if abs(d4) <= 1e-9 and _point_on_segment(first_end, second_start, second_end):
        return True
    return False


def is_simple_polygon(points: Sequence[Point]) -> bool:
    count = len(points)
    if count < 3:
        return False
    for first in range(count):
        first_start = points[first]
        first_end = points[(first + 1) % count]
        if math.hypot(first_end[0] - first_start[0], first_end[1] - first_start[1]) <= 1e-9:
            return False
        for second in range(first + 1, count):
            if second == first or second == (first + 1) % count:
                continue
            if first == (second + 1) % count:
                continue
            second_start = points[second]
            second_end = points[(second + 1) % count]
            if _segments_intersect(first_start, first_end, second_start, second_end):
                return False
    return True


def is_convex_polygon(points: Sequence[Point]) -> bool:
    count = len(points)
    if count < 3:
        return False
    direction = 0
    for index in range(count):
        turn = _cross(
            points[index - 1], points[index], points[(index + 1) % count]
        )
        if abs(turn) <= 1e-9:
            continue
        sign = 1 if turn > 0 else -1
        if direction == 0:
            direction = sign
        elif sign != direction:
            return False
    return True


def _point_in_triangle(point: Point, a: Point, b: Point, c: Point) -> bool:
    d1 = _cross(a, b, point)
    d2 = _cross(b, c, point)
    d3 = _cross(c, a, point)
    has_negative = d1 < -1e-9 or d2 < -1e-9 or d3 < -1e-9
    has_positive = d1 > 1e-9 or d2 > 1e-9 or d3 > 1e-9
    return not (has_negative and has_positive)


def triangulate_polygon(points: Sequence[Point]) -> tuple[Polygon, ...]:
    """Zerlegt ein einfaches Polygon per Ohrenschneiden in Dreiecke."""
    vertices = [(float(x), float(y)) for x, y in points]
    if _signed_area(vertices) < 0.0:
        vertices.reverse()
    indices = list(range(len(vertices)))
    triangles: list[Polygon] = []
    guard = 0
    while len(indices) > 3 and guard <= len(vertices) * len(vertices):
        guard += 1
        ear_found = False
        for position in range(len(indices)):
            previous = indices[position - 1]
            current = indices[position]
            following = indices[(position + 1) % len(indices)]
            a = vertices[previous]
            b = vertices[current]
            c = vertices[following]
            if _cross(a, b, c) <= 1e-12:
                continue
            blocked = False
            for other in indices:
                if other in (previous, current, following):
                    continue
                candidate = vertices[other]
                if _point_in_triangle(candidate, a, b, c):
                    blocked = True
                    break
            if blocked:
                continue
            triangles.append((a, b, c))
            indices.pop(position)
            ear_found = True
            break
        if not ear_found:
            break
    if len(indices) == 3:
        triangles.append(tuple(vertices[index] for index in indices))
    if not triangles and len(vertices) >= 3:
        # Sicherheitsnetz: Faecherzerlegung, falls kein Ohr gefunden wurde.
        triangles = [
            (vertices[0], vertices[index], vertices[index + 1])
            for index in range(1, len(vertices) - 1)
        ]
    if not triangles:
        triangles.append(tuple(vertices))
    return tuple(triangles)


def _project(points: Sequence[Point], axis: Point) -> tuple[float, float]:
    values = [x * axis[0] + y * axis[1] for x, y in points]
    return min(values), max(values)


def _convex_overlap(first: Sequence[Point], second: Sequence[Point]) -> bool:
    for polygon in (first, second):
        count = len(polygon)
        for index in range(count):
            x1, y1 = polygon[index]
            x2, y2 = polygon[(index + 1) % count]
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 1e-12:
                continue
            axis = (-dy / length, dx / length)
            first_min, first_max = _project(first, axis)
            second_min, second_max = _project(second, axis)
            if (
                first_max <= second_min + GEOMETRY_TOLERANCE
                or second_max <= first_min + GEOMETRY_TOLERANCE
            ):
                return False
    return True


def _bbox_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] <= second[0] + GEOMETRY_TOLERANCE
        or second[2] <= first[0] + GEOMETRY_TOLERANCE
        or first[3] <= second[1] + GEOMETRY_TOLERANCE
        or second[3] <= first[1] + GEOMETRY_TOLERANCE
    )


@dataclass(frozen=True)
class Solid:
    """Polygon mit vorbereiteter Kollisionspruefung."""

    outline: Polygon
    bounds: tuple[float, float, float, float]
    convex: bool
    triangles: tuple[Polygon, ...]

    @classmethod
    def from_polygon(cls, points: Sequence[Point]) -> "Solid":
        outline = tuple((float(x), float(y)) for x, y in points)
        convex = is_convex_polygon(outline)
        triangles = () if convex else triangulate_polygon(outline)
        return cls(
            outline=outline,
            bounds=polygon_bounds(outline),
            convex=convex,
            triangles=triangles,
        )


def solids_overlap(first: Solid, second: Solid) -> bool:
    if not _bbox_overlap(first.bounds, second.bounds):
        return False
    if first.convex and second.convex:
        return _convex_overlap(first.outline, second.outline)
    first_parts = (first.outline,) if first.convex else first.triangles
    second_parts = (second.outline,) if second.convex else second.triangles
    for left in first_parts:
        for right in second_parts:
            if _convex_overlap(left, right):
                return True
    return False


def polygons_overlap(first: Sequence[Point], second: Sequence[Point]) -> bool:
    """Prueft echte Ueberschneidung; gemeinsame Kanten/Punkte sind erlaubt."""
    return solids_overlap(
        Solid.from_polygon(first), Solid.from_polygon(second)
    )


# ---------------------------------------------------------------------------
# Eingabeformen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """Ein zu platzierendes Teil in lokalen, normierten Koordinaten."""

    part_index: int
    outline: Polygon
    area: float
    perimeter: float
    width: float
    height: float

    @classmethod
    def from_polygon(
        cls, part_index: int, points: Sequence[Point], *, label: str | None = None
    ) -> "Shape":
        name = label or f"Teil {part_index}"
        cleaned = dedupe_points(points)
        if len(cleaned) < 3:
            raise NestingError(f"{name} hat weniger als drei Eckpunkte.")
        for x, y in cleaned:
            if not (math.isfinite(x) and math.isfinite(y)):
                raise NestingError(f"{name} enthaelt ungueltige Koordinaten.")
        if not is_simple_polygon(cleaned):
            raise NestingError(
                f"{name} ist kein einfaches Polygon (Selbstueberschneidung)."
            )
        area = polygon_area(cleaned)
        if area <= 1e-9:
            raise NestingError(f"{name} hat keine messbare Flaeche.")
        min_x, min_y, max_x, max_y = polygon_bounds(cleaned)
        width = max_x - min_x
        height = max_y - min_y
        if width <= 1e-9 and height <= 1e-9:
            raise NestingError(f"{name} hat keine messbare Ausdehnung.")
        normalized = tuple((x - min_x, y - min_y) for x, y in cleaned)
        return cls(
            part_index=part_index,
            outline=normalized,
            area=area,
            perimeter=polygon_perimeter(normalized),
            width=width,
            height=height,
        )


@dataclass(frozen=True)
class Placement:
    """Platzierung eines Teils in absoluten Materialkoordinaten."""

    part_index: int
    polygon: Polygon
    angle: float
    area: float
    bounds: tuple[float, float, float, float]

    @property
    def x(self) -> float:
        return self.bounds[0]

    @property
    def y(self) -> float:
        return self.bounds[1]

    @property
    def width(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> float:
        return self.bounds[3] - self.bounds[1]

    @property
    def is_right_angle(self) -> bool:
        angle = self.angle % 360.0
        return (
            abs(angle) < ANGLE_TOLERANCE
            or abs(angle - 180.0) < ANGLE_TOLERANCE
            or abs(angle - 360.0) < ANGLE_TOLERANCE
        )


def _is_quarter_angle(angle: float) -> bool:
    normalized = angle % 360.0
    return any(
        abs(normalized - target) <= 1e-4
        for target in (0.0, 90.0, 180.0, 270.0, 360.0)
    )


def score_layout(
    layout: Layout,
    mode: str = SCORING_BALANCED,
    waste_weight: float = 0.5,
    cut_weight: float = 0.5,
) -> float:
    """Bewertung einer Anordnung fuer den gewaehlten Modus.

    Die ausgewogene Regel normalisiert beide Ziele an ihren unteren Schranken:

    * ``waste_excess = (Laenge - Mindestlaenge) / Mindestlaenge`` mit
      ``Mindestlaenge = Summe der Polygonflaechen / Materialbreite``.
    * ``cut_excess = (Schnitte - Untergrenze) / Untergrenze`` mit
      ``Untergrenze = max(1, Teile - gemeinsam genutzte Linien)``.

    Damit wird kein Schnitt in eine feste Zentimeterzahl umgerechnet; beide
    Ziele gehen als relative Verschlechterung gegenueber ihrer Untergrenze
    ein. Die Schnitt-Untergrenze ist dabei ``1`` (eine zusammenhaengende
    Kontur) und wird auf ``Teile - 1`` bezogen, damit die Bewertung nicht
    davon abhaengt, wie viele gemeinsame Linien eine Anordnung zufaellig hat.
    ``waste_weight``/``cut_weight`` gewichten beide Ziele (Standard 0.5/0.5).
    """
    minimum = layout.min_length
    waste_excess = 0.0
    if minimum > 1e-9:
        waste_excess = max(0.0, layout.length - minimum) / minimum
    plan = layout.cut_plan
    parts = len(layout.items)
    baseline = 1 if parts > 0 else 0
    cut_excess = max(0, plan.operations - baseline) / max(1, parts - baseline)
    if mode == SCORING_WASTE:
        return waste_excess
    if mode == SCORING_CUTS:
        return cut_excess
    total_weight = waste_weight + cut_weight
    if total_weight <= 1e-12:
        total_weight = 1.0
    return (
        waste_weight * waste_excess + cut_weight * cut_excess
    ) / total_weight


def ranking_key(
    layout: Layout,
    mode: str = SCORING_BALANCED,
    waste_weight: float = 0.5,
    cut_weight: float = 0.5,
) -> tuple[float, ...]:
    """Sortierschluessel passend zum Bewertungsmodus."""
    score = score_layout(layout, mode, waste_weight, cut_weight)
    operations = layout.cut_operations
    if mode == SCORING_WASTE:
        return (round(layout.length, 6), operations, round(score, 9))
    if mode == SCORING_CUTS:
        return (operations, round(layout.length, 6), round(score, 9))
    return (round(score, 9), round(layout.length, 6), operations)


def pareto_front(
    layouts: Iterable[Layout],
    limit: int = MAX_PARETO_KEPT,
    unique_objectives: bool = True,
) -> list[Layout]:
    """Nicht dominierte Anordnungen bezueglich Laenge und Schnittanzahl.

    ``unique_objectives`` fasst Anordnungen mit gleichem Zielvektor
    (Laenge, Schnitte) zu einem Vertreter zusammen, damit die Vergleichstabelle
    echte Zielkonflikte zeigt statt mehrfach dieselbe Bewertung.
    """
    candidates = [layout for layout in layouts if layout.complete]
    front: list[Layout] = []
    seen: set[object] = set()
    for layout in candidates:
        dominated = False
        for other in candidates:
            if other is layout:
                continue
            no_worse = (
                other.length <= layout.length + 1e-9
                and other.cut_operations <= layout.cut_operations
            )
            strictly_better = (
                other.length < layout.length - 1e-9
                or other.cut_operations < layout.cut_operations
            )
            if no_worse and strictly_better:
                dominated = True
                break
        if dominated:
            continue
        if unique_objectives:
            key: object = (
                round(layout.length, 2),
                layout.cut_operations,
            )
        else:
            key = layout.geometry_signature()
        if key in seen:
            continue
        seen.add(key)
        front.append(layout)
    front.sort(key=lambda entry: (entry.length, entry.cut_operations))
    return front[:limit]


@dataclass(frozen=True)
class Layout:
    """Eine vollstaendige oder teilweise Anordnung."""

    items: tuple[Placement, ...]
    width: float
    length: float
    phase: str = "A"
    free_rotation: bool = False
    complete: bool = True
    elapsed_s: float = 0.0
    candidates: int = 0
    groups: tuple[tuple[int, ...], ...] = ()
    strategy: str = ""
    assumptions: CutAssumptions = field(
        default_factory=CutAssumptions, compare=False, repr=False
    )
    _cut_plan: CutPlan | None = field(
        default=None, compare=False, repr=False, hash=False
    )

    @property
    def used_area(self) -> float:
        return sum(item.area for item in self.items)

    @property
    def material_area(self) -> float:
        return self.width * self.length

    @property
    def waste_area(self) -> float:
        return max(0.0, self.material_area - self.used_area)

    @property
    def waste_percent(self) -> float:
        if self.material_area <= 0.0:
            return 0.0
        return self.waste_area / self.material_area * 100.0

    @property
    def angles(self) -> tuple[float, ...]:
        return tuple(round(item.angle % 360.0, 3) for item in self.items)

    @property
    def right_angle_count(self) -> int:
        return sum(1 for item in self.items if item.is_right_angle)

    @property
    def free_angle_count(self) -> int:
        return len(self.items) - self.right_angle_count

    @property
    def quarter_turn_count(self) -> int:
        return sum(
            1
            for item in self.items
            if item.is_right_angle or _is_quarter_angle(item.angle)
        )

    @property
    def alternative_angle_count(self) -> int:
        return len(self.items) - self.quarter_turn_count

    @property
    def group_count(self) -> int:
        return sum(1 for group in self.groups if len(group) > 1)

    @property
    def single_count(self) -> int:
        return len(self.items) - sum(
            len(group) for group in self.groups if len(group) > 1
        )

    @property
    def cut_plan(self) -> CutPlan:
        """Modellierte Schnittkosten; wird beim ersten Zugriff berechnet."""
        plan = self._cut_plan
        if plan is None:
            plan = compute_cut_plan(
                [(item.part_index, item.polygon) for item in self.items],
                self.width,
                self.length,
                self.assumptions,
            )
            object.__setattr__(self, "_cut_plan", plan)
        return plan

    @property
    def cut_operations(self) -> int:
        return self.cut_plan.operations

    @property
    def min_length(self) -> float:
        """Theoretische Mindestlaenge aus der Summe der Polygonflaechen."""
        if self.width <= 0.0:
            return 0.0
        return self.used_area / self.width

    def score(
        self,
        mode: str = SCORING_BALANCED,
        waste_weight: float = 0.5,
        cut_weight: float = 0.5,
    ) -> float:
        return score_layout(self, mode, waste_weight, cut_weight)

    def ranking_key(
        self,
        mode: str = SCORING_BALANCED,
        waste_weight: float = 0.5,
        cut_weight: float = 0.5,
    ) -> tuple[float, ...]:
        return ranking_key(self, mode, waste_weight, cut_weight)

    def signature(self) -> tuple[tuple[int, float, float, float], ...]:
        """Vergleichsschluessel fuer identische Anordnungen."""
        direct = tuple(
            sorted(
                (
                    item.part_index,
                    round(item.bounds[0], 3),
                    round(item.bounds[1], 3),
                    round(item.angle % 360.0, 3),
                )
                for item in self.items
            )
        )
        rotated = tuple(
            sorted(
                (
                    item.part_index,
                    round(self.width - item.bounds[2], 3),
                    round(self.length - item.bounds[3], 3),
                    round((item.angle + 180.0) % 360.0, 3),
                )
                for item in self.items
            )
        )
        return min(direct, rotated)

    def geometry_signature(self) -> tuple[tuple[float, float, float, float], ...]:
        """Vergleichsschluessel der reinen Geometrie ohne Teilnummern.

        Damit werden Anordnungen entfernt, die sich nur durch die Zuordnung
        gleicher Teile oder durch eine 180-Grad-Spiegelung unterscheiden.
        """
        direct = tuple(
            sorted(
                (
                    round(item.bounds[0], 2),
                    round(item.bounds[1], 2),
                    round(item.angle % 360.0, 1),
                    round(item.area, 2),
                )
                for item in self.items
            )
        )
        mirrored = tuple(
            sorted(
                (
                    round(self.width - item.bounds[2], 2),
                    round(self.length - item.bounds[3], 2),
                    round((item.angle + 180.0) % 360.0, 1),
                    round(item.area, 2),
                )
                for item in self.items
            )
        )
        return min(direct, mirrored)


@dataclass(frozen=True)
class NestingProgress:
    """Unveraenderlicher Zustandsschnappschuss fuer die Live-Ansicht."""

    phase: str
    phase_label: str
    event: str
    layouts: int
    attempts: int
    elapsed_s: float
    best_length: float | None
    layout: Layout | None = None
    attempt_polygon: Polygon | None = None
    attempt_valid: bool | None = None
    part_index: int | None = None
    angle: float | None = None
    x: float | None = None
    y: float | None = None
    message: str = ""
    strategy: str = ""
    groups: tuple[tuple[int, ...], ...] = ()
    cuts: int | None = None
    waste_percent: float | None = None
    score: float | None = None


@dataclass(frozen=True)
class NestingResult:
    """Ergebnis eines Suchlaufs inklusive Pareto-Front und Annahmen."""

    layouts: tuple[Layout, ...]
    pareto: tuple[Layout, ...]
    all_layouts: tuple[Layout, ...]
    assumptions: CutAssumptions
    scoring: str
    elapsed_s: float
    candidates: int
    phase_counts: tuple[tuple[str, int], ...]
    min_length: float
    timed_out: bool = False
    cancelled: bool = False

    @property
    def best(self) -> Layout | None:
        return self.layouts[0] if self.layouts else None

    @property
    def complete_shortfall(self) -> bool:
        """Weniger als drei unterschiedliche gueltige Loesungen gefunden."""
        return len(self.layouts) < 3

    def phase_count(self, phase: str) -> int:
        for name, count in self.phase_counts:
            if name == phase:
                return count
        return 0


@dataclass
class NestingOptions:
    """Einstellungen der Optimierung."""

    width: float = STRIP_WIDTH_CM
    time_budget_s: float = 5.0
    max_candidates: int = 400
    coarse_angle_step_deg: float = COARSE_ANGLE_STEP_DEG
    fine_angle_step_deg: float = FINE_ANGLE_STEP_DEG
    random_seed: int = 20260310
    allow_free_rotation: bool = True
    solver: str = "own"
    scoring: str = SCORING_BALANCED
    waste_weight: float = 0.5
    cut_weight: float = 0.5
    phase_shares: tuple[float, float, float, float] = (0.30, 0.20, 0.25, 0.25)
    use_groups: bool = True
    group_size: int = 3
    idle_runs: int = 8
    cut_assumptions: CutAssumptions = field(default_factory=CutAssumptions)

    def validated(self) -> "NestingOptions":
        if not math.isfinite(self.width) or self.width <= 0.0:
            raise NestingError("Die Materialbreite muss groesser als 0 cm sein.")
        if not math.isfinite(self.time_budget_s) or self.time_budget_s <= 0.0:
            raise NestingError("Das Zeitbudget muss groesser als 0 s sein.")
        if self.max_candidates < 1:
            raise NestingError("Es muss mindestens ein Kandidat erlaubt sein.")
        if self.coarse_angle_step_deg < MIN_ANGLE_STEP_DEG:
            raise NestingError(
                f"Die Winkelschrittweite muss mindestens {MIN_ANGLE_STEP_DEG:g} Grad betragen."
            )
        if self.fine_angle_step_deg <= 0.0:
            raise NestingError("Die feine Winkelschrittweite muss positiv sein.")
        if self.scoring not in SCORING_MODES:
            raise NestingError(
                "Unbekannter Bewertungsmodus. Erlaubt sind: "
                + ", ".join(SCORING_MODES)
                + "."
            )
        if self.waste_weight < 0.0 or self.cut_weight < 0.0:
            raise NestingError("Die Gewichte duerfen nicht negativ sein.")
        if self.waste_weight + self.cut_weight <= 1e-12:
            raise NestingError("Mindestens ein Gewicht muss groesser als 0 sein.")
        if len(self.phase_shares) != 4 or any(
            share < 0.0 for share in self.phase_shares
        ):
            raise NestingError("phase_shares braucht vier nichtnegative Werte.")
        if sum(self.phase_shares) <= 1e-12:
            raise NestingError("Die Summe der Phasenanteile muss positiv sein.")
        if self.group_size < 1:
            raise NestingError("group_size muss mindestens 1 sein.")
        if self.idle_runs < 0:
            raise NestingError("idle_runs darf nicht negativ sein.")
        if self.solver not in ("own", "sparrow"):
            raise NestingError(
                "Unbekannter Solver. Erlaubt sind: own, sparrow."
            )
        self.cut_assumptions.validated()
        return self


@dataclass(frozen=True)
class _Variant:
    angle: float
    outline: Polygon
    width: float
    height: float
    solid: Solid


@dataclass(frozen=True)
class _Placed:
    part_index: int
    polygon: Polygon
    angle: float
    area: float
    bounds: tuple[float, float, float, float]
    solid: Solid


@dataclass
class _Candidate:
    variant: _Variant
    dx: float
    dy: float
    score: tuple[float, float, float, float]


@dataclass(frozen=True)
class _ClusterMember:
    """Teil innerhalb einer vorlaeufigen Gruppe (lokale Koordinaten)."""

    shape_index: int
    part_index: int
    angle: float
    outline: Polygon
    bounds: tuple[float, float, float, float]
    solid: Solid


@dataclass(frozen=True)
class _Cluster:
    """Vorlaeufige Einheit aus zwei bis vier Teilen."""

    members: tuple[_ClusterMember, ...]
    width: float
    height: float

    @property
    def part_indices(self) -> tuple[int, ...]:
        return tuple(member.part_index for member in self.members)

    @property
    def area(self) -> float:
        return self.width * self.height


# ---------------------------------------------------------------------------
# Suchlauf
# ---------------------------------------------------------------------------


class _Search:
    def __init__(
        self,
        shapes: Sequence[Shape],
        options: NestingOptions,
        progress_cb: Callable[[NestingProgress], None] | None,
        cancel_event: "object | None",
    ) -> None:
        self.shapes = list(shapes)
        self.options = options
        self.width = options.width
        self._progress_cb = progress_cb
        self._cancel_event = cancel_event
        self._random = random.Random(options.random_seed)
        self._variant_cache: dict[tuple[int, float], _Variant] = {}
        self._cluster_cache: dict[tuple[tuple[int, ...], str], "_Cluster | None"] = {}
        self._solutions: list[Layout] = []
        self._seen: set[tuple] = set()
        self._start = 0.0
        self._phase = "A"
        self._phase_label = "Phase A: 0\u00b0/180\u00b0"
        self._strategy = ""
        self._layouts_done = 0
        self._attempts = 0
        self._best_length: float | None = None
        self._last_emit = 0.0
        self._cancelled = False
        self._timed_out = False
        self._unplaceable: int | None = None
        self._runs = 0 
        self._phase_counts: dict[str, int] = {}
        self._phase_angle_cache: dict[object, tuple[float, ...]] = {}

    # -- oeffentliche Steuerung -------------------------------------------------

    def run(self) -> NestingResult:
        if not self.shapes:
            return NestingResult(
                layouts=(),
                pareto=(),
                all_layouts=(),
                assumptions=self.options.cut_assumptions,
                scoring=self.options.scoring,
                elapsed_s=0.0,
                candidates=0,
                phase_counts=(),
                min_length=0.0,
            )
        self._start = time.monotonic()
        self._check_feasibility()
        try:
            self._run_phases()
        except _StopSearch:
            pass
        except _Unplaceable as error:
            self._unplaceable = error.part_index
        return self._build_result()

    def _run_phases(self) -> None:
        budget = self.options.time_budget_s
        total_share = sum(self.options.phase_shares) or 1.0
        phases = (
            ("A", "Phase A: 0\u00b0/180\u00b0", self._angles_a),
            ("B", "Phase B: 90\u00b0/270\u00b0", self._angles_b),
            ("C", "Phase C: alternative Winkel", self._angles_c),
            ("D", "Phase D: gemischte Drehungen", self._angles_d),
        )
        cumulative = 0.0
        for index, (phase, label, policy) in enumerate(phases):
            if self._stop_requested():
                break
            if phase != "A" and not self.options.allow_free_rotation:
                break
            share = self.options.phase_shares[index]
            if share <= 0.0:
                continue
            cumulative += share
            deadline = budget * cumulative / total_share
            self._phase_angle_cache.clear()
            self._emit_phase(phase, label, self._phase_message(phase))
            self._search_phase(phase, policy, deadline)
            if self._optimal_enough():
                break

    @staticmethod
    def _phase_message(phase: str) -> str:
        return {
            "A": "Paarweise 180\u00b0-Passung gerader und ungerader Teile ...",
            "B": "Vierteldrehungen und freie Zwischenraeume ...",
            "C": "Zusaetzliche Drehwinkel mit Verfeinerung ...",
            "D": "Gemischte Drehungen je Teil ...",
        }.get(phase, "")

    def _optimal_enough(self) -> bool:
        """Abbruch, wenn Laenge und Schnittzahl ihre Untergrenzen erreichen."""
        completed = [layout for layout in self._solutions if layout.complete]
        if not completed:
            return False
        distinct = {
            layout.geometry_signature() for layout in completed
        }
        if len(distinct) < 3:
            return False
        best = min(completed, key=self._layout_key)
        return (
            best.length <= best.min_length + 1e-6
            and best.cut_operations <= best.cut_plan.lower_bound
        )

    # -- Hilfsroutinen ----------------------------------------------------------

    def _elapsed(self) -> float:
        return time.monotonic() - self._start

    def _cancel_triggered(self) -> bool:
        return self._cancel_event is not None and bool(
            self._cancel_event.is_set()  # type: ignore[attr-defined]
        )

    def _stop_requested(self) -> bool:
        if self._cancel_triggered():
            self._cancelled = True
            return True
        if self._runs >= self.options.max_candidates:
            return True
        if self._elapsed() >= self.options.time_budget_s:
            self._timed_out = True
            return True
        return False

    def _check_stop(self) -> None:
        if self._stop_requested():
            raise _StopSearch()

    def _time_limit_reached(self, limit: float) -> bool:
        if self._elapsed() >= limit:
            return True
        return self._stop_requested()

    def _check_feasibility(self) -> None:
        for shape in self.shapes:
            fits = False
            for angle in range(0, 180):
                variant = self._variant(shape, float(angle))
                if variant.width <= self.width + GEOMETRY_TOLERANCE:
                    fits = True
                    break
            if not fits:
                raise NestingError(
                    f"Teil {shape.part_index} ist mit keiner Drehung "
                    f"schmaler als die Materialbreite von "
                    f"{self.width:g} cm."
                )

    def _variant(self, shape: Shape, angle: float) -> _Variant:
        normalized = angle % 360.0
        key = (id(shape), round(normalized, 6))
        cached = self._variant_cache.get(key)
        if cached is not None:
            return cached
        rotated = normalize_points(rotate_points(shape.outline, normalized))
        outline = tuple(rotated)
        min_x, min_y, max_x, max_y = polygon_bounds(outline)
        variant = _Variant(
            angle=normalized,
            outline=outline,
            width=max_x - min_x,
            height=max_y - min_y,
            solid=Solid.from_polygon(outline),
        )
        self._variant_cache[key] = variant
        return variant

    def _emit(self, progress: NestingProgress) -> None:
        if self._progress_cb is not None:
            self._progress_cb(progress)

    def _base_progress(self, event: str, **kwargs) -> NestingProgress:
        return NestingProgress(
            phase=self._phase,
            phase_label=self._phase_label,
            event=event,
            layouts=self._layouts_done,
            attempts=self._attempts,
            elapsed_s=self._elapsed(),
            best_length=self._best_length,
            strategy=self._strategy,
            **kwargs,
        )

    def _emit_phase(self, phase: str, label: str, message: str = "") -> None:
        self._phase = phase
        self._phase_label = label
        self._emit(self._base_progress("phase", message=message))

    def _should_emit(self) -> bool:
        if self._progress_cb is None:
            return False
        now = time.monotonic()
        if now - self._last_emit < PROGRESS_EMIT_INTERVAL_S:
            return False
        self._last_emit = now
        return True

    def _partial_layout(
        self,
        items: list[Placement],
        length: float,
        groups: tuple[tuple[int, ...], ...] = (),
    ) -> Layout:
        free = any(not item.is_right_angle for item in items)
        return Layout(
            items=tuple(items),
            width=self.width,
            length=length,
            phase=self._phase,
            free_rotation=free,
            complete=False,
            elapsed_s=self._elapsed(),
            candidates=self._layouts_done,
            groups=groups,
            strategy=self._strategy,
            assumptions=self.options.cut_assumptions,
        )

    # -- Kandidatensuche --------------------------------------------------------

    def _candidate_positions(
        self, variant: _Variant, placed: Sequence[_Placed]
    ) -> list[tuple[float, float]]:
        positions: set[tuple[float, float]] = {
            (0.0, 0.0),
            (self.width - variant.width, 0.0),
        }
        width = variant.width
        height = variant.height
        for item in placed:
            min_x, min_y, max_x, max_y = item.bounds
            positions.add((min_x, max_y))
            positions.add((max_x, max_y))
            positions.add((max_x, min_y))
            positions.add((min_x, min_y - height))
            positions.add((max_x, min_y - height))
            positions.add((max_x - width, min_y - height))
            positions.add((min_x - width, min_y))
            for vx, vy in variant.outline:
                for px, py in item.polygon:
                    positions.add((px - vx, py - vy))
                polygon = item.polygon
                count = len(polygon)
                for index in range(count):
                    start = polygon[index]
                    end = polygon[(index + 1) % count]
                    edge_x = end[0] - start[0]
                    edge_y = end[1] - start[1]
                    denominator = edge_x * edge_x + edge_y * edge_y
                    if denominator <= 1e-12:
                        continue
                    factor = (
                        (vx - start[0]) * edge_x + (vy - start[1]) * edge_y
                    ) / denominator
                    factor = max(0.0, min(1.0, factor))
                    contact_x = start[0] + factor * edge_x
                    contact_y = start[1] + factor * edge_y
                    positions.add((contact_x - vx, contact_y - vy))

        result: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for dx, dy in positions:
            if dx < -GEOMETRY_TOLERANCE or dy < -GEOMETRY_TOLERANCE:
                continue
            if dx + width > self.width + GEOMETRY_TOLERANCE:
                continue
            key = (round(dx, 6), round(dy, 6))
            if key in seen:
                continue
            seen.add(key)
            result.append((dx, dy))
        result.sort(key=lambda position: (position[1], position[0]))
        return result

    def _best_candidate(
        self,
        shape: Shape,
        placed: Sequence[_Placed],
        angles: Sequence[float],
        current_length: float,
        layout_items: Sequence[Placement] | None = None,
        layout_length: float = 0.0,
        score_mode: str = PLACEMENT_COMPACT,
    ) -> _Candidate | None:
        best: _Candidate | None = None
        for angle in angles:
            variant = self._variant(shape, angle)
            if variant.width > self.width + GEOMETRY_TOLERANCE:
                continue
            for dx, dy in self._candidate_positions(variant, placed):
                self._attempts += 1
                if self._attempts % 64 == 0:
                    self._check_stop()
                candidate_bounds = (
                    dx,
                    dy,
                    dx + variant.width,
                    dy + variant.height,
                )
                polygon = translate_points(variant.outline, dx, dy)
                collides = False
                candidate_solid: Solid | None = None
                for item in placed:
                    if not _bbox_overlap(candidate_bounds, item.bounds):
                        continue
                    if candidate_solid is None:
                        candidate_solid = Solid.from_polygon(polygon)
                    if solids_overlap(candidate_solid, item.solid):
                        collides = True
                        break
                if collides:
                    if self._should_emit():
                        self._emit(
                            self._base_progress(
                                "attempt",
                                layout=(
                                    self._partial_layout(
                                        list(layout_items), layout_length
                                    )
                                    if layout_items is not None
                                    else None
                                ),
                                attempt_polygon=polygon,
                                attempt_valid=False,
                                part_index=shape.part_index,
                                angle=angle,
                                x=dx,
                                y=dy,
                            )
                        )
                    continue
                new_length = max(current_length, candidate_bounds[3])
                if score_mode == PLACEMENT_COLUMN:
                    score = (dx, dy, new_length, angle)
                elif score_mode == PLACEMENT_ROW:
                    score = (dy, dx, new_length, angle)
                else:
                    score = (new_length, dy, dx, angle)
                if best is None or score < best.score:
                    best = _Candidate(variant=variant, dx=dx, dy=dy, score=score)
                    if self._should_emit():
                        self._emit(
                            self._base_progress(
                                "attempt",
                                layout=(
                                    self._partial_layout(
                                        list(layout_items), layout_length
                                    )
                                    if layout_items is not None
                                    else None
                                ),
                                attempt_polygon=polygon,
                                attempt_valid=True,
                                part_index=shape.part_index,
                                angle=angle,
                                x=dx,
                                y=dy,
                            )
                        )
                if score_mode in (PLACEMENT_COMPACT, PLACEMENT_ROW):
                    # Positionen sind nach (y, x) sortiert: die erste gueltige
                    # Position ist fuer diesen Winkel bereits die beste.
                    break
        return best

    def _place_single(
        self,
        shape_index: int,
        placed: list[_Placed],
        items: list[Placement],
        length: float,
        angles_for: Callable[[Shape], Sequence[float]],
        score_mode: str,
    ) -> tuple[Placement, float]:
        shape = self.shapes[shape_index]
        candidate = self._best_candidate(
            shape,
            placed,
            angles_for(shape),
            length,
            items,
            length,
            score_mode,
        )
        if candidate is None:
            raise _Unplaceable(shape.part_index, self._phase_label)
        polygon = translate_points(
            candidate.variant.outline, candidate.dx, candidate.dy
        )
        bounds = (
            candidate.dx,
            candidate.dy,
            candidate.dx + candidate.variant.width,
            candidate.dy + candidate.variant.height,
        )
        placement = Placement(
            part_index=shape.part_index,
            polygon=polygon,
            angle=candidate.variant.angle,
            area=shape.area,
            bounds=bounds,
        )
        placed.append(
            _Placed(
                part_index=shape.part_index,
                polygon=polygon,
                angle=candidate.variant.angle,
                area=shape.area,
                bounds=bounds,
                solid=Solid.from_polygon(polygon),
            )
        )
        return placement, max(length, bounds[3])

    def _greedy(
        self,
        order: Sequence[int],
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
        score_mode: str = PLACEMENT_COMPACT,
        groups: tuple[tuple[int, ...], ...] = (),
    ) -> tuple[list[Placement], float, tuple[tuple[int, ...], ...]]:
        placed: list[_Placed] = []
        items: list[Placement] = []
        length = 0.0
        for shape_index in order:
            if self._time_limit_reached(deadline):
                raise _StopSearch()
            placement, length = self._place_single(
                shape_index, placed, items, length, angles_for, score_mode
            )
            items.append(placement)
            if self._should_emit():
                self._emit(
                    self._base_progress(
                        "placed",
                        layout=self._partial_layout(items, length, groups),
                        groups=groups,
                        part_index=placement.part_index,
                        angle=placement.angle,
                        x=placement.bounds[0],
                        y=placement.bounds[1],
                    )
                )
        return items, length, groups

    # -- Paar- und Gruppenbildung ----------------------------------------------

    def _relative_positions(
        self, variant: _Variant, members: Sequence[_ClusterMember]
    ) -> list[tuple[float, float]]:
        """Kontaktpositionen fuer den Aufbau einer Gruppe (lokale Koordinaten)."""
        positions: set[tuple[float, float]] = {(0.0, 0.0)}
        width = variant.width
        height = variant.height
        for member in members:
            min_x, min_y, max_x, max_y = member.bounds
            positions.update(
                {
                    (min_x, max_y),
                    (max_x, max_y),
                    (max_x, min_y),
                    (min_x, min_y - height),
                    (max_x, min_y - height),
                    (max_x - width, min_y - height),
                    (max_x - width, max_y),
                    (min_x - width, min_y),
                    (max_x - width, max_y - height),
                    (min_x, max_y - height),
                }
            )
            for vx, vy in variant.outline:
                for px, py in member.outline:
                    positions.add((px - vx, py - vy))
        return sorted(positions, key=lambda entry: (entry[1], entry[0]))

    def _build_cluster(
        self,
        shape_indices: Sequence[int],
        angles_for: Callable[[Shape], Sequence[float]],
    ) -> _Cluster | None:
        """Baut eine kompakte Gruppe aus zwei bis vier Teilen."""
        if len(shape_indices) < 2:
            return None
        first_index = shape_indices[0]
        first_shape = self.shapes[first_index]
        best_cluster: _Cluster | None = None
        best_score: tuple[float, ...] | None = None
        for angle in list(angles_for(first_shape))[:4]:
            variant = self._variant(first_shape, angle)
            if variant.width > self.width + GEOMETRY_TOLERANCE:
                continue
            members = [
                _ClusterMember(
                    shape_index=first_index,
                    part_index=first_shape.part_index,
                    angle=variant.angle,
                    outline=variant.outline,
                    bounds=(0.0, 0.0, variant.width, variant.height),
                    solid=variant.solid,
                )
            ]
            feasible = True
            for shape_index in shape_indices[1:]:
                shape = self.shapes[shape_index]
                choice: tuple[tuple[float, ...], _ClusterMember] | None = None
                for angle2 in list(angles_for(shape))[:4]:
                    variant2 = self._variant(shape, angle2)
                    if variant2.width > self.width + GEOMETRY_TOLERANCE:
                        continue
                    for dx, dy in self._relative_positions(variant2, members):
                        bounds = (
                            dx,
                            dy,
                            dx + variant2.width,
                            dy + variant2.height,
                        )
                        collides = False
                        for member in members:
                            if not _bbox_overlap(bounds, member.bounds):
                                continue
                            polygon = translate_points(
                                variant2.outline, dx, dy
                            )
                            if solids_overlap(
                                Solid.from_polygon(polygon), member.solid
                            ):
                                collides = True
                                break
                        if collides:
                            continue
                        union_min_x = min(
                            [bounds[0]] + [m.bounds[0] for m in members]
                        )
                        union_min_y = min(
                            [bounds[1]] + [m.bounds[1] for m in members]
                        )
                        union_max_x = max(
                            [bounds[2]] + [m.bounds[2] for m in members]
                        )
                        union_max_y = max(
                            [bounds[3]] + [m.bounds[3] for m in members]
                        )
                        if (
                            union_max_x - union_min_x
                            > self.width + GEOMETRY_TOLERANCE
                        ):
                            continue
                        score = (
                            (union_max_x - union_min_x)
                            * (union_max_y - union_min_y),
                            union_max_y - union_min_y,
                            union_max_x - union_min_x,
                            dy,
                            dx,
                            variant2.angle,
                        )
                        if choice is None or score < choice[0]:
                            choice = (
                                score,
                                _ClusterMember(
                                    shape_index=shape_index,
                                    part_index=shape.part_index,
                                    angle=variant2.angle,
                                    outline=tuple(
                                        translate_points(
                                            variant2.outline, dx, dy
                                        )
                                    ),
                                    bounds=bounds,
                                    solid=Solid.from_polygon(
                                        translate_points(
                                            variant2.outline, dx, dy
                                        )
                                    ),
                                ),
                            )
                if choice is None:
                    feasible = False
                    break
                members.append(choice[1])
            if not feasible:
                continue
            min_x = min(member.bounds[0] for member in members)
            min_y = min(member.bounds[1] for member in members)
            max_x = max(member.bounds[2] for member in members)
            max_y = max(member.bounds[3] for member in members)
            normalized: list[_ClusterMember] = []
            for member in members:
                bounds = (
                    member.bounds[0] - min_x,
                    member.bounds[1] - min_y,
                    member.bounds[2] - min_x,
                    member.bounds[3] - min_y,
                )
                outline = tuple(
                    translate_points(member.outline, -min_x, -min_y)
                )
                normalized.append(
                    _ClusterMember(
                        shape_index=member.shape_index,
                        part_index=member.part_index,
                        angle=member.angle,
                        outline=outline,
                        bounds=bounds,
                        solid=Solid.from_polygon(outline),
                    )
                )
            cluster = _Cluster(
                members=tuple(normalized),
                width=max_x - min_x,
                height=max_y - min_y,
            )
            score = (cluster.area, cluster.height, cluster.width)
            if best_score is None or score < best_score:
                best_score = score
                best_cluster = cluster
        return best_cluster

    def _place_cluster(
        self,
        cluster: _Cluster,
        placed: Sequence[_Placed],
        current_length: float,
    ) -> tuple[list[Placement], float] | None:
        offsets: set[tuple[float, float]] = {
            (0.0, 0.0),
            (self.width - cluster.width, 0.0),
        }
        for item in placed:
            min_x, min_y, max_x, max_y = item.bounds
            offsets.update(
                {
                    (min_x, max_y),
                    (max_x, max_y),
                    (min_x - cluster.width, min_y),
                    (max_x - cluster.width, min_y),
                    (min_x, min_y - cluster.height),
                    (max_x, min_y - cluster.height),
                    (max_x - cluster.width, max_y),
                    (0.0, max_y),
                    (max_x - cluster.width, 0.0),
                }
            )
        ordered = sorted(
            offset
            for offset in offsets
            if -GEOMETRY_TOLERANCE <= offset[0]
            and offset[0] + cluster.width <= self.width + GEOMETRY_TOLERANCE
            and offset[1] >= -GEOMETRY_TOLERANCE
        )
        for dx, dy in ordered:
            placements: list[Placement] = []
            valid = True
            for member in cluster.members:
                bounds = (
                    member.bounds[0] + dx,
                    member.bounds[1] + dy,
                    member.bounds[2] + dx,
                    member.bounds[3] + dy,
                )
                if any(
                    _bbox_overlap(bounds, item.bounds)
                    and solids_overlap(member.solid, item.solid)
                    for item in placed
                ):
                    valid = False
                    break
                placements.append(
                    Placement(
                        part_index=member.part_index,
                        polygon=tuple(
                            translate_points(member.outline, dx, dy)
                        ),
                        angle=member.angle,
                        area=polygon_area(member.outline),
                        bounds=bounds,
                    )
                )
            if valid and placements:
                new_length = max(
                    current_length,
                    max(placement.bounds[3] for placement in placements),
                )
                return placements, new_length
        return None

    def _greedy_clustered(
        self,
        order: Sequence[int],
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
        cluster_size: int,
        score_mode: str,
        policy_key: str,
    ) -> tuple[list[Placement], float, tuple[tuple[int, ...], ...]]:
        placed: list[_Placed] = []
        items: list[Placement] = []
        length = 0.0
        groups: list[tuple[int, ...]] = []
        index = 0
        size = max(2, cluster_size)
        while index < len(order):
            if self._time_limit_reached(deadline):
                raise _StopSearch()
            chunk = list(order[index : index + size])
            cluster: _Cluster | None = None
            if len(chunk) > 1 and self.options.use_groups:
                cache_key = (tuple(chunk), policy_key)
                if cache_key not in self._cluster_cache:
                    self._cluster_cache[cache_key] = self._build_cluster(
                        chunk, angles_for
                    )
                cluster = self._cluster_cache[cache_key]
            if cluster is not None:
                result = self._place_cluster(cluster, placed, length)
                if result is not None:
                    placements, length = result
                    items.extend(placements)
                    placed.extend(self._to_placed(placement) for placement in placements)
                    group = tuple(placement.part_index for placement in placements)
                    groups.append(group)
                    self._strategy = (
                        f"Gruppe aus {len(group)} Teilen ({self._strategy})"
                    )
                    if self._should_emit():
                        self._emit(
                            self._base_progress(
                                "group",
                                layout=self._partial_layout(items, length, tuple(groups)),
                                groups=tuple(groups),
                                message="Gruppe platziert: "
                                + ", ".join(str(index) for index in group),
                            )
                        )
                    index += len(chunk)
                    continue
            # Gruppe passt nicht: aufloesen und einzeln platzieren
            for shape_index in chunk:
                if self._time_limit_reached(deadline):
                    raise _StopSearch()
                placement, length = self._place_single(
                    shape_index, placed, items, length, angles_for, score_mode
                )
                items.append(placement)
                index += 1
                if self._should_emit():
                    self._emit(
                        self._base_progress(
                            "placed",
                            layout=self._partial_layout(items, length, tuple(groups)),
                            groups=tuple(groups),
                            part_index=placement.part_index,
                            angle=placement.angle,
                            x=placement.bounds[0],
                            y=placement.bounds[1],
                        )
                    )
        return items, length, tuple(groups)

    def _layout_key(self, layout: Layout) -> tuple[float, ...]:
        return layout.ranking_key(
            self.options.scoring,
            self.options.waste_weight,
            self.options.cut_weight,
        )

    def _register(
        self,
        items: Sequence[Placement],
        length: float,
        groups: tuple[tuple[int, ...], ...] = (),
        strategy: str = "",
    ) -> None:
        if len(items) != len(self.shapes):
            return
        layout = self._make_layout(items, length, groups, strategy)
        layout = Layout(
            items=layout.items,
            width=layout.width,
            length=layout.length,
            phase=layout.phase,
            free_rotation=layout.free_rotation,
            complete=True,
            elapsed_s=layout.elapsed_s,
            candidates=self._layouts_done + 1,
            groups=layout.groups,
            strategy=layout.strategy,
            assumptions=layout.assumptions,
        )
        if validate_layout(layout, self.width):
            return
        self._layouts_done += 1
        self._phase_counts[self._phase] = self._phase_counts.get(self._phase, 0) + 1
        key = layout.geometry_signature()
        if key in self._seen:
            return
        self._seen.add(key)
        self._solutions.append(layout)
        self._trim_solutions()
        if self._best_length is None or layout.length < self._best_length:
            self._best_length = layout.length
        if self._should_emit():
            plan = layout.cut_plan
            self._emit(
                self._base_progress(
                    "layout",
                    layout=layout,
                    groups=layout.groups,
                    cuts=plan.operations,
                    waste_percent=layout.waste_percent,
                    score=layout.score(
                        self.options.scoring,
                        self.options.waste_weight,
                        self.options.cut_weight,
                    ),
                    message=(
                        f"Kandidat {self._layouts_done}: "
                        f"{layout.length:.2f} cm, "
                        f"{plan.operations} modellierte Schnitte"
                    ),
                )
            )

    def _trim_solutions(self) -> None:
        if len(self._solutions) <= MAX_LAYOUTS_KEPT:
            return
        front = {
            layout.geometry_signature()
            for layout in pareto_front(self._solutions, unique_objectives=False)
        }
        self._solutions.sort(key=self._layout_key)
        removable = [
            layout
            for layout in reversed(self._solutions)
            if layout.geometry_signature() not in front
        ]
        if not removable:
            removable = [self._solutions[-1]]
        self._solutions.remove(removable[0])

    # -- Startreihenfolgen ------------------------------------------------------

    # -- Drehwinkel je Phase ----------------------------------------------------

    def _angles_a(self, _shape: Shape) -> tuple[float, ...]:
        """Phase A: 0 und 180 Grad."""
        return (0.0, 180.0)

    def _angles_b(self, _shape: Shape) -> tuple[float, ...]:
        """Phase B: Vierteldrehungen."""
        return (0.0, 90.0, 180.0, 270.0)

    def _angles_c(self, shape: Shape) -> tuple[float, ...]:
        """Phase C: grobe Schrittweite plus kantenabgeleitete Winkel."""
        cached = self._phase_angle_cache.get(("C", shape.part_index))
        if cached is not None:
            return cached
        angles: list[float] = [0.0, 90.0, 180.0, 270.0]
        points = shape.outline
        for index in range(len(points)):
            start = points[index]
            end = points[(index + 1) % len(points)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            if math.hypot(dx, dy) <= 1e-9:
                continue
            base = -math.degrees(math.atan2(dy, dx))
            for offset in (0.0, 90.0, 180.0, 270.0):
                angles.append(base + offset)
        step = max(MIN_ANGLE_STEP_DEG, self.options.coarse_angle_step_deg)
        coarse = step
        while coarse < 360.0 - ANGLE_TOLERANCE:
            angles.append(coarse)
            coarse += step
        result = self._unique_angles(angles, limit=36)
        self._phase_angle_cache[("C", shape.part_index)] = result
        return result

    def _angles_d(self, shape: Shape) -> tuple[float, ...]:
        """Phase D: gemischte Drehungen je Teil (deterministisch je Teil).

        Jedes Teil bekommt eine andere Auswahl aus dem erweiterten Winkelpool,
        damit innerhalb einer Anordnung unterschiedliche Drehungen auftreten.
        Der Seed bleibt reproduzierbar.
        """
        key = ("D", shape.part_index)
        cached = self._phase_angle_cache.get(key)
        if cached is not None:
            return cached
        pool = list(self._angles_c(shape))
        generator = random.Random(f"{self.options.random_seed}:{shape.part_index}")
        if len(pool) > 8:
            sample = generator.sample(pool, k=min(6, len(pool)))
        else:
            sample = pool
        angles = list(self._angles_b(shape)) + list(sample)
        result = self._unique_angles(angles, limit=12)
        self._phase_angle_cache[key] = result
        return result

    @staticmethod
    def _unique_angles(
        angles: Iterable[float], limit: int | None = None
    ) -> tuple[float, ...]:
        seen: set[float] = set()
        result: list[float] = []
        for angle in angles:
            normalized = round(angle % 360.0, 4) % 360.0
            if any(abs(normalized - known) <= 1e-6 for known in seen):
                continue
            seen.add(normalized)
            result.append(normalized)
            if limit is not None and len(result) >= limit:
                break
        return tuple(result)

    def _refine_angles(
        self, angles: Sequence[float], fine: float | None = None
    ) -> tuple[float, ...]:
        """Verfeinert Winkel innerhalb von +-5 Grad."""
        step = max(0.05, fine if fine is not None else self.options.fine_angle_step_deg)
        values: list[float] = list(angles)
        for angle in angles:
            offset = step
            guard = 0
            while offset <= 5.0 + 1e-9 and guard < 12:
                values.append(angle + offset)
                values.append(angle - offset)
                offset += step
                guard += 1
        return self._unique_angles(values, limit=48)

    # -- Startreihenfolgen ------------------------------------------------------

    @staticmethod
    def _edge_lengths(shape: Shape) -> list[float]:
        points = shape.outline
        lengths: list[float] = []
        for index in range(len(points)):
            start = points[index]
            end = points[(index + 1) % len(points)]
            lengths.append(math.hypot(end[0] - start[0], end[1] - start[1]))
        return lengths

    @classmethod
    def _skew_measure(cls, shape: Shape) -> float:
        """Wie stark weicht die Kontur von achsparallelen Kanten ab?"""
        points = shape.outline
        worst = 0.0
        for index in range(len(points)):
            start = points[index]
            end = points[(index + 1) % len(points)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            if math.hypot(dx, dy) <= 1e-9:
                continue
            angle = abs(math.degrees(math.atan2(dy, dx))) % 90.0
            worst = max(worst, min(angle, 90.0 - angle))
        return worst

    def _partner_counts(self) -> dict[int, int]:
        """Zaehlt je Teil, mit wie vielen anderen Teilen es kombinierbar ist."""
        dimensions: list[list[float]] = []
        for shape in self.shapes:
            values = [shape.width, shape.height] + self._edge_lengths(shape)
            dimensions.append(values)
        tolerance = 0.5
        counts: dict[int, int] = {}
        for index, shape in enumerate(self.shapes):
            partners = 0
            for other_index, other_dimensions in enumerate(dimensions):
                if other_index == index:
                    continue
                if any(
                    abs(value - other) <= tolerance
                    for value in dimensions[index]
                    for other in other_dimensions
                ):
                    partners += 1
            counts[shape.part_index] = partners
        return counts

    def _orders(self) -> list[list[int]]:
        """Verschiedene Startreihenfolgen fuer die Greedy-Suche."""
        shapes = self.shapes
        partners = self._partner_counts()
        by_area = sorted(shapes, key=lambda s: (-s.area, s.part_index))
        by_width = sorted(
            shapes, key=lambda s: (-max(s.width, s.height), s.part_index)
        )
        by_height = sorted(
            shapes, key=lambda s: (-min(s.width, s.height), s.part_index)
        )
        by_longest_edge = sorted(
            shapes,
            key=lambda s: (-max(self._edge_lengths(s), default=0.0), s.part_index),
        )
        by_skew = sorted(
            shapes, key=lambda s: (-self._skew_measure(s), -s.area)
        )
        by_complexity = sorted(
            shapes,
            key=lambda s: (-len(s.outline), -s.perimeter, -s.area),
        )
        few_partners = sorted(
            shapes, key=lambda s: (partners.get(s.part_index, 0), -s.area)
        )
        good_partners = sorted(
            shapes, key=lambda s: (-partners.get(s.part_index, 0), -s.area)
        )
        triangles = [shape for shape in shapes if len(shape.outline) == 3]
        non_triangles = [shape for shape in shapes if len(shape.outline) != 3]
        triangles_first = triangles + list(reversed(non_triangles))
        triangles_last = list(non_triangles) + list(reversed(triangles))
        natural = list(shapes)
        odd = [shape for shape in shapes if shape.part_index % 2 == 1]
        even = [shape for shape in shapes if shape.part_index % 2 == 0]
        interleaved: list[Shape] = []
        for first, second in zip(odd, even):
            interleaved.extend((first, second))
        interleaved.extend(odd[len(even) :])
        interleaved.extend(even[len(odd) :])
        paired: list[Shape] = []
        ordered = sorted(shapes, key=lambda s: s.part_index)
        for index in range(0, len(ordered), 2):
            pair = ordered[index : index + 2]
            paired.extend(reversed(pair))
        index_of = {id(shape): position for position, shape in enumerate(shapes)}
        candidates = [
            by_area,
            by_width,
            by_height,
            by_longest_edge,
            by_skew,
            by_complexity,
            good_partners,
            few_partners,
            triangles_first,
            triangles_last,
            natural,
            interleaved,
            paired,
            list(reversed(by_area)),
            odd + even,
            even + odd,
        ]
        result: list[list[int]] = []
        seen: set[tuple[int, ...]] = set()
        for order in candidates:
            indices = tuple(index_of[id(shape)] for shape in order)
            if indices in seen:
                continue
            seen.add(indices)
            result.append(list(indices))
        return result

    def _random_order(self) -> list[int]:
        order = list(range(len(self.shapes)))
        self._random.shuffle(order)
        # gerade und ungerade Teile haeufig paarweise mischen
        if len(order) > 2 and self._random.random() < 0.5:
            order.sort(
                key=lambda index: (
                    self.shapes[index].part_index % 2,
                    self._random.random(),
                )
            )
        return order

    # -- Phasen -----------------------------------------------------------------

    def _search_phase(
        self,
        phase: str,
        policy: Callable[[Shape], Sequence[float]],
        deadline: float,
    ) -> None:
        """Fuehrt eine Suchphase mit mehreren Startreihenfolgen aus."""
        orders = self._orders()
        limit = len(orders) if phase == "A" else max(6, len(orders) // 2)
        phase_limit = max(1, self.options.max_candidates // 4)
        phase_runs = 0
        for position, order in enumerate(orders[:limit]):
            if phase_runs >= phase_limit:
                return
            if self._time_limit_reached(deadline):
                return
            mode = PLACEMENT_COLUMN if position % 3 == 1 else PLACEMENT_COMPACT
            self._run_order(order, policy, deadline, phase, mode)
            phase_runs += 1
        if phase == "A" and not self._solutions:
            # Ohne 0/180-Loesung ist eine Zufallssuche sinnlos.
            return
        idle = 0
        while phase_runs < phase_limit and not self._time_limit_reached(deadline):
            if idle >= self.options.idle_runs:
                break
            before = len(self._solutions)
            mode = (
                PLACEMENT_COLUMN
                if self._random.random() < 0.3
                else PLACEMENT_COMPACT
            )
            self._run_order(self._random_order(), policy, deadline, phase, mode)
            phase_runs += 1
            if len(self._solutions) == before:
                idle += 1
            else:
                idle = 0

    def _run_order(
        self,
        order: Sequence[int],
        policy: Callable[[Shape], Sequence[float]],
        deadline: float,
        phase: str,
        score_mode: str,
    ) -> None:
        """Eine Startreihenfolge vollstaendig auswerten und verbessern."""
        self._runs += 1
        use_groups = (
            self.options.use_groups
            and score_mode == PLACEMENT_COMPACT
            and len(order) > 1
        )
        strategy = (
            "Gruppen + " if use_groups else ""
        ) + f"{score_mode} / Phase {phase}"
        groups: tuple[tuple[int, ...], ...] = ()
        try:
            if use_groups:
                items, length, groups = self._greedy_clustered(
                    order,
                    policy,
                    deadline,
                    max(2, min(4, self.options.group_size)),
                    score_mode,
                    f"{phase}:{score_mode}",
                )
            else:
                items, length, groups = self._greedy(
                    order, policy, deadline, score_mode
                )
        except _Unplaceable:
            return
        except _StopSearch:
            if self._stop_requested():
                raise
            return
        self._register(items, length, groups, strategy)
        self._improve(items, length, policy, deadline, groups, strategy)
        if phase in ("C", "D"):
            self._refine_layout(
                items, length, deadline, groups, strategy
            )
        self._improve_cuts(items, length, policy, deadline, groups, strategy)

    # -- Lokale Verbesserung ----------------------------------------------------

    def _make_layout(
        self,
        items: Sequence[Placement],
        length: float,
        groups: tuple[tuple[int, ...], ...] = (),
        strategy: str = "",
    ) -> Layout:
        return Layout(
            items=tuple(items),
            width=self.width,
            length=length,
            phase=self._phase,
            free_rotation=any(not item.is_right_angle for item in items),
            complete=len(items) == len(self.shapes),
            elapsed_s=self._elapsed(),
            candidates=self._layouts_done,
            groups=groups,
            strategy=strategy or self._strategy,
            assumptions=self.options.cut_assumptions,
        )

    def _improve(
        self,
        items: Sequence[Placement],
        length: float,
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
        groups: tuple[tuple[int, ...], ...] = (),
        strategy: str = "",
    ) -> None:
        """Lokale Verbesserung: verschieben, umdrehen, verdichten."""
        current = list(items)
        current_length = length
        best_key = self._layout_key(
            self._make_layout(current, current_length, groups, strategy)
        )
        for _attempt in range(min(4, len(current))):
            if self._time_limit_reached(deadline):
                return
            moved = self._move_worst(
                current, current_length, angles_for, deadline
            )
            if moved is None:
                break
            candidate_items, candidate_length = moved
            candidate = self._make_layout(
                candidate_items, candidate_length, groups, strategy
            )
            if self._layout_key(candidate) >= best_key:
                break
            current, current_length = candidate_items, candidate_length
            best_key = self._layout_key(candidate)
            self._register(current, current_length, groups, strategy)
        packed = self._repack(current, current_length, deadline)
        if packed is None:
            return
        candidate_items, candidate_length = packed
        candidate = self._make_layout(
            candidate_items, candidate_length, groups, strategy
        )
        if self._layout_key(candidate) < best_key:
            self._register(candidate_items, candidate_length, groups, strategy)

    def _move_worst(
        self,
        items: Sequence[Placement],
        length: float,
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
    ) -> tuple[list[Placement], float] | None:
        del deadline
        if not items:
            return None
        worst = max(
            items, key=lambda item: (item.bounds[3], item.bounds[2])
        )
        shape = self._shape_for(worst.part_index)
        if shape is None:
            return None
        others = [item for item in items if item is not worst]
        placed = [self._to_placed(item) for item in others]
        rest_length = max(
            (item.bounds[3] for item in others), default=0.0
        )
        candidate = self._best_candidate(
            shape,
            placed,
            angles_for(shape),
            rest_length,
            others,
            rest_length,
        )
        if candidate is None:
            return None
        polygon = translate_points(
            candidate.variant.outline, candidate.dx, candidate.dy
        )
        bounds = (
            candidate.dx,
            candidate.dy,
            candidate.dx + candidate.variant.width,
            candidate.dy + candidate.variant.height,
        )
        replacement = Placement(
            part_index=shape.part_index,
            polygon=polygon,
            angle=candidate.variant.angle,
            area=shape.area,
            bounds=bounds,
        )
        new_length = max(rest_length, bounds[3])
        return others + [replacement], new_length

    def _repack(
        self,
        items: Sequence[Placement],
        length: float,
        deadline: float,
    ) -> tuple[list[Placement], float] | None:
        """Verdichtet die Anordnung, ohne die Drehwinkel zu veraendern."""
        del length
        ordered = sorted(
            items,
            key=lambda item: (
                round(item.bounds[1], 3),
                round(item.bounds[0], 3),
            ),
        )
        angle_of = {
            item.part_index: item.angle for item in ordered
        }
        order: list[int] = []
        for item in ordered:
            shape = self._shape_for(item.part_index)
            if shape is None:
                return None
            order.append(self.shapes.index(shape))

        def policy(shape: Shape) -> tuple[float, ...]:
            return (angle_of.get(shape.part_index, 0.0),)

        try:
            packed_items, packed_length, _groups = self._greedy(
                order, policy, deadline, PLACEMENT_COMPACT
            )
        except _Unplaceable:
            return None
        except _StopSearch:
            if self._stop_requested():
                raise
            return None
        return packed_items, packed_length

    def _refine_layout(
        self,
        items: Sequence[Placement],
        length: float,
        deadline: float,
        groups: tuple[tuple[int, ...], ...] = (),
        strategy: str = "",
    ) -> None:
        """Feinjustierung der Drehwinkel einzelner Teile (Phase C/D)."""
        current = list(items)
        current_length = length
        for item in sorted(current, key=lambda entry: -entry.bounds[3]):
            if self._time_limit_reached(deadline):
                return
            shape = self._shape_for(item.part_index)
            if shape is None:
                continue
            others = [other for other in current if other is not item]
            placed = [self._to_placed(other) for other in others]
            rest_length = max(
                (other.bounds[3] for other in others), default=0.0
            )
            angles = self._refine_angles((item.angle,))
            candidate = self._best_candidate(
                shape,
                placed,
                angles,
                rest_length,
                others,
                rest_length,
            )
            if candidate is None:
                continue
            polygon = translate_points(
                candidate.variant.outline, candidate.dx, candidate.dy
            )
            bounds = (
                candidate.dx,
                candidate.dy,
                candidate.dx + candidate.variant.width,
                candidate.dy + candidate.variant.height,
            )
            candidate_items = others + [
                Placement(
                    part_index=shape.part_index,
                    polygon=polygon,
                    angle=candidate.variant.angle,
                    area=shape.area,
                    bounds=bounds,
                )
            ]
            candidate_length = max(rest_length, bounds[3])
            if self._layout_key(
                self._make_layout(candidate_items, candidate_length, groups, strategy)
            ) >= self._layout_key(
                self._make_layout(current, current_length, groups, strategy)
            ):
                continue
            current, current_length = candidate_items, candidate_length
            self._register(current, current_length, groups, strategy)

    def _improve_cuts(
        self,
        items: Sequence[Placement],
        length: float,
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
        groups: tuple[tuple[int, ...], ...] = (),
        strategy: str = "",
    ) -> None:
        """Schnittoptimierte Varianten: gestapelte Spalten und Zeilen."""
        if len(items) < 2:
            return
        order: list[int] = []
        for item in sorted(
            items, key=lambda entry: (entry.bounds[1], entry.bounds[0])
        ):
            shape = self._shape_for(item.part_index)
            if shape is None:
                return
            order.append(self.shapes.index(shape))
        for mode in (PLACEMENT_COLUMN, PLACEMENT_ROW):
            if self._time_limit_reached(deadline):
                return
            try:
                candidate_items, candidate_length, candidate_groups = (
                    self._greedy(order, angles_for, deadline, mode)
                )
            except _Unplaceable:
                continue
            except _StopSearch:
                if self._stop_requested():
                    raise
                return
            self._register(
                candidate_items,
                candidate_length,
                candidate_groups,
                f"Schnittoptimiert ({mode}) / Phase {self._phase}",
            )

    def _to_placed(self, item: Placement) -> _Placed:
        return _Placed(
            part_index=item.part_index,
            polygon=item.polygon,
            angle=item.angle,
            area=item.area,
            bounds=item.bounds,
            solid=Solid.from_polygon(item.polygon),
        )

    def _shape_for(self, part_index: int) -> Shape | None:
        for shape in self.shapes:
            if shape.part_index == part_index:
                return shape
        return None

    # -- Ergebnisauswahl --------------------------------------------------------

    def _build_result(self) -> NestingResult:
        completed = [
            layout
            for layout in self._solutions
            if layout.complete and not validate_layout(layout, self.width)
        ]
        ordered = sorted(completed, key=self._layout_key)
        selected: list[Layout] = []
        seen: set[tuple] = set()
        for layout in ordered:
            key = layout.signature()
            if key in seen:
                continue
            seen.add(key)
            selected.append(layout)
            if len(selected) >= 3:
                break
        front = pareto_front(completed)
        min_length = min(
            (layout.min_length for layout in completed),
            default=0.0,
        )
        return NestingResult(
            layouts=tuple(selected),
            pareto=tuple(front),
            all_layouts=tuple(ordered),
            assumptions=self.options.cut_assumptions,
            scoring=self.options.scoring,
            elapsed_s=self._elapsed(),
            candidates=self._layouts_done,
            phase_counts=tuple(sorted(self._phase_counts.items())),
            min_length=min_length,
            timed_out=self._timed_out,
            cancelled=self._cancelled,
        )


def validate_layout(layout: Layout, width: float = STRIP_WIDTH_CM) -> list[str]:
    """Prueft eine Anordnung vollstaendig; liefert verstaendliche Fehler."""
    errors: list[str] = []
    tolerance = GEOMETRY_TOLERANCE
    if layout.length < 0.0:
        errors.append("Die Anordnung hat eine negative Laenge.")
    for item in layout.items:
        min_x, min_y, max_x, max_y = item.bounds
        if min_x < -tolerance:
            errors.append(f"Teil {item.part_index} ragt links heraus.")
        if max_x > width + tolerance:
            errors.append(f"Teil {item.part_index} ragt rechts heraus.")
        if min_y < -tolerance:
            errors.append(f"Teil {item.part_index} ragt oben heraus.")
        if max_y > layout.length + tolerance:
            errors.append(f"Teil {item.part_index} ragt unten heraus.")
        if abs(polygon_area(item.polygon) - item.area) > max(1e-6, item.area * 1e-6):
            errors.append(
                f"Teil {item.part_index} hat eine unplausible Flaeche."
            )
    for index, first in enumerate(layout.items):
        for second in layout.items[index + 1 :]:
            if polygons_overlap(first.polygon, second.polygon):
                errors.append(
                    f"Teile {first.part_index} und {second.part_index} "
                    "ueberschneiden sich."
                )
    try:
        plan = layout.cut_plan
    except (CutModelError, ZeroDivisionError) as error:
        errors.append(f"Schnittmodell nicht auswertbar: {error}")
    else:
        if plan.total_length < -tolerance:
            errors.append("Das Schnittmodell liefert eine negative Laenge.")
        if plan.shared_length > plan.total_length + tolerance:
            errors.append(
                "Gemeinsam genutzte Schnittlinien sind laenger als die "
                "gesamte Schnittlaenge."
            )
    return errors


def nest_shapes_detailed(
    shapes: Sequence[Shape],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> NestingResult:
    """Vollstaendiges Suchergebnis inklusive Pareto-Front und Annahmen."""
    settings = (options or NestingOptions()).validated()
    shapes = list(shapes)
    if not shapes:
        return NestingResult(
            layouts=(),
            pareto=(),
            all_layouts=(),
            assumptions=settings.cut_assumptions,
            scoring=settings.scoring,
            elapsed_s=0.0,
            candidates=0,
            phase_counts=(),
            min_length=0.0,
        )
    if settings.solver == "sparrow":
        try:
            from gaubenmaster.spyrrow_solver import (
                is_spyrrow_available,
                solve_sparrow_detailed,
            )

            if is_spyrrow_available():
                result = solve_sparrow_detailed(
                    shapes, settings, progress_cb, cancel_event
                )
                if result is not None and result.layouts:
                    return result
        except Exception:
            pass
    # fallback to own
    indices = [shape.part_index for shape in shapes]
    if len(set(indices)) != len(indices):
        raise NestingError(
            "Die Teilnummern sind nicht eindeutig. Jedes Teil braucht eine "
            "eigene Nummer."
        )
    return _Search(shapes, settings, progress_cb, cancel_event).run()


def nest_shapes(
    shapes: Sequence[Shape],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> list[Layout]:
    """Berechnet bis zu drei unterschiedliche gueltige Anordnungen."""
    return list(
        nest_shapes_detailed(
            shapes, options, progress_cb, cancel_event
        ).layouts
    )


def nest_polygons_detailed(
    polygons: Sequence[tuple[int, Sequence[Point]]],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> NestingResult:
    """Bequeme Schnittstelle fuer bereits bekannte Polygone (Detailform)."""
    shapes = [
        Shape.from_polygon(part_index, points) for part_index, points in polygons
    ]
    return nest_shapes_detailed(shapes, options, progress_cb, cancel_event)


def nest_polygons(
    polygons: Sequence[tuple[int, Sequence[Point]]],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> list[Layout]:
    """Bequeme Schnittstelle fuer bereits bekannte Polygone."""
    return list(
        nest_polygons_detailed(
            polygons, options, progress_cb, cancel_event
        ).layouts
    )


def shapes_from_parts(
    triangle,
    parts: Sequence,
    height_name: str,
    extras: tuple[float, float, float],
) -> list[Shape]:
    """Erzeugt Nesting-Formen aus den Einzelteilen der Hoehenteilung.

    Wiederverwendet die bestehende Aufbereitung (parallele Seiten horizontal,
    Zuschnitt-Zugaenge) aus :mod:`gaubenmaster.partdraw`, veraendert die
    Konturen aber nicht kuenstlich.
    """
    from gaubenmaster.partdraw import _extended_geometry, _local_points, height_axis

    if not parts:
        return []
    axis = height_axis(triangle, height_name) if triangle is not None else (0.0, 1.0)
    extra_length, fold_front, fold_back = extras
    shapes: list[Shape] = []
    for part in parts:
        local = _local_points(part.points, axis)
        extended, *_rest = _extended_geometry(
            local, extra_length, fold_front, fold_back
        )
        shapes.append(
            Shape.from_polygon(part.index, extended, label=f"Teil {part.index}")
        )
    return shapes


def layout_signature(layout: Layout) -> tuple[tuple[int, float, float, float], ...]:
    """Oeffentlicher Vergleichsschluessel fuer Tests und Duplikatpruefung."""
    return layout.signature()
