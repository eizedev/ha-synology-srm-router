"""Base entity: one device in Home Assistant per SRM router or access point."""

from __future__ import annotations

import ipaddress
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import CONF_USE_HTTPS
from .coordinator import SrmConfigEntry, device_identifier


def url_host(host: str) -> str:
    """Return a host as it goes into a URL: IPv6 addresses in brackets."""
    try:
        return f"[{host}]" if ipaddress.ip_address(host).version == 6 else host  # noqa: PLR2004
    except ValueError:
        return host


def device_info(entry: SrmConfigEntry) -> DeviceInfo:
    """Describe the SRM device of an entry for the device registry."""
    system = entry.runtime_data.slow.data.system
    scheme = "https" if entry.data[CONF_USE_HTTPS] else "http"
    return DeviceInfo(
        identifiers={device_identifier(entry)},
        manufacturer="Synology",
        model=system.model,
        name=entry.title,
        serial_number=system.serial,
        sw_version=system.firmware_ver,
        configuration_url=f"{scheme}://{url_host(entry.data[CONF_HOST])}:{entry.data[CONF_PORT]}",
    )


class SrmEntity[CoordinatorT: DataUpdateCoordinator[Any]](CoordinatorEntity[CoordinatorT]):
    """An entity that belongs to one SRM device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: SrmConfigEntry,
        coordinator: CoordinatorT,
        description: EntityDescription,
    ) -> None:
        """Bind the entity to its entry, coordinator and description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = device_info(entry)
