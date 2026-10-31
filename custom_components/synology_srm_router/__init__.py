"""The Synology SRM Router integration: Synology routers and access points, read only."""

from __future__ import annotations

from datetime import datetime
from ssl import SSLContext

import aiohttp
from aiosynologysrm import SrmBlockedError, SrmCertificateError, SrmClient, SrmError
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.ssl import get_default_context

from .changes import store as router_events_store
from .const import (
    BLOCKED_RETRY,
    CONF_CERTIFICATE_NAME,
    CONF_FINGERPRINT,
    CONF_IS_ROUTER,
    CONF_USE_HTTPS,
    CONF_VERIFY_CERTIFICATE,
    DOMAIN,
    REQUEST_TIMEOUT,
    SESSION_NAME,
)
from .coordinator import (
    SrmConfigEntry,
    SrmFastCoordinator,
    SrmRuntimeData,
    SrmSlowCoordinator,
    create_blocked_issue,
    delete_blocked_issue,
    device_identifier,
    get_hub,
    map_error,
)
from .repairs import delete_risk_issues, update_risk_issues

BLOCKED_AT: HassKey[dict[str, datetime]] = HassKey(f"{DOMAIN}_blocked_at")
PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.EVENT, Platform.SENSOR]
# The reads the coordinators use; each is checked against the device's API catalog once.
GETTERS = (
    "get_utilization",
    "get_network_devices",
    "get_wifi_devices",
    "get_connection_status",
    "get_external_ip",
    "get_dhcp_clients",
    "get_dhcp_reservations",
    "get_dhcp_servers",
    "get_firewall_rules",
    "get_firewall_hit_counts",
    "get_ipv6_prefixes",
    "get_allow_srm_from_wan",
    "get_auto_block",
    "get_usb_volumes",
    "get_wifi_radio_settings",
    "get_wifi_radio_status",
    "get_wifi_networks",
    "get_eth_port_info",
)


async def session_name(hass: HomeAssistant, purpose: str | None = None) -> str:
    """Name the SRM session after this installation, so two of them do not end each other's."""
    name = f"{SESSION_NAME}-{(await instance_id.async_get(hass))[:8]}"
    return f"{name}-{purpose}" if purpose else name


def create_client(hass: HomeAssistant, data: dict[str, object], session: str) -> SrmClient:
    """Build a client from an entry's data: how its certificate is checked decides the rest.

    A pinned fingerprint accepts exactly one certificate. A certificate from a public authority
    is checked against the authorities and the name the user gave, so renewals need nothing; the
    pin wins if both are stored. None is checked only when chosen. An entry that checks its
    certificate but has lost both name and fingerprint is refused rather than connected
    unchecked; the certificate error leads to reauthentication, which shows the certificate for
    confirmation.
    """
    fingerprint = data.get(CONF_FINGERPRINT)
    name = data.get(CONF_CERTIFICATE_NAME)
    use_https = bool(data[CONF_USE_HTTPS])
    ssl: bool | aiohttp.Fingerprint | SSLContext = False
    server_hostname: str | None = None
    if use_https and fingerprint and isinstance(fingerprint, str):
        ssl = aiohttp.Fingerprint(bytes.fromhex(fingerprint))
    elif use_https and name and isinstance(name, str):
        ssl, server_hostname = get_default_context(), name
    elif use_https and data.get(CONF_VERIFY_CERTIFICATE):
        msg = "The certificate is checked, but neither its name nor its fingerprint is stored"
        raise SrmCertificateError(msg)
    return SrmClient(
        str(data[CONF_HOST]),
        str(data[CONF_USERNAME]),
        str(data[CONF_PASSWORD]),
        session=async_get_clientsession(hass, verify_ssl=False),
        port=int(str(data[CONF_PORT])),
        use_https=use_https,
        ssl=ssl,
        timeout=REQUEST_TIMEOUT,
        session_name=session,
        server_hostname=server_hostname,
    )


async def async_setup_entry(hass: HomeAssistant, entry: SrmConfigEntry) -> bool:
    """Connect to one SRM device and start polling it."""
    # After SRM's auto block, Home Assistant retries the setup on its own schedule; every retry
    # would be one more login while blocked. Wait as long as a running entry would.
    blocked = hass.data.setdefault(BLOCKED_AT, {})
    since = blocked.get(entry.entry_id)
    if since is not None and dt_util.utcnow() - since < BLOCKED_RETRY:
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="blocked")
    try:
        client = create_client(hass, dict(entry.data), await session_name(hass))
    except SrmCertificateError as err:
        raise map_error(err) from err
    try:
        await client.login()
        topology = await client.get_topology()
        supported = frozenset(
            [name for name in GETTERS if await client.supports(getattr(client, name))]
        )
        is_router = topology.net_topology == "router"
        fast = SrmFastCoordinator(hass, entry, client, supported, is_router=is_router)
        slow = SrmSlowCoordinator(hass, entry, client, supported, is_router=is_router)
        entry.runtime_data = SrmRuntimeData(
            client=client, topology=topology, supported=supported, fast=fast, slow=slow
        )
        await slow.async_config_entry_first_refresh()
        await fast.async_config_entry_first_refresh()
    except SrmError as err:
        await client.logout()
        if isinstance(err, SrmBlockedError):
            blocked[entry.entry_id] = dt_util.utcnow()
            create_blocked_issue(hass, entry)
        mapped = map_error(err)
        if isinstance(mapped, ConfigEntryAuthFailed):
            raise mapped from err
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key=mapped.translation_key if isinstance(mapped, UpdateFailed) else None,
            translation_placeholders=getattr(mapped, "translation_placeholders", None),
        ) from err
    except (ConfigEntryAuthFailed, ConfigEntryNotReady) as err:
        await client.logout()  # do not leave a session open on the router for every retry
        if err.translation_key == "blocked":  # the block showed in the first update, not the login
            blocked[entry.entry_id] = dt_util.utcnow()
            create_blocked_issue(hass, entry)
        raise

    if entry.data.get(CONF_IS_ROUTER) != is_router:
        # Remembered so that trackers are owned by routers even while an entry is not loaded.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_IS_ROUTER: is_router}
        )
    blocked.pop(entry.entry_id, None)
    delete_blocked_issue(hass, entry)

    def _check_risks() -> None:
        update_risk_issues(hass, entry, slow.data, is_router=is_router, supported=supported)

    _check_risks()
    entry.async_on_unload(slow.async_add_listener(_check_risks))
    hub = get_hub(hass)
    await hub.async_load()
    hub.async_add(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SrmConfigEntry) -> bool:
    """Stop polling and end the router session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        get_hub(hass).async_remove(entry)
        delete_blocked_issue(hass, entry)
        await entry.runtime_data.client.logout()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SrmConfigEntry) -> None:
    """Forget the entry's last seen prefixes and firewall; the clients once no entry is left."""
    await router_events_store(hass, entry.entry_id).async_remove()
    delete_risk_issues(hass, entry)
    if not any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        await get_hub(hass).async_forget()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SrmConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a tracked client's device; the router or AP itself stays while set up."""
    return device_identifier(entry) not in device.identifiers
