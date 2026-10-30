"""Wi-Fi events: a fixed channel changed, a Wi-Fi network switched off or on; and the blueprint."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiosynologysrm import SrmConnectionError, WifiNetworks, WifiRadioStatus
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import load_yaml_dict

from .conftest import ROUTER_HOST, SERIALS, UNSUPPORTED, FakeClient, load, make_entry

ROUTER, AP = SERIALS["router"], SERIALS["ap"]
BLUEPRINT = (
    Path(__file__).parents[1] / "blueprints/automation/synology_srm_router/notify_wifi_events.yaml"
)


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


def _events(hass: HomeAssistant, serial: str) -> list[dict[str, Any]]:
    """Every state the events entity was written with, from the start of the test."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "event", "synology_srm_router", f"{serial}_wifi_events"
    )
    assert entity_id is not None
    return [dict(s.attributes) for s in _written[entity_id] if s.state != "unknown"]


_written: dict[str, list[Any]] = {}


def _record(hass: HomeAssistant) -> None:
    _written.clear()

    def listener(event: Any) -> None:
        new = event.data["new_state"]
        if new is not None and new.domain == "event":
            _written.setdefault(new.entity_id, []).append(new)

    hass.bus.async_listen("state_changed", listener)


async def _value(value: Any) -> Any:
    return value


def _status(channel_5g: int) -> WifiRadioStatus:
    data = copy.deepcopy(load("router", "wifi_radio_status"))
    data["status_list"][1]["channel"] = channel_5g
    return WifiRadioStatus.from_api(data)


async def test_nothing_fires_at_startup(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry(), make_entry("ap"))
    await _refresh_slow(hass)
    assert _events(hass, ROUTER) == []
    assert _events(hass, AP) == []


async def test_a_fixed_channel_that_changes(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    with patch.object(FakeClient, "get_wifi_radio_status", lambda self: _value(_status(100))):
        await _refresh_slow(hass)
    [event] = _events(hass, ROUTER)
    assert event["event_type"] == "channel_changed"
    assert (event["band"], event["channel"], event["previous"]) == ("5 GHz", 100, 36)


async def test_an_automatic_channel_that_changes_is_no_event(hass: HomeAssistant) -> None:
    # The access point picks 5G-1's channel itself (0 in SRM): a change is normal.
    _record(hass)
    await _setup(hass, make_entry("ap"))
    data = copy.deepcopy(load("ap", "wifi_radio_status"))
    data["status_list"][1]["channel"] = 116
    with patch.object(
        FakeClient,
        "get_wifi_radio_status",
        lambda self: _value(WifiRadioStatus.from_api(data)),
    ):
        await _refresh_slow(hass)
    assert _events(hass, AP) == []


async def test_a_network_switched_off_and_on_fires_once_each(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    data = copy.deepcopy(load("router", "wifi_networks"))
    guest = data["profiles"][1]
    smart = next(r for r in guest["radio_list"] if r["radio_type"] == "SmartConnect")
    smart["enable"] = False
    with patch.object(
        FakeClient, "get_wifi_networks", lambda self: _value(WifiNetworks.from_api(data))
    ):
        await _refresh_slow(hass)
    await _refresh_slow(hass)  # back as recorded: on again
    events = _events(hass, ROUTER)
    assert [e["event_type"] for e in events] == ["network_off", "network_on"]
    assert events[0]["network"] == "name-2"
    assert events[0]["bands"] == ["2.4 GHz", "5 GHz"]


async def test_a_failed_read_is_no_change(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry())
    client = next(c for c in reversed(FakeClient.instances) if c.folder == "router")
    client.errors["get_wifi_radio_status"] = SrmConnectionError("down")
    client.errors["get_wifi_networks"] = SrmConnectionError("down")
    await _refresh_slow(hass)
    client.errors.clear()
    await _refresh_slow(hass)
    assert _events(hass, ROUTER) == []


async def test_a_network_without_a_known_state_is_skipped(hass: HomeAssistant) -> None:
    # Smart Connect on without its entry: on or off is unknown, which is no change either.
    _record(hass)
    await _setup(hass, make_entry())
    data = copy.deepcopy(load("router", "wifi_networks"))
    guest = data["profiles"][1]
    guest["radio_list"] = [r for r in guest["radio_list"] if r["radio_type"] != "SmartConnect"]
    with patch.object(
        FakeClient, "get_wifi_networks", lambda self: _value(WifiNetworks.from_api(data))
    ):
        await _refresh_slow(hass)
    assert _events(hass, ROUTER) == []


async def test_no_events_entity_without_wifi_reads(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_wifi_radio_settings", "get_wifi_networks"}
    await _setup(hass, make_entry())
    assert (
        er.async_get(hass).async_get_entity_id(
            "event", "synology_srm_router", f"{ROUTER}_wifi_events"
        )
        is None
    )


def test_the_blueprint_is_valid() -> None:
    blueprint = Blueprint(
        load_yaml_dict(str(BLUEPRINT)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert set(blueprint.inputs) == {"events_entity", "event_types", "notify_action"}
