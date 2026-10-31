"""Data update coordinators and the cross-entry client locator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from aiosynologysrm import (
    AllowSrmFromWan,
    AutoBlock,
    ConnectionStatus,
    DhcpClients,
    DhcpReservations,
    DhcpServers,
    EthPortInfo,
    ExternalIp,
    FirewallRule,
    FirewallRules,
    Ipv6Prefixes,
    NetworkDevices,
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmClient,
    SrmError,
    SrmPermissionError,
    SrmTwoFactorRequiredError,
    StorageVolumes,
    SystemInfo,
    Topology,
    Utilization,
    WifiDevices,
    WifiNetworks,
    WifiRadioSettings,
    WifiRadioStatus,
    helpers,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .clients import Client, DhcpAddress, combine, dhcp_addresses
from .const import (
    BLOCKED_RETRY,
    CONF_FAST_INTERVAL,
    CONF_IS_ROUTER,
    CONF_OWN_TRACKERS,
    CONF_SLOW_INTERVAL,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_SLOW_INTERVAL,
    DOCS_URL,
    DOMAIN,
    LOGGER,
    RECENTLY_SEEN,
    UPDATE_TIMEOUT,
)
from .firewall import rule_keys

SIGNAL_LOCATIONS = f"{DOMAIN}_locations"
# A client seen for the first time: (entry id of the device it is on, MAC address).
SIGNAL_NEW_CLIENT = f"{DOMAIN}_new_client"
STORE_VERSION = 1
# "Last seen" is written at most this often; it only needs to survive a restart roughly.
# (Store.async_delay_save postpones on every call, so it is not called on every update.)
SAVE_INTERVAL = timedelta(minutes=5)
HUB_KEY: HassKey[LocationHub] = HassKey(DOMAIN)

type SrmConfigEntry = ConfigEntry[SrmRuntimeData]


@dataclass(kw_only=True)
class FastData:
    """What changes quickly: load, clients, Wi-Fi clients, Ethernet ports, WAN."""

    utilization: Utilization | None = None
    devices: NetworkDevices | None = None
    wifi: WifiDevices | None = None
    connection: ConnectionStatus | None = None
    external_ip: tuple[ExternalIp, ...] = ()
    ports: EthPortInfo | None = None


@dataclass(kw_only=True)
class SlowData:
    """What changes rarely: system information, USB storage, Wi-Fi; DHCP, firewall, IPv6 on routers.

    Everything but the system information is optional: a read that fails keeps what is known.
    """

    system: SystemInfo
    boot_time: datetime | None = None
    dhcp: dict[str, DhcpAddress] = field(default_factory=dict)
    """Addresses by MAC from DHCP leases and reservations."""
    leases: DhcpClients | None = None
    reservations: DhcpReservations | None = None
    dhcp_servers: DhcpServers | None = None
    firewall: FirewallRules | None = None
    hits: dict[int, int] | None = None
    """Packets per firewall rule (``ui_id``), since SRM last built its firewall.

    Not kept when its read fails: a counter must not be matched against a newer rule list.
    """
    prefixes: Ipv6Prefixes | None = None
    allow_wan: AllowSrmFromWan | None = None
    """Whether SRM's web interface is reachable from the internet."""
    auto_block: AutoBlock | None = None
    usb: StorageVolumes | None = None
    radio_settings: WifiRadioSettings | None = None
    radio_status: WifiRadioStatus | None = None
    wifi_networks: WifiNetworks | None = None
    """Every Wi-Fi network with its bands; the library keeps the Wi-Fi keys out of it."""
    rules: dict[str, FirewallRule] = field(default_factory=dict)
    """Firewall rules by a key from their content (see firewall.rule_keys), computed once."""


