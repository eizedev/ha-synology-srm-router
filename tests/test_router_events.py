"""Router events: the IPv6 prefix or the firewall changed, also while Home Assistant was off."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiosynologysrm import FirewallRules, Ipv6Prefixes, SrmConnectionError
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.synology_srm_router.changes import Snapshot, changes

from .conftest import ERRORS, ROUTER_HOST, SERIALS, UNSUPPORTED, FakeClient, load, make_entry

ROUTER, AP = SERIALS["router"], SERIALS["ap"]
BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints/automation/synology_srm_router/notify_router_events.yaml"
)


async def _value(value: Any) -> Any:
    return value


async def _setup(hass: HomeAssistant, *entries: Any) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh_slow(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries("synology_srm_router"):
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.slow.async_refresh()
    await hass.async_block_till_done()


_written: list[dict[str, Any]] = []


def _record(hass: HomeAssistant) -> None:
    _written.clear()

    def listener(event: Any) -> None:
        new = event.data["new_state"]
        if new is not None and new.entity_id.endswith("router_events") and new.state != "unknown":
            _written.append(dict(new.attributes))

    hass.bus.async_listen("state_changed", listener)


def _entity_id(hass: HomeAssistant, serial: str = ROUTER, key: str = "router_events") -> str | None:
    platform = "event" if key == "router_events" else "sensor"
    return er.async_get(hass).async_get_entity_id(
        platform, "synology_srm_router", f"{serial}_{key}"
    )


def _store_key(entry: Any) -> str:
    return f"synology_srm_router.router_events.{entry.entry_id}"


async def _saved(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()


def _prefixes(**by_lan: str) -> Ipv6Prefixes:
    data = copy.deepcopy(load("router", "ipv6_prefixes"))
    for item in data["prefix"]:
        if item["lan"] in by_lan:
            item["prefix"] = by_lan[item["lan"]]
    return Ipv6Prefixes.from_api(data)


def _rules(change: Any) -> FirewallRules:
    data = copy.deepcopy(load("router", "firewall_rules"))
    change(data)
    return FirewallRules.from_api(data)


async def test_the_first_start_only_remembers(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    _record(hass)
    entry = make_entry()
    await _setup(hass, entry)
    await _refresh_slow(hass)
    await _saved(hass)
    assert _written == []
    stored = hass_storage[_store_key(entry)]["data"]
    assert stored["prefixes"] == {"lan": "2001:db8:1::", "guest": "2001:db8:2::"}
    assert len(stored["rules"]) == len(load("router", "firewall_rules")["rules"])
    assert stored["policy"]["ipv6_wan_to_lan"] == "deny"


async def test_a_new_prefix_fires_once(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    new = _prefixes(lbr0="2001:db8:11::", gbr0="2001:db8:12::")
    with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(new)):
        await _refresh_slow(hass)
        await _refresh_slow(hass)  # still the same: no second event
    [event] = _written
    assert event["event_type"] == "prefix_changed"
    assert event["changes"] == [
        {"network": "guest", "prefix": "2001:db8:12::", "previous": "2001:db8:2::"},
        {"network": "lan", "prefix": "2001:db8:11::", "previous": "2001:db8:1::"},
    ]


async def test_lifetimes_and_unused_prefixes_are_no_change(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    data = copy.deepcopy(load("router", "ipv6_prefixes"))
    for item in data["prefix"]:
        item["valid_lft"] = item["preferred_lft"] = 10
        if not item["lan"]:
            item["prefix"] = "2001:db8:ff::"
    with patch.object(
        FakeClient, "get_ipv6_prefixes", lambda self: _value(Ipv6Prefixes.from_api(data))
    ):
        await _refresh_slow(hass)
    assert _written == []


async def test_a_lost_prefix_is_a_change(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    empty = Ipv6Prefixes.from_api({"prefix": []})
    with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(empty)):
        await _refresh_slow(hass)
    [event] = _written
    assert {c["network"]: c["prefix"] for c in event["changes"]} == {"guest": None, "lan": None}


def _edit(data: dict[str, Any]) -> None:
    rules = data["rules"]
    rules[0]["enabled"] = not rules[0]["enabled"]  # switched
    removed = rules.pop(1)
    rules.append({**removed, "name": "new rule", "ui_id": 99})  # an edit: removed and added
    rules[2], rules[3] = rules[3], rules[2]  # moved
    data["default_policy"]["ipv6_wan_to_lan"] = "allow"


async def test_firewall_changes_fire_one_event(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    original = load("router", "firewall_rules")["rules"]
    with patch.object(FakeClient, "get_firewall_rules", lambda self: _value(_rules(_edit))):
        await _refresh_slow(hass)
    [event] = _written
    assert event["event_type"] == "firewall_changed"
    assert event["added"] == ["new rule"]
    assert len(event["removed"]) == 1
    switched = event["disabled"] if original[0]["enabled"] else event["enabled"]
    assert len(switched) == 1
    assert event["reordered"] is True
    assert event["policy"] == [
        {"traffic": "ipv6_wan_to_lan", "policy": "allow", "previous": "deny"}
    ]


async def test_a_change_while_home_assistant_was_off(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = make_entry()
    stored = Snapshot(
        prefixes={"lan": "2001:db8:99::", "guest": "2001:db8:2::"},
        rules=None,  # never read: no firewall comparison
        policy=None,
    )
    hass_storage[_store_key(entry)] = {"version": 1, "key": _store_key(entry), "data": stored}
    _record(hass)
    await _setup(hass, entry)
    [event] = _written
    assert event["changes"] == [
        {"network": "lan", "prefix": "2001:db8:1::", "previous": "2001:db8:99::"}
    ]


async def test_an_unchanged_router_after_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    await _saved(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    _record(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _written == []
    assert _store_key(entry) in hass_storage


async def test_nothing_fires_before_home_assistant_has_started(hass: HomeAssistant) -> None:
    _record(hass)
    with patch("custom_components.synology_srm_router.event.async_at_started"):
        await _setup(hass, make_entry())
    new = _prefixes(lbr0="2001:db8:11::")
    with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(new)):
        await _refresh_slow(hass)
    assert _written == []


async def test_a_failed_read_is_no_change(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    client = next(c for c in reversed(FakeClient.instances) if c.folder == "router")
    client.errors["get_ipv6_prefixes"] = SrmConnectionError("down")
    client.errors["get_firewall_rules"] = SrmConnectionError("down")
    await _refresh_slow(hass)
    client.errors.clear()
    await _refresh_slow(hass)
    assert _written == []


async def test_reads_that_failed_from_the_start_are_compared_later(hass: HomeAssistant) -> None:
    _record(hass)
    ERRORS[ROUTER_HOST] = {"get_ipv6_prefixes": SrmConnectionError("down")}
    await _setup(hass, make_entry())
    ERRORS.clear()
    for client in FakeClient.instances:
        client.errors.clear()
    await _refresh_slow(hass)  # the prefixes arrive: taken in, not a change
    assert _written == []


async def test_only_routers_have_router_events(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    assert _entity_id(hass) is not None
    assert _entity_id(hass, AP) is None
    assert _entity_id(hass, AP, "ipv6_prefix") is None


async def test_no_router_events_without_their_reads(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_ipv6_prefixes", "get_firewall_rules"}
    await _setup(hass, make_entry())
    assert _entity_id(hass) is None
    assert _entity_id(hass, ROUTER, "ipv6_prefix") is None


async def test_removing_the_entry_forgets_what_was_seen(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    await _saved(hass)
    assert _store_key(entry) in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _store_key(entry) not in hass_storage


async def test_the_prefix_sensor(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    entity_id = _entity_id(hass, ROUTER, "ipv6_prefix")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "2001:db8:1::"
    assert state.attributes["networks"] == {"lan": "2001:db8:1::", "guest": "2001:db8:2::"}
    guest_only = Ipv6Prefixes.from_api({"prefix": [{"lan": "gbr0", "prefix": "2001:db8:2::"}]})
    with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(guest_only)):
        await _refresh_slow(hass)
    assert hass.states.get(entity_id).state == "2001:db8:2::"  # type: ignore[union-attr]
    none = Ipv6Prefixes.from_api({"prefix": []})
    with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(none)):
        await _refresh_slow(hass)
    assert hass.states.get(entity_id).state == "unknown"  # type: ignore[union-attr]


def test_no_events_between_equal_snapshots() -> None:
    same = Snapshot(prefixes={"lan": "2001:db8:1::"}, rules=[["k", "rule", True]], policy={})
    assert changes(same, same) == []


def test_the_blueprint_is_valid() -> None:
    blueprint = Blueprint(
        load_yaml_dict(str(BLUEPRINT)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert set(blueprint.inputs) == {"events_entity", "event_types", "notify_action"}


async def test_the_blueprint_message(hass: HomeAssistant) -> None:
    message = load_yaml_dict(str(BLUEPRINT))["variables"]["message"]

    def render(event_type: str, attributes: dict[str, Any]) -> str:
        trigger = {"to_state": {"attributes": attributes}}
        text = Template(message, hass).async_render(
            {"event_type": event_type, "trigger": trigger}, parse_result=False
        )
        return " ".join(text.split())

    prefix = {"changes": [{"network": "lan", "prefix": "2001:db8:11::", "previous": None}]}
    assert render("prefix_changed", prefix) == "IPv6 prefix of lan: 2001:db8:11:: (was none)."
    firewall = {
        "added": ["a"],
        "removed": ["b", "c"],
        "enabled": [],
        "disabled": ["d"],
        "reordered": True,
        "policy": [{"traffic": "ipv6_wan_to_lan", "policy": "allow", "previous": "deny"}],
    }
    assert render("firewall_changed", firewall) == (
        "Firewall changed. Added: a. Removed: b, c. Switched off: d. Order of the rules changed."
        " Default policy ipv6_wan_to_lan: allow (was deny)."
    )


async def test_the_dashboard_card_shows_the_last_change(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    card = Path(__file__).parents[1] / "docs/assets/cards/router-changes.jinja"

    def render() -> str:
        return str(
            Template(card.read_text(encoding="utf-8"), hass).async_render(parse_result=False)
        )

    with patch.object(FakeClient, "get_firewall_rules", lambda self: _value(_rules(_edit))):
        await _refresh_slow(hass)
        shown = render()
        assert "added: new rule<br>" in shown
        assert "order changed<br>" in shown
        assert "default policy ipv6_wan_to_lan: allow (was deny)<br>" in shown
        new = _prefixes(lbr0="2001:db8:11::")
        with patch.object(FakeClient, "get_ipv6_prefixes", lambda self: _value(new)):
            await _refresh_slow(hass)
    assert "IPv6 prefix lan: 2001:db8:11:: (was 2001:db8:1::)<br>" in render()
