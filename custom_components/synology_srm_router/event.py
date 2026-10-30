"""Events of one device: Wi-Fi, new clients, and on routers IPv6 prefix and firewall changes."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.start import async_at_started

from .changes import (
    EVENT_FIREWALL_CHANGED,
    EVENT_PREFIX_CHANGED,
    Snapshot,
    changes,
    snapshot,
    store,
)
from .coordinator import (
    SIGNAL_NEW_CLIENT,
    SlowData,
    SrmConfigEntry,
    SrmFastCoordinator,
    SrmSlowCoordinator,
    get_hub,
    private_mac,
)
from .entity import SrmEntity
from .wifi import band_label, networks, radios

PARALLEL_UPDATES = 0
EVENT_CHANNEL_CHANGED = "channel_changed"
EVENT_NETWORK_OFF = "network_off"
EVENT_NETWORK_ON = "network_on"
DESCRIPTION = EventEntityDescription(
    key="wifi_events",
    translation_key="wifi_events",
    event_types=[EVENT_CHANNEL_CHANGED, EVENT_NETWORK_OFF, EVENT_NETWORK_ON],
)
WIFI_READS = ("get_wifi_radio_settings", "get_wifi_networks")
EVENT_NEW_CLIENT = "new_client"
CLIENT_DESCRIPTION = EventEntityDescription(
    key="client_events", translation_key="client_events", event_types=[EVENT_NEW_CLIENT]
)
ROUTER_DESCRIPTION = EventEntityDescription(
    key="router_events",
    translation_key="router_events",
    event_types=[EVENT_PREFIX_CHANGED, EVENT_FIREWALL_CHANGED],
)
ROUTER_READS = ("get_ipv6_prefixes", "get_firewall_rules")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the event entities the device offers: new clients, Wi-Fi, and router changes."""
    runtime = entry.runtime_data
    entities: list[EventEntity] = [SrmClientEvents(entry, runtime.fast)]
    if any(read in runtime.supported for read in WIFI_READS):
        entities.append(SrmWifiEvents(entry, runtime.slow))
    if runtime.is_router and any(read in runtime.supported for read in ROUTER_READS):
        entities.append(SrmRouterEvents(entry, runtime.slow))
    async_add_entities(entities)


def _channels(data: SlowData) -> dict[str, int]:
    """Return the channel in use of each radio set to a fixed channel in SRM."""
    return {
        band: state.channel
        for band, (setting, state) in radios(data).items()
        if setting.channel and state is not None and state.channel is not None
    }


def _networks_on(data: SlowData) -> dict[str, bool]:
    """Return whether each network is on per band, where SRM says."""
    return {key: on for key, (_, _, on) in networks(data).items() if on is not None}


