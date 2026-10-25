"""DHCP, firewall and USB sensors: created from what the device offers, following its changes."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path
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
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import parse_yaml

from custom_components.synology_srm_router.const import RECENTLY_SEEN
from custom_components.synology_srm_router.coordinator import SlowData, get_hub
from custom_components.synology_srm_router.firewall import rule_keys, rule_label, rule_rows
from custom_components.synology_srm_router.sensor import (
    USB_SENSORS,
    SrmDhcpPoolSensor,
    SrmFirewallHitsSensor,
    SrmSlowSensor,
    SrmUsbSensor,
    _firewall_attributes,
    _ipv4_count,
    _lease_attributes,
    _reservation_attributes,
    pool_usage,
)

from .conftest import ERRORS, ROUTER_HOST, SERIALS, FakeClient, load, make_entry

ROUTER = SERIALS["router"]


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


def _state(hass: HomeAssistant, unique_id: str) -> Any:
    entity_id = _entity(hass, unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


def _client(host_kind: str = "router") -> FakeClient:
    return next(c for c in reversed(FakeClient.instances) if c.folder == host_kind)


def _returning(value: Any) -> Any:
    async def getter() -> Any:
        return value

    return getter


def _serve_rules(raw: dict[str, Any]) -> None:
    _client().get_firewall_rules = _returning(FirewallRules.from_api(raw))  # type: ignore[method-assign]


async def test_router_counts_dhcp_and_firewall(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry())
    leases = load("router", "dhcp_clients")["clientList"]["ipv4"]
    reservations = load("router", "dhcp_reservations")["reservationList"]["ipv4"]
    assert _state(hass, f"{ROUTER}_dhcp_leases").state == str(len(leases))
    assert _state(hass, f"{ROUTER}_dhcp_reservations").state == str(len(reservations))
    rules = load("router", "firewall_rules")["rules"]
    state = _state(hass, f"{ROUTER}_firewall_rules")
    assert state.state == str(len(rules))
    assert len(state.attributes["config_hash"]) == 64
    assert len(state.attributes["rules"]) == len(rules)
    # The lists are for dashboards; the history keeps only the counts.
    assert {"leases", "reservations", "rules"} <= SrmSlowSensor._unrecorded_attributes


async def test_hits_sensors_only_with_the_option(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    rules = entry.runtime_data.slow.data.rules
    assert all(_entity(hass, f"{ROUTER}_firewall_rule_{key}") is None for key in rules)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "firewall_hits": True})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    hits = helpers.hits_by_rule(
        FirewallHitCount.list_from_api(load("router", "firewall_hit_counts"))
    )
    for key, rule in entry.runtime_data.slow.data.rules.items():
        state = _state(hass, f"{ROUTER}_firewall_rule_{key}")
        assert state.attributes["unit_of_measurement"] == "packets"
        expected = hits.get(rule.ui_id) if rule.ui_id is not None else None
        assert state.state == ("unknown" if expected is None else str(expected))
    hass.config_entries.async_update_entry(entry, options={**entry.options, "firewall_hits": False})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(_entity(hass, f"{ROUTER}_firewall_rule_{key}") is None for key in rules)


async def test_an_edited_rule_gets_a_new_sensor_and_its_old_one_back(hass: HomeAssistant) -> None:
    entry = make_entry(firewall_hits=True)
    await _setup(hass, entry)
    original = load("router", "firewall_rules")
    old_keys = set(entry.runtime_data.slow.data.rules)
    old_ids = {key: _entity(hass, f"{ROUTER}_firewall_rule_{key}") for key in old_keys}
    edited = load("router", "firewall_rules")
    edited["rules"][0] = {**edited["rules"][0], "dst_port_value": "65000", "enabled": False}
    _serve_rules(edited)
    await _refresh_slow(hass)
    new_keys = set(entry.runtime_data.slow.data.rules)
    (gone,) = old_keys - new_keys
    (added,) = new_keys - old_keys
    assert _entity(hass, f"{ROUTER}_firewall_rule_{gone}") is None
    entity_id = _entity(hass, f"{ROUTER}_firewall_rule_{added}")
    assert entity_id is not None
    # The old sensor was removed before the new one came, so the new one takes its entity ID
    # (same name) instead of one with "_2" appended.
    assert entity_id == old_ids[gone]
    registry_entry = er.async_get(hass).async_get(entity_id)
    assert registry_entry is not None
    assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION  # switched off
    _serve_rules(original)  # the edit is undone: the rule's sensor comes back
    await _refresh_slow(hass)
    assert _entity(hass, f"{ROUTER}_firewall_rule_{gone}") is not None


async def test_moving_or_switching_a_rule_keeps_its_sensor(hass: HomeAssistant) -> None:
    entry = make_entry(firewall_hits=True)
    await _setup(hass, entry)
    before = set(entry.runtime_data.slow.data.rules)
    raw = load("router", "firewall_rules")
    raw["rules"][0] = {**raw["rules"][0], "enabled": False, "ui_id": 99}
    _serve_rules(raw)
    await _refresh_slow(hass)
    assert set(entry.runtime_data.slow.data.rules) == before


async def test_hits_are_unknown_when_the_counters_cannot_be_read(hass: HomeAssistant) -> None:
    entry = make_entry(firewall_hits=True)
    await _setup(hass, entry)
    _client().errors["get_firewall_hit_counts"] = SrmConnectionError("x")
    await _refresh_slow(hass)
    assert entry.runtime_data.slow.data.hits is None
    key = next(iter(entry.runtime_data.slow.data.rules))
    assert _state(hass, f"{ROUTER}_firewall_rule_{key}").state == "unknown"


async def test_dhcp_pools(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    lan = _state(hass, f"{ROUTER}_dhcp_pool_lbr0")
    guest = _state(hass, f"{ROUTER}_dhcp_pool_gbr0")
    assert lan.attributes["unit_of_measurement"] == "%"
    assert "begin" in guest.attributes
    assert {"begin", "end"} <= SrmDhcpPoolSensor._unrecorded_attributes
    servers = load("router", "dhcp_servers")
    for server in servers["data"]:
        if server["ifname"] == "gbr0":
            server["ipv4"]["enable"] = False  # a switched-off server has no pool to fill
    _client().get_dhcp_servers = _returning(DhcpServers.from_api(servers))  # type: ignore[method-assign]
    await _refresh_slow(hass)
    assert _state(hass, f"{ROUTER}_dhcp_pool_gbr0").state == "unavailable"


async def test_lists_behind_the_dhcp_counts(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    leases = _state(hass, f"{ROUTER}_dhcp_leases").attributes["leases"]
    assert leases
    assert set(leases[0]) == {
        "name", "ip", "mac", "online", "reserved", "unknown", "expires_in_min"
    }  # fmt: skip
    online = [row["online"] for row in leases]
    assert online == sorted(online, reverse=True)  # online first
    assert all(not (row["reserved"] and row["unknown"]) for row in leases)
    reservations = _state(hass, f"{ROUTER}_dhcp_reservations").attributes["reservations"]
    assert set(reservations[0]) == {
        "name", "ip", "mac", "online", "last_seen", "stale", "in_pool"
    }  # fmt: skip
    # Home Assistant just started: nothing offline was seen yet, so offline ones are stale.
    assert all(row["stale"] == (not row["online"]) for row in reservations)
    hub = get_hub(hass)
    offline = next(row for row in reservations if not row["online"])
    hub.last_seen[offline["mac"]] = dt_util.utcnow() - timedelta(days=1)
    rows = _reservation_attributes(hass, entry.runtime_data.slow.data)["reservations"]
    row = next(r for r in rows if r["mac"] == offline["mac"])
    assert not row["stale"]
    assert row["last_seen"] is not None
    hub.last_seen[offline["mac"]] = dt_util.utcnow() - RECENTLY_SEEN - timedelta(days=1)
    rows = _reservation_attributes(hass, entry.runtime_data.slow.data)["reservations"]
    assert next(r for r in rows if r["mac"] == offline["mac"])["stale"]


async def test_usb_volumes_come_and_go(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    volume = load("router", "usb_volumes")["volumes"][0]
    path = volume["volume_path"]
    used = _state(hass, f"{ROUTER}_usb_used_{path}")
    total, free = int(volume["size_total_byte"]), int(volume["size_free_byte"])
    assert float(used.state) == round(100 * (total - free) / total, 1)
    assert _entity(hass, f"{ROUTER}_usb_free_{path}") is not None
    _client().get_usb_volumes = _returning(StorageVolumes.from_api({"volumes": []}))  # type: ignore[method-assign]
    await _refresh_slow(hass)
    assert _state(hass, f"{ROUTER}_usb_used_{path}").state == "unavailable"


async def test_access_point_has_no_dhcp_or_firewall_sensors(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(firewall_hits=True), make_entry("ap", firewall_hits=True))
    serial = SERIALS["ap"]
    for key in ("dhcp_leases", "dhcp_reservations", "firewall_rules", "dhcp_pool_lbr0"):
        assert _entity(hass, f"{serial}_{key}") is None
    ap_entries = er.async_entries_for_config_entry(
        er.async_get(hass), hass.config_entries.async_entries("synology_srm_router")[1].entry_id
    )
    assert not [e for e in ap_entries if "_firewall_rule_" in e.unique_id]


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
    data = SlowData(system=SystemInfo.from_api(load("router", "system_info")))
    assert _ipv4_count(None) is None
    assert rule_keys(()) == {}
    rules = FirewallRules.from_api(
        {"rules": [{"ui_id": 4}, {"ui_id": 5, "name": "x", "ip_version": "both_v4_v6"}]}
    ).rules
    assert rule_label(rules[0], rules) == "#4"
    twice = (rules[1], dataclasses.replace(rules[1], ui_id=6))
    assert rule_label(rules[1], twice) == "x"  # no single IP version to tell them apart
    same = FirewallRules.from_api({"rules": [{"ui_id": 1, "name": "y"}, {"ui_id": 2, "name": "y"}]})
    keyed = rule_keys(same.rules)
    assert list(keyed)[1].endswith("_2")  # identical rules each get a key of their own
    rows = rule_rows(keyed, {1: 7})
    assert [(r["hits"], r["duplicate"]) for r in rows] == [(7, False), (None, True)]
    assert rows[0]["label"] == "y"
    assert rows[0]["in_interfaces"] is None
    lan = FirewallRules.from_api(
        {"rules": [{"ui_id": 1, "in_interface_type": "specific", "in_interface_value": ["lan"]}]}
    )
    assert rule_rows(rule_keys(lan.rules), None)[0]["in_interfaces"] == ["lan"]
    assert all(r["hits"] is None for r in rule_rows(keyed, None))
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
    assert pool_usage(data, servers[2]) is None  # leases never read: unknown, not empty
    leases = load("router", "dhcp_clients")
    leases["clientList"]["ipv4"] = [{"ip": "192.0.2.2"}, {"ip": "bad"}, {"ip": "192.0.2.200"}]
    with_leases = dataclasses.replace(data, leases=DhcpClients.from_api(leases))
    assert pool_usage(with_leases, servers[2]) == 25.0
    empty = StorageVolumes.from_api({"volumes": [{"volume_path": "/v", "size_total_byte": 0}]})
    assert USB_SENSORS[0].value_fn(empty.volumes[0]) is None


async def test_sensors_whose_object_is_gone(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    data = entry.runtime_data.slow.data
    rule = next(iter(data.rules.values()))
    missing = SrmFirewallHitsSensor(entry, "missing", rule)
    assert missing.native_value is None
    assert missing.extra_state_attributes == {}
    assert SrmDhcpPoolSensor(entry, "missing").extra_state_attributes == {}
    nothing = dataclasses.replace(data, firewall=None, leases=None, reservations=None)
    assert _firewall_attributes(hass, nothing) == {}
    assert _lease_attributes(hass, nothing) == {}
    assert _reservation_attributes(hass, nothing) == {}
    volume = StorageVolumes.from_api({"volumes": [{"volume_path": "/volumeUSB1/usbshare/"}]})
    usb = SrmUsbSensor(entry, "/volumeUSB1/usbshare/", volume.volumes[0], USB_SENSORS[0])
    assert usb.translation_placeholders == {"volume": "usbshare"}


async def test_hits_option_without_any_rule_list(hass: HomeAssistant) -> None:
    ERRORS[ROUTER_HOST] = {"get_firewall_rules": SrmConnectionError("x")}
    entry = make_entry(firewall_hits=True)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.slow.data.rules == {}
    assert _entity(hass, f"{ROUTER}_firewall_rules") is not None


def test_example_dashboard_uses_the_card_templates() -> None:
    # The templates live once in docs/assets/cards; the example dashboard must carry them as is.
    docs = Path(__file__).parents[1] / "docs" / "assets"
    dashboard: Any = parse_yaml((docs / "example-dashboard.yaml").read_text(encoding="utf-8"))

    def cards(node: Any) -> Any:
        if isinstance(node, dict):
            if node.get("type") == "markdown":
                yield node["content"]
            for value in node.values():
                yield from cards(value)
        elif isinstance(node, list):
            for item in node:
                yield from cards(item)

    contents = list(cards(dashboard))
    for template in sorted((docs / "cards").glob("*.jinja")):
        assert template.read_text(encoding="utf-8") in contents, template.name


async def test_clients_by_band_and_cable(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry(), make_entry("ap"))
    for kind in ("router", "ap"):
        serial = SERIALS[kind]
        counts = {
            key: int(_state(hass, f"{serial}_{key}").state)
            for key in ("clients", "wifi_clients_2_4ghz", "wifi_clients_5ghz", "wired_clients")
        }
        assert counts["wifi_clients_2_4ghz"] + counts["wifi_clients_5ghz"] > 0, kind
        # Every online client is on one band or on a cable.
        parts = (
            counts["wifi_clients_2_4ghz"] + counts["wifi_clients_5ghz"] + counts["wired_clients"]
        )
        assert parts == counts["clients"], kind
