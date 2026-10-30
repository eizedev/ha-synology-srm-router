"""Print the test harness release that pins the oldest Home Assistant this integration supports.

    python3 scripts/oldest_ha.py    # for example 0.13.374

The oldest supported version is `homeassistant` in hacs.json. Each release of
pytest-homeassistant-custom-component pins exactly one Home Assistant version; CI installs the
release that pins the oldest supported one and runs the tests on it. Standard library only: CI runs
it with the runner's Python.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import json
from pathlib import Path
import re
import sys
from typing import Any
import urllib.request

ROOT = Path(__file__).parents[1]
HARNESS = "pytest-homeassistant-custom-component"
INDEX = "https://pypi.org/pypi"
TIMEOUT = 30


class HarnessError(Exception):
    """No harness release pins the oldest supported Home Assistant."""


def minimum(root: Path = ROOT) -> str:
    """Return the oldest Home Assistant version the integration claims to support."""
    return str(json.loads((root / "hacs.json").read_text(encoding="utf-8"))["homeassistant"])


def release_key(version: str) -> tuple[int, ...]:
    """Sort key of a version by its leading numbers: 2026.10.3 and 2026.10.3b1 sort alike."""
    match = re.match(r"\d+(\.\d+)*", version)
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()


def pinned(requires: Iterable[str]) -> str | None:
    """Return the Home Assistant version a harness release pins, or None."""
    for requirement in requires:
        match = re.fullmatch(r"homeassistant\s*==\s*([^\s;,]+)", requirement.strip())
        if match:
            return match.group(1)
    return None


def harness_for(
    version: str,
    releases: Iterable[str],
    requires_of: Callable[[str], Iterable[str]],
) -> str:
    """Return the newest harness release that pins `version`, looking from the newest down.

    Stops at the first release that pins an older Home Assistant: none further down can match.
    """
    wanted = release_key(version)
    for release in sorted(releases, key=release_key, reverse=True):
        ha = pinned(requires_of(release))
        if ha is None:
            continue
        if ha == version:
            return release
        if release_key(ha) < wanted:
            break
    msg = f"no {HARNESS} release pins homeassistant=={version}"
    raise HarnessError(msg)


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 (fixed https URL)
        return json.load(response)


def main() -> int:
    """Print the harness release for the version in hacs.json."""
    releases = [v for v, files in _get(f"{INDEX}/{HARNESS}/json")["releases"].items() if files]
    try:
        print(
            harness_for(
                minimum(),
                releases,
                lambda r: _get(f"{INDEX}/{HARNESS}/{r}/json")["info"]["requires_dist"] or [],
            )
        )
    except HarnessError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
