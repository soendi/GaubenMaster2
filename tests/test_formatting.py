import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.formatting import format_area, format_number  # noqa: E402


class FormattingTests(unittest.TestCase):
    def test_numbers_use_german_decimal_comma(self):
        self.assertEqual(format_number(12.345), "12,35")

    def test_small_area_stays_in_square_centimetres(self):
        self.assertEqual(format_area(999.99), "999,99 cm²")

    def test_large_area_switches_to_square_metres(self):
        self.assertEqual(format_area(1000.0), "0,1 m²")
        self.assertEqual(format_area(14211.26), "1,421126 m²")


if __name__ == "__main__":
    unittest.main()