class SrmWifiEvents(SrmEntity[SrmSlowCoordinator], EventEntity):
    """Fires when a fixed channel changes or a Wi-Fi network is switched off or on.

    A radio on automatic channel selection changes its channel by itself, which is not an
    event. A network switched off or on fires once, with all bands it concerns, since Smart
    Connect switches every band together. Nothing fires for the state at startup, and a read
    that fails keeps its last value, so it does not look like a change either.
    """

    _attr_should_poll = False

    def __init__(self, entry: SrmConfigEntry, coordinator: SrmSlowCoordinator) -> None:
        """Start from the current readings."""
        super().__init__(entry, coordinator, DESCRIPTION)
        self._channels = _channels(coordinator.data)
        self._on = _networks_on(coordinator.data)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Compare channels and networks with the previous reading."""
        data = self.coordinator.data
        channels = _channels(data)
        for band, channel in channels.items():
            previous = self._channels.get(band)
            if previous is not None and channel != previous:
                self._fire(
                    EVENT_CHANNEL_CHANGED,
                    {"band": band_label(band), "channel": channel, "previous": previous},
                )
        self._channels = channels
        changed: dict[tuple[str, bool], list[str]] = {}
        names: dict[str, str] = {}
        for key, (profile, band, on) in networks(data).items():
            if on is None:
                continue
            previous_on = self._on.get(key)
            if previous_on is not None and on != previous_on:
                network = str(profile.id)
                names[network] = profile.name or profile.network_type or network
                changed.setdefault((network, on), []).append(band_label(band))
        for (network, on), bands in changed.items():
            self._fire(
                EVENT_NETWORK_ON if on else EVENT_NETWORK_OFF,
                {"network": names[network], "bands": bands},
            )
        self._on = _networks_on(data)
        super()._handle_coordinator_update()

    @callback
    def _fire(self, event_type: str, attributes: dict[str, object]) -> None:
        """Fire and write the state at once, so two events in one update are both seen."""
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()


class SrmClientEvents(SrmEntity[SrmFastCoordinator], EventEntity):
    """Fires when a client is online for the first time, on the device it is attached to.

    A client counts as new once ever: its address is remembered across restarts (a private,
    random address for 30 days after it was last seen). Clients present at the integration's
    first start, and clients that appear while a device's list is missing, are taken in quietly.
    ``private_mac`` tells a phone or laptop with a random address, which may come back new.
    """

    _attr_should_poll = False
    # Names stay in the history; addresses do not.
    _unrecorded_attributes = frozenset({"mac", "ip"})

    def __init__(self, entry: SrmConfigEntry, coordinator: SrmFastCoordinator) -> None:
        """Bind the entity to its device."""
        super().__init__(entry, coordinator, CLIENT_DESCRIPTION)
        self._entry_id = entry.entry_id

    async def async_added_to_hass(self) -> None:
        """Listen for new clients."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NEW_CLIENT, self._new_client)
        )

    @callback
    def _new_client(self, source: str, mac: str) -> None:
        if source != self._entry_id:
            return
        hub = get_hub(self.hass)
        location = hub.locations.get(mac)
        radio = location.radio_type if location else None
        self._trigger_event(
            EVENT_NEW_CLIENT,
            {
                "name": hub.name(mac) or mac,
                "mac": mac,
                "ip": hub.ip(mac),
                "connection": location.connection if location else None,
                "band": band_label(radio) if radio else None,
                "private_mac": private_mac(mac),
            },
        )
        self.async_write_ha_state()


class SrmRouterEvents(SrmEntity[SrmSlowCoordinator], EventEntity):
    """Fires when a delegated IPv6 prefix or the firewall changes, at most once per kind and read.

    What was last seen is stored, so a change made while Home Assistant was not running fires
    once it has started (when automations listen). The very first start only takes in the
    current state, and a read that fails keeps the last values, so neither looks like a change.
    """

    _attr_should_poll = False

    def __init__(self, entry: SrmConfigEntry, coordinator: SrmSlowCoordinator) -> None:
        """Bind the entity to its router."""
        super().__init__(entry, coordinator, ROUTER_DESCRIPTION)
        self._store = store(coordinator.hass, entry.entry_id)
        self._seen: Snapshot | None = None
        self._started = False

    async def async_added_to_hass(self) -> None:
        """Read what was last seen, and compare once Home Assistant has started."""
        await super().async_added_to_hass()
        self._seen = await self._store.async_load()
        self.async_on_remove(async_at_started(self.hass, self._at_started))

    @callback
    def _at_started(self, _: HomeAssistant) -> None:
        self._started = True
        self._compare()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Compare with what was last seen."""
        if self._started:
            self._compare()
        super()._handle_coordinator_update()

    @callback
    def _compare(self) -> None:
        current = snapshot(self.coordinator.data, self._seen)
        if self._seen is not None:
            for event_type, attributes in changes(self._seen, current):
                self._trigger_event(event_type, attributes)
                self.async_write_ha_state()
        if current != self._seen:
            self._seen = current
            self._store.async_delay_save(lambda: current, 1)
