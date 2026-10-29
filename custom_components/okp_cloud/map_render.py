"""Render OKP/CoolKit sweep map (mapPaths) into a PNG image.

Pure-python PNG writer (zlib only) so the integration has no pip
dependencies beyond the HA core. mapPaths is a list of "(x,y,type)"
grid points: type 0 = sweep track, type 1 = boundary/wall.
"""
from __future__ import annotations

import struct
import zlib
from typing import Any

# point type -> RGBA
_COLORS: dict[int, tuple[int, int, int]] = {
    0: (30, 144, 255),  # dodgerblue sweep track
    1: (150, 150, 155),  # gray boundary / wall
}
_BACKGROUND = (248, 248, 248)

_CHUNK_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    out = struct.pack(">I", len(data)) + tag + data
    out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return out


def _png_bytes(width: int, height: int, rgb_rows: list[bytes]) -> bytes:
    raw = b"".join(b"\x00" + row for row in rgb_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(raw, 6)
    return (
        _CHUNK_SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def render_map_png(
    points: list[tuple[int, int, int]],
    scale: int | None = None,
    pad: int = 10,
    max_size: int = 640,
) -> bytes:
    """Render mapPaths points into a PNG image (RGB, plain PNG).

    Args:
        points: list of (x, y, point_type) grid points.
        scale: pixel size of one grid cell. Auto-computed when None so the
            longest axis stays within max_size.
        pad: grid cells of padding around the occupied area.
        max_size: target longest pixel axis (auto-scale mode).
    """
    if not points:
        # empty map -> blank 1x1 png
        return _png_bytes(1, 1, [bytes((248, 248, 248))])
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    gw = x1 - x0 + 1 + 2 * pad
    gh = y1 - y0 + 1 + 2 * pad
    if scale is None:
        scale = max(2, min(32, max_size // max(gw, gh)))
    grid: dict[tuple[int, int], int] = {}
    for x, y, t in points:
        grid[(x, y)] = t
    rows: list[bytes] = []
    for gy in range(y0 - pad, y1 + pad + 1):
        row = bytearray()
        for gx in range(x0 - pad, x1 + pad + 1):
            t = grid.get((gx, gy))
            if t in _COLORS:
                row += bytes(_COLORS[t])
            else:
                row += bytes(_BACKGROUND)
        # nearest-neighbor upscale horizontally, then replicate rows
        up = bytearray()
        for b in row:
            up.extend(bytes([b]) * scale)
        rows.append(bytes(up))
    # vertical upscale: repeat each row `scale` times
    scaled: list[bytes] = []
    for row in rows:
        for _ in range(scale):
            scaled.append(row)
    return _png_bytes(gw * scale, gh * scale, scaled)


def parse_map_paths(map_paths: list[str]) -> list[tuple[int, int, int]]:
    """Parse ['(x,y,t)', ...] into int tuples. Malformed entries skipped."""
    out: list[tuple[int, int, int]] = []
    for s in map_paths:
        s = s.strip()
        if not (s.startswith("(") and s.endswith(")")):
            continue
        parts = s[1:-1].split(",")
        if len(parts) != 3:
            continue
        try:
            out.append((int(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return out


def map_size(points: list[tuple[int, int, int]]) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) grid extent, or (0,0,0,0) when empty."""
    if not points:
        return (0, 0, 0, 0)
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _serialize_map_paths(points: list[tuple[int, int, int]]) -> str:
    """Helper for diagnostics: re-serialize parsed points."""
    return ",".join(f"({x},{y},{t})" for x, y, t in points)


def _any_extra_data(points: list[tuple[int, int, int]]) -> dict[str, Any]:
    """Optional: reserved for future map metadata (rooms etc.)."""
    return {}
