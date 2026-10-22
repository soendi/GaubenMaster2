"""Erzeugt assets/icon.ico ohne externe Bibliotheken."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256


def blend(base, color, alpha):
    return tuple(round(base[i] * (1 - alpha) + color[i] * alpha) for i in range(3))


def inside_rounded(x, y, left, top, right, bottom, radius):
    if not (left <= x <= right and top <= y <= bottom):
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def point_in_triangle(px, py, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def add_rect(pixels, left, top, right, bottom, color):
    for y in range(max(0, top), min(SIZE, bottom)):
        for x in range(max(0, left), min(SIZE, right)):
            pixels[y][x] = color


def render_master():
    pixels = [[(0, 0, 0, 0) for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(SIZE):
        for x in range(SIZE):
            if inside_rounded(x, y, 8, 8, 247, 247, 44):
                mix = y / SIZE
                base = blend((18, 62, 110), (12, 38, 72), mix)
                pixels[y][x] = (*base, 255)

    roof = ((34, 104), (128, 24), (222, 104))
    for y in range(20, 115):
        for x in range(20, 236):
            if point_in_triangle(x, y, *roof):
                pixels[y][x] = (238, 243, 248, 255)
            elif point_in_triangle(x, y, (34, 104), (128, 24), (222, 104)):
                pixels[y][x] = (238, 243, 248, 255)

    add_rect(pixels, 58, 104, 198, 216, (232, 238, 244, 255))
    add_rect(pixels, 50, 208, 206, 222, (196, 208, 220, 255))
    add_rect(pixels, 84, 126, 172, 198, (20, 78, 132, 255))
    add_rect(pixels, 122, 126, 134, 198, (232, 238, 244, 255))
    add_rect(pixels, 84, 156, 172, 168, (232, 238, 244, 255))
    add_rect(pixels, 84, 126, 172, 134, (232, 238, 244, 255))
    add_rect(pixels, 116, 186, 140, 216, (92, 62, 38, 255))
    return pixels


def downsample(master, size):
    factor = SIZE // size
    result = []
    for y in range(size):
        row = []
        for x in range(size):
            r = g = b = a = 0
            for dy in range(factor):
                for dx in range(factor):
                    pixel = master[y * factor + dy][x * factor + dx]
                    r += pixel[0] * pixel[3]
                    g += pixel[1] * pixel[3]
                    b += pixel[2] * pixel[3]
                    a += pixel[3]
            count = factor * factor
            if a:
                row.append((r // a, g // a, b // a, a // count))
            else:
                row.append((0, 0, 0, 0))
        result.append(row)
    return result


def png_bytes(pixels):
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b, a in row:
            raw.extend((r, g, b, a))
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", len(pixels[0]), len(pixels), 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main():
    master = render_master()
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [(size, png_bytes(downsample(master, size))) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, data in images:
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payload.extend(data)
        offset += len(data)
    target = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + entries + payload)
    print(f"{target} ({target.stat().st_size} Bytes)")


if __name__ == "__main__":
    main()
