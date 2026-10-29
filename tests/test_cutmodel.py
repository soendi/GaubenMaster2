"""Tests fuer das transparente Schnittkostenmodell."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.cutmodel import (
    CutAssumptions,
    CutModelError,
    CutPlan,
    compute_cut_plan,
    layout_cut_plan,
)
from gaubenmaster.nesting import Layout, Placement, Shape


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class CutModelTests(unittest.TestCase):
    def test_free_standing_polygon_needs_four_cuts(self):
        plan = compute_cut_plan([(1, rect(10, 10, 50, 30))], 100, 40)
        self.assertEqual(plan.operations, 4)
        self.assertEqual(plan.separating_operations, 0)
        self.assertEqual(plan.trim_operations, 4)
        self.assertEqual(plan.shared_edges, 0)
        self.assertAlmostEqual(plan.shared_length, 0.0, places=6)

    def test_corner_polygon_with_two_border_sides_needs_two_cuts(self):
        plan = compute_cut_plan([(1, rect(0, 0, 50, 50))], 100, 100)
        self.assertEqual(plan.operations, 2)
        self.assertEqual(plan.separating_operations, 0)
        self.assertEqual(plan.trim_operations, 2)

    def test_two_squares_border_left_top_right_need_two_cuts(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 50, 50)), (2, rect(50, 0, 100, 50))], 100, 60
        )
        self.assertEqual(plan.operations, 2)
        self.assertEqual(plan.separating_operations, 1)
        self.assertEqual(plan.trim_operations, 1)
        self.assertEqual(plan.shared_edges, 1)

    def test_two_side_by_side_share_one_vertical_line(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 40, 20)), (2, rect(40, 0, 80, 20))], 100, 20
        )
        self.assertEqual(plan.operations, 2)
        self.assertEqual(plan.shared_edges, 1)
        self.assertAlmostEqual(plan.shared_length, 20.0, places=6)
        self.assertAlmostEqual(plan.total_length, 40.0, places=6)

    def test_two_stacked_share_one_horizontal_line(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 50, 20)), (2, rect(0, 20, 50, 40))], 100, 40
        )
        self.assertEqual(plan.operations, 2)
        self.assertEqual(plan.shared_edges, 1)
        self.assertAlmostEqual(plan.shared_length, 50.0, places=6)

    def test_five_cm_gap_does_not_merge(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 40, 20)), (2, rect(45, 0, 85, 20))], 100, 20
        )
        self.assertEqual(plan.shared_edges, 0)
        self.assertAlmostEqual(plan.shared_length, 0.0, places=6)
        self.assertEqual(plan.operations, 3)

    def test_corner_touch_is_not_a_shared_cut(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 40, 20)), (2, rect(40, 20, 80, 40))], 100, 40
        )
        self.assertEqual(plan.shared_edges, 0)
        self.assertAlmostEqual(plan.shared_length, 0.0, places=6)

    def test_interlocked_triangles_need_two_cuts(self):
        plan = compute_cut_plan(
            [
                (1, [(0, 0), (60, 0), (0, 40)]),
                (2, [(60, 0), (60, 40), (0, 40)]),
            ],
            100,
            40,
        )
        self.assertEqual(plan.operations, 2)
        self.assertEqual(plan.separating_operations, 1)
        self.assertEqual(plan.trim_operations, 1)
        self.assertEqual(plan.shared_edges, 1)
        self.assertAlmostEqual(plan.shared_length, 72.111, places=2)

    def test_start_at_border_adds_plunge(self):
        plan = compute_cut_plan(
            [(1, rect(10, 10, 50, 30))],
            100,
            40,
            CutAssumptions(start_at_border=True),
        )
        self.assertEqual(plan.plunges, 1)
        self.assertEqual(plan.operations, 4)

    def test_border_rectangle_with_three_border_sides_needs_one_cut(self):
        plan = compute_cut_plan([(1, rect(0, 0, 100, 40))], 100, 100)
        self.assertEqual(plan.operations, 1)
        self.assertEqual(plan.trim_operations, 1)

    def test_kerf_non_zero_raises(self):
        with self.assertRaises(CutModelError):
            compute_cut_plan(
                [(1, rect(0, 0, 40, 20))],
                100,
                20,
                CutAssumptions(kerf_cm=0.5),
            )

    def test_negative_min_segment_raises(self):
        with self.assertRaises(CutModelError):
            CutAssumptions(min_segment_cm=-1.0).validated()

    def test_describe_contains_assumptions(self):
        plan = compute_cut_plan(
            [(1, rect(0, 0, 40, 20))], 100, 20
        )
        self.assertIn("Schnittmodell", plan.describe())
        self.assertIn("Fugenbreite", plan.assumptions.describe())

    def test_layout_cut_plan_convenience(self):
        shape = Shape.from_polygon(1, rect(0, 0, 40, 20))
        placement = Placement(
            part_index=1,
            polygon=shape.outline,
            angle=0.0,
            area=shape.area,
            bounds=(0.0, 0.0, 40.0, 20.0),
        )
        layout = Layout(
            items=(placement,),
            width=100.0,
            length=20.0,
            assumptions=CutAssumptions(),
        )
        plan = layout_cut_plan(layout.items, 100.0, 20.0)
        self.assertIsInstance(plan, CutPlan)
        self.assertEqual(plan.operations, 1)

    def test_empty_plan(self):
        plan = CutPlan.empty()
        self.assertEqual(plan.operations, 0)
        self.assertEqual(plan.segments, ())


if __name__ == "__main__":
    unittest.main()
