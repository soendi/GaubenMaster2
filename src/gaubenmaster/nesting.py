"""2D-Polygon-Nesting fuer GaubenMaster2.

Der Algorithmus platziert bis zu 20 Polygone (Vierecke und optional ein
Dreieck) auf einem Materialband mit fester Breite (100 cm) und minimiert die
benoetigte Laenge. Alle Masse sind Zentimeter; das Koordinatensystem hat den
Ursprung oben links, X zeigt nach rechts, Y nach unten.

Das Modul ist frei von Tkinter und damit direkt testbar. Die Suche laeuft in
zwei Phasen:

* Phase A erlaubt nur 0 und 180 Grad und hat absoluten Vorrang.
* Phase B erlaubt zusaetzliche Drehwinkel und wird nur als Alternative
  angeboten, wenn Phase A nicht bereits drei Loesungen liefert.

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

Point = tuple[float, float]
Polygon = tuple[Point, ...]

STRIP_WIDTH_CM = 100.0
GEOMETRY_TOLERANCE = 1e-7
ANGLE_TOLERANCE = 1e-6
MIN_ANGLE_STEP_DEG = 0.5

COARSE_ANGLE_STEP_DEG = 10.0
FINE_ANGLE_STEP_DEG = 1.0

MAX_LAYOUTS_KEPT = 24
PROGRESS_EMIT_INTERVAL_S = 0.02
PROGRESS_ATTEMPT_INTERVAL = 41


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
    phase_a_time_share: float = 0.7

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
        self._solutions: list[Layout] = []
        self._seen: set[tuple] = set()
        self._start = 0.0
        self._phase = "A"
        self._phase_label = "Phase A: 0\u00b0/180\u00b0"
        self._layouts_done = 0
        self._attempts = 0
        self._best_length: float | None = None
        self._last_emit = 0.0
        self._cancelled = False
        self._timed_out = False
        self._unplaceable: int | None = None

    # -- oeffentliche Steuerung -------------------------------------------------

    def run(self) -> list[Layout]:
        if not self.shapes:
            return []
        self._start = time.monotonic()
        self._check_feasibility()
        try:
            self._search_phase_a()
            enough_phase_a = (
                len(
                    [
                        layout
                        for layout in self._solutions
                        if not layout.free_rotation and layout.complete
                    ]
                )
                >= 3
            )
            if (
                self.options.allow_free_rotation
                and not enough_phase_a
                and not self._stop_requested()
                and self._layouts_done < self.options.max_candidates
            ):
                self._search_phase_b()
        except _StopSearch:
            pass
        except _Unplaceable as error:
            self._unplaceable = error.part_index
        self._solutions.sort(key=lambda layout: (layout.length, layout.waste_area))
        return self._select_results()

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
        if self._layouts_done >= self.options.max_candidates:
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

    def _partial_layout(self, items: list[Placement], length: float) -> Layout:
        free = any(not item.is_right_angle for item in items)
        return Layout(
            items=tuple(items),
            width=self.width,
            length=length,
            phase="B" if free else "A",
            free_rotation=free,
            complete=False,
            elapsed_s=self._elapsed(),
            candidates=self._layouts_done,
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
                score = (
                    max(current_length, candidate_bounds[3]),
                    dy,
                    dx,
                    angle,
                )
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
                # Positionen sind nach (y, x) sortiert: die erste gueltige
                # Position ist fuer diesen Winkel bereits die beste.
                break
        return best

    def _greedy(
        self,
        order: Sequence[int],
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
    ) -> tuple[list[Placement], float]:
        placed: list[_Placed] = []
        items: list[Placement] = []
        length = 0.0
        for shape_index in order:
            if self._time_limit_reached(deadline):
                raise _StopSearch()
            shape = self.shapes[shape_index]
            candidate = self._best_candidate(
                shape, placed, angles_for(shape), length, items, length
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
            items.append(placement)
            length = max(length, bounds[3])
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
            if self._should_emit():
                self._emit(
                    self._base_progress(
                        "placed",
                        layout=self._partial_layout(items, length),
                        part_index=shape.part_index,
                        angle=candidate.variant.angle,
                        x=bounds[0],
                        y=bounds[1],
                    )
                )
        return items, length

    def _register(self, items: Sequence[Placement], length: float) -> None:
        if len(items) != len(self.shapes):
            return
        free = any(not item.is_right_angle for item in items)
        layout = Layout(
            items=tuple(items),
            width=self.width,
            length=length,
            phase="B" if free else "A",
            free_rotation=free,
            complete=True,
            elapsed_s=self._elapsed(),
            candidates=self._layouts_done + 1,
        )
        if validate_layout(layout, self.width):
            return
        self._layouts_done += 1
        key = layout.signature()
        if key in self._seen:
            return
        self._seen.add(key)
        self._solutions.append(layout)
        self._solutions.sort(key=lambda entry: (entry.length, entry.waste_area))
        del self._solutions[MAX_LAYOUTS_KEPT:]
        if self._best_length is None or layout.length < self._best_length:
            self._best_length = layout.length
        if self._should_emit():
            self._emit(
                self._base_progress(
                    "layout",
                    layout=layout,
                    message=f"Kandidat {self._layouts_done}: {layout.length:.2f} cm",
                )
            )

    # -- Startreihenfolgen ------------------------------------------------------

    def _angle_policy_a(self, _shape: Shape) -> tuple[float, float]:
        return (0.0, 180.0)

    def _angle_policy_b(self, shape: Shape) -> tuple[float, ...]:
        angles = [0.0, 180.0]
        step = max(MIN_ANGLE_STEP_DEG, self.options.coarse_angle_step_deg)
        angle = step
        while angle < 360.0 - ANGLE_TOLERANCE:
            if abs(angle - 180.0) > ANGLE_TOLERANCE:
                angles.append(angle)
            angle += step
        return tuple(angles)

    def _orders(self) -> list[list[int]]:
        shapes = self.shapes
        by_area = sorted(shapes, key=lambda s: -s.area)
        by_width = sorted(shapes, key=lambda s: -max(s.width, s.height))
        by_height = sorted(shapes, key=lambda s: -min(s.width, s.height))
        by_form = sorted(
            shapes,
            key=lambda s: (len(s.outline), -s.perimeter, -s.area),
        )
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
            by_form,
            natural,
            interleaved,
            paired,
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

    def _search_phase_a(self) -> None:
        self._emit_phase(
            "A",
            "Phase A: 0\u00b0/180\u00b0",
            "Suche mit paarweiser 180\u00b0-Drehung ...",
        )
        deadline = self.options.time_budget_s * self.options.phase_a_time_share
        orders = self._orders()
        for order in orders:
            if self._time_limit_reached(deadline):
                break
            try:
                items, length = self._greedy(
                    order, self._angle_policy_a, deadline
                )
            except _Unplaceable:
                continue
            except _StopSearch:
                if self._stop_requested():
                    raise
                break
            self._register(items, length)
            try:
                self._improve(items, length, self._angle_policy_a, deadline)
            except _StopSearch:
                if self._stop_requested():
                    raise
                break
        if not self._solutions:
            # Ohne 0/180-Loesung ist die Zufallssuche in Phase A sinnlos.
            return
        while not self._time_limit_reached(deadline):
            if self._layouts_done >= self.options.max_candidates:
                break
            order = self._random_order()
            try:
                items, length = self._greedy(
                    order, self._angle_policy_a, deadline
                )
            except _Unplaceable:
                continue
            except _StopSearch:
                if self._stop_requested():
                    raise
                break
            self._register(items, length)

    def _search_phase_b(self) -> None:
        self._emit_phase(
            "B",
            "Phase B: freie Drehung",
            "Zusaetzliche Drehwinkel werden geprueft ...",
        )
        deadline = self.options.time_budget_s
        base_orders = self._orders()[:5]
        for order in base_orders:
            if self._time_limit_reached(deadline):
                break
            try:
                items, length = self._greedy(
                    order, self._angle_policy_b, deadline
                )
            except _Unplaceable:
                continue
            self._register(items, length)
            self._refine_free(
                items, length, deadline
            )
        while not self._time_limit_reached(deadline):
            if self._layouts_done >= self.options.max_candidates:
                break
            order = self._random_order()
            try:
                items, length = self._greedy(
                    order, self._angle_policy_b, deadline
                )
            except _Unplaceable:
                continue
            self._register(items, length)

    # -- Lokale Verbesserung ----------------------------------------------------

    def _improve(
        self,
        items: Sequence[Placement],
        length: float,
        angles_for: Callable[[Shape], Sequence[float]],
        deadline: float,
    ) -> None:
        current = list(items)
        current_length = length
        for _attempt in range(min(4, len(current))):
            if self._time_limit_reached(deadline):
                return
            worst = max(current, key=lambda item: item.bounds[3])
            others = [item for item in current if item is not worst]
            shape = self._shape_for(worst.part_index)
            if shape is None:
                return
            placed = [self._to_placed(item) for item in others]
            rest_length = max(
                (item.bounds[3] for item in others), default=0.0
            )
            candidate = self._best_candidate(
                shape, placed, angles_for(shape), rest_length,
                others, rest_length,
            )
            if candidate is None:
                return
            polygon = translate_points(
                candidate.variant.outline, candidate.dx, candidate.dy
            )
            bounds = (
                candidate.dx,
                candidate.dy,
                candidate.dx + candidate.variant.width,
                candidate.dy + candidate.variant.height,
            )
            new_length = max(
                max((item.bounds[3] for item in others), default=0.0), bounds[3]
            )
            if new_length >= current_length - 1e-6:
                return
            replacement = Placement(
                part_index=shape.part_index,
                polygon=polygon,
                angle=candidate.variant.angle,
                area=shape.area,
                bounds=bounds,
            )
            current = others + [replacement]
            current_length = new_length
            self._register(current, current_length)

    def _refine_free(
        self,
        items: Sequence[Placement],
        length: float,
        deadline: float,
    ) -> None:
        current = list(items)
        current_length = length
        fine = max(0.05, self.options.fine_angle_step_deg)
        for item in sorted(current, key=lambda entry: -entry.bounds[3]):
            if self._time_limit_reached(deadline):
                return
            shape = self._shape_for(item.part_index)
            if shape is None:
                continue
            others = [other for other in current if other is not item]
            placed = [self._to_placed(other) for other in others]
            base_angle = item.angle % 360.0
            angles: list[float] = [0.0, 180.0]
            offset = -5.0
            while offset <= 5.0:
                angles.append(base_angle + offset)
                offset += fine
            candidate = self._best_candidate(
                shape,
                placed,
                angles,
                max((other.bounds[3] for other in others), default=0.0),
                others,
                max((other.bounds[3] for other in others), default=0.0),
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
            new_length = max(
                max((other.bounds[3] for other in others), default=0.0),
                bounds[3],
            )
            if new_length >= current_length - 1e-6:
                continue
            current_length = new_length
            current = others + [
                Placement(
                    part_index=shape.part_index,
                    polygon=polygon,
                    angle=candidate.variant.angle,
                    area=shape.area,
                    bounds=bounds,
                )
            ]
            self._register(current, current_length)

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

    def _select_results(self) -> list[Layout]:
        phase_a = [
            layout
            for layout in self._solutions
            if layout.complete and not layout.free_rotation
        ]
        phase_b = [
            layout
            for layout in self._solutions
            if layout.complete and layout.free_rotation
        ]
        phase_a.sort(key=lambda layout: (layout.length, layout.waste_area))
        phase_b.sort(key=lambda layout: (layout.length, layout.waste_area))
        selected: list[Layout] = []
        for layout in phase_a:
            if len(selected) >= 3:
                break
            selected.append(layout)
        if len(selected) < 3:
            for layout in phase_b:
                if len(selected) >= 3:
                    break
                selected.append(layout)
        return selected


def validate_layout(layout: Layout, width: float = STRIP_WIDTH_CM) -> list[str]:
    """Prueft eine Anordnung vollstaendig; liefert verstaendliche Fehler."""
    errors: list[str] = []
    tolerance = GEOMETRY_TOLERANCE
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
    for index, first in enumerate(layout.items):
        for second in layout.items[index + 1 :]:
            if polygons_overlap(first.polygon, second.polygon):
                errors.append(
                    f"Teile {first.part_index} und {second.part_index} "
                    "ueberschneiden sich."
                )
    return errors


def nest_shapes(
    shapes: Sequence[Shape],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> list[Layout]:
    """Berechnet bis zu drei unterschiedliche gueltige Anordnungen."""
    settings = (options or NestingOptions()).validated()
    shapes = list(shapes)
    if not shapes:
        return []
    indices = [shape.part_index for shape in shapes]
    if len(set(indices)) != len(indices):
        raise NestingError(
            "Die Teilnummern sind nicht eindeutig. Jedes Teil braucht eine "
            "eigene Nummer."
        )
    return _Search(shapes, settings, progress_cb, cancel_event).run()


def nest_polygons(
    polygons: Sequence[tuple[int, Sequence[Point]]],
    options: NestingOptions | None = None,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event: "object | None" = None,
) -> list[Layout]:
    """Bequeme Schnittstelle fuer bereits bekannte Polygone."""
    shapes = [
        Shape.from_polygon(part_index, points) for part_index, points in polygons
    ]
    return nest_shapes(shapes, options, progress_cb, cancel_event)


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
