"""Check a release tag against the manifest and print its notes from CHANGELOG.md.

    python3 scripts/release_notes.py v0.1.0 > notes.md

Fails when the tag is not the manifest's version or CHANGELOG.md has no section for it, so a
release cannot go out with a wrong version or without notes. Standard library only: the release
workflow runs it with the runner's Python.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "synology_srm_router" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"
DOCS = "https://ha-synology-srm-router.eize.dev/"


class ReleaseError(Exception):
    """The tag, the manifest and the changelog do not agree."""


def section(changelog: str, version: str) -> str:
    """Return the body of the changelog's section for a version, without its heading."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        raise ReleaseError(f"CHANGELOG.md has no section [{version}]")
    rest = changelog[match.end() :]
    end = re.search(r"^## |^\[[^\]]+\]: ", rest, re.MULTILINE)
    body = (rest[: end.start()] if end else rest).strip()
    if not body:
        raise ReleaseError(f"The section [{version}] of CHANGELOG.md is empty")
    return body


def notes(tag: str, manifest: dict[str, object], changelog: str) -> str:
    """Return the release notes for a tag, after checking it against the manifest."""
    version = tag.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or tag != f"v{version}":
        raise ReleaseError(f"{tag} is not a tag of the form vX.Y.Z")
    if manifest.get("version") != version:
        raise ReleaseError(f"{tag} does not match the manifest version {manifest.get('version')}")
    return f"{section(changelog, version)}\n\nDocumentation: {DOCS}\n"


def main(argv: list[str]) -> int:
    """Print the notes for the tag in argv, or the reason there are none."""
    if len(argv) != 2:  # noqa: PLR2004 - the script and the tag
        print(__doc__, file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        print(notes(argv[1], manifest, CHANGELOG.read_text(encoding="utf-8")), end="")
    except ReleaseError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
