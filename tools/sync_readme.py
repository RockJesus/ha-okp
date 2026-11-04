#!/usr/bin/env python3
"""Sync the repository README into the integration directory.

HACS renders the README it finds next to the integration: with
``render_readme`` enabled it prefers ``custom_components/<domain>/README.md``
and only falls back to the repository root file. Keeping two hand-maintained
copies means the one users actually see in HACS drifts away from the one
maintained on GitHub - that is exactly what happened with the changelog
(v1.6.4 through v1.6.8 were missing from the copy HACS displayed).

Run ``python tools/sync_readme.py`` after editing the root README; CI verifies
the two files stay identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "README.md"
TARGET = ROOT / "custom_components" / "okp_cloud" / "README.md"

# The copies are identical on purpose: relative asset paths (`brand/logo.png`,
# `docs/...`) resolve the same way from the integration directory and from a
# HACS download, which unpacks the integration folder flat.
HEADER = ""


def render(source: str) -> str:
    return HEADER + source


def main(argv: list[str]) -> int:
    if not SOURCE.is_file():
        print(f"missing {SOURCE}", file=sys.stderr)
        return 2
    expected = render(SOURCE.read_text(encoding="utf-8"))

    if "--check" in argv:
        actual = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else None
        if actual != expected:
            print(
                "custom_components/okp_cloud/README.md is out of date.\n"
                "Run: python tools/sync_readme.py",
                file=sys.stderr,
            )
            return 1
        print("README copies are in sync")
        return 0

    TARGET.write_text(expected, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
