"""Transparentes Schnittkostenmodell fuer manuelles Schneiden.

Das Modell beantwortet die Frage, wie viele manuelle Schnittvorgaenge eine
gegebene Anordnung voraussichtlich benoetigt. Es arbeitet ausschliesslich auf
den tatsaechlichen Polygonkonturen und ist bewusst als austauschbares Modell
angelegt: Die Annahmen stecken in :class:`CutAssumptions`, die Auswertung in
:func:`compute_cut_plan`.

Drei Begriffe werden getrennt:

* **Geometrische Trennlinie** - eine Kante eines Teils, die nicht auf dem
  Materialrand liegt und deshalb geschnitten werden muss.
* **Zusammenhaengender Schnittweg** - eine Folge von Trennlinien, die ohne
  Absetzen zusammenhaengend geschnitten werden kann. Linien, die sich in einem
  Punkt beruehren, sind zusammenhaengend; ein T-Stoss erzeugt eine
  Verzweigung und beendet einen Weg.
* **Schnittvorgang** - ein realer manueller Ansatz. Er entspricht hier einem
  zusammenhaengenden Schnittweg plus, falls konfiguriert, einem zusaetzlichen
  Ansatz fuer Konturen, die nicht am Materialrand beginnen.

Standardannahmen (alle konfigurierbar):

* Schnittfugenbreite 0 cm, Konturen werden nicht veraendert.
* Eine gemeinsame Trennlinie zweier Teile wird genau einmal gezaehlt.
* Kollineare, lueckenlos aneinanderliegende Trennlinien bilden einen
  Schnittweg; ein ungeschnittener Abschnitt dazwischen trennt die Wege.
* Kanten auf dem Materialrand (x=0, x=Breite, y=0, y=Laenge) muessen nicht
  geschnitten werden.
* Schnitte duerfen grundsaetzlich im Material beginnen
  (``start_at_border = False``). Wird ``True`` gesetzt, kostet jede
  zusammenhaengende Kontur ohne Materialrand-Kontakt einen Zusatzansatz.

Die ermittelte Zahl ist eine **modellierte** Schnittanzahl. Ohne bekanntes
Werkzeug und ohne Regeln fuer Werkstueckhandhabung ist die real ausfuehrbare
Zahl nicht eindeutig bestimmbar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

Point = tuple[float, float]
Polygon = tuple[Point, ...]
Node = tuple[float, float]

LINE_TOLERANCE = 1e-4
SNAP_TOLERANCE = 1e-4
GAP_TOLERANCE = 1e-6

SEPARATING = "Trennschnitt (gemeinsame Linie)"
TRIM = "Trennschnitt zum Abfall"


class CutModelError(ValueError):
    """Ungueltige Annahmen oder nicht auswertbare Geometrie."""


@dataclass(frozen=True)
class CutAssumptions:
    """Annahmen des manuellen Schnittmodells."""

    name: str = "Manuell, 0 cm Fugenbreite"
    kerf_cm: float = 0.0
    count_shared_once: bool = True
    merge_collinear: bool = True
    ignore_material_border: bool = True
    start_at_border: bool = False
    min_segment_cm: float = 0.0

    def validated(self) -> "CutAssumptions":
        if abs(self.kerf_cm) > 1e-12:
            raise CutModelError(
                "Schnittfugenbreite ist im aktuellen Modell 0 cm. "
                "Andere Werte wuerden die Polygonkonturen veraendern."
            )
        if self.min_segment_cm < 0.0:
            raise CutModelError("min_segment_cm darf nicht negativ sein.")
        return self

    def describe(self) -> str:
        shared = (
            "gemeinsame Linie einmal"
            if self.count_shared_once
            else "gemeinsame Linie je Teil"
        )
        merge = (
            "kollineare Wege werden zusammengefasst"
            if self.merge_collinear
            else "jede Linie einzeln"
        )
        border = (
            "Materialrand muss nicht geschnitten werden"
            if self.ignore_material_border
            else "Materialrand zaehlt als Schnitt"
        )
        start = (
            "Ansatz nur am Materialrand"
            if self.start_at_border
            else "Ansatz auch im Material erlaubt"
        )
        return (
            f"Schnittmodell '{self.name}': Fugenbreite "
            f"{self.kerf_cm:g} cm, {shared}, {merge}, {border}, {start}."
        )


@dataclass(frozen=True)
class CutSegment:
    """Eine Trennlinie zwischen zwei Knoten."""

    start: Point
    end: Point
    length: float
    part_indices: tuple[int, ...]
    separated: bool = False

    @property
    def kind(self) -> str:
        return SEPARATING if self.separated else TRIM


@dataclass(frozen=True)
class CutPlan:
    """Ergebnis der Schnittkostenrechnung fuer eine Anordnung."""

    segments: tuple[CutSegment, ...] = ()
    shared_segments: tuple[CutSegment, ...] = ()
    total_length: float = 0.0
    shared_length: float = 0.0
    operations: int = 0
    separating_operations: int = 0
    trim_operations: int = 0
    plunges: int = 0
    border_paths: int = 0
    inner_paths: int = 0
    assumptions: CutAssumptions = field(default_factory=CutAssumptions)
    lower_bound: int = 1

    @property
    def shared_edges(self) -> int:
        return len(self.shared_segments)

    def summary(self) -> str:
        return (
            f"{self.operations} modellierte Schnittvorgaenge "
            f"({self.separating_operations} Trennschnitt(e), "
            f"{self.trim_operations} Abfallschnitt(e), "
            f"{self.plunges} Zusatzansatz/Ansätze) auf "
            f"{len(self.segments)} Linien, "
            f"{self.total_length:.1f} cm Schnittlaenge, davon "
            f"{self.shared_length:.1f} cm gemeinsam genutzt."
        )

    def describe(self) -> str:
        return f"{self.summary()}\n{self.assumptions.describe()}"

    @classmethod
    def empty(cls, assumptions: CutAssumptions | None = None) -> "CutPlan":
        return cls(assumptions=assumptions or CutAssumptions())


def _segment_length(start: Point, end: Point) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _on_material_border(
    start: Point, end: Point, width: float, length: float
) -> bool:
    tolerance = 1e-6
    if (abs(start[0]) <= tolerance and abs(end[0]) <= tolerance) or (
        abs(start[0] - width) <= tolerance and abs(end[0] - width) <= tolerance
    ):
        return True
    if (abs(start[1]) <= tolerance and abs(end[1]) <= tolerance) or (
        abs(start[1] - length) <= tolerance and abs(end[1] - length) <= tolerance
    ):
        return True
    return False


def _line_key(
    start: Point, end: Point
) -> tuple[tuple[float, float, float], float, float]:
    """Liefert (Schluessel, ux, uy) der Traegerlinie."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-12:
        raise CutModelError("Trennlinie hat die Laenge 0.")
    ux, uy = dx / distance, dy / distance
    if ux < -LINE_TOLERANCE or (abs(ux) <= LINE_TOLERANCE and uy < 0.0):
        ux, uy = -ux, -uy
    nx, ny = -uy, ux
    offset = nx * start[0] + ny * start[1]
    return (round(ux, 6), round(uy, 6), round(offset, 4)), ux, uy


