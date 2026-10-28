"""Optionaler Shapely-Adapter fuer die Geometriepruefungen.

Shapely ist **nicht** Pflichtabhaengigkeit der Anwendung. Die produktive
Geometrie (SAT + Ohrenschneiden) lebt in :mod:`gaubenmaster.geometry` und
bleibt unveraendert, damit der PyInstaller-Build ohne C-Erweiterungen
auskommt und die 119 vorhandenen Tests gruen bleiben.

Dieses Modul bietet dieselben Prueffunktionen in einer Shapely-Variante, so
dass sie bei Bedarf (z. B. fuer unabhaengige Referenzpruefungen oder fuer
eine spaetere Migration) genutzt werden koennen. Ist Shapely nicht
installiert, fallen alle Funktionen auf die eigene Implementierung zurueck.
"""

from __future__ import annotations

from typing import Sequence

from gaubenmaster.geometry import polygon_area as _own_area

try:
    from gaubenmaster.nesting import (
        is_convex_polygon as _own_is_convex,
        is_simple_polygon as _own_is_simple,
        polygons_overlap as _own_overlap,
    )
except Exception:  # pragma: no cover
    _own_is_convex = None
    _own_is_simple = None
    _own_overlap = None

try:  # optionale Abhaengigkeit
    from shapely.geometry import Polygon as _ShapelyPolygon

    _HAS_SHAPELY = True
except Exception:  # pragma: no cover - Umgebung ohne Shapely
    _ShapelyPolygon = None
    _HAS_SHAPELY = False


def has_shapely() -> bool:
    """True, wenn Shapely importiert werden konnte."""
    return _HAS_SHAPELY


def _to_polygon(points: Sequence[tuple[float, float]]):
    if not _HAS_SHAPELY:
        return None
    try:
        return _ShapelyPolygon(points)
    except Exception:
        return None


def shapely_area(points: Sequence[tuple[float, float]]) -> float:
    """Flaeche ueber Shapely (Fallback auf eigene Implementierung)."""
    polygon = _to_polygon(points)
    if polygon is None or not polygon.is_valid:
        return _own_area(points)
    return float(polygon.area)


def shapely_simple(points: Sequence[tuple[float, float]]) -> bool:
    """Einfachheitspruefung ueber Shapely."""
    polygon = _to_polygon(points)
    if polygon is None:
        return _own_is_simple(points)
    return bool(polygon.is_valid and not polygon.is_empty)


def shapely_convex(points: Sequence[tuple[float, float]]) -> bool:
    """Konvexitätspruefung ueber Shapely."""
    polygon = _to_polygon(points)
    if polygon is None:
        return _own_is_convex(points)
    # Ein Polygon ist konvex, wenn es seiner konvexen Huelle entspricht.
    return bool(polygon.equals(polygon.convex_hull))


def shapely_overlap(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> bool:
    """Kollisionspruefung ueber Shapely (Fallback auf SAT)."""
    first_poly = _to_polygon(first)
    second_poly = _to_polygon(second)
    if first_poly is None or second_poly is None:
        return _own_overlap(first, second)
    try:
        return bool(first_poly.overlaps(second_poly))
    except Exception:
        return _own_overlap(first, second)


__all__ = [
    "has_shapely",
    "shapely_area",
    "shapely_simple",
    "shapely_convex",
    "shapely_overlap",
]
