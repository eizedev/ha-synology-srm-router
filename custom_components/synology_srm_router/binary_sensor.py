"""Binary sensors: WAN connection and whether the router sits behind NAT."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aiosynologysrm import helpers
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FastData, SrmConfigEntry, SrmFastCoordinator
from .entity import SrmEntity

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
    """Add the WAN binary sensors; access points have no WAN of their own."""
    runtime = entry.runtime_data
    if not runtime.is_router or "get_connection_status" not in runtime.supported:
        return
    async_add_entities(SrmBinarySensor(entry, entry.runtime_data.fast, d) for d in BINARY_SENSORS)


class SrmBinarySensor(SrmEntity[SrmFastCoordinator], BinarySensorEntity):
    """A binary sensor computed from the fast coordinator's data."""

    entity_description: SrmBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """The current state."""
        return self.entity_description.value_fn(self.coordinator.data)
