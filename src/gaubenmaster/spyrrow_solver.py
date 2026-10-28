"""Optionaler Sparrow-Solver (spyrrow) als alternative Berechnungsengine.

Sparrow ist eine optionale Abhaengigkeit. Ist das Paket nicht installiert oder
schlaegt die Berechnung fehl, faellt der Aufrufer auf den eigenen Algorithmus
zurueck. Die Funktionen hier liefern entweder ein gueltiges :class:`Layout`
bzw. :class:`NestingResult` oder ``None``.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Sequence

from gaubenmaster.nesting import (
    Layout,
    NestingError,
    NestingOptions,
    NestingProgress,
    NestingResult,
    Placement,
    Shape,
    validate_layout,
    polygon_bounds,
    rotate_points,
    translate_points,
)


def is_spyrrow_available() -> bool:
    try:
        import spyrrow  # noqa: F401

        return True
    except Exception:
        return False


def _allowed_orientations(options: NestingOptions):
    if options.allow_free_rotation:
        return None
    return [0.0, 90.0, 180.0, 270.0]


def solve_sparrow_layout(
    shapes: Sequence[Shape],
    options: NestingOptions,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event=None,
) -> Layout | None:
    if not is_spyrrow_available():
        return None
    import spyrrow

    if not shapes:
        return None

    items = []
    for shape in shapes:
        sp_shape = [(float(y), float(x)) for (x, y) in shape.outline]
        items.append(
            spyrrow.Item(
                str(shape.part_index),
                sp_shape,
                demand=1,
                allowed_orientations=_allowed_orientations(options),
            )
        )

    instance = spyrrow.StripPackingInstance(
        "gaubenmaster", strip_height=float(options.width), items=items
    )
    config = spyrrow.StripPackingConfig(
        total_computation_time=max(1, int(round(options.time_budget_s))),
        seed=options.random_seed,
        early_termination=True,
    )

    progress_queue = None
    if progress_cb is not None:
        try:
            progress_queue = spyrrow.ProgressQueue(detailed=False)
        except Exception:
            progress_queue = None

    started = time.monotonic()
    try:
        solution = instance.solve(config, progress=progress_queue)
    except Exception:
        return None

    if solution is None or len(solution.placed_items) != len(shapes):
        return None

    shape_by_id = {str(shape.part_index): shape for shape in shapes}
    placements: list[Placement] = []
    for placed in solution.placed_items:
        shape = shape_by_id.get(str(placed.id))
        if shape is None:
            return None
        tx, ty = placed.translation  # spyrrow: (our_y, our_x)
        rotation = float(placed.rotation)
        our_angle = (-rotation) % 360.0
        polygon = translate_points(
            rotate_points(shape.outline, our_angle), float(ty), float(tx)
        )
        bounds = polygon_bounds(polygon)
        placements.append(
            Placement(
                part_index=shape.part_index,
                polygon=polygon,
                angle=our_angle,
                area=shape.area,
                bounds=bounds,
            )
        )

    layout = Layout(
        items=tuple(placements),
        width=float(options.width),
        length=float(solution.width),
        phase="Sparrow",
        free_rotation=any(
            not placement.is_right_angle for placement in placements
        ),
        complete=len(placements) == len(shapes),
        elapsed_s=time.monotonic() - started,
        candidates=1,
        groups=(),
        strategy="Sparrow (spyrrow)",
        assumptions=options.cut_assumptions,
    )

    if validate_layout(layout, options.width):
        return None
    return layout


def solve_sparrow_detailed(
    shapes: Sequence[Shape],
    options: NestingOptions,
    progress_cb: Callable[[NestingProgress], None] | None = None,
    cancel_event=None,
) -> NestingResult | None:
    if not is_spyrrow_available():
        return None
    started = time.monotonic()
    layout = solve_sparrow_layout(shapes, options, progress_cb, cancel_event)
    if layout is None:
        return None
    elapsed = time.monotonic() - started
    return NestingResult(
        layouts=(layout,),
        pareto=(layout,),
        all_layouts=(layout,),
        assumptions=options.cut_assumptions,
        scoring=options.scoring,
        elapsed_s=elapsed,
        candidates=1,
        phase_counts=(("Sparrow", 1),),
        min_length=layout.min_length,
        timed_out=False,
        cancelled=False,
    )
