"""Guard the artefacts HACS shows users.

The integration ships a copy of the root README because HACS prefers the one
inside the integration directory. That copy had silently stopped being updated
(changelog froze at v1.6.2 while the repo was at v1.6.8), so the sync is now
checked here as well as in CI - a stale copy should fail a test, not ship.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "okp_cloud"


def test_readme_copies_identical() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    shipped = (INTEGRATION / "README.md").read_text(encoding="utf-8")
    assert shipped == root_readme, (
        "custom_components/okp_cloud/README.md drifted from README.md; "
        "run: python tools/sync_readme.py"
    )


def test_readme_relative_assets_exist() -> None:
    """Every local path the README points at must exist.

    Paths may be written either repo-relative (``custom_components/...``, as in
    the root README) or integration-relative (``brand/logo.png``); both are
    accepted because the same text is rendered from two different directories.
    """
    shipped = (INTEGRATION / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\((?![a-z]+://|#)([^)]+)\)", shipped)
    targets += re.findall(r'<img[^>]+src="(?![a-z]+://)([^"]+)"', shipped)
    missing = [
        t
        for t in targets
        if not (INTEGRATION / t).exists() and not (ROOT / t).exists()
    ]
    assert not missing, f"broken local paths in shipped README: {missing}"


def test_changelog_mentions_shipped_version() -> None:
    version = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))[
        "version"
    ]
    shipped = (INTEGRATION / "README.md").read_text(encoding="utf-8")
    assert f"- v{version}（" in shipped or f"- v{version}(" in shipped, (
        f"manifest version {version} has no changelog entry in the README HACS renders"
    )


def test_manifest_declares_matching_version_files() -> None:
    """A release without the version in manifest.json is not installable."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"].count(".") == 2
    assert manifest["domain"] == INTEGRATION.name