# Optional reads of the slow coordinator: SlowData field, client getter, routers only.
SLOW_READS: tuple[tuple[str, str, bool], ...] = (
    ("leases", "get_dhcp_clients", True),
    ("reservations", "get_dhcp_reservations", True),
    ("dhcp_servers", "get_dhcp_servers", True),
    ("firewall", "get_firewall_rules", True),
    ("hits", "get_firewall_hit_counts", True),
    ("prefixes", "get_ipv6_prefixes", True),
    ("allow_wan", "get_allow_srm_from_wan", True),
    ("auto_block", "get_auto_block", True),
    ("usb", "get_usb_volumes", False),
    ("radio_settings", "get_wifi_radio_settings", False),
    ("radio_status", "get_wifi_radio_status", False),
    ("wifi_networks", "get_wifi_networks", False),
)


@dataclass(kw_only=True)
class SrmRuntimeData:
    """Everything one config entry keeps while it is loaded."""

    client: SrmClient
    topology: Topology
    supported: frozenset[str]
    fast: SrmFastCoordinator
    slow: SrmSlowCoordinator

    @property
    def is_router(self) -> bool:
        """Whether the device runs as router (not as standalone access point)."""
        return self.topology.net_topology == "router"


def map_error(err: SrmError) -> Exception:
    """Translate a library error into what Home Assistant expects from an update."""
    if isinstance(err, SrmTwoFactorRequiredError):
        return ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="two_factor")
    if isinstance(err, SrmAuthenticationError):
        return ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_auth")
    if isinstance(err, SrmPermissionError):
        return ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="not_admin")
    if isinstance(err, SrmCertificateError):
        return ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="certificate")
    if isinstance(err, SrmBlockedError):
        return UpdateFailed(translation_domain=DOMAIN, translation_key="blocked")
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="communication_error",
        translation_placeholders={"error": type(err).__name__},
    )


# Errors that need the user and must not be hidden behind a partial result.
_NEEDS_USER = (SrmAuthenticationError, SrmCertificateError, SrmPermissionError, SrmBlockedError)


async def gather_partial(
    calls: dict[str, Callable[[], Awaitable[Any]]],
    failing: set[str],
    device: str,
) -> dict[str, Any]:
    """Run reads concurrently; a read that fails is left out, unless every read failed.

    Errors that need the user (credentials, certificate, permission, auto block) always win.
    `failing` holds the reads that failed last time, so a partial result logs once when a read
    fails and once when it works again; a failed update is logged by the coordinator.
    """
    names = list(calls)
    results = await asyncio.gather(*(calls[n]() for n in names), return_exceptions=True)
    errors: list[SrmError] = []
    for name, result in zip(names, results, strict=True):
        if isinstance(result, SrmError):
            LOGGER.debug("Reading %s failed: %s", name, type(result).__name__)
            errors.append(result)
        elif isinstance(result, BaseException):
            raise result
    for error in errors:
        if isinstance(error, _NEEDS_USER):
            raise map_error(error) from error
    if errors and len(errors) == len(results):
        raise map_error(errors[0]) from errors[0]
    for name, result in zip(names, results, strict=True):
        if isinstance(result, SrmError) and name not in failing:
            failing.add(name)
            LOGGER.info("Reading %s from %s failed: %s", name, device, type(result).__name__)
        elif not isinstance(result, SrmError) and name in failing:
            failing.discard(name)
            LOGGER.info("Reading %s from %s works again", name, device)
    return {n: r for n, r in zip(names, results, strict=True) if not isinstance(r, BaseException)}


