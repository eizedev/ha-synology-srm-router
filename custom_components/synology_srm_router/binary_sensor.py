"""Binary sensors: WAN connection, behind NAT, Wi-Fi networks on or off, Ethernet port links."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiosynologysrm import WifiNetworkProfile, WifiNetworkRadio, helpers
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FastData, SrmConfigEntry, SrmFastCoordinator, SrmSlowCoordinator
from .entity import SrmEntity
from .ports import own_ports, port_label
from .wifi import band_label, networks

PARALLEL_UPDATES = 0


def _wan_ipv4(data: FastData) -> str | None:
    return data.connection.ipv4.ip if data.connection and data.connection.ipv4 else None


@dataclass(frozen=True, kw_only=True)
class SrmBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor fed by the fast coordinator; all of them are router only."""

    value_fn: Callable[[FastData], bool | None]


BINARY_SENSORS: tuple[SrmBinarySensorDescription, ...] = (
    SrmBinarySensorDescription(
        key="wan_connected",
        translation_key="wan_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: (
            None
            if not d.connection or not d.connection.ipv4
            else d.connection.ipv4.conn_status == "normal"
        ),
    ),
    SrmBinarySensorDescription(
        key="behind_nat",
        translation_key="behind_nat",
        entity_category=EntityCategory.DIAGNOSTIC,
        # private: another router in front; cgnat: the provider's carrier-grade NAT. Either way,
        # nothing on the internet reaches this router over IPv4 directly (port forwards).
        value_fn=lambda d: (
            None
            if (scope := helpers.address_scope(_wan_ipv4(d))) is None
            else scope in ("private", "cgnat")
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the WAN binary sensors (access points have no WAN of their own) and Wi-Fi networks."""
    runtime = entry.runtime_data
    if runtime.is_router and "get_connection_status" in runtime.supported:
        async_add_entities(SrmBinarySensor(entry, runtime.fast, d) for d in BINARY_SENSORS)
    _add_networks(entry, async_add_entities)
    _add_ports(entry, async_add_entities)


@callback
def _add_ports(entry: SrmConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Add a link sensor for every Ethernet port of the device, as they appear."""
    fast = entry.runtime_data.fast
    added: set[str] = set()

    @callback
    def _update() -> None:
        new = [SrmPortLinkSensor(entry, port) for port in own_ports(fast.data) if port not in added]
        if new:
            added.update(sensor.port for sensor in new)
            async_add_entities(new)

    _update()
    entry.async_on_unload(fast.async_add_listener(_update))


@callback
def _add_networks(
    entry: SrmConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add a binary sensor for every Wi-Fi network on every band, as they appear.

    A network or band that is gone leaves its sensor unavailable, since it may come back.
    """
    slow = entry.runtime_data.slow
    added: set[str] = set()

    @callback
    def _update() -> None:
        new = [
            SrmWifiNetworkSensor(entry, key, profile, band)
            for key, (profile, band, _) in networks(slow.data).items()
            if key not in added
        ]
        if new:
            added.update(sensor.network_key for sensor in new)
            async_add_entities(new)

    _update()
    entry.async_on_unload(slow.async_add_listener(_update))


class SrmBinarySensor(SrmEntity[SrmFastCoordinator], BinarySensorEntity):
    """A binary sensor computed from the fast coordinator's data."""

    entity_description: SrmBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """The current state."""
        return self.entity_description.value_fn(self.coordinator.data)


class SrmWifiNetworkSensor(SrmEntity[SrmSlowCoordinator], BinarySensorEntity):
    """Whether one Wi-Fi network is on on one band, as set in SRM."""

    # The SSID is not a secret, but the history does not need it.
    _unrecorded_attributes = frozenset({"ssid"})

    def __init__(
        self, entry: SrmConfigEntry, key: str, profile: WifiNetworkProfile, band: str
    ) -> None:
        """Bind the sensor to one network and band; named after the network as in SRM."""
        super().__init__(
            entry,
            entry.runtime_data.slow,
            BinarySensorEntityDescription(
                key=f"wifi_network_{key}", translation_key="wifi_network"
            ),
        )
        self.network_key = key
        self._attr_translation_placeholders = {
            "network": profile.name or profile.network_type or str(profile.id),
            "band": band_label(band),
        }

    @property
    def _network(self) -> tuple[WifiNetworkProfile, str, bool | None] | None:
        return networks(self.coordinator.data).get(self.network_key)

    @property
    def available(self) -> bool:
        """Unavailable while the device does not list the network on this band."""
        return super().available and self._network is not None

    @property
    def is_on(self) -> bool | None:
        """Whether the network is on on this band."""
        network = self._network
        return network[2] if network else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """SSID and settings of the entry that decides: Smart Connect or the band's own."""
        network = self._network
        if network is None:
            return {}
        profile, band, _ = network
        wanted = helpers.SMART_CONNECT if profile.enable_smart_connect else band
        radio: WifiNetworkRadio | None = next(
            (r for r in profile.radio_list if r.radio_type == wanted), None
        )
        return {
            "ssid": radio.ssid if radio else None,
            "network_type": profile.network_type,
            "smart_connect": profile.enable_smart_connect,
            "hidden": radio.hide_ssid if radio else None,
        }


class SrmPortLinkSensor(SrmEntity[SrmFastCoordinator], BinarySensorEntity):
    """Whether an Ethernet port of the device has a link."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry: SrmConfigEntry, port: str) -> None:
        """Bind the sensor to one port, by SRM's name (``wp1``, ``lp1``)."""
        super().__init__(
            entry,
            entry.runtime_data.fast,
            BinarySensorEntityDescription(key=f"port_{port}_link", translation_key="port_link"),
        )
        self.port = port
        self._attr_translation_placeholders = {"port": port_label(port)}

    @property
    def available(self) -> bool:
        """Unavailable while the device does not list the port."""
        return super().available and self.port in own_ports(self.coordinator.data)

    @property
    def is_on(self) -> bool | None:
        """Whether the port has a link."""
        port = own_ports(self.coordinator.data).get(self.port)
        return port.has_link if port else None
