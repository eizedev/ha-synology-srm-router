"""Repairs for risky router settings: raised, removed once safe, kept while unknown."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiosynologysrm import (
    AllowSrmFromWan,
    AutoBlock,
    FirewallRules,
    SrmConnectionError,
    Topology,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.synology_srm_router.const import DOMAIN
from custom_components.synology_srm_router.repairs import RISKS

from .conftest import ROUTER_HOST, UNSUPPORTED, FakeClient, load, make_entry

ROOT = Path(__file__).parents[1]


async def _value(value: Any) -> Any:
    return value


async def _setup(hass: HomeAssistant, *entries: Any) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()


def _issues(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    suffix = f"_{entry.entry_id}"
    return {
        issue_id.removesuffix(suffix)
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.endswith(suffix) and not issue_id.startswith("blocked")
    }


def _auto_block(enable: bool) -> AutoBlock:
    return AutoBlock.from_api({**load("router", "auto_block"), "enable": enable})


def _open_firewall() -> FirewallRules:
    data = copy.deepcopy(load("router", "firewall_rules"))
    data["default_policy"]["ipv6_wan_to_lan"] = "allow"
    return FirewallRules.from_api(data)


async def test_the_recorded_router(hass: HomeAssistant) -> None:
    # The recorded router allows SRM from the internet; its auto block is on, its firewall closed.
    router, ap = make_entry(), make_entry("ap")
    await _setup(hass, router, ap)
    assert _issues(hass, router) == {"srm_from_internet"}
    assert _issues(hass, ap) == set()  # access points are not checked
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"srm_from_internet_{router.entry_id}")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"name": router.title}
    assert issue.learn_more_url is not None
    assert issue.learn_more_url.endswith("/repairs/srm-from-internet/")


async def test_a_repair_goes_once_the_setting_is_safe(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    closed = AllowSrmFromWan.from_api({"enable": False})
    with (
        patch.object(FakeClient, "get_allow_srm_from_wan", lambda self: _value(closed)),
        patch.object(FakeClient, "get_auto_block", lambda self: _value(_auto_block(False))),
        patch.object(FakeClient, "get_firewall_rules", lambda self: _value(_open_firewall())),
    ):
        await _refresh(hass, entry)
    assert _issues(hass, entry) == {"auto_block_off", "firewall_open"}
    await _refresh(hass, entry)  # as recorded again
    assert _issues(hass, entry) == {"srm_from_internet"}


async def test_an_unknown_setting_keeps_its_repair(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    client = next(c for c in reversed(FakeClient.instances) if c.folder == "router")
    client.errors["get_allow_srm_from_wan"] = SrmConnectionError("down")
    await _refresh(hass, entry)
    assert _issues(hass, entry) == {"srm_from_internet"}
    unknown = AutoBlock.from_api({})
    with patch.object(FakeClient, "get_auto_block", lambda self: _value(unknown)):
        await _refresh(hass, entry)
    assert _issues(hass, entry) == {"srm_from_internet"}


async def test_no_repairs_without_the_reads(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_allow_srm_from_wan", "get_auto_block", "get_firewall_rules"}
    entry = make_entry()
    await _setup(hass, entry)
    assert _issues(hass, entry) == set()


async def test_removing_the_entry_removes_its_repairs(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _issues(hass, entry) == {"srm_from_internet"}  # unloading keeps it, and its ignore
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass, entry) == set()


def test_every_repair_has_texts_and_a_page() -> None:
    component = ROOT / "custom_components" / DOMAIN
    for path in (
        component / "strings.json",
        component / "translations/en.json",
        component / "translations/de.json",
    ):
        issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
        for key in RISKS:
            assert {"title", "description"} <= issues[key].keys(), (path.name, key)
    for key in RISKS:
        page = ROOT / "docs" / "repairs" / f"{key.replace('_', '-')}.md"
        assert page.is_file(), page
        assert f"repairs/{page.name}" in (ROOT / "zensical.toml").read_text(encoding="utf-8")


async def test_a_router_switched_to_access_point_loses_its_repairs(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    assert _issues(hass, entry) == {"srm_from_internet"}
    assert await hass.config_entries.async_unload(entry.entry_id)
    access_point = load("ap", "topology")
    with patch.object(
        FakeClient, "get_topology", lambda self: _value(Topology.from_api(access_point))
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert _issues(hass, entry) == set()