class SrmFastCoordinator(DataUpdateCoordinator[FastData]):
    """Reads load, clients, Wi-Fi clients and WAN state every 30 s by default."""

    config_entry: SrmConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SrmConfigEntry,
        client: SrmClient,
        supported: frozenset[str],
        *,
        is_router: bool,
    ) -> None:
        """Prepare the coordinator; the interval comes from the entry's options."""
        seconds = entry.options.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL.total_seconds())
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} fast {entry.title}",
            update_interval=timedelta(seconds=seconds),
            # Trackers count down "consider home" on every update, also when nothing changed.
            always_update=True,
        )
        self.client = client
        self.supported = supported
        self.is_router = is_router
        self.blocked_since: datetime | None = None
        self.failing: set[str] = set()

    async def _async_update_data(self) -> FastData:
        await self._retry_after_block()
        calls: dict[str, Callable[[], Awaitable[Any]]] = {}
        for name, getter in (
            ("utilization", self.client.get_utilization),
            ("devices", self.client.get_network_devices),
            ("wifi", self.client.get_wifi_devices),
            ("ports", self.client.get_eth_port_info),
        ):
            if getter.__name__ in self.supported:
                calls[name] = getter
        if self.is_router:
            if "get_connection_status" in self.supported:
                calls["connection"] = self.client.get_connection_status
            if "get_external_ip" in self.supported:
                calls["external_ip"] = self.client.get_external_ip
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT):
                results = await gather_partial(calls, self.failing, self.config_entry.title)
        except UpdateFailed as err:
            if isinstance(err.__cause__, SrmBlockedError):
                self._blocked()
            raise
        self._unblocked()
        return FastData(**results)

    async def _retry_after_block(self) -> None:
        """Log in once more a while after a block; the library does not retry on its own."""
        if self.blocked_since is None or dt_util.utcnow() - self.blocked_since < BLOCKED_RETRY:
            return
        self.blocked_since = dt_util.utcnow()
        try:
            await self.client.login()
        except SrmError as err:
            raise map_error(err) from err

    def _blocked(self) -> None:
        if self.blocked_since is None:
            self.blocked_since = dt_util.utcnow()
        create_blocked_issue(self.hass, self.config_entry)

    def _unblocked(self) -> None:
        if self.blocked_since is not None:
            self.blocked_since = None
            delete_blocked_issue(self.hass, self.config_entry)


def device_identifier(entry: ConfigEntry) -> tuple[str, str]:
    """Return the identifier of the router's or access point's own device."""
    return (DOMAIN, entry.unique_id or entry.entry_id)


def _blocked_issue_id(entry: ConfigEntry) -> str:
    return f"blocked_{entry.entry_id}"


def create_blocked_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Tell the user that SRM's auto block refuses this installation's logins."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _blocked_issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="blocked",
        translation_placeholders={"name": entry.title},
        learn_more_url=f"{DOCS_URL}repairs/blocked/",
    )


