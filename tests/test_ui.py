import sys
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.ui import App  # noqa: E402


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tkinter ist nicht verfuegbar: {exc}")
        self.root.withdraw()
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def test_default_triangle_and_parts(self):
        self.app._calculate()
        self.assertIsNotNone(self.app.triangle)
        self.assertAlmostEqual(self.app.triangle.area, 6.0)
        self.assertIn("α=36,87°", self.app.status.cget("text"))

    def test_height_split_updates_view_and_sidebar(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.assertEqual(len(self.app.parts), 4)
        self.assertEqual(len(self.app.view.parts), 4)
        text = self.app.parts_text.get("1.0", "end")
        for index in range(1, 5):
            self.assertIn(f"Teil {index}", text)

    def test_invalid_input_shows_error(self):
        self.app.side_vars["a"].set("1")
        self.app.side_vars["b"].set("1")
        self.app.side_vars["c"].set("3")
        self.app._calculate()
        self.assertIsNone(self.app.triangle)
        self.assertIn("✗", self.app.validation.cget("text"))

    def test_length_mode_updates_spinbox(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app.mode_var.set("length")
        self.app._mode_changed()
        self.assertEqual(self.app.param_label.cget("text"), "Teil-Länge (cm)")
        self.assertEqual(len(self.app.parts), 2)


if __name__ == "__main__":
    unittest.main()
