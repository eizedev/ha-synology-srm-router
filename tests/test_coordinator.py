"""Coordinator error mapping, boot time, ownership of trackers and edge cases."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from aiosynologysrm import (
    NetworkDevices,
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmConnectionError,
    SrmTwoFactorRequiredError,
    Utilization,
    WifiDevices,
    helpers,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.synology_srm_router.config_flow import client_options
from custom_components.synology_srm_router.const import LOCATION_GRACE
from custom_components.synology_srm_router.coordinator import (
    FastData,
    gather_partial,
    get_hub,
    map_error,
)
from custom_components.synology_srm_router.device_tracker import SrmTracker
from custom_components.synology_srm_router.sensor import _load, _total

from .conftest import ROUTER_HOST, UNSUPPORTED, FakeClient, make_entry


async def _setup(hass: HomeAssistant, *entries: Any) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("error", "kind", "key"),
    [
        (SrmTwoFactorRequiredError(403, "a"), ConfigEntryAuthFailed, "two_factor"),
        (SrmAuthenticationError(400, "a"), ConfigEntryAuthFailed, "invalid_auth"),
        (SrmCertificateError("x"), ConfigEntryAuthFailed, "certificate"),
        (SrmBlockedError(407, "a"), UpdateFailed, "blocked"),
        (SrmConnectionError("x"), UpdateFailed, "communication_error"),
    ],
)
def test_error_mapping(error: Exception, kind: type[Exception], key: str) -> None:
    mapped = map_error(error)  # type: ignore[arg-type]
    assert isinstance(mapped, kind)
    assert mapped.translation_key == key  # type: ignore[attr-defined]


async def test_unexpected_errors_are_not_swallowed() -> None:
    async def broken() -> None:
        raise RuntimeError("bug")

    async def fine() -> int:
        return 1

    with pytest.raises(RuntimeError):
        await gather_partial({"a": broken, "b": fine})


async def test_access_point_without_optional_reads(hass: HomeAssistant) -> None:
    UNSUPPORTED[ROUTER_HOST] = {
        "get_utilization",
        "get_wifi_devices",
        "get_connection_status",
    }
    entry = make_entry()
    await _setup(hass, entry)
    data = entry.runtime_data.fast.data
    assert data.utilization is None
    assert data.connection is None
    assert hass.states.get("sensor.router_192_0_2_1_cpu_load") is None
    assert hass.states.get("binary_sensor.router_192_0_2_1_wan_connection") is None
    assert int(hass.states.get("sensor.router_192_0_2_1_clients").state) > 0  # type: ignore[union-attr]


async def test_first_slow_update_needs_system_information(hass: HomeAssistant) -> None:
    async def no_system(self: FakeClient) -> Any:
        raise SrmConnectionError("x")

    with patch.object(FakeClient, "get_system_info", no_system):
        entry = make_entry()
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_boot_time_and_failing_system_information(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    slow = entry.runtime_data.slow
    boot = slow.data.boot_time
    assert boot is not None
    freezer.tick(timedelta(seconds=30))  # uptime in SRM stays the same: the boot moves by 30 s
    await slow.async_refresh()
    assert slow.data.boot_time == boot  # small drift is ignored
    FakeClient.instances[-1].errors["get_system_info"] = SrmConnectionError("x")
    await slow.async_refresh()
    assert not slow.last_update_success
    assert slow.data.system.model == "RT2600ac"  # the last data stays for the next update
    freezer.tick(timedelta(hours=2))  # a restart: the uptime would be small, the boot later
    FakeClient.instances[-1].errors.clear()
    await slow.async_refresh()
    assert slow.data.boot_time is not None
    assert slow.data.boot_time > boot


async def test_unknown_uptime_has_no_boot_time(hass: HomeAssistant) -> None:
    async def odd(self: FakeClient) -> Any:
        info = await original(self)
        return type(info).from_api({**info.raw, "up_time": "soon"})

    original = FakeClient.get_system_info
    with patch.object(FakeClient, "get_system_info", odd):
        entry = make_entry()
        await _setup(hass, entry)
        assert entry.runtime_data.slow.data.boot_time is None


async def test_owner_and_names(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    hub = get_hub(hass)
    assert hub.owner("aa:bb:cc:dd:ee:ff") == entry.entry_id  # a single router owns every client
    assert hub.name_of(None) is None
    assert hub.name_of(entry.entry_id) == entry.title


async def test_unload_failure_keeps_the_session(hass: HomeAssistant) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(entry.entry_id)
    assert FakeClient.instances[-1].logged_in


def test_sensor_helpers_without_data() -> None:
    assert _total(FastData(), "rx") is None
    assert _load(FastData(), "load_1min") is None
    util = Utilization.from_api({"cpu": {"1min_load": 57}})
    assert _load(FastData(utilization=util), "load_1min") == 0.57


def test_client_options_skip_odd_macs() -> None:
    devices = NetworkDevices.from_api(
        {
            "devices": [
                {"mac": "nope"},
                {"mac": "AA-BB-CC-DD-EE-01", "hostname": "x", "is_online": True},
            ]
        }
    )
    assert client_options(devices) == [
        {"value": "aa:bb:cc:dd:ee:01", "label": "x / aa:bb:cc:dd:ee:01"}
    ]
    assert client_options(None) == []


async def test_options_of_an_entry_that_is_not_loaded(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"


class _Hub:
    def __init__(self, locations: dict[str, helpers.ClientLocation]) -> None:
        self.locations = locations
        self.missing: frozenset[str] = frozenset()
        self.anything_available = True

    def name_of(self, entry_id: str | None) -> str | None:
        return entry_id


def _location(**changes: Any) -> helpers.ClientLocation:
    base: dict[str, Any] = {
        "mac": "aa:bb:cc:dd:ee:ff",
        "online": True,
        "source": "ap",
        "connection": "wifi",
        "basis": "wifi_list",
        "incomplete": False,
    }
    return helpers.ClientLocation(**{**base, **changes})


def test_tracker_without_location_and_offline() -> None:
    entry = make_entry(tracked=["aa:bb:cc:dd:ee:ff"])
    tracker = SrmTracker(_Hub({}), entry, "aa:bb:cc:dd:ee:ff")  # type: ignore[arg-type]
    assert not tracker.is_connected
    assert tracker.extra_state_attributes == {}
    hub = _Hub({"aa:bb:cc:dd:ee:ff": _location(online=False, source=None, basis="offline")})
    tracker = SrmTracker(hub, entry, "aa:bb:cc:dd:ee:ff")  # type: ignore[arg-type]
    assert not tracker.is_connected
    assert tracker.extra_state_attributes == {}


def test_tracker_holds_the_location_while_its_device_is_missing(
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = make_entry(tracked=["aa:bb:cc:dd:ee:ff"])
    hub = _Hub({"aa:bb:cc:dd:ee:ff": _location()})
    tracker = SrmTracker(hub, entry, "aa:bb:cc:dd:ee:ff")  # type: ignore[arg-type]
    hub.missing = frozenset({"ap"})  # the access point cannot be read
    hub.locations["aa:bb:cc:dd:ee:ff"] = _location(
        source="router", connection="ethernet", basis="device_list", incomplete=True
    )
    tracker._update_from_hub()
    assert tracker.extra_state_attributes["connected_to"] == "ap"
    freezer.tick(LOCATION_GRACE - timedelta(seconds=1))
    tracker._update_from_hub()
    assert tracker.extra_state_attributes["connected_to"] == "ap"
    freezer.tick(timedelta(seconds=2))
    tracker._update_from_hub()
    assert tracker.extra_state_attributes["connected_to"] == "router"


def test_tracker_leaves_home_after_the_grace_while_its_device_is_missing(
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = make_entry(tracked=["aa:bb:cc:dd:ee:ff"])
    hub = _Hub({"aa:bb:cc:dd:ee:ff": _location()})
    tracker = SrmTracker(hub, entry, "aa:bb:cc:dd:ee:ff")  # type: ignore[arg-type]
    hub.missing = frozenset({"ap"})
    del hub.locations["aa:bb:cc:dd:ee:ff"]
    tracker._update_from_hub()
    assert tracker.is_connected
    freezer.tick(LOCATION_GRACE)
    tracker._update_from_hub()
    assert not tracker.is_connected


def test_tracker_takes_a_wifi_location_at_once() -> None:
    entry = make_entry(tracked=["aa:bb:cc:dd:ee:ff"])
    hub = _Hub({"aa:bb:cc:dd:ee:ff": _location()})
    tracker = SrmTracker(hub, entry, "aa:bb:cc:dd:ee:ff")  # type: ignore[arg-type]
    hub.missing = frozenset({"ap"})
    hub.locations["aa:bb:cc:dd:ee:ff"] = _location(source="router")
    tracker._update_from_hub()
    assert tracker.extra_state_attributes["connected_to"] == "router"
    hub.anything_available = False
    assert not tracker.available


def test_views_of_an_unreachable_entry() -> None:
    located = helpers.locate_clients(
        [helpers.SourceView("r", NetworkDevices(), WifiDevices()), helpers.SourceView("ap", None)]
    )
    assert located == {}
