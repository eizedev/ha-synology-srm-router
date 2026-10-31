"""CI tests the oldest Home Assistant in hacs.json; the script finds the harness that pins it."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from homeassistant.const import __version__
import pytest

ROOT = Path(__file__).parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("oldest_ha", ROOT / "scripts/oldest_ha.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["oldest_ha"] = module
    spec.loader.exec_module(module)
    return module


oldest = _load()

PINS = {
    "0.13.380": ["homeassistant==2026.11.1", "pytest>=8"],
    "0.13.379": ["homeassistant==2026.11.0b2"],
    "0.13.378": [],  # a release without the pin is skipped
    "0.13.376": ["homeassistant==2026.10.3"],
    "0.13.375": ["homeassistant==2026.10.3"],
    "0.13.370": ["homeassistant==2026.10.1"],
    "0.13.300": ["homeassistant==2026.1.0"],
}


def test_the_newest_harness_for_the_minimum() -> None:
    assert oldest.harness_for("2026.10.3", PINS, PINS.__getitem__) == "0.13.376"


def test_it_stops_below_the_minimum() -> None:
    asked: list[str] = []

    def requires(release: str) -> list[str]:
        asked.append(release)
        return PINS[release]

    with pytest.raises(oldest.HarnessError):
        oldest.harness_for("2026.10.2", PINS, requires)
    assert "0.13.300" not in asked  # 0.13.370 already pins an older version


def test_a_beta_counts_as_its_release() -> None:
    assert oldest.harness_for("2026.11.0b2", PINS, PINS.__getitem__) == "0.13.379"
    assert oldest.release_key("2026.11.0b2") == (2026, 11, 0)
    assert oldest.release_key("dev") == ()


def test_the_minimum_is_the_one_in_the_docs() -> None:
    # README and the installation page name the minimum by hand; they must agree with hacs.json.
    version = oldest.minimum()
    assert f"Assistant {version} or newer" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Home Assistant {version} or newer" in (ROOT / "docs/installation.md").read_text(
        encoding="utf-8"
    )


def test_the_installed_home_assistant_is_not_older_than_the_minimum() -> None:
    # Both test jobs run a Home Assistant at or above the minimum: the locked one, and the oldest.
    assert oldest.release_key(__version__) >= oldest.release_key(oldest.minimum())


def test_yanked_releases_are_left_out() -> None:
    releases = {
        "0.13.376": [{"yanked": True}],
        "0.13.375": [{"yanked": True}, {"yanked": False}],
        "0.13.374": [{}],
        "0.13.373": [],
    }
    assert oldest.available(releases) == ["0.13.375", "0.13.374"]


def test_main_prints_the_harness(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pins = {
        "0.13.380": ["homeassistant==2099.1.0"],
        "0.13.376": [f"homeassistant=={oldest.minimum()}"],
    }

    def get(url: str) -> object:
        if url.endswith(f"{oldest.HARNESS}/json"):
            return {"releases": {release: [{}] for release in pins}}
        release = url.rsplit("/", 2)[-2]
        return {"info": {"requires_dist": pins[release]}}

    monkeypatch.setattr(oldest, "_get", get)
    assert oldest.main() == 0
    assert capsys.readouterr().out == "0.13.376\n"
    pins.pop("0.13.376")
    assert oldest.main() == 1
    assert "no pytest-homeassistant-custom-component release" in capsys.readouterr().err


def test_pypi_is_asked_again_after_a_hiccup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Answer:
        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b'{"ok": true}'

    def urlopen(url: str, timeout: int) -> Answer:
        calls.append(url)
        if len(calls) < oldest.ATTEMPTS:
            raise oldest.urllib.error.URLError("down")
        return Answer()

    monkeypatch.setattr(oldest.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(oldest.time, "sleep", lambda seconds: None)
    assert oldest._get("https://pypi.org/x") == {"ok": True}
    assert len(calls) == oldest.ATTEMPTS

    def down(url: str, timeout: int) -> Answer:
        raise oldest.urllib.error.URLError("down")

    monkeypatch.setattr(oldest.urllib.request, "urlopen", down)
    with pytest.raises(oldest.urllib.error.URLError):
        oldest._get("https://pypi.org/x")
