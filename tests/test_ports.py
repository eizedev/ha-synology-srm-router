"""Ethernet ports of routers and access points: link and speed."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from aiosynologysrm import EthPortInfo
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.synology_srm_router.coordinator import FastData
from custom_components.synology_srm_router.ports import own_ports, port_label

from .conftest import ROUTER_HOST, SERIALS, UNSUPPORTED, FakeClient, load, make_entry

ROUTER, AP = SERIALS["router"], SERIALS["ap"]


async def _setup(hass: HomeAssistant, *entries: Any) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries("synology_srm_router"):
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, domain: str, unique_id: str) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id(domain, "synology_srm_router", unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


def _ports(nodes: list[dict[str, Any]]) -> Any:
    async def getter(self: FakeClient) -> EthPortInfo:
        return EthPortInfo.from_api({"nodes": nodes})

    getter.__name__ = "get_eth_port_info"  # the coordinator checks reads by name
    return getter


@pytest.mark.parametrize(
    ("port", "label"), [("wp1", "WAN"), ("lp1", "LAN 1"), ("lp12", "LAN 12"), ("sfp1", "sfp1")]
)
def test_port_labels(port: str, label: str) -> None:
    assert port_label(port) == label


def test_only_the_device_itself_counts() -> None:
    mesh = EthPortInfo.from_api(
        {
            "nodes": [
                {"node_id": 1, "eth_port_info": [{"port": "lp1", "has_link": True}]},
                {"node_id": 0, "eth_port_info": [{"port": "wp1", "has_link": True}, {}]},
            ]
        }
    )
    assert set(own_ports(FastData(ports=mesh))) == {"wp1"}
    assert own_ports(FastData(ports=EthPortInfo.from_api({"nodes": [{"node_id": 2}]}))) == {}
    assert own_ports(FastData()) == {}


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_ports_of_router_and_access_point(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    wan = _state(hass, "binary_sensor", f"{ROUTER}_port_wp1_link")
    assert wan.state == "on"
    assert wan.attributes["friendly_name"].endswith("Port WAN")
    assert wan.attributes["device_class"] == "connectivity"
    assert _state(hass, "binary_sensor", f"{ROUTER}_port_lp2_link").state == "off"
    assert _state(hass, "sensor", f"{ROUTER}_port_lp1_speed").state == "1000"
    assert _state(hass, "sensor", f"{ROUTER}_port_lp2_speed").state == "0"
    slow = _state(hass, "sensor", f"{ROUTER}_port_lp3_speed")
    assert slow.state == "10"
    assert slow.attributes["friendly_name"].endswith("Port LAN 3 speed")
    assert _state(hass, "binary_sensor", f"{AP}_port_wp1_link").state == "on"
    assert _state(hass, "binary_sensor", f"{AP}_port_lp1_link").state == "off"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_a_port_that_disappears(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    recorded = load("router", "eth_port_info")["nodes"][0]
    only_wan = [{**recorded, "eth_port_info": recorded["eth_port_info"][:1]}]
    with patch.object(FakeClient, "get_eth_port_info", _ports(only_wan)):
        await _refresh(hass)
    assert _state(hass, "binary_sensor", f"{ROUTER}_port_lp1_link").state == "unavailable"
    assert _state(hass, "sensor", f"{ROUTER}_port_lp1_speed").state == "unavailable"
    assert _state(hass, "binary_sensor", f"{ROUTER}_port_wp1_link").state == "on"


async def test_no_port_entities_without_the_read(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_eth_port_info"}
    await _setup(hass, make_entry())
    ids = [e.unique_id for e in er.async_get(hass).entities.values()]
    assert not [i for i in ids if "_port_" in i]
