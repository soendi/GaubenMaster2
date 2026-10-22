import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.geometry import (  # noqa: E402
    GeometryError,
    calculate_triangle,
    distance,
    polygon_area,
    polygon_centroid,
)


class TriangleTests(unittest.TestCase):
    def test_three_four_five(self):
        triangle = calculate_triangle(3, 4, 5)
        self.assertAlmostEqual(triangle.area, 6.0, places=9)
        self.assertAlmostEqual(triangle.perimeter, 12.0, places=9)
        self.assertAlmostEqual(triangle.semiperimeter, 6.0, places=9)
        self.assertAlmostEqual(triangle.inradius, 1.0, places=9)
        self.assertAlmostEqual(triangle.circumradius, 2.5, places=9)
        self.assertAlmostEqual(triangle.ha, 4.0, places=9)
        self.assertAlmostEqual(triangle.hb, 3.0, places=9)
        self.assertAlmostEqual(triangle.hc, 2.4, places=9)
        self.assertAlmostEqual(triangle.alpha, 36.86989765, places=6)
        self.assertAlmostEqual(triangle.beta, 53.13010235, places=6)
        self.assertAlmostEqual(triangle.gamma, 90.0, places=9)

    def test_vertices_match_named_side_lengths(self):
        triangle = calculate_triangle(3, 4, 5)
        vertices = triangle.vertices
        self.assertAlmostEqual(distance(vertices[1], vertices[2]), triangle.a, places=9)
        self.assertAlmostEqual(distance(vertices[2], vertices[0]), triangle.b, places=9)
        self.assertAlmostEqual(distance(vertices[0], vertices[1]), triangle.c, places=9)

    def test_decimal_comma_is_not_part_of_geometry(self):
        triangle = calculate_triangle(3.0, 4.0, 5.0)
        self.assertEqual(triangle.vertices[1], (0.0, 0.0))
        self.assertAlmostEqual(triangle.vertices[2][0], 3.0)

    def test_invalid_sides_are_rejected(self):
        cases = (
            (0, 4, 5),
            (-3, 4, 5),
            (1, 1, 2),
            (1, 2, 4),
            (float("nan"), 3, 4),
            (3, float("inf"), 4),
        )
        for sides in cases:
            with self.subTest(sides=sides):
                with self.assertRaises(GeometryError):
                    calculate_triangle(*sides)

    def test_height_and_angle_sums(self):
        triangle = calculate_triangle(7.2, 8.1, 9.3)
        self.assertAlmostEqual(
            triangle.alpha + triangle.beta + triangle.gamma, 180.0, places=9
        )


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.triangle = calculate_triangle(3, 4, 5)

    def test_count_split_for_every_height(self):
        for name in ("ha", "hb", "hc"):
            with self.subTest(height=name):
                parts = self.triangle.split_height(name, "count", 4)  # type: ignore[arg-type]
                self.assertEqual(len(parts), 4)
                self.assertAlmostEqual(
                    sum(part.area_cm2 for part in parts),
                    self.triangle.area,
                    places=9,
                )
                self.assertAlmostEqual(
                    sum(part.height_cm for part in parts),
                    self.triangle.height(name),  # type: ignore[arg-type]
                    places=9,
                )
                for part in parts:
                    self.assertEqual(len(part.edges_cm), len(part.points))
                    self.assertEqual(len(part.angles_deg), len(part.points))
                    self.assertGreater(part.area_cm2, 0)

    def test_count_split_has_straight_strips(self):
        parts = self.triangle.split_height("ha", "count", 4)
        self.assertEqual([round(part.height_cm, 9) for part in parts], [1.0] * 4)

    def test_length_split_last_part_may_be_shorter(self):
        parts = self.triangle.split_height("ha", "length", 1.3)
        heights = [round(part.height_cm, 9) for part in parts]
        self.assertEqual(heights, [1.3, 1.3, 1.3, 0.1])
        self.assertAlmostEqual(sum(part.area_cm2 for part in parts), 6.0, places=9)

    def test_split_bounds(self):
        self.assertEqual(len(self.triangle.split_height("ha", "count", 2)), 2)
        self.assertEqual(len(self.triangle.split_height("ha", "count", 20)), 20)
        for value in (1, 21, 2.5):
            with self.subTest(value=value):
                with self.assertRaises(GeometryError):
                    self.triangle.split_height("ha", "count", value)
        for value in (0.0, 50.1):
            with self.subTest(value=value):
                with self.assertRaises(GeometryError):
                    self.triangle.split_height("ha", "length", value)

    def test_excessive_length_split_is_rejected(self):
        tall = calculate_triangle(2, 100, 100)
        with self.assertRaises(GeometryError):
            tall.split_height("ha", "length", 0.1)

    def test_polygon_helpers(self):
        square = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
        self.assertAlmostEqual(polygon_area(square), 4.0)
        self.assertEqual(polygon_centroid(square), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
