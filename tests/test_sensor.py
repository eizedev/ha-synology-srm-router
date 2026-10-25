"""DHCP, firewall and USB sensors: created from what the device offers, following its changes."""

from __future__ import annotations

import dataclasses
from typing import Any

from aiosynologysrm import (
    DhcpClients,
    DhcpServers,
    FirewallHitCount,
    FirewallRules,
    SrmConnectionError,
    StorageVolumes,
    SystemInfo,
    helpers,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.synology_srm_router.coordinator import SlowData
from custom_components.synology_srm_router.sensor import (
    USB_SENSORS,
    SrmDhcpPoolSensor,
    SrmFirewallHitsSensor,
    _firewall_attributes,
    _ipv4_count,
    firewall_rules,
    pool_usage,
    rule_label,
)

from .conftest import SERIALS, FakeClient, load, make_entry


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


def _entity(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", "synology_srm_router", unique_id)


def _value(hass: HomeAssistant, unique_id: str) -> Any:
    entity_id = _entity(hass, unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


def _client(host_kind: str = "router") -> FakeClient:
    return next(c for c in reversed(FakeClient.instances) if c.folder == host_kind)


async def test_router_counts_dhcp_and_firewall(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    serial = SERIALS["router"]
    leases = load("router", "dhcp_clients")["clientList"]["ipv4"]
    reservations = load("router", "dhcp_reservations")["reservationList"]["ipv4"]
    assert _value(hass, f"{serial}_dhcp_leases").state == str(len(leases))
    assert _value(hass, f"{serial}_dhcp_reservations").state == str(len(reservations))
    rules = load("router", "firewall_rules")["rules"]
    state = _value(hass, f"{serial}_firewall_rules")
    assert state.state == str(len(rules))
    assert len(state.attributes["config_hash"]) == 64


async def test_one_hits_sensor_per_rule(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    data = entry.runtime_data.slow.data
    rules = firewall_rules(data)
    assert len(rules) == len(load("router", "firewall_rules")["rules"])
    hits = helpers.hits_by_rule(
        FirewallHitCount.list_from_api(load("router", "firewall_hit_counts"))
    )
    for key, rule in rules.items():
        state = _value(hass, f"{SERIALS['router']}_firewall_rule_{key}")
        assert state.attributes["unit_of_measurement"] == "packets"
        expected = hits.get(rule.ui_id) if rule.ui_id is not None else None
        assert state.state == ("unknown" if expected is None else str(expected))


async def test_an_edited_rule_gets_a_new_sensor(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    raw = load("router", "firewall_rules")
    old_keys = set(firewall_rules(entry.runtime_data.slow.data))
    raw["rules"][0] = {**raw["rules"][0], "dst_port_value": "65000", "enabled": False}
    edited = FirewallRules.from_api(raw)
    client = _client()
    client.get_firewall_rules = _returning(edited)  # type: ignore[method-assign]
    await _refresh_slow(hass)
    new_keys = set(firewall_rules(entry.runtime_data.slow.data))
    (gone,) = old_keys - new_keys
    (added,) = new_keys - old_keys
    assert _entity(hass, f"{SERIALS['router']}_firewall_rule_{gone}") is None
    entity_id = _entity(hass, f"{SERIALS['router']}_firewall_rule_{added}")
    assert entity_id is not None
    registry_entry = er.async_get(hass).async_get(entity_id)
    assert registry_entry is not None
    assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION  # switched off


async def test_switching_a_rule_keeps_its_sensor(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    raw = load("router", "firewall_rules")
    before = set(firewall_rules(entry.runtime_data.slow.data))
    raw["rules"][0] = {**raw["rules"][0], "enabled": False, "ui_id": 99}
    _client().get_firewall_rules = _returning(FirewallRules.from_api(raw))  # type: ignore[method-assign]
    await _refresh_slow(hass)
    assert set(firewall_rules(entry.runtime_data.slow.data)) == before


async def test_dhcp_pools(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    serial = SERIALS["router"]
    lan = _value(hass, f"{serial}_dhcp_pool_lbr0")
    guest = _value(hass, f"{serial}_dhcp_pool_gbr0")
    assert lan.attributes["unit_of_measurement"] == "%"
    assert "begin" in guest.attributes
    servers = load("router", "dhcp_servers")
    servers["data"] = [s for s in servers["data"] if s["ifname"] != "gbr0"]
    _client().get_dhcp_servers = _returning(DhcpServers.from_api(servers))  # type: ignore[method-assign]
    await _refresh_slow(hass)
    assert _value(hass, f"{serial}_dhcp_pool_gbr0").state == "unavailable"


async def test_usb_volumes_come_and_go(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    serial = SERIALS["router"]
    volume = load("router", "usb_volumes")["volumes"][0]
    path = volume["volume_path"]
    used = _value(hass, f"{serial}_usb_used_{path}")
    total, free = int(volume["size_total_byte"]), int(volume["size_free_byte"])
    assert abs(float(used.state) - 100 * (total - free) / total) < 0.01
    assert _entity(hass, f"{serial}_usb_free_{path}") is not None
    _client().get_usb_volumes = _returning(StorageVolumes.from_api({"volumes": []}))  # type: ignore[method-assign]
    await _refresh_slow(hass)
    assert _value(hass, f"{serial}_usb_used_{path}").state == "unavailable"


async def test_access_point_has_no_dhcp_or_firewall_sensors(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    serial = SERIALS["ap"]
    for key in ("dhcp_leases", "dhcp_reservations", "firewall_rules", "dhcp_pool_lbr0"):
        assert _entity(hass, f"{serial}_{key}") is None


async def test_a_failed_optional_read_keeps_what_is_known(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    slow = entry.runtime_data.slow
    known = slow.data.firewall
    for name in ("get_firewall_rules", "get_usb_volumes"):
        _client().errors[name] = SrmConnectionError("x")
    await slow.async_refresh()
    assert slow.last_update_success
    assert slow.data.firewall == known
    assert slow.data.usb is not None
    for name in ("get_firewall_hit_counts", "get_dhcp_clients", "get_dhcp_reservations"):
        _client().errors[name] = SrmConnectionError("x")
    _client().errors["get_dhcp_servers"] = SrmConnectionError("x")
    await slow.async_refresh()  # every optional read failed: still no failed update
    assert slow.last_update_success
    assert slow.data.firewall == known


def test_helpers_without_data() -> None:
    system = load("router", "system_info")
    data = SlowData(system=SystemInfo.from_api(system))
    assert _ipv4_count(None) is None
    assert firewall_rules(data) == {}
    rules = FirewallRules.from_api(
        {"rules": [{"ui_id": 4}, {"ui_id": 5, "name": "x", "ip_version": "both_v4_v6"}]}
    ).rules
    assert rule_label(rules[0], rules) == "#4"
    same = FirewallRules.from_api({"rules": [{"ui_id": 1, "name": "y"}, {"ui_id": 2, "name": "y"}]})
    # Identical rules (apart from position) each get a key of their own.
    assert list(firewall_rules(dataclasses.replace(data, firewall=same)))[1].endswith("_2")
    twice = (rules[1], dataclasses.replace(rules[1], ui_id=6))
    assert rule_label(rules[1], twice) == "x"  # no single IP version to tell them apart
    servers = DhcpServers.from_api(
        {
            "data": [
                {"ifname": "a", "ipv4": {"begin": "nonsense", "end": "192.0.2.9"}},
                {"ifname": "b", "ipv4": {"begin": "192.0.2.9", "end": "192.0.2.1"}},
                {"ifname": "c", "ipv4": {"begin": "192.0.2.1", "end": "192.0.2.4"}},
            ]
        }
    ).data
    assert pool_usage(data, servers[0]) is None
    assert pool_usage(data, servers[1]) is None
    leases = load("router", "dhcp_clients")
    leases["clientList"]["ipv4"] = [{"ip": "192.0.2.2"}, {"ip": "bad"}, {"ip": "192.0.2.200"}]
    with_leases = dataclasses.replace(data, leases=DhcpClients.from_api(leases))
    assert pool_usage(with_leases, servers[2]) == 25.0
    empty = StorageVolumes.from_api({"volumes": [{"volume_path": "/v", "size_total_byte": 0}]})
    assert USB_SENSORS[0].value_fn(empty.volumes[0]) is None


def _returning(value: Any) -> Any:
    async def getter() -> Any:
        return value

    return getter


async def test_sensors_whose_object_is_gone(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    rule = next(iter(firewall_rules(entry.runtime_data.slow.data).values()))
    missing = SrmFirewallHitsSensor(entry, "missing", rule)
    assert missing.native_value is None
    assert missing.extra_state_attributes == {}
    assert SrmDhcpPoolSensor(entry, "missing").extra_state_attributes == {}
    data = entry.runtime_data.slow.data
    assert _firewall_attributes(dataclasses.replace(data, firewall=None)) == {}
