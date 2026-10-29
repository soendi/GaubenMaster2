import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.geometry import calculate_triangle  # noqa: E402
from gaubenmaster.nesting import (  # noqa: E402
    TARGET_LAYOUTS,
    NestingError,
    NestingOptions,
    Shape,
    layout_signature,
    nest_polygons,
    nest_shapes,
    polygons_overlap,
    shapes_from_parts,
    validate_layout,
)

TOLERANCE = 1e-6


def rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rect_shapes(sizes, start=1):
    return [
        Shape.from_polygon(start + index, rectangle(0.0, 0.0, width, height))
        for index, (width, height) in enumerate(sizes)
    ]


def fast_options(**overrides):
    values = {
        "time_budget_s": 6.0,
        "max_candidates": 40,
        "allow_free_rotation": True,
    }
    values.update(overrides)
    return NestingOptions(**values)


class GeometryTests(unittest.TestCase):
    def test_touching_rectangles_do_not_overlap(self):
        left = rectangle(0, 0, 10, 10)
        right = rectangle(10, 0, 20, 10)
        self.assertFalse(polygons_overlap(left, right))

    def test_overlapping_rectangles_collide(self):
        self.assertTrue(
            polygons_overlap(rectangle(0, 0, 10, 10), rectangle(9, 0, 20, 10))
        )

    def test_contained_polygon_collides(self):
        self.assertTrue(
            polygons_overlap(
                rectangle(0, 0, 20, 20), rectangle(5, 5, 10, 10)
            )
        )

    def test_concave_polygon_collision(self):
        # L-foermiges Polygon in der linken unteren Ecke.
        l_shape = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
        self.assertFalse(polygons_overlap(l_shape, rectangle(5, 5, 8, 8)))
        self.assertTrue(polygons_overlap(l_shape, rectangle(1, 1, 3, 3)))
        self.assertFalse(polygons_overlap(l_shape, rectangle(4, 4, 8, 8)))

    def test_self_intersecting_polygon_is_rejected(self):
        bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
        with self.assertRaises(NestingError):
            Shape.from_polygon(1, bowtie)

    def test_too_few_points_are_rejected(self):
        with self.assertRaises(NestingError):
            Shape.from_polygon(1, [(0, 0), (10, 0)])


