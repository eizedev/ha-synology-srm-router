"""Sensors: load, memory, traffic, uptime, clients and WAN addresses of an SRM device."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

from aiosynologysrm import helpers
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfDataRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import (
    SIGNAL_LOCATIONS,
    FastData,
    SlowData,
    SrmConfigEntry,
    SrmFastCoordinator,
    SrmSlowCoordinator,
    get_hub,
)
from .entity import SrmEntity

# Coordinators poll; entities never call the router themselves.
PARALLEL_UPDATES = 0


def _total(data: FastData, direction: str) -> int | None:
    if data.utilization is None:
        return None
    total = next((n for n in data.utilization.network if n.device == "total"), None)
    return getattr(total, direction) if total else None


def _load(data: FastData, attribute: str) -> float | None:
    cpu = data.utilization.cpu if data.utilization else None
    value = getattr(cpu, attribute) if cpu else None
    return None if value is None else value / 100  # SRM reports the load average times 100


def _public_ipv4(data: FastData) -> str | None:
    # The entry of the main connection, else the first one SRM lists.
    entries = sorted(data.external_ip, key=lambda e: e.type != "WAN")
    return entries[0].ip if entries else None


@dataclass(frozen=True, kw_only=True)
class SrmFastSensorDescription(SensorEntityDescription):
    """A sensor fed by the fast coordinator."""

    value_fn: Callable[[FastData], Any]
    requires: str
    """The client read the value comes from; without it, the sensor is not created."""
    router_only: bool = False


@dataclass(frozen=True, kw_only=True)
class SrmSlowSensorDescription(SensorEntityDescription):
    """A sensor fed by the slow coordinator."""

    value_fn: Callable[[SlowData], Any]


FAST_SENSORS: tuple[SrmFastSensorDescription, ...] = (
    SrmFastSensorDescription(
        key="cpu_load",
        requires="get_utilization",
        translation_key="cpu_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: helpers.cpu_total_percent(d.utilization.cpu if d.utilization else None),
    ),
    SrmFastSensorDescription(
        key="memory_usage",
        requires="get_utilization",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (
            d.utilization.memory.real_usage if d.utilization and d.utilization.memory else None
        ),
    ),
    *(
        SrmFastSensorDescription(
            key=f"load_{period}",
            requires="get_utilization",
            translation_key=f"load_{period}",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=partial(_load, attribute=f"load_{period}"),
        )
        for period in ("1min", "5min", "15min")
    ),
    SrmFastSensorDescription(
        key="download_rate",
        requires="get_utilization",
        translation_key="download_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _total(d, "rx"),
    ),
    SrmFastSensorDescription(
        key="upload_rate",
        requires="get_utilization",
        translation_key="upload_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _total(d, "tx"),
    ),
    SrmFastSensorDescription(
        key="public_ipv4",
        requires="get_external_ip",
        translation_key="public_ipv4",
        router_only=True,
        value_fn=_public_ipv4,
    ),
    SrmFastSensorDescription(
        key="ipv6_address",
        requires="get_connection_status",
        translation_key="ipv6_address",
        router_only=True,
        value_fn=lambda d: d.connection.ipv6.ip if d.connection and d.connection.ipv6 else None,
    ),
    SrmFastSensorDescription(
        key="wan_ipv4",
        requires="get_connection_status",
        translation_key="wan_ipv4",
        router_only=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.connection.ipv4.ip if d.connection and d.connection.ipv4 else None,
    ),
    SrmFastSensorDescription(
        key="wan_address_type",
        requires="get_connection_status",
        translation_key="wan_address_type",
        router_only=True,
        device_class=SensorDeviceClass.ENUM,
        options=["public", "private", "cgnat", "link_local", "other"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: helpers.address_scope(
            d.connection.ipv4.ip if d.connection and d.connection.ipv4 else None
        ),
    ),
)

SLOW_SENSORS: tuple[SrmSlowSensorDescription, ...] = (
    SrmSlowSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.boot_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of one SRM device."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        SrmFastSensor(entry, runtime.fast, description)
        for description in FAST_SENSORS
        if description.requires in runtime.supported
        and (runtime.is_router or not description.router_only)
    ]
    entities += [SrmSlowSensor(entry, runtime.slow, d) for d in SLOW_SENSORS]
    entities.append(SrmClientsSensor(entry))
    async_add_entities(entities)


class SrmFastSensor(SrmEntity[SrmFastCoordinator], SensorEntity):
    """A sensor computed from the fast coordinator's data."""

    entity_description: SrmFastSensorDescription

    @property
    def native_value(self) -> Any:
        """The current value."""
        return self.entity_description.value_fn(self.coordinator.data)


class SrmSlowSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """A sensor computed from the slow coordinator's data."""

    entity_description: SrmSlowSensorDescription

    @property
    def native_value(self) -> datetime | None:
        """The current value."""
        value: datetime | None = self.entity_description.value_fn(self.coordinator.data)
        return value


class SrmClientsSensor(SrmEntity[SrmFastCoordinator], SensorEntity):
    """How many clients are attached to this device, by Wi-Fi or cable, across all entries."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: SrmConfigEntry) -> None:
        """Count from the shared client locations."""
        super().__init__(
            entry,
            entry.runtime_data.fast,
            SensorEntityDescription(key="clients", translation_key="clients"),
        )
        self._entry_id = entry.entry_id

    async def async_added_to_hass(self) -> None:
        """Also update when another device's data changes the locations."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_LOCATIONS, self._locations_changed)
        )

    @callback
    def _locations_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Online clients whose location is this device."""
        locations = get_hub(self.hass).locations.values()
        return sum(1 for loc in locations if loc.online and loc.source == self._entry_id)
