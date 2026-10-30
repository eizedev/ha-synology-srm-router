"""Wi-Fi events of one device: a fixed channel changed, a Wi-Fi network was switched off or on."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SlowData, SrmConfigEntry, SrmSlowCoordinator
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Wi-Fi events entity of a device that offers its Wi-Fi settings."""
    runtime = entry.runtime_data
    if any(read in runtime.supported for read in WIFI_READS):
        async_add_entities([SrmWifiEvents(entry, runtime.slow)])


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