def delete_blocked_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the auto block repair, once logins work again or the entry is gone."""
    ir.async_delete_issue(hass, DOMAIN, _blocked_issue_id(entry))


class SrmSlowCoordinator(DataUpdateCoordinator[SlowData]):
    """Reads system information, and DHCP on routers, every 5 min by default."""

    config_entry: SrmConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SrmConfigEntry,
        client: SrmClient,
        supported: frozenset[str],
        *,
        is_router: bool,
    ) -> None:
        """Prepare the coordinator; the interval comes from the entry's options."""
        seconds = entry.options.get(CONF_SLOW_INTERVAL, DEFAULT_SLOW_INTERVAL.total_seconds())
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} slow {entry.title}",
            update_interval=timedelta(seconds=seconds),
        )
        self.client = client
        self.supported = supported
        self.is_router = is_router
        self.failing: set[str] = set()

    async def _async_update_data(self) -> SlowData:
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT):
                system = await self.client.get_system_info()
                optional = await self._optional()
        except SrmError as err:
            raise map_error(err) from err
        uptime = helpers.up_time(system.up_time)
        boot = None
        if uptime is not None:
            boot = (dt_util.utcnow() - uptime).replace(second=0, microsecond=0)
            # Keep the boot time stable between updates; only a real restart moves it.
            previous = self.data.boot_time if self.data else None
            if previous is not None and abs((boot - previous).total_seconds()) < 120:  # noqa: PLR2004
                boot = previous
        self._update_device(system)
        optional["dhcp"] = dhcp_addresses(optional["leases"], optional["reservations"])
        optional["rules"] = rule_keys(optional["firewall"].rules if optional["firewall"] else ())
        return SlowData(system=system, boot_time=boot, **optional)

    async def _optional(self) -> dict[str, Any]:
        """Run the optional reads this device offers; a failed one keeps its last value."""
        calls: dict[str, Callable[[], Awaitable[Any]]] = {
            field: getattr(self.client, getter)
            for field, getter, router_only in SLOW_READS
            if getter in self.supported and (self.is_router or not router_only)
        }
        title = self.config_entry.title
        try:
            results = await gather_partial(calls, self.failing, title) if calls else {}
        except UpdateFailed as err:
            cause = type(err.__cause__).__name__
            for name in calls.keys() - self.failing:
                LOGGER.info("Reading %s from %s failed: %s", name, title, cause)
            self.failing.update(calls)
            results = {}
        if "hits" in results:
            results["hits"] = helpers.hits_by_rule(results["hits"])
        return {
            field: results.get(field)
            if field in results or field == "hits"
            else getattr(self.data, field, None)
            for field, _, _ in SLOW_READS
        }

    def _update_device(self, system: SystemInfo) -> None:
        """Keep the device registry's firmware version current after an update."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            device_identifier(self.config_entry), self.config_entry.entry_id
        )
        if device is not None and device.sw_version != system.firmware_ver:
            registry.async_update_device(device.id, sw_version=system.firmware_ver)


def private_mac(mac: str) -> bool:
    """Whether an address is locally administered: a private (random) one of a phone or laptop."""
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


@dataclass
class LocationHub:
    """Combines the client lists of every configured entry into one location per client.

    Entries that are configured but not loaded, or whose last update failed, count as missing,
    so their clients are not silently moved to the router.
    """

    hass: HomeAssistant
    loaded: dict[str, SrmConfigEntry] = field(default_factory=dict)
    last_seen: dict[str, datetime] = field(default_factory=dict)
    _cache: dict[str, helpers.ClientLocation] | None = None
    _clients: dict[str, Client] | None = None
    _missing: frozenset[str] = frozenset()
    _known: dict[str, frozenset[str]] = field(default_factory=dict)
    _store: Store[dict[str, str]] | None = None
    _saved_at: datetime | None = None
    first_seen: dict[str, datetime] = field(default_factory=dict)
    """Every client ever seen, by MAC: a client not in it is new. Private (random) addresses are
    forgotten after RECENTLY_SEEN, like in last_seen; fixed ones are kept."""
    _known_store: Store[dict[str, str]] | None = None
    _baseline: bool = False
    """Whether the clients present at the very first start were taken in without events."""

    async def async_load(self) -> None:
        """Read when clients were last seen online; once per Home Assistant run."""
        if self._store is not None:
            return
        self._store = Store(self.hass, STORE_VERSION, f"{DOMAIN}.last_seen")
        stored = await self._store.async_load() or {}
        for mac, text in stored.items():
            if (seen := dt_util.parse_datetime(text)) is not None:
                self.last_seen.setdefault(mac, seen)
        self._known_store = Store(self.hass, STORE_VERSION, f"{DOMAIN}.known_clients")
        known = await self._known_store.async_load()
        self._baseline = known is not None
        for mac, text in (known or {}).items():
            if (seen := dt_util.parse_datetime(text)) is not None:
                self.first_seen.setdefault(mac, seen)
        self._prune(dt_util.utcnow())

    def _prune(self, now: datetime) -> None:
        """Forget clients not seen for RECENTLY_SEEN; only recent ones matter for "track all".

        Without this, rotating private MAC addresses would make the file grow forever.
        """
        for mac in [m for m, seen in self.last_seen.items() if now - seen > RECENTLY_SEEN]:
            del self.last_seen[mac]
        for mac in [
            m
            for m in self.first_seen
            if private_mac(m) and now - self.last_seen.get(m, self.first_seen[m]) > RECENTLY_SEEN
        ]:
            del self.first_seen[mac]

    async def async_forget(self) -> None:
        """Delete what was remembered about clients; done when the last entry is removed."""
        store = self._store or Store(self.hass, STORE_VERSION, f"{DOMAIN}.last_seen")
        await store.async_remove()
        known = self._known_store or Store(self.hass, STORE_VERSION, f"{DOMAIN}.known_clients")
        await known.async_remove()
        self._store = self._known_store = None
        self._baseline = False
        self.last_seen.clear()
        self.first_seen.clear()

    @callback
    def async_add(self, entry: SrmConfigEntry) -> None:
        """Start using an entry and recompute when its fast data changes."""
        self.loaded[entry.entry_id] = entry
        entry.async_on_unload(entry.runtime_data.fast.async_add_listener(self.async_invalidate))
        entry.async_on_unload(entry.runtime_data.slow.async_add_listener(self.async_invalidate))
        self.async_invalidate()

    @callback
    def async_remove(self, entry: SrmConfigEntry) -> None:
        """Stop using an entry; its clients then count as unknown, not as moved."""
        self.loaded.pop(entry.entry_id, None)
        self.async_invalidate()

    @callback
    def async_invalidate(self) -> None:
        """Drop the cached locations and tell the trackers."""
        self._cache = None
        self._clients = None
        self._known.clear()
        async_dispatcher_send(self.hass, SIGNAL_LOCATIONS)

    def configured(self) -> list[ConfigEntry]:
        """Return the enabled entries, routers first, then by unique id: a fixed order."""
        entries = [
            e for e in self.hass.config_entries.async_entries(DOMAIN) if e.disabled_by is None
        ]
        return sorted(entries, key=lambda e: (not e.data.get(CONF_IS_ROUTER), e.unique_id or ""))

    def _view(self, entry: ConfigEntry) -> helpers.SourceView:
        loaded = self.loaded.get(entry.entry_id)
        if loaded is None or not loaded.runtime_data.fast.last_update_success:
            return helpers.SourceView(entry.entry_id, None)
        runtime = loaded.runtime_data
        data = runtime.fast.data
        wifi = data.wifi
        if wifi is None and "get_wifi_devices" not in runtime.supported:
            wifi = WifiDevices()  # the device has no Wi-Fi list to wait for
        return helpers.SourceView(entry.entry_id, data.devices, wifi)

    def _refresh(self) -> dict[str, helpers.ClientLocation]:
        if self._cache is None:
            views = [self._view(entry) for entry in self.configured()]
            self._missing = frozenset(
                v.name
                for v in views
                if v.devices is None or v.wifi is None or v.devices.exceed_dev_list_max is True
            )
            self._cache = helpers.locate_clients(views)
            self._remember(self._cache)
        return self._cache

    def _remember(self, locations: dict[str, helpers.ClientLocation]) -> None:
        now = dt_util.utcnow()
        for mac, location in locations.items():
            if location.online:
                self.last_seen[mac] = now
        self._find_new(locations, now)
        if self._store is not None and (
            self._saved_at is None or now - self._saved_at >= SAVE_INTERVAL
        ):
            self._saved_at = now
            self._prune(now)
            self._store.async_delay_save(
                lambda: {mac: seen.isoformat() for mac, seen in self.last_seen.items()}
            )

    def _find_new(self, locations: dict[str, helpers.ClientLocation], now: datetime) -> None:
        """Announce clients online for the first time; quietly take in everything else.

        Only while every device delivered its lists: a device that loads late, or a truncated
        list, would otherwise make clients seen long ago look new. At the very first start
        everything present is taken in without events.
        """
        if self._known_store is None:
            return
        complete = self._baseline and not self._missing
        new = [mac for mac in locations if mac not in self.first_seen]
        for mac in new:
            self.first_seen[mac] = now
            location = locations[mac]
            if complete and location.online and location.source is not None:
                async_dispatcher_send(self.hass, SIGNAL_NEW_CLIENT, location.source, mac)
        if not self._missing:
            self._baseline = True
        if new:
            self._known_store.async_delay_save(
                lambda: {mac: seen.isoformat() for mac, seen in self.first_seen.items()},
                SAVE_INTERVAL.total_seconds(),
            )

    @property
    def clients(self) -> dict[str, Client]:
        """Every client known to any loaded entry, with its best name."""
        if self._clients is None:
            self._refresh()  # updates last_seen first
            entries = [self.loaded.get(e.entry_id) for e in self.configured()]
            runtimes = [e.runtime_data for e in entries if e is not None]
            dhcp: dict[str, DhcpAddress] = {}
            for runtime in reversed(runtimes):  # routers come first and win
                dhcp.update(runtime.slow.data.dhcp if runtime.slow.data else {})
            lists = [r.fast.data.devices if r.fast.data else None for r in runtimes]
            self._clients = combine(lists, dhcp, self.last_seen)
        return self._clients

    def name(self, mac: str) -> str | None:
        """Return the best name of a client: given in SRM, else reported by the client."""
        client = self.clients.get(mac)
        return client.name if client else None

    def ip(self, mac: str) -> str | None:
        """Return a client's IPv4 address, from any device's list or the DHCP server."""
        client = self.clients.get(mac)
        return client.ip if client else None

    def ip6(self, mac: str) -> str | None:
        """Return a client's IPv6 address other than link-local, from the lists or DHCPv6."""
        client = self.clients.get(mac)
        return client.ip6 if client else None

    def relevant(self, mac: str) -> bool:
        """Whether "track all" covers the client (see clients.Client.relevant)."""
        client = self.clients.get(mac)
        return client is not None and client.relevant(dt_util.utcnow())

    @property
    def locations(self) -> dict[str, helpers.ClientLocation]:
        """Where every known client is, by normalized MAC address."""
        return self._refresh()

    @property
    def missing(self) -> frozenset[str]:
        """Entries whose client lists are not available right now."""
        self._refresh()
        return self._missing

    @property
    def anything_available(self) -> bool:
        """Whether at least one entry delivered client data."""
        self._refresh()
        return any(e.entry_id not in self._missing for e in self.configured())

    def known(self, entry_id: str) -> frozenset[str]:
        """Return the clients an entry's own device and Wi-Fi lists contain (cached per update)."""
        if (cached := self._known.get(entry_id)) is not None:
            return cached
        loaded = self.loaded.get(entry_id)
        data = loaded.runtime_data.fast.data if loaded else None
        if data is None:
            return frozenset()
        macs = [d.mac for d in data.devices.devices] if data.devices else []
        macs += [w.mac_address for w in data.wifi.device_list] if data.wifi else []
        known = frozenset(m for mac in macs if (m := helpers.normalize_mac(mac)))
        self._known[entry_id] = known
        return known

    def keeps_trackers(self, entry: ConfigEntry) -> bool:
        """Whether an entry keeps trackers.

        Routers do, and access points without a router or set to keep their own.
        """
        if entry.data.get(CONF_IS_ROUTER) or entry.options.get(CONF_OWN_TRACKERS):
            return True
        return not any(e.data.get(CONF_IS_ROUTER) for e in self.configured())

    def wants(self, entry: ConfigEntry, mac: str) -> bool:
        """Whether an entry wants a tracker for a client: picked by name, or covered by "all"."""
        if not self.keeps_trackers(entry):
            return False
        if mac in entry.options.get(CONF_TRACKED, []):
            return True
        return bool(entry.options.get(CONF_TRACK_ALL, False)) and self.relevant(mac)

    def owner(self, mac: str) -> str | None:
        """Return the entry that creates a client's tracker.

        The first entry that knows the client and wants a tracker for it, routers before access
        points, in an order that does not depend on which entry loaded first. Two routers of
        separate networks, or an access point in a network without a Synology router, each keep
        the trackers of their own clients.
        """
        for entry in self.configured():
            if mac in self.known(entry.entry_id) and self.wants(entry, mac):
                return entry.entry_id
        return None

    def name_of(self, entry_id: str | None) -> str | None:
        """Return the title of an entry, which says where a client is attached."""
        entry = self.hass.config_entries.async_get_entry(entry_id or "")
        return entry.title if entry else None


def get_hub(hass: HomeAssistant) -> LocationHub:
    """Return the hub shared by all entries of this integration."""
    if HUB_KEY not in hass.data:
        hass.data[HUB_KEY] = LocationHub(hass)
    return hass.data[HUB_KEY]