def _node(point: Point) -> Node:
    return (round(point[0], 4), round(point[1], 4))


def _point_at(ux: float, uy: float, offset: float, t: float) -> Point:
    """Punkt auf der Linie mit Normale (-uy, ux) und gegebenem Offset."""
    base_x, base_y = -uy * offset, ux * offset
    return (base_x + ux * t, base_y + uy * t)


def _subtract_intervals(
    start: float, end: float, cuts: Sequence[float]
) -> list[tuple[float, float]]:
    points = [start]
    for value in sorted(cuts):
        if start + SNAP_TOLERANCE < value < end - SNAP_TOLERANCE:
            points.append(value)
    points.append(end)
    result: list[tuple[float, float]] = []
    for first, second in zip(points, points[1:]):
        if second - first > SNAP_TOLERANCE:
            result.append((first, second))
    return result


def _shared_coverage(
    pieces: Sequence[tuple[float, float, int]]
) -> tuple[float, list[tuple[float, float]]]:
    """Laenge und Abschnitte, die von mindestens zwei Teilen belegt sind."""
    if not pieces:
        return 0.0, []
    breakpoints = sorted(
        {value for start, end, _pid in pieces for value in (start, end)}
    )
    shared_total = 0.0
    shared_parts: list[tuple[float, float]] = []
    for first, second in zip(breakpoints, breakpoints[1:]):
        if second - first <= SNAP_TOLERANCE:
            continue
        middle = (first + second) / 2.0
        owners = {
            pid
            for start, end, pid in pieces
            if start - SNAP_TOLERANCE <= middle <= end + SNAP_TOLERANCE
        }
        if len(owners) >= 2:
            shared_total += second - first
            if shared_parts and abs(shared_parts[-1][1] - first) <= SNAP_TOLERANCE:
                shared_parts[-1] = (shared_parts[-1][0], second)
            else:
                shared_parts.append((first, second))
    return shared_total, shared_parts


