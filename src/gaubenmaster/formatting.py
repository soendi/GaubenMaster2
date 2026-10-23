"""Gemeinsame Zahlen- und Flaechenformatierung."""

from __future__ import annotations

AREA_M2_THRESHOLD_CM2 = 999.99


def format_number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _compact_number(value: float, digits: int) -> str:
    text = format_number(value, digits)
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def format_area(area_cm2: float) -> str:
    if area_cm2 > AREA_M2_THRESHOLD_CM2:
        return f"{_compact_number(area_cm2 / 10000.0, 6)} m²"
    return f"{format_number(area_cm2, 2)} cm²"
