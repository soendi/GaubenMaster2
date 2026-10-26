import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.geometry import calculate_triangle  # noqa: E402
from gaubenmaster.plateplanning import (  # noqa: E402
    ANGLE_STEP_DEG,
    STRIP_WIDTH_CM,
    _bounds,
    _pack_strip_best,
    _part_shapes,
    _strip_length,
)

TOLERANCE = 1e-6


def _convex_hull(points):
    unique = sorted({(round(x, 9), round(y, 9)) for x, y in points})
    if len(unique) <= 2:
        return unique

    def cross(origin, first, second):
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _axes(polygon):
    axes = []
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-12:
            continue
        axes.append((-dy / length, dx / length))
    return axes


def _project(polygon, axis):
    values = [x * axis[0] + y * axis[1] for x, y in polygon]
    return min(values), max(values)


def _hulls_overlap(first, second):
    for polygon in (first, second):
        for axis in _axes(polygon):
            first_min, first_max = _project(first, axis)
            second_min, second_max = _project(second, axis)
            if (
                first_max <= second_min + TOLERANCE
                or second_max <= first_min + TOLERANCE
            ):
                return False
    return True


class StripPackingTests(unittest.TestCase):
    def setUp(self):
        self.triangle = calculate_triangle(11.0, 8.5, 17.5)
        self.parts = self.triangle.split_height("hb", "count", 6)
        self.extras = (4.0, 2.0, 3.0)

    def _layout(self, extras=None, rotation=True, width=STRIP_WIDTH_CM):
        shapes = _part_shapes(
            self.triangle,
            self.parts,
            "hb",
            self.extras if extras is None else extras,
            rotation,
        )
        return _pack_strip_best(shapes, width)

    def test_all_parts_fit_on_coil(self):
        strip, unplaced = self._layout()
        self.assertEqual(unplaced, [])
        self.assertEqual(len(strip["items"]), len(self.parts))
        self.assertGreater(_strip_length(strip), 0.0)

    def test_parts_stay_inside_coil_width_and_computed_length(self):
        strip, _unplaced = self._layout()
        length = _strip_length(strip)
        self.assertGreater(length, 0.0)
        for item in strip["items"]:
            x0, y0, x1, y1 = _bounds(item["polygon"])
            self.assertGreaterEqual(x0, -TOLERANCE)
            self.assertGreaterEqual(y0, -TOLERANCE)
            self.assertLessEqual(x1, STRIP_WIDTH_CM + TOLERANCE)
            self.assertLessEqual(y1, length + TOLERANCE)

    def test_parts_do_not_overlap(self):
        strip, _unplaced = self._layout()
        hulls = [
            _convex_hull(item["polygon"]) for item in strip["items"]
        ]
        for index, first in enumerate(hulls):
            for second in hulls[index + 1 :]:
                self.assertFalse(_hulls_overlap(first, second))

    def test_computed_length_matches_parts(self):
        strip, _unplaced = self._layout()
        highest = max(
            _bounds(item["polygon"])[3] for item in strip["items"]
        )
        self.assertAlmostEqual(_strip_length(strip), highest)

    def test_nesting_uses_the_strip_length_instead_of_rows(self):
        strip, _unplaced = self._layout()
        # Reine Reihenplatzierung brauchte fuer diese Teile 12,65 cm.
        self.assertLess(_strip_length(strip), 10.0)

    def test_nesting_interlocks_parts(self):
        strip, _unplaced = self._layout()
        ranges = [
            (_bounds(item["polygon"])[1], _bounds(item["polygon"])[3])
            for item in strip["items"]
        ]
        overlapping_pairs = 0
        for index, first in enumerate(ranges):
            for second in ranges[index + 1 :]:
                if min(first[1], second[1]) > max(first[0], second[0]) + TOLERANCE:
                    overlapping_pairs += 1
        self.assertGreater(overlapping_pairs, 0)

    def test_nesting_uses_non_right_angles(self):
        strip, _unplaced = self._layout()
        self.assertTrue(
            any(
                abs(item["angle"] % 90.0) > TOLERANCE
                for item in strip["items"]
            )
        )

    def test_free_rotation_uses_more_than_right_angles(self):
        shapes = _part_shapes(
            self.triangle, self.parts, "hb", self.extras, True
        )
        for shape in shapes:
            angles = {variant["angle"] for variant in shape["variants"]}
            self.assertGreater(len(angles), 2)
            self.assertTrue(any(angle % 90 != 0 for angle in angles))
            self.assertTrue(all(0 <= angle < 180 for angle in angles))
            self.assertTrue(
                all(angle % ANGLE_STEP_DEG == 0 for angle in angles)
            )

    def test_rotation_reduces_bounding_box_width(self):
        shapes = _part_shapes(
            self.triangle, self.parts, "hb", self.extras, True
        )
        for shape in shapes:
            widths = [variant["width"] for variant in shape["variants"]]
            self.assertLess(min(widths), shape["variants"][0]["width"])

    def test_rotation_can_be_disabled(self):
        strip, unplaced = self._layout(rotation=False)
        self.assertEqual(unplaced, [])
        for item in strip["items"]:
            self.assertAlmostEqual(item["angle"] % 360.0, 0.0)

    def test_allowances_increase_cut_area(self):
        plain = _part_shapes(
            self.triangle, self.parts, "hb", (0.0, 0.0, 0.0), True
        )
        extended = _part_shapes(
            self.triangle, self.parts, "hb", self.extras, True
        )
        self.assertGreater(
            sum(shape["area"] for shape in extended),
            sum(shape["area"] for shape in plain),
        )

    def test_part_wider_than_coil_is_reported(self):
        shapes = _part_shapes(
            self.triangle, self.parts, "hb", self.extras, True
        )
        strip, unplaced = _pack_strip_best(shapes, 1.0)
        self.assertEqual(strip["items"], [])
        self.assertEqual(len(unplaced), len(self.parts))

    def test_empty_input(self):
        strip, unplaced = _pack_strip_best([], STRIP_WIDTH_CM)
        self.assertEqual(strip["items"], [])
        self.assertEqual(unplaced, [])
        self.assertEqual(_strip_length(strip), 0.0)

    def test_random_layouts_have_no_overlap(self):
        generator = random.Random(20260310)
        for _case in range(3):
            while True:
                sides = [generator.uniform(3.0, 40.0) for _ in range(3)]
                if (
                    sides[0] + sides[1] > sides[2]
                    and sides[0] + sides[2] > sides[1]
                    and sides[1] + sides[2] > sides[0]
                ):
                    break
            triangle = calculate_triangle(*sides)
            height_name = generator.choice(["ha", "hb", "hc"])
            count = generator.randint(3, 6)
            parts = triangle.split_height(height_name, "count", count)
            extras = tuple(
                generator.uniform(0.0, 6.0) for _ in range(3)
            )
            shapes = _part_shapes(
                triangle, parts, height_name, extras, True
            )
            strip, unplaced = _pack_strip_best(shapes, STRIP_WIDTH_CM)
            self.assertEqual(unplaced, [])
            for item in strip["items"]:
                x0, _y0, x1, _y1 = _bounds(item["polygon"])
                self.assertGreaterEqual(x0, -TOLERANCE)
                self.assertLessEqual(x1, STRIP_WIDTH_CM + TOLERANCE)
            hulls = [
                _convex_hull(item["polygon"]) for item in strip["items"]
            ]
            for index, first in enumerate(hulls):
                for second in hulls[index + 1 :]:
                    self.assertFalse(_hulls_overlap(first, second))


if __name__ == "__main__":
    unittest.main()
