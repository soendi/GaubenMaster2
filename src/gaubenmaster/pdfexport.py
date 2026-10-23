"""Minimaler PDF-Export der Tkinter-Zeichnungen."""

from __future__ import annotations

import math
import re
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from .geometry import Part, Point, Triangle
from .partdraw import draw_part, height_axis
from .plot import DisplayOptions, TriangleView

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
PARTS_PER_PAGE = 4


def _rgb(color: str) -> tuple[float, float, float] | None:
    value = color.strip()
    if not value.startswith("#") or len(value) != 7:
        return None
    try:
        return (
            int(value[1:3], 16) / 255.0,
            int(value[3:5], 16) / 255.0,
            int(value[5:7], 16) / 255.0,
        )
    except ValueError:
        return None


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def _text_bytes(text: str) -> bytes:
    return text.encode("cp1252", "replace")


def _escape_text(text: str) -> bytes:
    replaced = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return _text_bytes(replaced)


def _item_font(canvas: tk.Canvas, item: int) -> tuple[str, int, bool]:
    spec = canvas.itemcget(item, "font")
    try:
        actual = tkfont.Font(root=canvas, font=spec).actual()
    except tk.TclError:
        return "Helvetica", 9, False
    family = str(actual.get("family", "Helvetica")).lower()
    size = abs(int(actual.get("size", 9))) or 9
    weight = str(actual.get("weight", "normal")).lower()
    bold = weight == "bold"
    if "courier" in family:
        name = "Courier-Bold" if bold else "Courier"
    elif "times" in family or "serif" in family:
        name = "Times-Bold" if bold else "Times"
    else:
        name = "Helvetica-Bold" if bold else "Helvetica"
    return name, size, bold


def _line_width(canvas: tk.Canvas, item: int) -> float:
    try:
        return max(0.1, float(canvas.itemcget(item, "width") or 1))
    except ValueError:
        return 1.0


def _dash(canvas: tk.Canvas, item: int) -> str:
    raw = canvas.itemcget(item, "dash")
    if not raw:
        return ""
    parts = [part for part in re.split(r"[,\s]+", raw.strip()) if part]
    values = []
    for part in parts:
        try:
            value = float(part)
        except ValueError:
            continue
        if value > 0:
            values.append(_number(value))
    return f"[{' '.join(values)}] 0 d" if values else ""


def _set_fill(color: str) -> str:
    rgb = _rgb(color)
    if rgb is None:
        return ""
    return f"{_number(rgb[0])} {_number(rgb[1])} {_number(rgb[2])} rg"


def _set_stroke(color: str) -> str:
    rgb = _rgb(color)
    if rgb is None:
        return ""
    return f"{_number(rgb[0])} {_number(rgb[1])} {_number(rgb[2])} RG"


def _path_from_coords(coords: list[float]) -> list[str]:
    if len(coords) < 4:
        return []
    commands = [f"{_number(coords[0])} {_number(PAGE_HEIGHT - coords[1])} m"]
    for index in range(2, len(coords) - 1, 2):
        commands.append(
            f"{_number(coords[index])} {_number(PAGE_HEIGHT - coords[index + 1])} l"
        )
    return commands


def _draw_line(canvas: tk.Canvas, item: int) -> list[str]:
    coords = [float(value) for value in canvas.coords(item)]
    commands = _path_from_coords(coords)
    if not commands:
        return []
    color = canvas.itemcget(item, "fill")
    stroke = _set_stroke(color)
    if not stroke:
        return []
    commands.append(stroke)
    commands.append(f"{_number(_line_width(canvas, item))} w")
    dash = _dash(canvas, item)
    if dash:
        commands.append(dash)
    commands.append("S")
    if dash:
        commands.append("[] 0 d")
    return commands


