import math
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.partdraw import PartPopup  # noqa: E402
from gaubenmaster.pdfexport import export_pdf  # noqa: E402
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

    def test_left_sidebar_is_240_pixels_wide(self):
        self.assertEqual(int(self.app.left.cget("width")), 240)

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

    def test_angle_labels_are_white_and_transparent(self):
        self.app._calculate()
        items = self.app.view.find_withtag("angle-label")
        texts = [
            item for item in items if self.app.view.type(item) == "text"
        ]
        self.assertEqual(len(texts), 3)
        for item in texts:
            self.assertEqual(self.app.view.itemcget(item, "fill"), "#ffffff")
        self.assertFalse(
            any(self.app.view.type(item) == "rectangle" for item in items)
        )

    def test_vertex_labels_are_transparent(self):
        self.app._calculate()
        items = self.app.view.find_withtag("vertex-label")
        texts = [
            item for item in items if self.app.view.type(item) == "text"
        ]
        self.assertEqual(len(texts), 3)
        self.assertFalse(
            any(self.app.view.type(item) == "rectangle" for item in items)
        )

    def test_side_dimensions_are_outside_centered_and_match_edge_lengths(self):
        view = self.app.view
        with (
            mock.patch.object(view, "winfo_width", return_value=1200),
            mock.patch.object(view, "winfo_height", return_value=800),
        ):
            self.app._calculate()
            self.app._rebuild_view()

        vertices = self.app.triangle.vertices
        screen = [view._to_screen(point) for point in vertices]
        centroid = (
            sum(point[0] for point in screen) / 3.0,
            sum(point[1] for point in screen) / 3.0,
        )
        for name, index1, index2 in (("a", 1, 2), ("b", 2, 0), ("c", 0, 1)):
            line_id = view.find_withtag(f"side-dimension-{name}")[0]
            self.assertEqual(float(view.itemcget(line_id, "width")), 1.0)
            x1, y1, x2, y2 = view.coords(line_id)
            edge_length = math.hypot(
                screen[index2][0] - screen[index1][0],
                screen[index2][1] - screen[index1][1],
            )
            self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), edge_length, places=6)

            line_mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            edge_mid = (
                (screen[index1][0] + screen[index2][0]) / 2.0,
                (screen[index1][1] + screen[index2][1]) / 2.0,
            )
            self.assertGreater(
                math.hypot(line_mid[0] - centroid[0], line_mid[1] - centroid[1]),
                math.hypot(edge_mid[0] - centroid[0], edge_mid[1] - centroid[1])
                + 50.0,
            )

            text_id = next(
                item
                for item in view.find_withtag(f"side-label-{name}")
                if view.type(item) == "text"
            )
            label_x, label_y = view.coords(text_id)
            self.assertAlmostEqual(label_x, line_mid[0], places=6)
            self.assertAlmostEqual(label_y, line_mid[1], places=6)

    def test_display_options_hide_main_measurements(self):
        self.app._calculate()
        self.app.option_vars["main_angles"].set(False)
        self.app.option_vars["main_angle_arcs"].set(False)
        self.app.option_vars["main_dimensions"].set(False)
        self.app._display_changed()
        self.assertEqual(self.app.view.find_withtag("angle-label"), ())
        self.assertEqual(self.app.view.find_withtag("angle-arc"), ())
        self.assertEqual(self.app.view.find_withtag("side-dimension-a"), ())

    def test_display_font_and_zoom_are_applied(self):
        self.app._calculate()
        self.app.font_var.set("13")
        self.app.zoom_var.set("2,0")
        self.app._display_changed()
        self.assertEqual(self.app.view.options.font_size, 13)
        self.assertAlmostEqual(self.app.view.zoom, 2.0)
        text_id = self.app.view.find_withtag("angle-label")[0]
        self.assertIn("26", self.app.view.itemcget(text_id, "font"))

    def test_part_area_labels_switch_to_square_metres(self):
        self.app.side_vars["a"].set("250")
        self.app.side_vars["b"].set("120")
        self.app.side_vars["c"].set("310")
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        canvas = self.app.parts_list.canvas
        with (
            mock.patch.object(canvas, "winfo_width", return_value=380),
            mock.patch.object(canvas, "winfo_height", return_value=800),
        ):
            self.app.parts_list.redraw()
        labels = [
            canvas.itemcget(item, "text")
            for item in canvas.find_withtag("part-area-label")
        ]
        self.assertTrue(labels)
        self.assertTrue(any("m²" in label for label in labels))

    def test_pdf_export_contains_main_and_part_pages(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.app.extra_vars["length_extra"].set("2,0")
        self.app.extra_vars["fold_front"].set("1,0")
        self.app.extra_vars["fold_back"].set("3,0")
        self.app._height_changed()
        self.app.view.rotation = 25.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gaube.pdf"
            export_pdf(
                path,
                self.app.triangle,
                self.app.parts,
                self.app._height_name(),
                self.app._extras(),
                self.app.display_options,
                rotation=self.app.view.rotation,
                master=self.root,
            )
            data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertEqual(data.count(b"/Type /Page "), 2)
        self.assertIn(b"Teil 1", data)

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

    def test_part_popup_is_800_pixels_and_draws_content(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.root.deiconify()
        part = self.app.parts[0]
        extras = (2.0, 1.0, 3.0)
        popup = PartPopup(self.app.parts_list, part, self.app.parts_list.axis, extras)
        try:
            popup.update_idletasks()
            self.assertEqual(popup.winfo_width(), 800)
            self.assertEqual(popup.winfo_height(), 800)
            popup._draw(part, self.app.parts_list.axis, extras)
            self.assertGreater(len(popup.canvas.find_all()), 0)
        finally:
            popup.destroy()
            self.root.withdraw()

    def test_plate_planning_window_packs_all_parts(self):
        self.app._calculate()
        self.app.height_var.set(True)
        self.app._rebuild_view()
        self.app._open_plate_planning()
        windows = [
            widget
            for widget in self.root.winfo_children()
            if isinstance(widget, tk.Toplevel)
        ]
        self.assertEqual(len(windows), 1)
        window = windows[0]
        try:
            window.update_idletasks()
            window._recalculate()
            with (
                mock.patch.object(
                    window.canvas, "winfo_width", return_value=900
                ),
                mock.patch.object(
                    window.canvas, "winfo_height", return_value=700
                ),
            ):
                window._draw_strip()
            self.assertEqual(len(window._strip["items"]), len(self.app.parts))
            self.assertEqual(window._unplaced, [])
            self.assertIn("Coil-Länge", window.status.cget("text"))
            self.assertGreater(len(window.canvas.find_all()), 0)
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
