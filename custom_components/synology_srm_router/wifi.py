"""Wi-Fi radios and networks of one SRM device, as the entities show them."""

from __future__ import annotations

from aiosynologysrm import WifiNetworkProfile, WifiRadioSetting, WifiRadioState, helpers

from .coordinator import SlowData

# SRM's band names; an unknown one is shown as SRM writes it.
BAND_LABELS = {
    "2.4G": "2.4 GHz",
    "5G": "5 GHz",
    "5G-1": "5 GHz-1",
    "5G-2": "5 GHz-2",
    "6G": "6 GHz",
}


def band_label(radio_type: str) -> str:
    """Return a band as people read it: ``5G-2`` becomes ``5 GHz-2``."""
    return BAND_LABELS.get(radio_type, radio_type)


def width_label(channel_width: str | None) -> str | None:
    """Return the channel widths allowed in SRM: ``20_40_80`` becomes ``20/40/80 MHz``."""
    return f"{channel_width.replace('_', '/')} MHz" if channel_width else None


def radios(data: SlowData) -> dict[str, tuple[WifiRadioSetting, WifiRadioState | None]]:
    """Return each radio's settings with its live state, by SRM's band name."""
    if data.radio_settings is None:
        return {}
    status = data.radio_status.status_list if data.radio_status else ()
    return {
        setting.radio_type: (setting, state)
        for setting, state in helpers.pair_radios(data.radio_settings.radio_list, status)
        if setting.radio_type
    }


def networks(data: SlowData) -> dict[str, tuple[WifiNetworkProfile, str, bool | None]]:
    """Return every Wi-Fi network on every band, on or off, by ``<network id>_<band>``.

    With Smart Connect on, the network's Smart Connect setting decides for all bands
    (``helpers.network_bands``).
    """
    if data.wifi_networks is None:
        return {}
    return {
        f"{profile.id}_{band}": (profile, band, on)
        for profile in data.wifi_networks.profiles
        if profile.id is not None
        for band, on in helpers.network_bands(profile)
    }