class NestingTests(unittest.TestCase):
    def test_single_polygon(self):
        results = nest_shapes(rect_shapes([(100.0, 20.0)]), fast_options())
        self.assertTrue(results)
        layout = results[0]
        self.assertAlmostEqual(layout.length, 20.0, places=6)
        self.assertEqual(len(layout.items), 1)
        self.assertAlmostEqual(layout.waste_area, 0.0, places=6)
        self.assertEqual(validate_layout(layout), [])

    def test_two_parts_fit_side_by_side(self):
        results = nest_shapes(
            rect_shapes([(50.0, 20.0), (50.0, 20.0)]), fast_options()
        )
        self.assertTrue(results)
        layout = results[0]
        self.assertEqual(len(layout.items), 2)
        self.assertAlmostEqual(layout.length, 20.0, places=6)
        self.assertAlmostEqual(layout.waste_area, 0.0, places=3)

    def test_two_matching_parts_with_180_degree(self):
        # Zwei gleiche Trapeze: ungedreht nebeneinander brauchen sie 120 cm,
        # mit einer 180-Grad-Drehung passen sie verzahnt in eine 20-cm-Reihe.
        trapezoid = [(0.0, 0.0), (60.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
        shapes = [
            Shape.from_polygon(1, trapezoid),
            Shape.from_polygon(2, trapezoid),
        ]
        results = nest_shapes(shapes, fast_options(max_candidates=20))
        self.assertTrue(results)
        layout = results[0]
        self.assertAlmostEqual(layout.length, 20.0, places=6)
        self.assertTrue(
            any(abs(item.angle - 180.0) < 1e-6 for item in layout.items)
        )
        self.assertEqual(validate_layout(layout), [])

    def test_several_straight_and_odd_parts(self):
        triangle = calculate_triangle(60.0, 50.0, 40.0)
        parts = triangle.split_height("hb", "count", 7)
        shapes = shapes_from_parts(triangle, parts, "hb", (2.0, 1.0, 1.0))
        results = nest_shapes(shapes, fast_options(max_candidates=20))
        self.assertTrue(results)
        layout = results[0]
        self.assertEqual(len(layout.items), 7)
        self.assertEqual(validate_layout(layout), [])
        self.assertGreater(layout.length, 0.0)

    def test_odd_number_of_parts(self):
        results = nest_shapes(
            rect_shapes([(35.0, 15.0)] * 5), fast_options(max_candidates=20)
        )
        self.assertTrue(results)
        self.assertEqual(len(results[0].items), 5)
        self.assertEqual(validate_layout(results[0]), [])

    def test_triangle_between_rectangles(self):
        polygons = [
            (1, rectangle(0.0, 0.0, 40.0, 20.0)),
            (2, [(0.0, 0.0), (30.0, 0.0), (15.0, 15.0)]),
            (3, rectangle(0.0, 0.0, 50.0, 25.0)),
        ]
        results = nest_polygons(polygons, fast_options(max_candidates=20))
        self.assertTrue(results)
        layout = results[0]
        self.assertEqual(len(layout.items), 3)
        self.assertEqual(validate_layout(layout), [])

    def test_material_width_violation_is_reported(self):
        with self.assertRaises(NestingError) as context:
            nest_shapes(rect_shapes([(120.0, 120.0)]), fast_options())
        self.assertIn("Materialbreite", str(context.exception))

    def test_width_violation_is_detected_by_validator(self):
        shapes = rect_shapes([(60.0, 20.0)])
        layout = nest_shapes(shapes, fast_options())[0]
        broken = type(layout)(
            items=layout.items,
            width=20.0,
            length=layout.length,
            complete=True,
        )
        self.assertTrue(validate_layout(broken, width=20.0))

    def test_collision_is_detected_by_validator(self):
        from gaubenmaster.nesting import Layout, Placement

        polygon = tuple(rectangle(0.0, 0.0, 40.0, 20.0))
        first = Placement(1, polygon, 0.0, 800.0, (0.0, 0.0, 40.0, 20.0))
        second = Placement(
            2, tuple(rectangle(0.0, 0.0, 40.0, 20.0)), 0.0, 800.0,
            (20.0, 0.0, 60.0, 20.0),
        )
        layout = Layout(items=(first, second), width=100.0, length=20.0)
        errors = validate_layout(layout)
        self.assertTrue(any("ueberschneiden" in error for error in errors))

    def test_free_rotation_is_used_when_needed(self):
        # 120 x 10 cm passt nur gedreht in die 100-cm-Breite.
        results = nest_shapes(
            rect_shapes([(120.0, 10.0)]), fast_options(max_candidates=20)
        )
        self.assertTrue(results)
        layout = results[0]
        self.assertTrue(layout.free_rotation)
        self.assertGreater(layout.free_angle_count, 0)
        self.assertLess(layout.length, 120.0)
        self.assertEqual(validate_layout(layout), [])

    def test_multiple_distinct_solutions(self):
        results = nest_shapes(
            rect_shapes([(30.0, 20.0)] * 6), fast_options(max_candidates=30)
        )
        self.assertGreaterEqual(len(results), 2)
        self.assertLessEqual(len(results), TARGET_LAYOUTS)
        signatures = {layout_signature(layout) for layout in results}
        self.assertEqual(len(signatures), len(results))

    def test_live_events_do_not_change_results(self):
        shapes = rect_shapes([(40.0, 20.0), (30.0, 20.0), (20.0, 20.0)] * 2)
        options = fast_options(time_budget_s=10.0, max_candidates=6)
        without_live = nest_shapes(shapes, options)
        events = []
        with_live = nest_shapes(shapes, options, progress_cb=events.append)
        self.assertTrue(events)
        self.assertEqual(
            [layout_signature(layout) for layout in without_live],
            [layout_signature(layout) for layout in with_live],
        )
        self.assertEqual(
            [layout.length for layout in without_live],
            [layout.length for layout in with_live],
        )

    def test_manual_cancel_keeps_best_solution(self):
        shapes = rect_shapes([(25.0, 20.0)] * 8)
        cancel = threading.Event()
        results = []

        def on_progress(progress):
            if progress.event == "layout":
                cancel.set()

        started = time.monotonic()
        results = nest_shapes(
            shapes,
            fast_options(time_budget_s=20.0, max_candidates=1000),
            progress_cb=on_progress,
            cancel_event=cancel,
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5.0)
        self.assertTrue(results)
        self.assertTrue(all(layout.complete for layout in results))
        for layout in results:
            self.assertEqual(validate_layout(layout), [])

    def test_time_budget_is_respected(self):
        shapes = rect_shapes([(20.0, 15.0)] * 15)
        started = time.monotonic()
        results = nest_shapes(
            shapes,
            fast_options(time_budget_s=0.15, max_candidates=1000),
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3.0)
        for layout in results:
            self.assertEqual(validate_layout(layout), [])

    def test_empty_input(self):
        self.assertEqual(nest_shapes([], fast_options()), [])

    def test_realistic_triangle_parts_are_valid(self):
        triangle = calculate_triangle(200.0, 150.0, 100.0)
        parts = triangle.split_height("hb", "count", 6)
        shapes = shapes_from_parts(triangle, parts, "hb", (4.0, 2.0, 3.0))
        results = nest_shapes(
            shapes, fast_options(time_budget_s=4.0, max_candidates=40)
        )
        self.assertTrue(results)
        for layout in results:
            self.assertEqual(len(layout.items), 6)
            self.assertEqual(validate_layout(layout), [])
            for item in layout.items:
                self.assertGreaterEqual(item.bounds[0], -TOLERANCE)
                self.assertLessEqual(item.bounds[2], 100.0 + TOLERANCE)
                self.assertLessEqual(item.bounds[3], layout.length + TOLERANCE)

    def test_phase_a_uses_only_right_angles(self):
        results = nest_shapes(
            rect_shapes([(40.0, 20.0), (35.0, 20.0), (25.0, 15.0)]),
            fast_options(max_candidates=20),
        )
        self.assertTrue(results)
        for layout in results:
            if layout.phase == "A":
                for item in layout.items:
                    self.assertTrue(item.is_right_angle)


if __name__ == "__main__":
    unittest.main()
