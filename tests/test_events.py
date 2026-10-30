"""Wi-Fi events: a fixed channel changed, a Wi-Fi network switched off or on; and the blueprint."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiosynologysrm import NetworkDevices, SrmConnectionError, WifiNetworks, WifiRadioStatus
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict

from custom_components.synology_srm_router.coordinator import get_hub, private_mac

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


# New clients ---------------------------------------------------------------------------------


def _known(hass_storage: dict[str, Any], *skip: str) -> None:
    """Remember every client of both fixtures, except the ones to skip, as an earlier run did."""
    macs = {
        d["mac"].lower()
        for folder in ("router", "ap")
        for d in load(folder, "network_devices")["devices"]
    } | {
        w["mac_address"].lower()
        for folder in ("router", "ap")
        for w in load(folder, "wifi_devices")["device_list"]
    }
    seen = (dt_util.utcnow() - timedelta(days=1)).isoformat()
    hass_storage["synology_srm_router.known_clients"] = {
        "version": 1,
        "key": "synology_srm_router.known_clients",
        "data": dict.fromkeys(macs - set(skip), seen) | {"02:00:00:00:00:fe": "nonsense"},
    }


def _with_client(mac: str, hostname: str) -> Any:
    """The router's client list with one more client online on a cable."""
    data = copy.deepcopy(load("router", "network_devices"))
    template = next(d for d in data["devices"] if d.get("connection") == "ethernet")
    data["devices"].append({**template, "mac": mac, "hostname": hostname, "is_online": True})
    return NetworkDevices.from_api(data)


async def _refresh_fast(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries("synology_srm_router"):
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()


def _client_events(hass: HomeAssistant, serial: str) -> list[dict[str, Any]]:
    entity_id = er.async_get(hass).async_get_entity_id(
        "event", "synology_srm_router", f"{serial}_client_events"
    )
    assert entity_id is not None
    return [dict(s.attributes) for s in _written.get(entity_id, []) if s.state != "unknown"]


async def test_a_new_client_fires_once(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    _known(hass_storage)
    _record(hass)
    await _setup(hass, make_entry(), make_entry("ap"))
    devices = _with_client("00:00:00:00:00:42", "new-laptop")
    with patch.object(FakeClient, "get_network_devices", _returning(devices, "router")):
        await _refresh_fast(hass)
        await _refresh_fast(hass)  # still there: no second event
    [event] = _client_events(hass, ROUTER)
    assert event["event_type"] == "new_client"
    assert event["name"] == "new-laptop"
    assert event["mac"] == "00:00:00:00:00:42"
    assert event["connection"] == "ethernet"
    assert event["private_mac"] is False
    assert _client_events(hass, AP) == []
    assert "00:00:00:00:00:42" in get_hub(hass).first_seen
    assert "02:00:00:00:00:fe" not in get_hub(hass).first_seen  # an unreadable date is skipped


async def test_a_private_address_is_marked(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    _known(hass_storage)
    _record(hass)
    await _setup(hass, make_entry(), make_entry("ap"))
    devices = _with_client("02:00:00:00:00:99", "phone")
    with patch.object(FakeClient, "get_network_devices", _returning(devices, "router")):
        await _refresh_fast(hass)
    [event] = _client_events(hass, ROUTER)
    assert event["private_mac"] is True


async def test_the_first_start_takes_in_every_client_quietly(hass: HomeAssistant) -> None:
    _record(hass)
    await _setup(hass, make_entry(), make_entry("ap"))
    await _refresh_fast(hass)
    assert _client_events(hass, ROUTER) == []
    assert get_hub(hass).first_seen
    # From now on a new client counts.
    devices = _with_client("00:00:00:00:00:43", "printer")
    with patch.object(FakeClient, "get_network_devices", _returning(devices, "router")):
        await _refresh_fast(hass)
    assert [e["name"] for e in _client_events(hass, ROUTER)] == ["printer"]


async def test_no_new_clients_while_a_device_is_missing(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    _known(hass_storage)
    _record(hass)
    await _setup(hass, make_entry(), make_entry("ap"))
    ap = next(c for c in reversed(FakeClient.instances) if c.folder == "ap")
    for name in ("get_utilization", "get_network_devices", "get_wifi_devices"):
        ap.errors[name] = SrmConnectionError("down")
    ap_entry = next(
        e for e in hass.config_entries.async_entries("synology_srm_router") if e.unique_id == AP
    )
    await ap_entry.runtime_data.fast.async_refresh()  # the access point's lists are gone first
    await hass.async_block_till_done()
    devices = _with_client("00:00:00:00:00:44", "tv")
    with patch.object(FakeClient, "get_network_devices", _returning(devices, "router")):
        await _refresh_fast(hass)
    assert _client_events(hass, ROUTER) == []
    assert "00:00:00:00:00:44" in get_hub(hass).first_seen  # taken in quietly


def test_private_addresses_are_forgotten_after_a_while(hass: HomeAssistant) -> None:
    hub = get_hub(hass)
    old = dt_util.utcnow() - timedelta(days=40)
    hub.first_seen.update({"02:00:00:00:00:01": old, "00:00:00:00:00:01": old})
    hub._prune(dt_util.utcnow())
    assert set(hub.first_seen) == {"00:00:00:00:00:01"}
    assert private_mac("02:00:00:00:00:01")
    assert not private_mac("00:00:00:00:00:01")
    assert not private_mac("zz:00:00:00:00:01")


def _returning(value: Any, folder: str) -> Any:
    """A getter that answers with value for one device and as recorded for the others."""
    original = FakeClient.get_network_devices

    async def getter(self: FakeClient) -> Any:
        if self.folder == folder:
            return value
        return await original(self)

    getter.__name__ = "get_network_devices"  # the coordinator checks reads by name
    return getter


def test_the_new_clients_blueprint_is_valid() -> None:
    path = BLUEPRINT.parent / "notify_new_clients.yaml"
    blueprint = Blueprint(
        load_yaml_dict(str(path)), expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA
    )
    assert set(blueprint.inputs) == {"events_entity", "include_private", "notify_action"}
