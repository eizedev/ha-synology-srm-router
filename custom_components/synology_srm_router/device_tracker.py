"""Device trackers: whether a client is home, and which router or access point it uses."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiosynologysrm import helpers
from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.components.person import persons_with_entity
from homeassistant.const import STATE_HOME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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
    there yet, and a deleted entity loses its name, area and history. Trackers "all" no longer
    covers are not provided at setup instead, so the user can delete them (see changed_by_user).
    """
    if entry.options.get(CONF_TRACK_ALL, False) and get_hub(hass).keeps_trackers(entry):
        return
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == Platform.DEVICE_TRACKER and not (
            chosen(entry, item.unique_id) and get_hub(hass).keeps_trackers(entry)
        ):
            registry.async_remove(item.entity_id)


@callback
def changed_by_user(hass: HomeAssistant, item: er.RegistryEntry) -> bool:
    """Whether the user changed a tracker or its device, so it stays provided.

    In doubt this says yes: a tracker kept by mistake only stays as it is. A changed entity ID
    alone does not count; there is no reliable way to tell it from a generated one. The device's
    name does not count either, since this integration writes it from SRM.
    """
    if (
        item.name
        or item.icon
        or item.area_id
        or item.labels
        or item.categories
        # [] or [COMPUTED_NAME], depending on when the entity was created, mean unchanged
        or any(isinstance(alias, str) for alias in item.aliases)
        or item.hidden_by is er.RegistryEntryHider.USER
        or persons_with_entity(hass, item.entity_id)
    ):
        return True
    device = dr.async_get(hass).async_get(item.device_id) if item.device_id else None
    return device is not None and bool(device.name_by_user or device.area_id or device.labels)


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

    # Trackers this entry created before come back even while their client is unknown, if they
    # are still wanted (chosen, or covered by "all") or the user changed them: away rather than
    # unavailable. The others are left in the registry: Home Assistant shows them unavailable and
    # lets the user delete them. They return through _add_new when their client is in a device
    # list again, otherwise at the next setup.
    devices = dr.async_get(hass)
    restored = {
        item.unique_id: _known_name(devices, item)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == Platform.DEVICE_TRACKER
        and (hub.wants(entry, item.unique_id) or changed_by_user(hass, item))
    }
    if restored:
        added.update(restored)
        async_add_entities(SrmTracker(hub, entry, mac, name) for mac, name in restored.items())
    _add_new()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_LOCATIONS, _add_new))


def _known_name(devices: dr.DeviceRegistry, item: er.RegistryEntry) -> str | None:
    """Return the last name of a tracker's client: its device's, or the entity's before 0.1.4."""
    device = devices.async_get(item.device_id) if item.device_id else None
    return (device.name if device else None) or item.original_name


class SrmTracker(ScannerEntity, RestoreEntity):
    """One client, located across every router and access point of this integration.

    A location from a device's own Wi-Fi list is always taken. Any other location is taken too,
    except while the device the client was last on cannot be read: then the tracker keeps the
    last location for LOCATION_GRACE, so a client of an unreachable access point does not jump
    to the router or appear away. A client counts as away only after it was missing for the
    entry's "consider home" time, because SRM marks idle wired clients offline now and then.
    A client that was home before Home Assistant restarted gets the same time to show up again.

    Each tracker is the main entity of a device of its own, named after the client in SRM.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    # The signal changes on almost every update; recording it would add a row to the database
    # for each tracker every few seconds.
    _unrecorded_attributes = frozenset({"signal"})

    def __init__(
        self, hub: LocationHub, entry: SrmConfigEntry, mac: str, name: str | None = None
    ) -> None:
        """Track one MAC address; the name is the last known one, for a client unknown now."""
        self._hub = hub
        self._attr_mac_address = mac
        self._client_name = name
        self._location: helpers.ClientLocation | None = None
        self._shown: helpers.ClientLocation | None = None
        self._held_since: datetime | None = None
        self._missing_since: datetime | None = None
        self._connected = False
        self._consider_home = timedelta(
            seconds=entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds())
        )
        self._picked = hub.wants(entry, mac)
        self._entry_id = entry.entry_id
        self._update_from_hub()

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Clients the user chose (by name or with "all") are enabled."""
        return self._picked

    @property
    def available(self) -> bool:
        """Unknown while no router or access point delivers client data."""
        return self._hub.anything_available

    @property  # type: ignore[misc]  # final in Home Assistant 2026.10
    def device_info(self) -> DeviceInfo:
        """The client as a device, named as in SRM.

        From Home Assistant 2026.11 a tracker provides its device. In 2026.10 the base class
        marks this property final, for type checkers only; a tracker with device info is then
        registered the usual way, instead of in a device of its own named after the host name.
        """
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self._attr_mac_address or "")},
            name=self._client_name,
        )

    async def async_added_to_hass(self) -> None:
        """Follow the shared locations."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if not self._connected and last is not None and last.state == STATE_HOME:
            # Missing from the first client list after a restart: away only after "consider home".
            self._connected, self._missing_since = True, dt_util.utcnow()
            self._update_from_hub()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_LOCATIONS, self._locations_changed)
        )
        self._name_device()

    @callback
    def _locations_changed(self) -> None:
        self._update_from_hub()
        self._name_device()
        self.async_write_ha_state()

    @callback
    def _name_device(self) -> None:
        """Rename the client's device when its name in SRM changes; a name set in HA stays."""
        device_id = self.registry_entry.device_id if self.registry_entry else None
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id) if device_id else None
        if (
            device is not None
            and device.config_entry_id == self._entry_id
            and device.name != self._client_name
        ):
            registry.async_update_device(device.id, name=self._client_name)

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
        self._attr_ip_address = (entry.ip_addr if entry else None) or self._hub.ip(mac)
        self._client_name = (
            self._hub.name(mac) or (entry.hostname if entry else None) or self._client_name or mac
        )

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
