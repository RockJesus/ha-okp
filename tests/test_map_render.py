"""Map pipeline: parse the cloud's string tuples into a real PNG.

The map is what the user actually looks at, and the parser is fed by a cloud
that has been seen to send junk; both halves must fail soft.
"""
from __future__ import annotations

from custom_components.okp_cloud.map_render import parse_map_paths, render_map_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

POINTS = [(0, 0, 1), (1, 0, 1), (1, 1, 2), (5, 3, 3)]


def test_parse_valid_points():
    out = parse_map_paths(["(0,0,1)", "(1,0,1)", "(1,1,2)", "(5,3,3)"])
    assert out == POINTS


def test_parse_tolerates_whitespace():
    assert parse_map_paths([" (0,0,1) "]) == [(0, 0, 1)]


def test_parse_skips_malformed_entries():
    out = parse_map_paths(["(0,0)", "junk", "()", "(1,2,3,4)", "(a,b,c)", "(2,2,1)"])
    assert out == [(2, 2, 1)]
    assert parse_map_paths([]) == []


def test_render_produces_png_bytes():
    png = render_map_png(POINTS)
    assert png.startswith(PNG_SIGNATURE)
    # A non-trivial image: signature + IHDR + IDAT + IEND is at least ~100 B.
    assert len(png) > 100


def test_render_empty_points_is_png_too():
    """Empty input still renders (blank canvas), never raises."""
    png = render_map_png([])
    assert png.startswith(PNG_SIGNATURE)


def test_render_is_deterministic():
    """Byte-identical output for identical input: recorder diffing and
    camera caching both rely on 'no change -> no new image'."""
    assert render_map_png(POINTS) == render_map_png(POINTS)


def test_render_single_point():
    png = render_map_png([(0, 0, 1)])
    assert png.startswith(PNG_SIGNATURE)
