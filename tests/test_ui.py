import sys
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.partdraw import PartPopup  # noqa: E402
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
        self.assertEqual(len(self.app.parts_list.parts), 4)
        self.assertEqual(
            [part.index for part in self.app.parts_list.parts], [1, 2, 3, 4]
        )

    def test_left_sidebar_is_220_pixels_wide(self):
        self.assertEqual(int(self.app.left.cget("width")), 220)

    def test_angle_labels_use_requested_format(self):
        self.app._calculate()
        texts = [
            self.app.view.itemcget(item, "text")
            for item in self.app.view.find_all()
            if self.app.view.type(item) == "text"
        ]
        self.assertIn("36.9°", texts)
        self.assertIn("53.1°", texts)
        self.assertIn("90.0°", texts)

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

    def test_cut_extras_are_passed_to_drawings(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.app.extra_vars["length_extra"].set("2,0")
        self.app.extra_vars["fold_front"].set("1,0")
        self.app.extra_vars["fold_back"].set("3,0")
        self.app._height_changed()
        self.assertEqual(self.app.parts_list.extras, (2.0, 1.0, 3.0))

    def test_part_popup_is_250_pixels_and_draws_content(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.root.deiconify()
        part = self.app.parts[0]
        extras = (2.0, 1.0, 3.0)
        popup = PartPopup(self.app.parts_list, part, self.app.parts_list.axis, extras)
        try:
            popup.update_idletasks()
            self.assertEqual(popup.winfo_width(), 250)
            self.assertEqual(popup.winfo_height(), 250)
            popup._draw(part, self.app.parts_list.axis, extras)
            self.assertGreater(len(popup.canvas.find_all()), 0)
        finally:
            popup.destroy()
            self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