def _fill_stroke(
    canvas: tk.Canvas,
    item: int,
    commands: list[str],
    *,
    closed: bool = True,
) -> list[str]:
    fill = canvas.itemcget(item, "fill") if canvas.type(item) != "line" else ""
    outline = canvas.itemcget(item, "outline") if canvas.type(item) != "line" else ""
    fill_set = _set_fill(fill)
    stroke_set = _set_stroke(outline)
    if not fill_set and not stroke_set:
        return []
    if closed:
        commands.append("h")
    if fill_set:
        commands.append(fill_set)
    if stroke_set:
        commands.append(stroke_set)
        commands.append(f"{_number(_line_width(canvas, item))} w")
    if fill_set and stroke_set:
        commands.append("B")
    elif fill_set:
        commands.append("f")
    else:
        commands.append("S")
    return commands


def _draw_rectangle(canvas: tk.Canvas, item: int) -> list[str]:
    x1, y1, x2, y2 = [float(value) for value in canvas.coords(item)]
    left, right = sorted((x1, x2))
    bottom, top = sorted((PAGE_HEIGHT - y1, PAGE_HEIGHT - y2))
    commands = [
        f"{_number(left)} {_number(bottom)} {_number(right - left)} "
        f"{_number(top - bottom)} re"
    ]
    fill = _set_fill(canvas.itemcget(item, "fill"))
    outline = _set_stroke(canvas.itemcget(item, "outline"))
    if not fill and not outline:
        return []
    if fill:
        commands.append(fill)
    if outline:
        commands.append(outline)
        commands.append(f"{_number(_line_width(canvas, item))} w")
    if fill and outline:
        commands.append("B")
    elif fill:
        commands.append("f")
    else:
        commands.append("S")
    return commands


def _draw_oval(canvas: tk.Canvas, item: int) -> list[str]:
    x1, y1, x2, y2 = [float(value) for value in canvas.coords(item)]
    left, right = sorted((x1, x2))
    top_canvas, bottom_canvas = sorted((y1, y2))
    cx = (left + right) / 2.0
    cy = PAGE_HEIGHT - (top_canvas + bottom_canvas) / 2.0
    rx = abs(right - left) / 2.0
    ry = abs(bottom_canvas - top_canvas) / 2.0
    if rx <= 0 or ry <= 0:
        return []
    k = 0.5522847498
    points = [
        (cx + rx, cy),
        (cx + rx, cy + ry * k),
        (cx + rx * k, cy + ry),
        (cx, cy + ry),
        (cx - rx * k, cy + ry),
        (cx - rx, cy + ry * k),
        (cx - rx, cy),
        (cx - rx, cy - ry * k),
        (cx - rx * k, cy - ry),
        (cx, cy - ry),
        (cx + rx * k, cy - ry),
        (cx + rx, cy - ry * k),
        (cx + rx, cy),
    ]
    commands = [f"{_number(points[0][0])} {_number(points[0][1])} m"]
    for index in range(1, len(points), 3):
        c1 = points[index]
        c2 = points[index + 1]
        end = points[index + 2]
        commands.append(
            f"{_number(c1[0])} {_number(c1[1])} {_number(c2[0])} "
            f"{_number(c2[1])} {_number(end[0])} {_number(end[1])} c"
        )
    return _fill_stroke(canvas, item, commands, closed=True)


def _draw_text(canvas: tk.Canvas, item: int) -> list[str]:
    text = canvas.itemcget(item, "text")
    if not text:
        return []
    fill = _set_fill(canvas.itemcget(item, "fill"))
    if not fill:
        return []
    font_name, size, _bold = _item_font(canvas, item)
    font_id = "F2" if font_name.endswith("Bold") else "F1"
    bbox = canvas.bbox(item)
    if not bbox:
        return []
    center_x = (bbox[0] + bbox[2]) / 2.0
    center_y = (bbox[1] + bbox[3]) / 2.0
    try:
        angle = math.radians(float(canvas.itemcget(item, "angle") or 0.0))
    except ValueError:
        angle = 0.0
    lines = text.split("\n")
    line_height = size * 1.18
    total_height = line_height * (len(lines) - 1)
    font = tkfont.Font(root=canvas, font=canvas.itemcget(item, "font"))
    commands = ["BT", fill, f"/{font_id} {_number(size)} Tf"]
    for index, line in enumerate(lines):
        width = font.measure(line)
        center_line_y = center_y - total_height / 2.0 + index * line_height
        local_x = -width / 2.0
        local_y = -size * 0.35
        cos_value = math.cos(angle)
        sin_value = math.sin(angle)
        origin_x = center_x + local_x * cos_value - local_y * sin_value
        origin_y = (
            PAGE_HEIGHT
            - center_line_y
            + local_x * sin_value
            + local_y * cos_value
        )
        commands.append(
            f"{_number(cos_value)} {_number(sin_value)} "
            f"{_number(-sin_value)} {_number(cos_value)} "
            f"{_number(origin_x)} {_number(origin_y)} Tm"
        )
        commands.append(f"({_escape_text(line).decode('cp1252')}) Tj")
    commands.append("ET")
    return commands


