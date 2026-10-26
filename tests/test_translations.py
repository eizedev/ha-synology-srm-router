"""Every text exists in strings.json and both translations, with the same placeholders."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

COMPONENT = Path(__file__).parents[1] / "custom_components" / "synology_srm_router"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _texts(node: Any, path: str = "") -> dict[str, str]:
    """Flatten a strings file into dotted keys and their texts."""
    if isinstance(node, dict):
        texts: dict[str, str] = {}
        for key, value in node.items():
            texts.update(_texts(value, f"{path}.{key}" if path else key))
        return texts
    return {path: str(node)}


def _load(name: str) -> dict[str, str]:
    return _texts(json.loads((COMPONENT / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", ["translations/en.json", "translations/de.json"])
def test_translations_match_strings(name: str) -> None:
    source, translated = _load("strings.json"), _load(name)
    assert set(translated) == set(source)
    for key, text in source.items():
        placeholders = set(PLACEHOLDER.findall(text))
        assert set(PLACEHOLDER.findall(translated[key])) == placeholders, key


def test_english_is_strings_json() -> None:
    assert _load("translations/en.json") == _load("strings.json")
