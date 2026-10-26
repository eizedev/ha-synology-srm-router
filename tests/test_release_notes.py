"""The release notes come from CHANGELOG.md, and a tag must match the manifest."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts/release_notes.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_notes"] = module
    spec.loader.exec_module(module)
    return module


release = _load()

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-01

### Fixed

- Something.

## [0.1.0] - 2026-10-26

### Added

- First version.

[Unreleased]: https://example.invalid/compare/v0.2.0...HEAD
[0.2.0]: https://example.invalid/compare/v0.1.0...v0.2.0
"""


def test_notes_are_the_versions_section() -> None:
    notes = release.notes("v0.2.0", {"version": "0.2.0"}, CHANGELOG)
    assert notes.startswith("### Fixed\n\n- Something.\n\nDocumentation: https://")
    assert "First version" not in notes
    assert release.notes("v0.1.0", {"version": "0.1.0"}, CHANGELOG).startswith("### Added")


@pytest.mark.parametrize(
    ("tag", "version", "changelog", "error"),
    [
        ("v0.3.0", "0.3.0", CHANGELOG, "no section [0.3.0]"),
        ("v0.2.0", "0.1.0", CHANGELOG, "does not match the manifest version 0.1.0"),
        ("0.2.0", "0.2.0", CHANGELOG, "not a tag of the form"),
        ("v0.2", "0.2", CHANGELOG, "not a tag of the form"),
        ("v1.0.0", "1.0.0", "## [1.0.0] - 2026-12-01\n\n## [0.9.0]\n", "is empty"),
    ],
)
def test_a_release_without_matching_version_or_notes_fails(
    tag: str, version: str, changelog: str, error: str
) -> None:
    with pytest.raises(release.ReleaseError, match=error.replace("[", r"\[").replace("]", r"\]")):
        release.notes(tag, {"version": version}, changelog)


def test_the_script_checks_this_repository(capsys: pytest.CaptureFixture[str]) -> None:
    version = json.loads(release.MANIFEST.read_text(encoding="utf-8"))["version"]
    assert release.main(["release_notes.py", f"v{version}"]) == 0  # the next tag has its notes
    assert capsys.readouterr().out.strip()
    assert release.main(["release_notes.py", "v99.0.0"]) == 1
    assert "does not match" in capsys.readouterr().err
    assert release.main(["release_notes.py"]) == 2
