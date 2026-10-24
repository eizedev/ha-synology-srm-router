"""The Synology SRM Router integration: Synology routers and access points, read only."""

from __future__ import annotations

import aiohttp
from aiosynologysrm import SrmClient, SrmError
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_FINGERPRINT,
    CONF_IS_ROUTER,
    CONF_USE_HTTPS,
    DOMAIN,
    REQUEST_TIMEOUT,
    SESSION_NAME,
)
from .coordinator import (
    SrmConfigEntry,
    SrmFastCoordinator,
    SrmRuntimeData,
    SrmSlowCoordinator,
    get_hub,
    map_error,
)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SENSOR]
# The reads the fast coordinator uses; each is checked against the device's API catalog once.
GETTERS = (
    "get_utilization",
    "get_network_devices",
    "get_wifi_devices",
    "get_connection_status",
    "get_external_ip",
)


def create_client(hass: HomeAssistant, data: dict[str, object]) -> SrmClient:
    """Build a client from an entry's data: pinned certificate, or none checked when chosen."""
    fingerprint = data.get(CONF_FINGERPRINT)
    use_https = bool(data[CONF_USE_HTTPS])
    ssl: bool | aiohttp.Fingerprint = False
    if use_https and isinstance(fingerprint, str):
        ssl = aiohttp.Fingerprint(bytes.fromhex(fingerprint))
    return SrmClient(
        str(data[CONF_HOST]),
        str(data[CONF_USERNAME]),
        str(data[CONF_PASSWORD]),
        session=async_get_clientsession(hass, verify_ssl=False),
        port=int(str(data[CONF_PORT])),
        use_https=use_https,
        ssl=ssl,
        timeout=REQUEST_TIMEOUT,
        session_name=SESSION_NAME,
    )


async def async_setup_entry(hass: HomeAssistant, entry: SrmConfigEntry) -> bool:
    """Connect to one SRM device and start polling it."""
    client = create_client(hass, dict(entry.data))
    try:
        await client.login()
        topology = await client.get_topology()
        supported = frozenset(
            [name for name in GETTERS if await client.supports(getattr(client, name))]
        )
        is_router = topology.net_topology == "router"
        fast = SrmFastCoordinator(hass, entry, client, supported, is_router=is_router)
        slow = SrmSlowCoordinator(hass, entry, client)
        entry.runtime_data = SrmRuntimeData(
            client=client, topology=topology, supported=supported, fast=fast, slow=slow
        )
        await slow.async_config_entry_first_refresh()
        await fast.async_config_entry_first_refresh()
    except SrmError as err:
        await client.logout()
        mapped = map_error(err)
        if isinstance(mapped, ConfigEntryAuthFailed):
            raise mapped from err
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key=mapped.translation_key if isinstance(mapped, UpdateFailed) else None,
            translation_placeholders=getattr(mapped, "translation_placeholders", None),
        ) from err
    except ConfigEntryAuthFailed, ConfigEntryNotReady:
        await client.logout()  # do not leave a session open on the router for every retry
        raise

    if entry.data.get(CONF_IS_ROUTER) != is_router:
        # Remembered so that trackers are owned by routers even while an entry is not loaded.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_IS_ROUTER: is_router}
        )
    get_hub(hass).async_add(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SrmConfigEntry) -> bool:
    """Stop polling and end the router session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        get_hub(hass).async_remove(entry)
        await entry.runtime_data.client.logout()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SrmConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a tracked client's device; the router or AP itself stays while set up."""
    return (DOMAIN, entry.unique_id or entry.entry_id) not in device.identifiers
