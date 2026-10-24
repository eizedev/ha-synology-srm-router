"""Device trackers: whether a client is home, and which router or access point it uses."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiosynologysrm import helpers
from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONSIDER_HOME,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    DEFAULT_CONSIDER_HOME,
    DOMAIN,
    LOCATION_GRACE,
)
from .coordinator import SIGNAL_LOCATIONS, LocationHub, SrmConfigEntry, get_hub

PARALLEL_UPDATES = 0


def chosen(entry: SrmConfigEntry, mac: str) -> bool:
    """Whether the user picked this client by name."""
    tracked: list[str] = entry.options.get(CONF_TRACKED, [])
    return mac in tracked


@callback
def remove_unwanted(hass: HomeAssistant, entry: SrmConfigEntry) -> None:
    """Delete this entry's trackers for clients that are no longer picked.

    With "all", nothing is deleted: whether a client is covered depends on data that may not be
    there yet, and a deleted entity loses its name, area and history.
    """
    if entry.options.get(CONF_TRACK_ALL, False) and get_hub(hass).keeps_trackers(entry):
        return
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == Platform.DEVICE_TRACKER and not (
            chosen(entry, item.unique_id) and get_hub(hass).keeps_trackers(entry)
        ):
            registry.async_remove(item.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add trackers for the clients this entry owns, now and when new ones appear."""
    hub = get_hub(hass)
    registry = er.async_get(hass)
    remove_unwanted(hass, entry)
    added: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for mac in hub.locations:
            if mac in added or hub.owner(mac) != entry.entry_id:
                continue
            entity_id = registry.async_get_entity_id(Platform.DEVICE_TRACKER, DOMAIN, mac)
            existing = registry.async_get(entity_id) if entity_id else None
            if existing is not None and existing.config_entry_id != entry.entry_id:
                continue  # another entry already has this client's tracker
            new.append(mac)
        if new:
            added.update(new)
            async_add_entities(SrmTracker(hub, entry, mac) for mac in new)

    _add_new()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_LOCATIONS, _add_new))


class SrmTracker(ScannerEntity):
    """One client, located across every router and access point of this integration.

    A location from a device's own Wi-Fi list is always taken. Any other location is taken too,
    except while the device the client was last on cannot be read: then the tracker keeps the
    last location for LOCATION_GRACE, so a client of an unreachable access point does not jump
    to the router or appear away. A client counts as away only after it was missing for the
    entry's "consider home" time, because SRM marks idle wired clients offline now and then.
    """

    _attr_should_poll = False

    def __init__(self, hub: LocationHub, entry: SrmConfigEntry, mac: str) -> None:
        """Track one MAC address."""
        self._hub = hub
        self._attr_mac_address = mac
        self._location: helpers.ClientLocation | None = None
        self._shown: helpers.ClientLocation | None = None
        self._held_since: datetime | None = None
        self._missing_since: datetime | None = None
        self._connected = False
        self._consider_home = timedelta(
            seconds=entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.seconds)
        )
        self._picked = hub.wants(entry, mac)
        self._update_from_hub()

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Clients the user chose (by name or with "all") are enabled."""
        return self._picked

    @property
    def available(self) -> bool:
        """Unknown while no router or access point delivers client data."""
        return self._hub.anything_available

    async def async_added_to_hass(self) -> None:
        """Follow the shared locations."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_LOCATIONS, self._locations_changed)
        )

    @callback
    def _locations_changed(self) -> None:
        self._update_from_hub()
        self.async_write_ha_state()

    @callback
    def _update_from_hub(self) -> None:
        mac = self._attr_mac_address or ""
        location = self._hub.locations.get(mac)
        previous = self._location
        hold = (
            previous is not None
            and previous.source is not None
            and previous.source in self._hub.missing
            and (location is None or location.basis != "wifi_list")
        )
        now = dt_util.utcnow()
        if hold:
            self._held_since = self._held_since or now
            if now - self._held_since < LOCATION_GRACE:
                return
        self._held_since = None
        self._location = location
        if location is not None and location.online:
            self._connected, self._missing_since, self._shown = True, None, location
        elif self._connected:
            self._missing_since = self._missing_since or now
            self._connected = now - self._missing_since < self._consider_home
        entry = location.entry if location else None
        if entry is not None:
            self._attr_hostname = entry.hostname
            self._attr_ip_address = entry.ip_addr
        self._attr_name = self._hub.name(mac) or (entry.hostname if entry else None) or mac

    @property
    def is_connected(self) -> bool:
        """Whether the client is on the network (or was, until "consider home" ran out)."""
        return self._connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which device, connection and radio the client uses."""
        loc = self._shown
        if not self._connected or loc is None:
            return {}
        return {
            "connected_to": self._hub.name_of(loc.source),
            "connection": loc.connection,
            "radio": loc.radio_type,
            "signal": loc.signal,
            "located_by": loc.basis,
            "ip6_address": self._hub.ip6(self._attr_mac_address or ""),
        }
