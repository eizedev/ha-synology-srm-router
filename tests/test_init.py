"""Setup, unload, error handling and the entities of a router and an access point."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
import json
from pathlib import Path
import tomllib
from typing import Any
from unittest.mock import patch

import aiohttp
from aiosynologysrm import (
    ExternalIp,
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmConnectionError,
    SrmPermissionError,
    SrmTwoFactorRequiredError,
    helpers,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.synology_srm_router import (
    async_remove_config_entry_device,
    create_client,
    session_name,
)
from custom_components.synology_srm_router.const import (
    BLOCKED_RETRY,
    DEFAULT_CONSIDER_HOME,
    DOMAIN,
    RECENTLY_SEEN,
)
from custom_components.synology_srm_router.coordinator import FastData, get_hub
from custom_components.synology_srm_router.device_tracker import SrmTracker
from custom_components.synology_srm_router.diagnostics import async_get_config_entry_diagnostics
from custom_components.synology_srm_router.entity import url_host
from custom_components.synology_srm_router.sensor import _public_ipv4

from .conftest import AP_HOST, ERRORS, ROUTER_HOST, UNSUPPORTED, FakeClient, load, make_entry

READS = (
    "get_utilization",
    "get_network_devices",
    "get_wifi_devices",
    "get_connection_status",
    "get_external_ip",
)


async def _setup(hass: HomeAssistant, *entries: object) -> None:
    for entry in entries:
        entry.add_to_hass(hass)  # type: ignore[attr-defined]
        await hass.config_entries.async_setup(entry.entry_id)  # type: ignore[attr-defined]
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant) -> None:
    """Run every fast coordinator once, as its timer would."""
    for entry in hass.config_entries.async_entries("synology_srm_router"):
        if entry.state is ConfigEntryState.LOADED:
            await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_router_entities(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor.router_192_0_2_1_cpu_load") == "35"
    assert float(_state(hass, "sensor.router_192_0_2_1_download_rate")) > 0
    assert _state(hass, "sensor.router_192_0_2_1_public_ipv4_address").count(".") == 3
    assert _state(hass, "binary_sensor.router_192_0_2_1_wan_connection") == "on"
    assert _state(hass, "binary_sensor.router_192_0_2_1_behind_nat") == "off"  # 192.0.2.x: other
    assert _state(hass, "sensor.router_192_0_2_1_wan_address_type") == "other"
    assert _state(hass, "sensor.router_192_0_2_1_last_boot") != "unknown"
    assert int(_state(hass, "sensor.router_192_0_2_1_clients")) > 0
    registry = er.async_get(hass)
    load_avg = registry.async_get("sensor.router_192_0_2_1_load_average_1_min")
    assert load_avg is not None
    assert load_avg.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state.value == ConfigEntryState.NOT_LOADED.value
    assert not FakeClient.instances[-1].logged_in


async def test_access_point_has_no_wan_entities(hass: HomeAssistant) -> None:
    await _setup(hass, make_entry("ap"))
    assert hass.states.get("binary_sensor.ap_192_0_2_2_wan_connection") is None
    assert hass.states.get("sensor.ap_192_0_2_2_public_ipv4_address") is None
    assert _state(hass, "sensor.ap_192_0_2_2_cpu_load") != "unknown"


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (SrmAuthenticationError(400, "SYNO.API.Auth"), ConfigEntryState.SETUP_ERROR),
        (SrmTwoFactorRequiredError(403, "SYNO.API.Auth"), ConfigEntryState.SETUP_ERROR),
        (SrmCertificateError("changed"), ConfigEntryState.SETUP_ERROR),
        (SrmConnectionError("down"), ConfigEntryState.SETUP_RETRY),
        (SrmBlockedError(407, "SYNO.API.Auth"), ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_errors(hass: HomeAssistant, error: Exception, state: ConfigEntryState) -> None:
    ERRORS[ROUTER_HOST] = {"login": error}
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is state
    if state is ConfigEntryState.SETUP_ERROR:
        assert any(
            flow["context"]["source"] == "reauth"
            for flow in hass.config_entries.flow.async_progress()
        )


async def test_unsupported_reads_are_skipped(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {"get_external_ip"}
    await _setup(hass, make_entry())
    assert hass.states.get("sensor.router_192_0_2_1_public_ipv4_address") is None
    assert _state(hass, "sensor.router_192_0_2_1_ipv6_address") != "unavailable"


async def test_one_failing_read_does_not_fail_the_update(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    FakeClient.instances[-1].errors["get_utilization"] = SrmConnectionError("x")
    await _refresh(hass)
    assert entry.runtime_data.fast.last_update_success
    assert _state(hass, "sensor.router_192_0_2_1_cpu_load") == "unknown"
    assert _state(hass, "binary_sensor.router_192_0_2_1_wan_connection") == "on"


async def test_all_reads_failing_makes_entities_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    client = FakeClient.instances[-1]
    for name in READS:
        client.errors[name] = SrmConnectionError("down")
    await _refresh(hass)
    assert _state(hass, "sensor.router_192_0_2_1_cpu_load") == "unavailable"


async def test_an_expired_password_starts_reauth(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    FakeClient.instances[-1].errors["get_network_devices"] = SrmAuthenticationError(
        400, "SYNO.API.Auth"
    )
    await _refresh(hass)
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_trackers_find_access_point_clients(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    router, ap = make_entry(track_all=True), make_entry("ap")
    await _setup(hass, router, ap)
    ap_wifi = load("ap", "wifi_devices")["device_list"]
    mac = ap_wifi[0]["mac_address"]
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", "synology_srm_router", mac)
    assert entity_id is not None
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(router.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "home"
    assert state.attributes["connected_to"] == ap.title
    assert state.attributes["located_by"] == "wifi_list"
    assert "ip6_address" in state.attributes
    assert state.attributes["radio"] == ap_wifi[0]["radio_type"]

    # The access point goes away: its clients must not jump to the router.
    for client in FakeClient.instances:
        if client.host == AP_HOST:
            for name in ("get_utilization", "get_network_devices", "get_wifi_devices"):
                client.errors[name] = SrmConnectionError("down")
    await _refresh(hass)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["connected_to"] == ap.title


async def test_selected_trackers_are_enabled(hass: HomeAssistant) -> None:
    mac = load("router", "wifi_devices")["device_list"][0]["mac_address"]
    await _setup(hass, make_entry(tracked=[mac]))
    entity_id = er.async_get(hass).async_get_entity_id("device_tracker", "synology_srm_router", mac)
    assert entity_id is not None
    assert _state(hass, entity_id) == "home"


async def test_diagnostics_hold_no_secrets(hass: HomeAssistant) -> None:
    entry = make_entry(tracked=["02:00:00:00:00:01"])
    await _setup(hass, entry)
    report = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(report)
    for secret in ("secret", ROUTER_HOST, "02:00:00:00:00:01", "homeassistant"):
        assert secret not in text
    assert report["entry"]["options"]["tracked"] == 1
    assert report["device"] == {"library": "test"}


async def test_setup_failures_end_the_session(hass: HomeAssistant) -> None:
    ERRORS[ROUTER_HOST] = {"get_topology": SrmConnectionError("x")}
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not FakeClient.instances[-1].logged_in
    ERRORS[ROUTER_HOST] = {name: SrmConnectionError("x") for name in READS}
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not FakeClient.instances[-1].logged_in


async def test_setup_remembers_whether_it_is_a_router(hass: HomeAssistant) -> None:
    entry = make_entry("ap")
    data = dict(entry.data)
    data["is_router"] = True  # stored wrongly, e.g. the device was switched to AP mode
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=entry.title,
        unique_id=entry.unique_id,
        data=data,
        options=entry.options,
    )
    await _setup(hass, entry)
    assert entry.data["is_router"] is False


async def test_blocked_device_retries_and_reports_a_repair(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    client = FakeClient.instances[-1]
    client.errors["get_network_devices"] = SrmBlockedError(407, "SYNO.API.Auth")
    await _refresh(hass)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is not None
    await _refresh(hass)  # still blocked: no login attempt before BLOCKED_RETRY
    client.errors["login"] = SrmBlockedError(407, "SYNO.API.Auth")
    freezer.tick(BLOCKED_RETRY)
    await _refresh(hass)  # the retry is refused as well
    assert not entry.runtime_data.fast.last_update_success
    client.errors.clear()
    freezer.tick(BLOCKED_RETRY)
    await _refresh(hass)
    assert entry.runtime_data.fast.last_update_success
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is None


async def test_a_block_in_the_first_update_waits_like_one_at_login(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    ERRORS[ROUTER_HOST] = {"get_system_info": SrmBlockedError(407, "SYNO.API.Auth")}
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is not None
    ERRORS.clear()
    clients = len(FakeClient.instances)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY  # no new login before BLOCKED_RETRY
    assert len(FakeClient.instances) == clients
    freezer.tick(BLOCKED_RETRY)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED  # type: ignore[comparison-overlap]


async def test_missing_admin_rights_start_reauth(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    FakeClient.instances[-1].errors["get_network_devices"] = SrmPermissionError(105, "x")
    await _refresh(hass)
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_trackers_belong_to_the_router_whatever_loads_first(hass: HomeAssistant) -> None:
    router, ap = make_entry(track_all=True), make_entry("ap", track_all=True)
    ERRORS[ROUTER_HOST] = {"login": SrmConnectionError("down")}  # the router starts late
    await _setup(hass, router, ap)
    assert router.state is ConfigEntryState.SETUP_RETRY
    assert ap.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, ap.entry_id)
        if e.domain == "device_tracker"
    ]
    ERRORS.clear()
    await hass.config_entries.async_reload(router.entry_id)
    await hass.async_block_till_done()
    trackers = [
        e
        for e in er.async_entries_for_config_entry(registry, router.entry_id)
        if e.domain == "device_tracker"
    ]
    assert trackers
    assert all(e.disabled_by is None for e in trackers)  # "all" counts as chosen


async def test_two_routers_split_their_clients(hass: HomeAssistant) -> None:
    first = make_entry(track_all=True)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="second",
        unique_id="ROUTER0003",
        data={**first.data, "host": "192.0.2.3"},
        options=first.options,
    )
    await _setup(hass, first, second)
    hub = get_hub(hass)
    mac = next(iter(hub.locations))
    owner = hub.owner(mac)
    assert owner in (first.entry_id, second.entry_id)
    assert hub.owner("02:00:00:00:00:99") is None  # nobody knows it


async def test_a_tracker_of_another_entry_is_not_duplicated(hass: HomeAssistant) -> None:
    mac = load("router", "wifi_devices")["device_list"][0]["mac_address"]
    other = MockConfigEntry(domain=DOMAIN, unique_id="OTHER")
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("device_tracker", DOMAIN, mac, config_entry=other)
    entry = make_entry(tracked=[mac])
    await _setup(hass, entry)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, mac) is not None
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "device_tracker"
    ]


async def test_a_tracker_of_a_forgotten_client_comes_back_away(hass: HomeAssistant) -> None:
    # SRM no longer lists the client, so "track all" does not cover it: the tracker stays.
    entry = make_entry(track_all=True)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        DOMAIN,
        "02:00:00:00:00:77",
        config_entry=entry,
        suggested_object_id="old_laptop",
        original_name="Old laptop",
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("device_tracker.old_laptop")
    assert state is not None
    assert state.state == "not_home"
    assert state.attributes["friendly_name"] == "Old laptop"


async def test_unchosen_trackers_are_removed(hass: HomeAssistant) -> None:
    mac = load("router", "wifi_devices")["device_list"][0]["mac_address"]
    entry = make_entry(tracked=[mac])
    await _setup(hass, entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, mac) is not None
    hass.config_entries.async_update_entry(entry, options={**entry.options, "tracked": []})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("device_tracker", DOMAIN, mac) is None


async def test_firmware_updates_reach_the_device_registry(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    original = FakeClient.get_system_info

    async def updated(self: FakeClient) -> Any:
        return dataclasses.replace(await original(self), firmware_ver="SRM 9.9")

    with patch.object(FakeClient, "get_system_info", updated):
        await entry.runtime_data.slow.async_refresh()
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.unique_id or ""), entry.entry_id
    )
    assert device is not None
    assert device.sw_version == "SRM 9.9"


async def test_only_client_devices_can_be_removed(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    registry = dr.async_get(hass)
    own = registry.async_get_device_by_identifier((DOMAIN, entry.unique_id or ""), entry.entry_id)
    assert own is not None
    assert not await async_remove_config_entry_device(hass, entry, own)
    client = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "02:00:00:00:00:01")},
    )
    assert await async_remove_config_entry_device(hass, entry, client)


def test_ipv6_hosts_get_brackets_in_urls() -> None:
    assert url_host("2001:db8::1") == "[2001:db8::1]"
    assert url_host("192.0.2.1") == "192.0.2.1"
    assert url_host("router.example") == "router.example"


def test_public_ipv4_prefers_the_main_connection() -> None:
    entries = ExternalIp.list_from_api(
        [{"ip": "198.51.100.1", "type": "PPPoE"}, {"ip": "203.0.113.1", "type": "WAN"}]
    )
    assert _public_ipv4(FastData(external_ip=entries)) == "203.0.113.1"


def test_manifest_requirement_matches_the_lock() -> None:
    root = Path(__file__).parent.parent
    manifest = json.loads(
        (root / "custom_components" / DOMAIN / "manifest.json").read_text(encoding="utf-8")
    )
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"]: p["version"] for p in lock["package"]}
    for requirement in manifest["requirements"]:
        name, version = requirement.split("==")
        assert locked[name] == version, requirement


async def test_dhcp_read_failures_keep_what_is_known(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    slow = entry.runtime_data.slow
    known = slow.data.dhcp
    assert known
    client = FakeClient.instances[-1]
    client.errors["get_dhcp_clients"] = SrmConnectionError("x")
    client.errors["get_dhcp_reservations"] = SrmConnectionError("x")
    await slow.async_refresh()
    assert slow.last_update_success
    assert slow.data.dhcp == known


async def test_last_seen_survives_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage["synology_srm_router.last_seen"] = {
        "version": 1,
        "key": "synology_srm_router.last_seen",
        "data": {
            "02:00:00:00:00:77": (dt_util.utcnow() - timedelta(days=1)).isoformat(),
            "02:00:00:00:00:78": "nonsense",
            "02:00:00:00:00:79": (dt_util.utcnow() - RECENTLY_SEEN - timedelta(days=1)).isoformat(),
        },
    }
    await _setup(hass, make_entry())
    hub = get_hub(hass)
    assert "02:00:00:00:00:77" in hub.last_seen
    assert "02:00:00:00:00:78" not in hub.last_seen
    assert "02:00:00:00:00:79" not in hub.last_seen  # too old to matter, forgotten


async def test_a_blocked_login_at_setup_reports_a_repair(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    ERRORS[ROUTER_HOST] = {"login": SrmBlockedError(407, "SYNO.API.Auth")}
    entry = make_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is not None
    ERRORS.clear()
    # Home Assistant retries within seconds; no login before BLOCKED_RETRY has passed.
    clients = len(FakeClient.instances)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(FakeClient.instances) == clients
    freezer.tick(BLOCKED_RETRY)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED  # type: ignore[comparison-overlap]
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is None


async def test_unloading_removes_the_block_repair(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    FakeClient.instances[-1].errors["get_network_devices"] = SrmBlockedError(407, "a")
    await _refresh(hass)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is not None
    await hass.config_entries.async_unload(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, f"blocked_{entry.entry_id}") is None


async def test_the_client_pins_the_certificate_and_names_the_session(
    hass: HomeAssistant,
) -> None:
    entry = make_entry()
    name = await session_name(hass)
    assert name.startswith("HomeAssistant-")
    assert len(name) == len("HomeAssistant-") + 8
    assert await session_name(hass, "setup") == f"{name}-setup"
    with patch("custom_components.synology_srm_router.SrmClient") as client:
        create_client(hass, dict(entry.data), name)
        kwargs = client.call_args.kwargs
        assert kwargs["session_name"] == name
        assert isinstance(kwargs["ssl"], aiohttp.Fingerprint)
        assert kwargs["ssl"].fingerprint == bytes.fromhex(entry.data["fingerprint"])
        create_client(hass, {**entry.data, "fingerprint": None, "verify_certificate": False}, name)
        assert client.call_args.kwargs["ssl"] is False  # chosen: no certificate check
        with pytest.raises(SrmCertificateError):  # pinned, but the fingerprint is gone
            create_client(hass, {**entry.data, "fingerprint": None}, name)
        create_client(hass, {**entry.data, "use_https": False}, name)
        assert client.call_args.kwargs["ssl"] is False


async def test_a_client_that_was_home_waits_for_consider_home_after_a_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    # A wired client SRM shows offline at the first update after the restart.
    device = next(
        d for d in load("router", "network_devices")["devices"] if d.get("is_online") is False
    )
    mac = helpers.normalize_mac(device["mac"])
    assert mac is not None
    entry = make_entry(tracked=[mac])
    entry.add_to_hass(hass)
    entity_id = "device_tracker.restored_client"
    er.async_get(hass).async_get_or_create(
        "device_tracker", DOMAIN, mac, config_entry=entry, suggested_object_id="restored_client"
    )
    mock_restore_cache(hass, [State(entity_id, "home")])
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, entity_id) == "home"
    assert "signal" in SrmTracker._unrecorded_attributes
    freezer.tick(timedelta(seconds=DEFAULT_CONSIDER_HOME.seconds + 1))
    await _refresh(hass)
    assert _state(hass, entity_id) == "not_home"


async def test_last_seen_is_deleted_with_the_last_entry(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    router, ap = make_entry(), make_entry("ap")
    await _setup(hass, router, ap)
    hub = get_hub(hass)
    hub.last_seen["02:00:00:00:00:77"] = dt_util.utcnow()
    store = hub._store
    assert store is not None
    store.async_delay_save(lambda: {"02:00:00:00:00:77": "x"})
    await hass.config_entries.async_remove(ap.entry_id)
    assert hub.last_seen  # the router is still there
    await hass.config_entries.async_remove(router.entry_id)
    await hass.async_block_till_done()
    assert hub.last_seen == {}
    assert "synology_srm_router.last_seen" not in hass_storage
