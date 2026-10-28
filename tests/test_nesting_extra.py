"""Erweiterte Tests fuer Nesting, Pareto und Modi."""

import random
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.nesting import (
    MAX_PARETO_KEPT,
    SCORING_BALANCED,
    SCORING_CUTS,
    SCORING_WASTE,
    NestingOptions,
    NestingResult,
    Shape,
    nest_shapes,
    nest_shapes_detailed,
    pareto_front,
    validate_layout,
)


def rect_shape(i, w, h):
    return Shape.from_polygon(i, [(0, 0), (w, 0), (w, h), (0, h)])


class ExtendedNestingTests(unittest.TestCase):
    def test_reproducibility_with_seed(self):
        shapes = [rect_shape(i, 20, 15) for i in range(1, 9)]
        opts = NestingOptions(time_budget_s=1.0, random_seed=42)
        r1 = nest_shapes_detailed(shapes, opts)
        r2 = nest_shapes_detailed(shapes, opts)
        self.assertEqual(
            [round(l.length, 6) for l in r1.layouts],
            [round(l.length, 6) for l in r2.layouts],
        )
        self.assertEqual(
            [l.cut_operations for l in r1.layouts],
            [l.cut_operations for l in r2.layouts],
        )

    def test_three_modes_change_ranking(self):
        shapes = [rect_shape(i, 30, 20) for i in range(1, 7)]
        waste = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.5, scoring=SCORING_WASTE)
        )
        cuts = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.5, scoring=SCORING_CUTS)
        )
        balanced = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.5, scoring=SCORING_BALANCED)
        )
        self.assertTrue(waste.layouts)
        self.assertTrue(cuts.layouts)
        self.assertTrue(balanced.layouts)
        # Die Sortierreihenfolge darf sich unterscheiden.
        self.assertEqual(
            waste.scoring, SCORING_WASTE
        )
        self.assertEqual(cuts.scoring, SCORING_CUTS)
        self.assertEqual(balanced.scoring, SCORING_BALANCED)

    def test_pareto_front_non_dominated(self):
        shapes = [rect_shape(i, 20, 20) for i in range(1, 7)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=2.0)
        )
        front = result.pareto
        self.assertTrue(front)
        for layout in front:
            for other in front:
                if other is layout:
                    continue
                # kein anderer darf strikt besser in beiden Zielen sein
                self.assertFalse(
                    other.length < layout.length - 1e-9
                    and other.cut_operations < layout.cut_operations
                )

    def test_nesting_result_fields(self):
        shapes = [rect_shape(1, 40, 20), rect_shape(2, 40, 20)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0)
        )
        self.assertIsInstance(result, NestingResult)
        self.assertTrue(result.layouts)
        self.assertGreaterEqual(result.candidates, 0)
        self.assertGreaterEqual(result.elapsed_s, 0.0)
        self.assertTrue(result.min_length > 0)

    def test_groups_are_reported(self):
        shapes = [rect_shape(i, 20, 20) for i in range(1, 7)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.5, use_groups=True)
        )
        grouped = [layout for layout in result.layouts if layout.groups]
        self.assertTrue(grouped)
        self.assertGreater(grouped[0].group_count, 0)
        self.assertLessEqual(
            grouped[0].group_count + grouped[0].single_count,
            len(shapes),
        )

    def test_live_on_off_same_result(self):
        shapes = [rect_shape(i, 25, 15) for i in range(1, 7)]
        opts = NestingOptions(time_budget_s=1.0, random_seed=7)
        events = []
        with_live = nest_shapes_detailed(
            shapes, opts, progress_cb=events.append
        )
        without_live = nest_shapes_detailed(shapes, opts)
        self.assertEqual(
            [round(l.length, 6) for l in with_live.layouts],
            [round(l.length, 6) for l in without_live.layouts],
        )
        self.assertEqual(
            [l.cut_operations for l in with_live.layouts],
            [l.cut_operations for l in without_live.layouts],
        )

    def test_timeout_returns_valid_layouts(self):
        shapes = [rect_shape(i, 12, 18) for i in range(1, 6)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=0.2)
        )
        self.assertTrue(result.layouts)
        for layout in result.layouts:
            self.assertEqual(validate_layout(layout), [])
        # entweder Timeout oder Kandidatenlimit
        self.assertTrue(result.timed_out or result.candidates >= 1)

    def test_cancel_returns_valid_layouts(self):
        cancel = threading.Event()
        shapes = [rect_shape(i, 12, 18) for i in range(1, 21)]
        result_holder = {}

        def worker():
            result_holder["result"] = nest_shapes_detailed(
                shapes,
                NestingOptions(time_budget_s=10.0),
                cancel_event=cancel,
            )

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        cancel.set()
        thread.join(timeout=5.0)
        result = result_holder.get("result")
        self.assertIsNotNone(result)
        self.assertTrue(result.layouts)
        self.assertTrue(result.cancelled)
        for layout in result.layouts:
            self.assertEqual(validate_layout(layout), [])

    def test_duplicates_removed(self):
        shapes = [rect_shape(i, 20, 20) for i in range(1, 5)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0)
        )
        sigs = {layout.geometry_signature() for layout in result.layouts}
        self.assertEqual(len(sigs), len(result.layouts))

    def test_cut_operations_property(self):
        shapes = [rect_shape(1, 40, 20), rect_shape(2, 40, 20)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0)
        )
        self.assertTrue(result.layouts)
        for layout in result.layouts:
            self.assertGreaterEqual(layout.cut_operations, 0)
            self.assertGreaterEqual(layout.cut_plan.operations, 0)

    def test_validate_layout_checks_cut_plan(self):
        shapes = [rect_shape(1, 40, 20)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0)
        )
        layout = result.layouts[0]
        self.assertEqual(validate_layout(layout), [])

    def test_all_zero_rotation_phase_a_only(self):
        shapes = [rect_shape(i, 20, 20) for i in range(1, 5)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0, allow_free_rotation=False)
        )
        self.assertTrue(result.layouts)
        for layout in result.layouts:
            self.assertFalse(layout.free_rotation)
        self.assertEqual(result.phase_count("B"), 0)

    def test_shortfall_for_single_part(self):
        shapes = [rect_shape(1, 40, 20)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=1.0)
        )
        # nur eine geometrische Familie
        self.assertTrue(result.complete_shortfall)

    def test_pareto_front_limit(self):
        shapes = [rect_shape(i, 20, 20) for i in range(1, 7)]
        result = nest_shapes_detailed(
            shapes, NestingOptions(time_budget_s=2.0)
        )
        self.assertLessEqual(len(result.pareto), MAX_PARETO_KEPT)

    def test_empty_shapes_returns_empty_result(self):
        result = nest_shapes_detailed([], NestingOptions())
        self.assertEqual(result.layouts, ())
        self.assertEqual(result.pareto, ())


if __name__ == "__main__":
    unittest.main()