def _canvas_content(canvas: tk.Canvas) -> bytes:
    commands: list[str] = []
    for item in canvas.find_all():
        if canvas.itemcget(item, "state") == "hidden":
            continue
        kind = canvas.type(item)
        if kind == "line":
            commands.extend(_draw_line(canvas, item))
        elif kind == "polygon":
            coords = [float(value) for value in canvas.coords(item)]
            if len(coords) >= 6:
                commands.extend(
                    _fill_stroke(canvas, item, _path_from_coords(coords), closed=True)
                )
        elif kind == "rectangle":
            commands.extend(_draw_rectangle(canvas, item))
        elif kind == "oval":
            commands.extend(_draw_oval(canvas, item))
        elif kind == "text":
            commands.extend(_draw_text(canvas, item))
    return ("\n".join(commands) + "\n").encode("cp1252", "replace")


def _content_bbox(canvas: tk.Canvas) -> tuple[float, float, float, float] | None:
    boxes = [
        box
        for item in canvas.find_all()
        if "canvas-background" not in canvas.gettags(item)
        if (box := canvas.bbox(item))
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _tag_bbox(
    canvas: tk.Canvas, tag: str
) -> tuple[float, float, float, float] | None:
    boxes = [
        box
        for item in canvas.find_withtag(tag)
        if (box := canvas.bbox(item))
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _pdf_document(pages: list[bytes]) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_numbers: list[int] = []
    for content in pages:
        stream = add(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )
        page = add(
            (
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 "
                f"{_number(PAGE_WIDTH)} {_number(PAGE_HEIGHT)}] "
                f"/Resources << /Font << /F1 {regular} 0 R /F2 {bold} 0 R >> >> "
                f"/Contents {stream} 0 R >>"
            ).encode("ascii")
        )
        page_numbers.append(page)

    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    pages_object = add(
        f"<< /Type /Pages /Count {len(page_numbers)} /Kids [{kids}] >>".encode("ascii")
    )
    for number in page_numbers:
        objects[number - 1] = objects[number - 1].replace(
            b"/Parent 0 0 R", f"/Parent {pages_object} 0 R".encode("ascii")
        )
    catalog = add(
        f"<< /Type /Catalog /Pages {pages_object} 0 R >>".encode("ascii")
    )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode("ascii")
        output += body
        output += b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode("ascii")
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(output)


def _make_canvas(master: tk.Misc) -> tk.Canvas:
    return tk.Canvas(
        master,
        width=int(PAGE_WIDTH),
        height=int(PAGE_HEIGHT),
        background="#ffffff",
        highlightthickness=0,
        borderwidth=0,
    )


def _main_page(
    master: tk.Misc,
    triangle: Triangle,
    parts: list[Part],
    height_name: str,
    height_active: bool,
    options: DisplayOptions,
    rotation: float,
) -> bytes:
    view = TriangleView(master)
    view.render_size = (int(PAGE_WIDTH), int(PAGE_HEIGHT))
    view.options = options
    view.rotation = rotation
    view.pan_x = 0.0
    view.pan_y = 0.0
    view.fit_fraction = 0.90
    view.set_data(triangle, parts, height_name, height_active)

    target_width = PAGE_WIDTH * 0.90
    target_height = PAGE_HEIGHT * 0.90
    low = 0.05
    high = 0.90
    for _ in range(28):
        middle = (low + high) / 2.0
        view.fit_fraction = middle
        view.redraw()
        box = _content_bbox(view)
        if (
            box is not None
            and box[2] - box[0] <= target_width
            and box[3] - box[1] <= target_height
        ):
            low = middle
        else:
            high = middle

    view.fit_fraction = low
    view.redraw()
    box = _content_bbox(view)
    if box is not None:
        view.pan_x = PAGE_WIDTH / 2.0 - (box[0] + box[2]) / 2.0
        view.pan_y = PAGE_HEIGHT / 2.0 - (box[1] + box[3]) / 2.0
        view.redraw()

    content = _canvas_content(view)
    view.destroy()
    return content


def _part_page(
    master: tk.Misc,
    page_parts: list[Part],
    axis: Point,
    extras: tuple[float, float, float],
    options: DisplayOptions,
) -> bytes:
    canvas = _make_canvas(master)
    margin = 18.0
    gap = 8.0
    top_margin = 24.0
    cell_width = (PAGE_WIDTH - margin * 2 - gap) / 2.0
    cell_height = (PAGE_HEIGHT - top_margin - margin - gap) / 2.0
    for index, part in enumerate(page_parts):
        column = index % 2
        row = index // 2
        x0 = margin + column * (cell_width + gap)
        y0 = top_margin + row * (cell_height + gap)
        canvas.create_rectangle(
            x0,
            y0,
            x0 + cell_width,
            y0 + cell_height,
            fill="",
            outline="#b8c4d4",
            width=1,
        )
        canvas.create_text(
            x0 + 8.0,
            y0 + 5.0,
            text=f"Teil {part.index}",
            fill="#12263f",
            font=("Segoe UI", 11, "bold"),
            anchor="nw",
        )
        bbox = (x0, y0 + 24.0, x0 + cell_width, y0 + cell_height)
        available_width = bbox[2] - bbox[0]
        available_height = bbox[3] - bbox[1]
        pad_x = max(16.0, min(34.0, available_width * 0.11))
        pad_y = max(16.0, min(46.0, available_height * 0.115))
        tag = f"part-frame-{part.index}"
        frame = (x0 + 6.0, y0 + 6.0, x0 + cell_width - 6.0, y0 + cell_height - 6.0)
        for _ in range(20):
            canvas.delete(tag)
            draw_part(
                canvas,
                part,
                bbox,
                axis,
                extras[0],
                extras[1],
                extras[2],
                compact=False,
                tags=(tag,),
                options=options,
                rotate_clockwise=True,
                padding=(pad_x, pad_x * 0.92, pad_y, pad_y),
            )
            box = _tag_bbox(canvas, tag)
            if box is None:
                break
            overflow_x = max(0.0, frame[0] - box[0], box[2] - frame[2])
            overflow_y = max(0.0, frame[1] - box[1], box[3] - frame[3])
            if overflow_x <= 0.0 and overflow_y <= 0.0:
                break
            pad_x = min(available_width * 0.40, pad_x + overflow_x + 2.0)
            pad_y = min(available_height * 0.40, pad_y + overflow_y + 2.0)
    content = _canvas_content(canvas)
    canvas.destroy()
    return content


def export_pdf(
    path: Path,
    triangle: Triangle,
    parts: list[Part],
    height_name: str,
    extras: tuple[float, float, float],
    options: DisplayOptions,
    *,
    rotation: float = 0.0,
    master: tk.Misc | None = None,
) -> None:
    own_root = False
    if master is None:
        master = tk._default_root
    if master is None:
        master = tk.Tk()
        master.withdraw()
        own_root = True
    try:
        pages = [
            _main_page(
                master,
                triangle,
                parts,
                height_name,
                bool(parts),
                options,
                rotation,
            )
        ]
        if parts:
            axis = height_axis(triangle, height_name)
            for start in range(0, len(parts), PARTS_PER_PAGE):
                pages.append(
                    _part_page(
                        master,
                        parts[start : start + PARTS_PER_PAGE],
                        axis,
                        extras,
                        options,
                    )
                )
        path.write_bytes(_pdf_document(pages))
    finally:
        if own_root:
            master.destroy()
