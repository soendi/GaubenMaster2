import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.updater import (  # noqa: E402
    installer_filename,
    is_newer,
    parse_version,
)


class VersionTests(unittest.TestCase):
    def test_parse_plain_and_tag(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("  v10.0.12 "), (10, 0, 12))

    def test_parse_rejects_invalid(self):
        for value in ("", "1.2", "1.2.3.4", "v1.2.3-beta", "1.2.x", "01.2.3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_version(value)

    def test_semantic_comparison(self):
        self.assertTrue(is_newer("1.0.1", "1.0.0"))
        self.assertTrue(is_newer("1.10.0", "1.9.9"))
        self.assertTrue(is_newer("2.0.0", "1.99.99"))
        self.assertFalse(is_newer("1.0.0", "1.0.0"))
        self.assertFalse(is_newer("1.0.0", "1.0.1"))

    def test_installer_name(self):
        self.assertEqual(
            installer_filename("1.2.3"), "GaubenMaster2-Setup-1.2.3.msi"
        )


if __name__ == "__main__":
    unittest.main()