def _analyze_graph(
    edges: Sequence[tuple[Node, Node, bool]]
) -> tuple[int, int, int, int, int]:
    """Minimale Zahl zusammenhaengender Wege je Komponente.

    Rueckgabe: (Wege, Wege mit Randkontakt, Wege ohne Randkontakt,
    Wege in Komponenten mit gemeinsamer Linie, Wege ohne gemeinsame Linie).
    """
    if not edges:
        return 0, 0, 0, 0, 0
    adjacency: dict[Node, list[Node]] = {}
    for start, end, _separated in edges:
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)
    parent = {node: node for node in adjacency}

    def find(node: Node) -> Node:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for start, end, _separated in edges:
        root_start, root_end = find(start), find(end)
        if root_start != root_end:
            parent[root_end] = root_start

    groups: dict[Node, list[Node]] = {}
    for node in adjacency:
        groups.setdefault(find(node), []).append(node)

    separated_roots = {find(start) for start, _end, flag in edges if flag}

    trails = border_paths = inner_paths = 0
    separating_paths = trim_paths = 0
    for root, nodes in groups.items():
        odd = sum(1 for node in nodes if len(adjacency[node]) % 2 == 1)
        count = max(1, odd // 2)
        trails += count
        if any(
            abs(node[0]) <= SNAP_TOLERANCE or abs(node[1]) <= SNAP_TOLERANCE
            for node in nodes
        ):
            border_paths += count
        else:
            inner_paths += count
        if root in separated_roots:
            separating_paths += count
        else:
            trim_paths += count
    return trails, border_paths, inner_paths, separating_paths, trim_paths


def compute_cut_plan(
    polygons: Sequence[tuple[int, Sequence[Point]]],
    width: float,
    length: float,
    assumptions: CutAssumptions | None = None,
) -> CutPlan:
    """Berechnet die modellierte Schnittanzahl einer Anordnung."""
    rules = (assumptions or CutAssumptions()).validated()

    lines: dict[
        tuple[float, float, float], list[tuple[float, float, int]]
    ] = {}
    for part_index, polygon in polygons:
        points = [(float(x), float(y)) for x, y in polygon]
        count = len(points)
        for index in range(count):
            start = points[index]
            end = points[(index + 1) % count]
            if _segment_length(start, end) <= rules.min_segment_cm:
                continue
            if rules.ignore_material_border and _on_material_border(
                start, end, width, length
            ):
                continue
            key, ux, uy = _line_key(start, end)
            start_t = ux * start[0] + uy * start[1]
            end_t = ux * end[0] + uy * end[1]
            low, high = sorted((start_t, end_t))
            lines.setdefault(key, []).append((low, high, part_index))

    segments: list[CutSegment] = []
    shared_segments: list[CutSegment] = []
    total_length = 0.0
    shared_total = 0.0
    extra_shared_operations = 0

    for (ux, uy, offset), pieces in lines.items():
        pieces.sort(key=lambda entry: (entry[0], entry[1]))
        merged: list[list[tuple[float, float, int]]] = []
        merged_end = -math.inf
        for low, high, part_index in pieces:
            if merged and low <= merged_end + (
                GAP_TOLERANCE if rules.merge_collinear else -1.0
            ):
                merged[-1].append((low, high, part_index))
                merged_end = max(merged_end, high)
            else:
                merged.append([(low, high, part_index)])
                merged_end = high

        for bucket in merged:
            start_t = min(entry[0] for entry in bucket)
            end_t = max(entry[1] for entry in bucket)
            owners: list[int] = []
            for _low, _high, part_index in bucket:
                if part_index not in owners:
                    owners.append(part_index)
            shared_length, shared_parts = _shared_coverage(bucket)
            separated = shared_length > SNAP_TOLERANCE
            total_length += end_t - start_t
            segments.append(
                CutSegment(
                    start=_point_at(ux, uy, offset, start_t),
                    end=_point_at(ux, uy, offset, end_t),
                    length=end_t - start_t,
                    part_indices=tuple(sorted(owners)),
                    separated=separated,
                )
            )
            if not separated:
                continue
            shared_total += shared_length
            if not rules.count_shared_once:
                extra_shared_operations += max(0, len(owners) - 1)
            for part_start, part_end in shared_parts:
                shared_segments.append(
                    CutSegment(
                        start=_point_at(ux, uy, offset, part_start),
                        end=_point_at(ux, uy, offset, part_end),
                        length=part_end - part_start,
                        part_indices=tuple(sorted(owners)),
                        separated=True,
                    )
                )

    edges = _split_edges(segments)
    trails, border_paths, inner_paths, separating_ops, trim_ops = _analyze_graph(
        edges
    )
    plunges = inner_paths if rules.start_at_border else 0
    operations = trails + plunges + extra_shared_operations
    lower_bound = max(1, len(polygons) - len(shared_segments))

    return CutPlan(
        segments=tuple(segments),
        shared_segments=tuple(shared_segments),
        total_length=total_length,
        shared_length=shared_total,
        operations=operations,
        separating_operations=separating_ops,
        trim_operations=trim_ops,
        plunges=plunges,
        border_paths=border_paths,
        inner_paths=inner_paths,
        assumptions=rules,
        lower_bound=lower_bound,
    )


def _split_edges(segments: Sequence[CutSegment]) -> list[tuple[Node, Node, bool]]:
    """Teilt Linien an Stuetzpunkten anderer Linien (T-Stoesse)."""
    endpoints: dict[Node, Point] = {}
    for segment in segments:
        endpoints.setdefault(_node(segment.start), segment.start)
        endpoints.setdefault(_node(segment.end), segment.end)

    edges: list[tuple[Node, Node, bool]] = []
    for segment in segments:
        start, end = segment.start, segment.end
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.hypot(dx, dy)
        if distance <= 1e-12:
            continue
        ux, uy = dx / distance, dy / distance
        if ux < -LINE_TOLERANCE or (abs(ux) <= LINE_TOLERANCE and uy < 0.0):
            ux, uy = -ux, -uy
        normal_x, normal_y = -uy, ux
        start_t = ux * start[0] + uy * start[1]
        end_t = ux * end[0] + uy * end[1]
        low, high = sorted((start_t, end_t))
        normal_offset = normal_x * start[0] + normal_y * start[1]
        cuts: list[float] = []
        for point in endpoints.values():
            if abs(normal_x * point[0] + normal_y * point[1] - normal_offset) > (
                LINE_TOLERANCE
            ):
                continue
            value = ux * point[0] + uy * point[1]
            if low + SNAP_TOLERANCE < value < high - SNAP_TOLERANCE:
                cuts.append(value)
        for piece_start, piece_end in _subtract_intervals(low, high, cuts):
            first = _point_at(ux, uy, normal_offset, piece_start)
            second = _point_at(ux, uy, normal_offset, piece_end)
            edges.append((_node(first), _node(second), segment.separated))
    return edges


def layout_cut_plan(
    items: Iterable,
    width: float,
    length: float,
    assumptions: CutAssumptions | None = None,
) -> CutPlan:
    """Bequeme Schnittstellenfunktion fuer Objekte mit ``part_index``/``polygon``."""
    return compute_cut_plan(
        [(item.part_index, item.polygon) for item in items],
        width,
        length,
        assumptions,
    )
