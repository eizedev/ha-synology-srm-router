"""Wi-Fi radios (channel and settings) and Wi-Fi networks on or off, per band."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from aiosynologysrm import SrmConnectionError, WifiNetworks
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.synology_srm_router.wifi import band_label, width_label

from .conftest import ROUTER_HOST, SERIALS, UNSUPPORTED, FakeClient, load, make_entry

ROUTER, AP = SERIALS["router"], SERIALS["ap"]


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


def _state(hass: HomeAssistant, domain: str, unique_id: str) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id(domain, "synology_srm_router", unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


def test_labels() -> None:
    assert band_label("2.4G") == "2.4 GHz"
    assert band_label("5G-2") == "5 GHz-2"
    assert band_label("7G") == "7G"  # unknown: as SRM writes it
    assert width_label("20_40_80") == "20/40/80 MHz"
    assert width_label(None) is None


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_radios_of_router_and_access_point(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    channel = _state(hass, "sensor", f"{ROUTER}_radio_channel_5G")
    assert channel.state == "36"
    assert channel.attributes["configured_channel"] == 36
    assert channel.attributes["friendly_name"].endswith("Channel 5 GHz")
    assert _state(hass, "sensor", f"{ROUTER}_radio_channel_width_2.4G").state == "20 MHz"
    assert _state(hass, "sensor", f"{ROUTER}_radio_transmit_power_5G").state == "high"
    assert _state(hass, "sensor", f"{ROUTER}_radio_wireless_mode_5G").state == "a_n_ac"
    # The access point picks 5G-1's channel itself: 0 in the settings, 100 in use.
    ap = _state(hass, "sensor", f"{AP}_radio_channel_5G-1")
    assert ap.state == "100"
    assert ap.attributes["configured_channel"] == 0
    assert _state(hass, "sensor", f"{AP}_radio_channel_width_5G-1").state == "20/40/80 MHz"
    # Only the channel has the configured channel as an attribute.
    width = _state(hass, "sensor", f"{AP}_radio_channel_width_5G-2")
    assert "configured_channel" not in width.attributes


async def test_radio_settings_off_by_default(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "synology_srm_router", f"{ROUTER}_radio_transmit_power_5G"
    )
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert _state(hass, "sensor", f"{ROUTER}_radio_channel_width_5G").state == "20/40 MHz"


async def test_wifi_networks_per_band(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    # The router: Smart Connect on, so the guest network is on on both bands.
    primary = _state(hass, "binary_sensor", f"{ROUTER}_wifi_network_0_2.4G")
    assert primary.state == "on"
    assert primary.attributes["friendly_name"].endswith("Wi-Fi name-1 2.4 GHz")
    assert primary.attributes["ssid"] == "ssid-1"  # the Smart Connect entry decides
    assert primary.attributes["smart_connect"] is True
    assert primary.attributes["network_type"] == "primary"
    assert primary.attributes["hidden"] is False
    assert _state(hass, "binary_sensor", f"{ROUTER}_wifi_network_1_5G").state == "on"
    # The access point: Smart Connect off, so each band decides; 5G-1 is off, guest off.
    assert _state(hass, "binary_sensor", f"{AP}_wifi_network_0_2.4G").state == "on"
    assert _state(hass, "binary_sensor", f"{AP}_wifi_network_0_5G-1").state == "off"
    assert _state(hass, "binary_sensor", f"{AP}_wifi_network_0_5G-2").state == "on"
    band = _state(hass, "binary_sensor", f"{AP}_wifi_network_0_5G-2")
    assert band.attributes["ssid"] == "ssid-1"  # the band's own entry decides
    assert _state(hass, "binary_sensor", f"{AP}_wifi_network_1_5G-2").state == "off"


async def test_a_network_that_disappears_and_comes_back(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    full = load("router", "wifi_networks")
    primary_only = {"profiles": [full["profiles"][0]]}
    with patch.object(
        FakeClient,
        "get_wifi_networks",
        lambda self: _value(WifiNetworks.from_api(primary_only)),
    ):
        await _refresh_slow(hass)
        guest = _state(hass, "binary_sensor", f"{ROUTER}_wifi_network_1_2.4G")
        assert guest.state == "unavailable"
        entity = hass.data["entity_components"]["binary_sensor"].get_entity(guest.entity_id)
        assert entity.extra_state_attributes == {}
    await _refresh_slow(hass)
    assert _state(hass, "binary_sensor", f"{ROUTER}_wifi_network_1_2.4G").state == "on"


async def test_a_new_network_gets_its_sensor(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    full = load("router", "wifi_networks")
    extra = {**full["profiles"][1], "id": 7, "name": None, "network_type": "guest"}
    with patch.object(
        FakeClient,
        "get_wifi_networks",
        lambda self: _value(WifiNetworks.from_api({"profiles": [*full["profiles"], extra]})),
    ):
        await _refresh_slow(hass)
        state = _state(hass, "binary_sensor", f"{ROUTER}_wifi_network_7_5G")
    assert state.attributes["friendly_name"].endswith("Wi-Fi guest 5 GHz")


async def test_radios_that_cannot_be_read(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    client = next(c for c in reversed(FakeClient.instances) if c.folder == "router")
    client.errors["get_wifi_radio_settings"] = SrmConnectionError("down")
    client.errors["get_wifi_radio_status"] = SrmConnectionError("down")
    # A failed optional read keeps the last value, so the channel stays.
    await _refresh_slow(hass)
    assert _state(hass, "sensor", f"{ROUTER}_radio_channel_5G").state == "36"


async def test_a_radio_that_disappears(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    settings = load("router", "wifi_radio_settings")
    only_24 = {"radio_list": [settings["radio_list"][0]]}
    with patch.object(
        FakeClient,
        "get_wifi_radio_settings",
        lambda self: _value(type(entry.runtime_data.slow.data.radio_settings).from_api(only_24)),
    ):
        await _refresh_slow(hass)
    assert _state(hass, "sensor", f"{ROUTER}_radio_channel_5G").state == "unavailable"
    assert _state(hass, "sensor", f"{ROUTER}_radio_channel_2.4G").state == "1"


async def _value(value: Any) -> Any:
    return value


async def test_devices_without_wifi_reads_have_no_wifi_entities(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_wifi_radio_settings", "get_wifi_networks"}
    await _setup(hass, make_entry())
    registry = er.async_get(hass)
    ids = [e.unique_id for e in registry.entities.values() if e.platform == "synology_srm_router"]
    assert not [i for i in ids if "_radio_" in i or "_wifi_network_" in i]
