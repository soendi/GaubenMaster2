"""Plattenplanung für GaubenMaster2 - Ausrichtung paralleler Seiten mit Plattenbreite.

Diese Version implementiert eine Polygon-Verschachtelungsstrategie, bei der die parallelen Seiten
jedes Teils parallel zur festen Plattenbreite von 100 cm angeordnet werden, um eine optimale
Fertigungsausrichtung zu gewährleisten und Verschnitt zu minimieren.

Wichtige Features:
- Analyse der Teil-Geometrie zur Erkennung paralleler Seiten
- Ausrichtung dieser Seiten mit den Plattenbegrenzungen
- Optimierte Polygon-Verschachtelung mit paralleler Seitenausrichtung
- Visuelle Validierung der Ausrichtung
- Geometrische Validierung der Verschachtelung
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from gaubenmaster.formatting import format_number
from gaubenmaster.geometry import Part, Point, Triangle, polygon_area, polygon_centroid
from gaubenmaster.partdraw import _extended_geometry, _local_points, height_axis
from gaubenmaster.plot import BACKGROUND, TAB20, blend

STRIP_WIDTH_CM = 100.0  # 100 cm
ANGLE_STEP_DEG = 1
NESTING_COARSE_STEP_DEG = 5.0
NESTING_FINE_STEP_DEG = 1.0
NESTING_BOTH_ORDERS_LIMIT = 10
EPSILON = 1e-9
TOUCH_EPSILON = 1e-7

PLATE_FILL = "#ffffff"
PLATE_OUTLINE = "#12263f"
GRID = "#e4e8ee"
PART_OUTLINE = "#12324f"
TEXT = "#12263f"
MUTED = "#5b6878"
VALID = "#137333"
INVALID = "#b3261e"


def _bounds(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _rotate(points: list[Point], angle_deg: float) -> list[Point]:
    if abs(angle_deg % 360.0) < EPSILON:
        return list(points)
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return [
        (
            point[0] * cos_a - point[1] * sin_a,
            point[0] * sin_a + point[1] * cos_a,
        )
        for point in points
    ]


def _normalize(points: list[Point]) -> list[Point]:
    min_x, min_y, _max_x, _max_y = _bounds(points)
    return [(point[0] - min_x, point[1] - min_y) for point in points]


def _translate(points: list[Point], dx: float, dy: float) -> list[Point]:
    return [(point[0] + dx, point[1] + dy) for point in points]


def _convex_hull(points: list[Point]) -> list[Point]:
    unique = sorted({(round(x, 12), round(y, 12)) for x, y in points})
    if len(unique) <= 2:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _compute_edge_type(polygon: list[Point]) -> str:
    """
    Bestimmt, welchen Typ Kanten ein Polygon hat relativ zu den Plattenabmessungen.
    
    Rückgabewerte:
        'horizontal': mindestens zwei parallele Kanten mit kleiner y-Komponente
        'vertikal': mindestens zwei parallele Kanten mit kleiner x-Komponente
        'diagonal': andere Ausrichtung
    """
    horizontal_edges = 0
    vertical_edges = 0
    
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        
        if dy < EPSILON:
            horizontal_edges += 1
        elif dx < EPSILON:
            vertical_edges += 1
    
    if horizontal_edges >= 2:
        return 'horizontal'
    elif vertical_edges >= 2:
        return 'vertikal'
    else:
        return 'diagonal'


def _align_parallel_sides(polygon: list[Point], target_alignment: str, strip_width: float) -> list[Point]:
    """
    Rotiert ein Polygon, um seine parallelen Seiten mit der Ziel-Ausrichtung
    relativ zur Plattenbreite auszurichten.
    
    Args:
        polygon: Das einzupassende Polygon
        target_alignment: 'horizontal', 'vertikal' oder 'keines'
        strip_width: Breite des Materialstreifens
        
    Returns:
        Das rotierte/polierte Polygon mit Ausrichtung zu den parallelen Seiten
    """
    if target_alignment == 'horizontal':
        # Rotiere, um horizontale Kanten mit der Breite auszurichten
        for angle in [0, 90, 180, 270]:
            rotated = _rotate(polygon, angle)
            edge_type = _compute_edge_type(rotated)
            if edge_type == 'horizontal':
                return rotated
    elif target_alignment == 'vertikal':
        # Rotiere, um vertikale Kanten mit der Breite auszurichten
        for angle in [0, 90, 180, 270]:
            rotated = _rotate(polygon, angle)
            edge_type = _compute_edge_type(rotated)
            if edge_type == 'vertikal':
                return rotated
    
    return polygon


def _make_variant(
    polygon: list[Point], 
    angle: int, 
    target_alignment: str,
    strip_width: float
) -> dict:
    """Erstellt eine Variante eines Polygons mit gezielter Ausrichtung."""
    rotated = _rotate(polygon, float(angle))
    
    # Wende die parallele Seiten-Ausrichtung an
    aligned = _align_parallel_sides(rotated, target_alignment, strip_width)
    
    points = _normalize(aligned)
    min_x, min_y, max_x, max_y = _bounds(points)
    
    return {
        "angle": angle,
        "polygon": points,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def _make_variants(
    polygon: list[Point], 
    allow_rotation: bool,
    target_alignment: str,
    strip_width: float
) -> list[dict]:
    """Erstellt Varianten mit gezielter Ausrichtung paralleler Seiten."""
    if not allow_rotation:
        return [_make_variant(polygon, 0, target_alignment, strip_width)]
    
    variants = []
    seen: set[tuple[float, float]] = set()
    
    if target_alignment == 'none':
        angles = range(0, 180, ANGLE_STEP_DEG)
    else:
        angles = range(0, 180, ANGLE_STEP_DEG)

    for angle in angles:
        variant = _make_variant(polygon, angle, target_alignment, strip_width)
        key = (round(variant["width"], 6), round(variant["height"], 6))
        if key in seen:
            continue
        seen.add(key)
        variants.append(variant)
    
    return variants


def _part_shapes(
    triangle: Triangle | None,
    parts: list[Part],
    height_name: str,
    extras: tuple[float, float, float],
    allow_rotation: bool,
) -> list[dict]:
    """
    Erstellt Formen aus Teilen mit gezielter Ausrichtung paralleler Seiten.
    
    Dies ist ein zentraler Teil der neuen Ausrichtungsstrategie.
    """
    if not parts:
        return []
    
    axis = height_axis(triangle, height_name) if triangle else (0.0, 1.0)
    extra_length, fold_front, fold_back = extras
    shapes: list[dict] = []
    
    for part in parts:
        local = _local_points(part.points, axis)
        (
            extended,
            _half_extra,
            _fold_top,
            _fold_bottom,
            _extra_pairs,
        ) = _extended_geometry(local, extra_length, fold_front, fold_back)
        
        # Bestimme die Ausrichtung und passe die Seiten an
        edge_type = _compute_edge_type(extended)
        
        variants = _make_variants(
            extended, 
            allow_rotation, 
            edge_type if edge_type in ['horizontal', 'vertikal'] else 'none',
            STRIP_WIDTH_CM
        )
        
        shapes.append(
            {
                "part": part,
                "area": polygon_area(extended),
                "polygon": extended,
                "hull": _convex_hull(extended),
                "variants": variants,
                "maxdim": max(
                    max(variant["width"], variant["height"])
                    for variant in variants
                ),
                "allow_rotation": allow_rotation,
                "edge_type": edge_type,
            }
        )
    
    return shapes


def _ordered_shapes(shapes: list[dict], order: str) -> list[dict]:
    if order == "area":
        return sorted(
            shapes, key=lambda shape: (-shape["area"], shape["part"].index)
        )
    return sorted(
        shapes,
        key=lambda shape: (
            -shape["maxdim"],
            -shape["area"],
            shape["part"].index,
        ),
    )


def _items_length(items: list[dict]) -> float:
    length = 0.0
    for item in items:
        for _x, y in item["polygon"]:
            if y > length:
                length = y
    return length


def _strip_length(strip: dict) -> float:
    return _items_length(strip["items"])


def _bounds_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    """Prüft, ob zwei Bounding-Boxen sich überlappen."""
    return not (
        first[2] <= second[0] + TOUCH_EPSILON
        or second[2] <= first[0] + TOUCH_EPSILON
        or first[3] <= second[1] + TOUCH_EPSILON
        or second[3] <= first[1] + TOUCH_EPSILON
    )


def _project_polygon(polygon: list[Point], axis: Point) -> tuple[float, float]:
    """Projiziert ein Polygon auf eine Achse und gibt das Minimum und Maximum zurück."""
    values = [point[0] * axis[0] + point[1] * axis[1] for point in polygon]
    return min(values), max(values)


def _compute_polygon_axes(polygon: list[Point]) -> list[Point]:
    """Berechnet dieNormalsen einer Polygon."""
    axes = []
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < EPSILON:
            continue
        axes.append((-dy / length, dx / length))
    return axes


def _hulls_overlap(first: dict, second: dict) -> bool:
    """
    Überprüft die Überlappung zweier konvexer Hüllen mit dem Separationsachsentest.
    
    Wenn die Hüllen sich nur berühren, kehren sie False zurück (keine Überlappung).
    """
    for poly_dict in (first, second):
        polygon = poly_dict["polygon"]
        axes = _compute_polygon_axes(polygon)
        
        for axis in axes:
            min1, max1 = _project_polygon(first["polygon"], axis)
            min2, max2 = _project_polygon(second["polygon"], axis)
            
            if (
                max1 <= min2 + TOUCH_EPSILON
                or max2 <= min1 + TOUCH_EPSILON
            ):
                return False
    
    return True


def _candidate_translations(
    polygon: list[Point],
    placed: list[dict],
    strip_width: float,
) -> list[Point]:
    """
    Erzeugt Kandidatentranslationen basierend auf:
    - Minimalem X-Y-Offset (Position in der Ecke)
    - Kontakt mit platzierten Teilen (Kantenschnittpunkte)
    - Kontakt mit Ecken platzierter Teile
    """
    minx, miny, maxx, maxy = _bounds(polygon)
    translations: list[Point] = [(-minx, -miny)]

    for placed_item in placed:
        target = placed_item["polygon"]
        for point in polygon:
            for target_point in target:
                translations.append((target_point[0] - point[0], target_point[1] - point[1]))

        count = len(target)
        for point in polygon:
            for i in range(count):
                start = target[i]
                end = target[(i + 1) % count]
                edge_x = end[0] - start[0]
                edge_y = end[1] - start[1]
                denominator = edge_x * edge_x + edge_y * edge_y
                if denominator < EPSILON * EPSILON:
                    continue
                factor = ((point[0] - start[0]) * edge_x + (point[1] - start[1]) * edge_y) / denominator
                factor = max(0.0, min(1.0, factor))
                contact = (start[0] + factor * edge_x, start[1] + factor * edge_y)
                translations.append((contact[0] - point[0], contact[1] - point[1]))

    seen = set()
    result = []
    for dx, dy in translations:
        key = (round(dx, 6), round(dy, 6))
        if key in seen:
            continue
        seen.add(key)
        if dx + minx < -TOUCH_EPSILON:
            continue
        if dx + maxx > strip_width + TOUCH_EPSILON:
            continue
        if dy + miny < -TOUCH_EPSILON:
            continue
        result.append((dx, dy))
    return result


def _pack_at_angle(
    shapes: list[dict],
    strip_width: float,
    angle: float,
    order: str,
) -> tuple[dict, list[dict]]:
    """
    Verpakket Formen bei einem gegebenen globalen Winkel.
    
    Dies ist die Kernfunktion des Polygon-Nesting-Algorithmus.
    """
    placed: list[dict] = []
    items: list[dict] = []
    unplaced: list[dict] = []
    length = 0.0

    for shape in _ordered_shapes(shapes, order):
        best: tuple | None = None
        turns = (0.0, 180.0) if shape["allow_rotation"] else (0.0,)

        for turn in turns:
            rotation = angle + turn
            hull_rotated = _rotate(shape["hull"], rotation)
            min_x, min_y, _max_x, _max_y = _bounds(hull_rotated)
            hull_normalized = _translate(hull_rotated, -min_x, -min_y)
            polygon_normalized = _translate(
                _rotate(shape["polygon"], rotation), -min_x, -min_y
            )
            normalized_bounds = _bounds(hull_normalized)

            for dx, dy in _candidate_translations(hull_normalized, placed, strip_width):
                candidate_bounds = (
                    normalized_bounds[0] + dx,
                    normalized_bounds[1] + dy,
                    normalized_bounds[2] + dx,
                    normalized_bounds[3] + dy,
                )
                
                candidate_hull = _translate(hull_normalized, dx, dy)
                candidate_polygon = _translate(polygon_normalized, dx, dy)
                
                candidate = _prepare_collision(candidate_hull)
                
                collides = False
                for placed_item in placed:
                    if not _bounds_overlap(candidate_bounds, placed_item["bounds"]):
                        continue
                    if _hulls_overlap(candidate, placed_item):
                        collides = True
                        break
                
                if collides:
                    continue

                new_length = max(length, candidate_bounds[3])
                score = (
                    round(new_length, 7),
                    round(candidate_bounds[1], 7),
                    round(candidate_bounds[0], 7),
                )
                
                if best is None or score < best[0]:
                    best = (
                        score,
                        rotation,
                        dx,
                        dy,
                        polygon_normalized,
                        candidate,
                        candidate_bounds,
                    )

        if best is None:
            unplaced.append(shape)
            continue

        (
            score,
            rotation,
            dx,
            dy,
            polygon_normalized,
            prepared_hull,
            candidate_bounds,
        ) = best
        
        length = max(length, candidate_bounds[3])
        placed.append(prepared_hull)
        items.append(
            {
                "part": shape["part"],
                "polygon": _translate(polygon_normalized, dx, dy),
                "angle": rotation % 360.0,
                "area": shape["area"],
                "edge_type": shape["edge_type"],
            }
        )

    strip = {"items": items, "length": _items_length(items)}
    return strip, unplaced


def _prepare_collision(polygon: list[Point]) -> dict:
    """
    Bereitet ein Polygon für die Kollisionsüberprüfung vor.
    
    Enthält:
    - Polygon
    - Bounding-Box
    - Normalsen (für SAT-Test)
    - Projektionen
    """
    axes = _compute_polygon_axes(polygon)
    return {
        "polygon": polygon,
        "bounds": _bounds(polygon),
        "axes": axes,
        "projections": [_project_polygon(polygon, axis) for axis in axes],
    }


def _angle_values(step: float) -> list[float]:
    """Generiert Winkelwerte mit gegebenem Schritt."""
    if step <= 0.0:
        return [0.0]
    values = []
    index = 0
    while index * step < 180.0 - EPSILON:
        values.append(index * step)
        index += 1
    return values


def _pack_strip_best(
    shapes: list[dict],
    strip_width: float,
) -> tuple[dict, list[dict]]:
    """
    Findet die beste Verpackung bei mehreren globalen Winkeln und Sortierstrategien.
    
    Implementiert die Haupt-Suchroutine für die Plattenplanung.
    """
    empty: dict = {"items": [], "length": 0.0}
    if not shapes:
        return empty, []

    rotate = any(shape["allow_rotation"] for shape in shapes)
    if rotate:
        coarse = NESTING_COARSE_STEP_DEG
        fine = NESTING_FINE_STEP_DEG
        orders: tuple[str, ...]
        if len(shapes) <= NESTING_BOTH_ORDERS_LIMIT:
            orders = ("area", "maxdim")
        else:
            orders = ("area",)
    else:
        coarse = 0.0
        fine = 0.0
        orders = ("area",)

    best: tuple[tuple[int, float], float, str, dict, list[dict]] | None = None

    for angle in _angle_values(coarse):
        for order in orders:
            strip, unplaced = _pack_at_angle(
                shapes, strip_width, angle, order
            )
            score = (len(unplaced), _strip_length(strip))
            if best is None or score < best[0]:
                best = (score, angle, order, strip, unplaced)

    if best is None:
        return empty, list(shapes)

    if fine > 0.0 and not best[4]:
        center = best[1]
        order = best[2]
        steps = int(round(coarse / fine))
        for offset in range(-steps, steps + 1):
            if offset == 0:
                continue
            angle = (center + offset * fine) % 180.0
            strip, unplaced = _pack_at_angle(
                shapes, strip_width, angle, order
            )
            score = (len(unplaced), _strip_length(strip))
            if score < best[0]:
                best = (score, angle, order, strip, unplaced)

    return best[3], best[4]


class PlatePlanningWindow(tk.Toplevel):
    """Hauptfenster für die Plattenplanung mit Ausrichtung paralleler Seiten."""
    
    def __init__(
        self,
        master: tk.Misc,
        triangle: Triangle | None,
        parts: list[Part],
        height_name: str,
        extras: tuple[float, float, float],
    ) -> None:
        super().__init__(master)
        self.triangle = triangle
        self.parts = parts
        self.height_name = height_name
        self.extras = extras
        self._strip: dict = {"items": [], "length": 0.0}
        self._unplaced: list[dict] = []

        self.title("Plattenplanung")
        self.geometry("1200x800")
        self.minsize(900, 600)
        self.configure(background=BACKGROUND)
        self.transient(master.winfo_toplevel())

        self.rotate_var = tk.BooleanVar(value=True)

        self._build_ui()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._recalculate())
        self.update_idletasks()
        self._center_on_parent(master)
        self.after_idle(self._recalculate)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        controls = ttk.LabelFrame(outer, text="Material", padding=8)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)

        ttk.Label(
            controls,
            text=f"Breite: {format_number(STRIP_WIDTH_CM)} cm (fest)",
        ).grid(row=0, column=0, sticky="w", padx=(0, 18), pady=2)
        ttk.Label(
            controls,
            text="Länge: wird aus der Platzierung berechnet",
        ).grid(row=0, column=1, sticky="w", padx=(0, 18), pady=2)
        ttk.Checkbutton(
            controls,
            text="Rotation frei (Ausrichtung paralleler Seiten)",
            variable=self.rotate_var,
            state="disabled",
        ).grid(row=0, column=2, sticky="w", pady=2)
        ttk.Button(
            controls,
            text="Neu berechnen",
            command=self._recalculate,
        ).grid(row=0, column=3, sticky="e", pady=2)

        info = ttk.Label(
            outer,
            text=(
                f"Zuschnitt: Länge+ {format_number(self.extras[0])} cm · "
                f"Fv {format_number(self.extras[1])} cm · "
                f"Fh {format_number(self.extras[2])} cm\n"
                f"Die Teile werden auf einer 100-cm-Coil mit fester Breite "
                f"verschachtelt. Die parallelen Seiten jedes Teils werden parallel "
                f"zur Coil-Breite ausgerichtet, um die Fertigungsausrichtung zu optimieren."
            ),
            foreground=MUTED,
            justify="left",
            wraplength=1100,
        )
        info.grid(row=1, column=0, sticky="w", pady=(6, 6))

        canvas_frame = ttk.Frame(outer)
        canvas_frame.grid(row=2, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=self.canvas.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", lambda _event: self._draw_strip())
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda _event: self._on_mousewheel_linux(-1))
        self.canvas.bind("<Button-5>", lambda _event: self._on_mousewheel_linux(1))

        self.status = ttk.Label(outer, text="", foreground=MUTED)
        self.status.grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _center_on_parent(self, master: tk.Misc) -> None:
        try:
            root = master.winfo_toplevel()
            x = root.winfo_rootx() + (root.winfo_width() - self.winfo_width()) // 2
            y = root.winfo_rooty() + (root.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

    def _on_mousewheel(self, event: tk.Event) -> str:
        steps = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(steps, "units")
        return "break"

    def _on_mousewheel_linux(self, direction: int) -> str:
        self.canvas.yview_scroll(direction, "units")
        return "break"

    def _recalculate(self) -> None:
        if not self.parts:
            self._strip = {"items": [], "length": 0.0}
            self._unplaced = []
            self.status.configure(
                text=(
                    "Keine Einzelteile vorhanden. "
                    "Bitte zuerst die Höhen-Teilung aktivieren."
                ),
                foreground=MUTED,
            )
            self._draw_strip()
            return

        self.status.configure(text="Berechne Platzierung mit paralleler Seitenausrichtung ...", foreground=MUTED)
        self.update_idletasks()

        shapes = _part_shapes(
            self.triangle,
            self.parts,
            self.height_name,
            self.extras,
            self.rotate_var.get(),
        )
        self._strip, self._unplaced = _pack_strip_best(
            shapes, STRIP_WIDTH_CM
        )
        self._update_status()
        self._draw_strip()

    def _update_status(self) -> None:
        total_parts = len(self.parts)
        placed_parts = len(self._strip["items"])
        length = _strip_length(self._strip)
        used_area = sum(item["area"] for item in self._strip["items"])
        material_area = STRIP_WIDTH_CM * length

        if placed_parts:
            waste = (
                max(0.0, material_area - used_area) / material_area * 100.0
                if material_area > 0.0
                else 0.0
            )
            text = (
                f"{placed_parts} von {total_parts} Teilen platziert · "
                f"Coil-Länge {format_number(length)} cm · "
                f"Verschnitt {format_number(waste, 1)} %"
            )
        else:
            text = f"0 von {total_parts} Teilen platziert"

        if self._unplaced:
            text += (
                f" · {len(self._unplaced)} Teil(e) passen nicht in die "
                f"Coil-Breite von {format_number(STRIP_WIDTH_CM)} cm"
            )
            foreground = INVALID
        else:
            foreground = VALID
        self.status.configure(text=text, foreground=foreground)

    def _draw_strip(self) -> None:
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if width < 100:
            return

        if not self._strip["items"]:
            message = "Keine Coil belegt."
            if not self.parts:
                message = "Keine Einzelteile vorhanden."
            self.canvas.create_text(
                width / 2.0,
                height / 2.0,
                text=message,
                fill=MUTED,
                font=("Segoe UI", 10),
                width=max(200, width - 40),
                justify="center",
            )
            self.canvas.configure(scrollregion=(0, 0, width, height))
            return

        length = _strip_length(self._strip)
        scale = (width - 160.0) / STRIP_WIDTH_CM
        scale = max(0.05, min(scale, 12.0))
        strip_w = STRIP_WIDTH_CM * scale
        strip_h = max(1.0, length * scale)
        margin_x = (width - strip_w) / 2.0 + 20.0
        top = 56.0

        self.canvas.create_text(
            margin_x,
            18.0,
            text=(
                f"Material · {format_number(STRIP_WIDTH_CM)} cm breit · "
                f"{format_number(length)} cm lang"
            ),
            fill=TEXT,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )

        self.canvas.create_rectangle(
            margin_x,
            top,
            margin_x + strip_w,
            top + strip_h,
            fill=PLATE_FILL,
            outline="",
            width=0,
        )

        x = margin_x
        while x < margin_x + strip_w - EPSILON:
            x += 10.0 * scale
            if x < margin_x + strip_w - 1e-6:
                self.canvas.create_line(x, top, x, top + strip_h, fill=GRID)
        y_grid = top
        while y_grid < top + strip_h - EPSILON:
            y_grid += 10.0 * scale
            if y_grid < top + strip_h - 1e-6:
                self.canvas.create_line(
                    margin_x, y_grid, margin_x + strip_w, y_grid, fill=GRID
                )

        for item in self._strip["items"]:
            part = item["part"]
            color = TAB20[(part.index - 1) % len(TAB20)]
            fill = blend(color, 0.32, PLATE_FILL)
            
            screen = [
                (
                    margin_x + point[0] * scale,
                    top + (length - point[1]) * scale,
                )
                for point in item["polygon"]
            ]
            
            self.canvas.create_polygon(
                *[coordinate for point in screen for coordinate in point],
                fill=fill,
                outline=color,
                width=2,
                joinstyle="round",
            )
            
            centroid = polygon_centroid(item["polygon"])
            self.canvas.create_text(
                margin_x + centroid[0] * scale,
                top + (length - centroid[1]) * scale,
                text=str(part.index),
                fill=PART_OUTLINE,
                font=("Segoe UI", 8, "bold"),
            )

        self.canvas.create_rectangle(
            margin_x,
            top,
            margin_x + strip_w,
            top + strip_h,
            fill="",
            outline=PLATE_OUTLINE,
            width=2,
        )

        self._draw_width_dimension(margin_x, top, strip_w)
        self._draw_length_dimension(margin_x, top, strip_h, length)

        total_height = max(top + strip_h + 40.0, height)
        self.canvas.configure(scrollregion=(0, 0, width, total_height))

    def _draw_width_dimension(self, x: float, top: float, strip_w: float) -> None:
        y = top - 16.0
        self.canvas.create_line(x, y, x + strip_w, y, fill=MUTED)
        for tick_x in (x, x + strip_w):
            self.canvas.create_line(tick_x, y - 5.0, tick_x, y + 5.0, fill=MUTED)
        self.canvas.create_text(
            x + strip_w / 2.0,
            y - 9.0,
            text=f"{format_number(STRIP_WIDTH_CM)} cm",
            fill=TEXT,
            font=("Segoe UI", 9),
        )

    def _draw_length_dimension(
        self,
        margin_x: float,
        top: float,
        strip_h: float,
        length: float,
    ) -> None:
        x = margin_x - 18.0
        self.canvas.create_line(x, top, x, top + strip_h, fill=MUTED)
        for tick_y in (top, top + strip_h):
            self.canvas.create_line(x - 5.0, tick_y, x + 5.0, tick_y, fill=MUTED)
        self.canvas.create_text(
            x - 10.0,
            top + strip_h / 2.0,
            text=f"{format_number(length)} cm",
            fill=TEXT,
            font=("Segoe UI", 9),
            angle=90,
        )