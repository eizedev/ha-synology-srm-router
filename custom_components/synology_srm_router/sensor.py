"""Sensors: load, traffic, clients, WAN, DHCP, firewall hits and USB storage of an SRM device."""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from dataclasses import dataclass
from functools import partial
import ipaddress
from typing import Any

from aiosynologysrm import DhcpServer, FirewallRule, StorageVolume, helpers
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfDataRate, UnitOfInformation
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_FIREWALL_HITS, RECENTLY_SEEN
from .coordinator import (
    SIGNAL_LOCATIONS,
    FastData,
    SlowData,
    SrmConfigEntry,
    SrmFastCoordinator,
    SrmSlowCoordinator,
    get_hub,
)
from .entity import SrmEntity
from .firewall import address_key, rule_label, rule_rows

# Coordinators poll; entities never call the router themselves.
PARALLEL_UPDATES = 0


def _total(data: FastData, direction: str) -> int | None:
    if data.utilization is None:
        return None
    total = next((n for n in data.utilization.network if n.device == "total"), None)
    return getattr(total, direction) if total else None


def _load(data: FastData, attribute: str) -> float | None:
    cpu = data.utilization.cpu if data.utilization else None
    value = getattr(cpu, attribute) if cpu else None
    return None if value is None else value / 100  # SRM reports the load average times 100


def _public_ipv4(data: FastData) -> str | None:
    # The entry of the main connection, else the first one SRM lists.
    entries = sorted(data.external_ip, key=lambda e: e.type != "WAN")
    return entries[0].ip if entries else None


@dataclass(frozen=True, kw_only=True)
class SrmFastSensorDescription(SensorEntityDescription):
    """A sensor fed by the fast coordinator."""

    value_fn: Callable[[FastData], Any]
    requires: str
    """The client read the value comes from; without it, the sensor is not created."""
    router_only: bool = False


@dataclass(frozen=True, kw_only=True)
class SrmSlowSensorDescription(SensorEntityDescription):
    """A sensor fed by the slow coordinator."""

    value_fn: Callable[[SlowData], Any]
    requires: str | None = None
    """The client read the value comes from; without it, the sensor is not created."""
    router_only: bool = False
    attributes_fn: Callable[[HomeAssistant, SlowData], dict[str, Any]] | None = None


FAST_SENSORS: tuple[SrmFastSensorDescription, ...] = (
    SrmFastSensorDescription(
        key="cpu_load",
        requires="get_utilization",
        translation_key="cpu_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: helpers.cpu_total_percent(d.utilization.cpu if d.utilization else None),
    ),
    SrmFastSensorDescription(
        key="memory_usage",
        requires="get_utilization",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (
            d.utilization.memory.real_usage if d.utilization and d.utilization.memory else None
        ),
    ),
    *(
        SrmFastSensorDescription(
            key=f"load_{period}",
            requires="get_utilization",
            translation_key=f"load_{period}",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=partial(_load, attribute=f"load_{period}"),
        )
        for period in ("1min", "5min", "15min")
    ),
    SrmFastSensorDescription(
        key="download_rate",
        requires="get_utilization",
        translation_key="download_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _total(d, "rx"),
    ),
    SrmFastSensorDescription(
        key="upload_rate",
        requires="get_utilization",
        translation_key="upload_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _total(d, "tx"),
    ),
    SrmFastSensorDescription(
        key="public_ipv4",
        requires="get_external_ip",
        translation_key="public_ipv4",
        router_only=True,
        value_fn=_public_ipv4,
    ),
    SrmFastSensorDescription(
        key="ipv6_address",
        requires="get_connection_status",
        translation_key="ipv6_address",
        router_only=True,
        value_fn=lambda d: d.connection.ipv6.ip if d.connection and d.connection.ipv6 else None,
    ),
    SrmFastSensorDescription(
        key="wan_ipv4",
        requires="get_connection_status",
        translation_key="wan_ipv4",
        router_only=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.connection.ipv4.ip if d.connection and d.connection.ipv4 else None,
    ),
    SrmFastSensorDescription(
        key="wan_address_type",
        requires="get_connection_status",
        translation_key="wan_address_type",
        router_only=True,
        device_class=SensorDeviceClass.ENUM,
        options=["public", "private", "cgnat", "link_local", "other"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: helpers.address_scope(
            d.connection.ipv4.ip if d.connection and d.connection.ipv4 else None
        ),
    ),
)


def _ipv4_count(entries: Any) -> int | None:
    lists = getattr(entries, "client_list", None) or getattr(entries, "reservation_list", None)
    return None if entries is None else len(lists.ipv4) if lists else 0


def _firewall_attributes(hass: HomeAssistant, data: SlowData) -> dict[str, Any]:
    if data.firewall is None:
        return {}
    return {
        # Changes whenever a rule is added, removed, edited, switched or moved.
        "config_hash": helpers.config_hash(rule.raw for rule in data.firewall.rules),
        "rules": rule_rows(data.rules, data.hits, _address_names(hass, data)),
    }


def _address_names(hass: HomeAssistant, data: SlowData) -> dict[str, str]:
    """Client names by address, from the client lists and the router's DHCP data."""
    hub = get_hub(hass)
    names: dict[str, str] = {}
    for mac, address in data.dhcp.items():
        if name := hub.name(mac):
            for value in (address.ip, address.ip6):
                if value:
                    names[address_key(value)] = name
    for client in hub.clients.values():  # the client lists win over DHCP
        for value in (client.ip, client.ip6):
            if value and client.name:
                names[address_key(value)] = client.name
    return names


def _reserved_macs(data: SlowData) -> set[str]:
    lists = data.reservations.reservation_list if data.reservations else None
    return {m for r in (lists.ipv4 if lists else ()) if (m := helpers.normalize_mac(r.clid))}


def _lease_attributes(hass: HomeAssistant, data: SlowData) -> dict[str, Any]:
    """Every IPv4 lease: who holds it, whether it is online, reserved, or unknown."""
    lists = data.leases.client_list if data.leases else None
    if lists is None:
        return {}
    hub, reserved = get_hub(hass), _reserved_macs(data)
    rows: list[dict[str, Any]] = []
    for lease in lists.ipv4:
        mac = helpers.normalize_mac(lease.clid) or ""
        client = hub.clients.get(mac)
        location = hub.locations.get(mac)
        remaining = helpers.lease_remaining(lease.expire)
        rows.append(
            {
                "name": (client.name if client else None) or lease.hostname,
                "ip": lease.ip,
                "mac": mac,
                "online": bool(location and location.online),
                "reserved": mac in reserved,
                # Neither reserved nor named in SRM: a device nobody has looked at yet.
                "unknown": mac not in reserved and not (client and client.named),
                "expires_in_min": int(remaining.total_seconds() // 60) if remaining else None,
            }
        )
    rows.sort(key=lambda r: (not r["online"], (r["name"] or "~").lower()))
    return {"leases": rows}


def _reservation_attributes(hass: HomeAssistant, data: SlowData) -> dict[str, Any]:
    """Every IPv4 reservation: whether its device is around, and whether it sits in a pool."""
    lists = data.reservations.reservation_list if data.reservations else None
    if lists is None:
        return {}
    hub, now = get_hub(hass), dt_util.utcnow()
    pools = [pool_range(s) for s in dhcp_pools(data).values()]
    rows: list[dict[str, Any]] = []
    for item in lists.ipv4:
        mac = helpers.normalize_mac(item.clid) or ""
        client = hub.clients.get(mac)
        location = hub.locations.get(mac)
        online = bool(location and location.online)
        seen = hub.last_seen.get(mac)
        rows.append(
            {
                "name": (client.name if client else None) or item.hostname,
                "ip": item.ip,
                "mac": mac,
                "online": online,
                "last_seen": seen.date().isoformat() if seen else None,
                # Not seen online by Home Assistant within RECENTLY_SEEN (since installing).
                "stale": not online and (seen is None or now - seen > RECENTLY_SEEN),
                "in_pool": any(_in(item.ip, r) for r in pools if r is not None),
            }
        )
    rows.sort(key=lambda r: (not r["stale"], (r["name"] or "~").lower()))
    return {"reservations": rows}


SLOW_SENSORS: tuple[SrmSlowSensorDescription, ...] = (
    SrmSlowSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.boot_time,
    ),
    SrmSlowSensorDescription(
        key="dhcp_leases",
        translation_key="dhcp_leases",
        # Its list names every device or rule, visible to every user: switched on by choice.
        entity_registry_enabled_default=False,
        requires="get_dhcp_clients",
        router_only=True,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ipv4_count(d.leases),
        attributes_fn=_lease_attributes,
    ),
    SrmSlowSensorDescription(
        key="dhcp_reservations",
        translation_key="dhcp_reservations",
        # Its list names every device or rule, visible to every user: switched on by choice.
        entity_registry_enabled_default=False,
        requires="get_dhcp_reservations",
        router_only=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _ipv4_count(d.reservations),
        attributes_fn=_reservation_attributes,
    ),
    SrmSlowSensorDescription(
        key="firewall_rules",
        translation_key="firewall_rules",
        # Its list names every device or rule, visible to every user: switched on by choice.
        entity_registry_enabled_default=False,
        requires="get_firewall_rules",
        router_only=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.firewall.rules) if d.firewall else None,
        attributes_fn=_firewall_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SrmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of one SRM device."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        SrmFastSensor(entry, runtime.fast, description)
        for description in FAST_SENSORS
        if description.requires in runtime.supported
        and (runtime.is_router or not description.router_only)
    ]
    entities += [
        SrmSlowSensor(entry, runtime.slow, description)
        for description in SLOW_SENSORS
        if (description.requires is None or description.requires in runtime.supported)
        and (runtime.is_router or not description.router_only)
    ]
    entities += [SrmClientsSensor(entry, key, match) for key, match in CLIENT_COUNTS.items()]
    async_add_entities(entities)
    _add_dynamic(hass, entry, async_add_entities)


class SrmFastSensor(SrmEntity[SrmFastCoordinator], SensorEntity):
    """A sensor computed from the fast coordinator's data."""

    entity_description: SrmFastSensorDescription

    @property
    def native_value(self) -> Any:
        """The current value."""
        return self.entity_description.value_fn(self.coordinator.data)


class SrmSlowSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """A sensor computed from the slow coordinator's data."""

    entity_description: SrmSlowSensorDescription
    # Lists for dashboards and templates; history keeps only the counts.
    _unrecorded_attributes = frozenset({"leases", "reservations", "rules"})

    @property
    def native_value(self) -> Any:
        """The current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Lists behind the counts, and the firewall's configuration hash."""
        attributes_fn = self.entity_description.attributes_fn
        return attributes_fn(self.hass, self.coordinator.data) if attributes_fn else None


# Clients attached to a device, all of them or by band and cable. SRM names radios 2.4G, 5G and
# 5G-2 (a second 5 GHz radio).
CLIENT_COUNTS: dict[str, Callable[[helpers.ClientLocation], bool]] = {
    "clients": lambda loc: True,
    "wifi_clients_2_4ghz": lambda loc: loc.connection == "wifi" and loc.radio_type == "2.4G",
    "wifi_clients_5ghz": lambda loc: (
        loc.connection == "wifi" and (loc.radio_type or "").startswith("5G")
    ),
    "wired_clients": lambda loc: loc.connection == "ethernet",
}


class SrmClientsSensor(SrmEntity[SrmFastCoordinator], SensorEntity):
    """How many clients are attached to this device, across all entries: all, or by band."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: SrmConfigEntry,
        key: str,
        match: Callable[[helpers.ClientLocation], bool],
    ) -> None:
        """Count from the shared client locations."""
        super().__init__(
            entry,
            entry.runtime_data.fast,
            SensorEntityDescription(key=key, translation_key=key),
        )
        self._entry_id = entry.entry_id
        self._match = match

    async def async_added_to_hass(self) -> None:
        """Also update when another device's data changes the locations."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_LOCATIONS, self._locations_changed)
        )

    @callback
    def _locations_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Online clients whose location is this device and that match."""
        locations = get_hub(self.hass).locations.values()
        return sum(
            1
            for loc in locations
            if loc.online and loc.source == self._entry_id and self._match(loc)
        )


# Names of SRM's local networks (measured on an RT2600ac and an MR2200ac); any other interface
# keeps its own name.
NETWORK_KEYS = {"lbr0": "dhcp_pool_lan", "gbr0": "dhcp_pool_guest"}

type AddressRange = tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]


def dhcp_pools(data: SlowData) -> dict[str, DhcpServer]:
    """DHCP servers that hand out IPv4 addresses, by interface."""
    servers = data.dhcp_servers.data if data.dhcp_servers else ()
    return {
        s.ifname: s
        for s in servers
        if s.ifname and s.ipv4 and s.ipv4.enable is not False and s.ipv4.begin and s.ipv4.end
    }


def pool_range(server: DhcpServer) -> AddressRange | None:
    """First and last address of a pool, or None if SRM's values are not usable."""
    try:
        begin = ipaddress.IPv4Address(server.ipv4.begin if server.ipv4 else "")
        end = ipaddress.IPv4Address(server.ipv4.end if server.ipv4 else "")
    except ValueError:
        return None
    return (begin, end) if begin <= end else None


def _in(ip: str | None, pool: AddressRange) -> bool:
    try:
        address = ipaddress.IPv4Address(ip or "")
    except ValueError:
        return False
    return pool[0] <= address <= pool[1]


def pool_usage(data: SlowData, server: DhcpServer) -> float | None:
    """Share of the pool's addresses that are leased or reserved, in percent."""
    pool = pool_range(server)
    if pool is None or data.leases is None:
        return None  # nothing known about the leases is not an empty pool
    lists = [
        data.leases.client_list,
        data.reservations.reservation_list if data.reservations else None,
    ]
    used = {
        item.ip
        for entries in lists
        for item in (entries.ipv4 if entries else ())
        if _in(item.ip, pool)
    }
    return round(100 * len(used) / (int(pool[1]) - int(pool[0]) + 1), 1)


def usb_volumes(data: SlowData) -> dict[str, StorageVolume]:
    """USB volumes by path."""
    volumes = data.usb.volumes if data.usb else ()
    return {v.volume_path: v for v in volumes if v.volume_path}


@callback
def _add_dynamic(
    hass: HomeAssistant, entry: SrmConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add sensors for firewall rules, DHCP pools and USB volumes as they appear.

    Hits sensors exist only with the option "firewall_hits". A rule that is gone (deleted, or
    edited, which gives it a new key) loses its sensor, and gets one again if it returns; a DHCP
    pool or USB volume that is gone leaves its sensor unavailable, since it may come back.
    """
    runtime = entry.runtime_data
    slow = runtime.slow
    with_hits = runtime.is_router and bool(entry.options.get(CONF_FIREWALL_HITS, False))
    rules_added: set[str] = set()
    added: set[str] = set()

    @callback
    def _update() -> None:
        data = slow.data
        new: list[SensorEntity] = []
        if data.firewall is not None or not with_hits:
            current = set(data.rules) if with_hits else set()
            # Remove first, so an edited rule's new sensor does not get a "_2" entity ID.
            _remove_rules(hass, entry, {f"{entry.unique_id}_firewall_rule_{k}" for k in current})
            rules_added.intersection_update(current)
        if with_hits:
            for key, rule in data.rules.items():
                if key not in rules_added:
                    rules_added.add(key)
                    new.append(SrmFirewallHitsSensor(entry, key, rule))
        if runtime.is_router:
            for ifname in dhcp_pools(data):
                if f"pool_{ifname}" not in added:
                    added.add(f"pool_{ifname}")
                    new.append(SrmDhcpPoolSensor(entry, ifname))
        for path, volume in usb_volumes(data).items():
            if f"usb_{path}" not in added:
                added.add(f"usb_{path}")
                new += [SrmUsbSensor(entry, path, volume, kind) for kind in USB_SENSORS]
        if new:
            async_add_entities(new)

    _update()
    entry.async_on_unload(slow.async_add_listener(_update))


@callback
def _remove_rules(hass: HomeAssistant, entry: SrmConfigEntry, current: set[str]) -> None:
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_firewall_rule_"
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.unique_id.startswith(prefix) and item.unique_id not in current:
            registry.async_remove(item.entity_id)


class SrmFirewallHitsSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """Packets one firewall rule matched since SRM last built its firewall."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "packets"
    # What the rule does stays out of the history: addresses, ports and lists of countries.
    _unrecorded_attributes = frozenset(
        {"enabled", "action", "ip_version", "protocol", "chain", "source", "destination", "ports"}
    )

    def __init__(self, entry: SrmConfigEntry, key: str, rule: FirewallRule) -> None:
        """Bind the sensor to one rule; switched-off rules start disabled."""
        super().__init__(
            entry,
            entry.runtime_data.slow,
            SensorEntityDescription(
                key=f"firewall_rule_{key}",
                translation_key="firewall_hits",
                entity_registry_enabled_default=rule.enabled is not False,
            ),
        )
        self._key = key
        rules = entry.runtime_data.slow.data.rules.values()
        self._attr_translation_placeholders = {"rule": rule_label(rule, rules)}

    @property
    def _rule(self) -> FirewallRule | None:
        return self.coordinator.data.rules.get(self._key)

    @property
    def available(self) -> bool:
        """Unavailable while the rule is not in the last list."""
        return super().available and self._rule is not None

    @property
    def native_value(self) -> int | None:
        """The rule's packet counter; unknown when the counters could not be read."""
        rule, hits = self._rule, self.coordinator.data.hits
        if rule is None or hits is None or rule.ui_id is None:
            return None
        return hits.get(rule.ui_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the rule does, as SRM lists it."""
        rule = self._rule
        if rule is None:
            return {}
        return {
            "enabled": rule.enabled,
            "action": rule.action,
            "ip_version": rule.ip_version,
            "protocol": rule.protocol,
            "chain": rule.chain,
            "source": rule.src_ip_value,
            "destination": rule.dst_ip_value,
            "ports": rule.dst_port_value,
        }


class SrmDhcpPoolSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """How full one network's IPv4 DHCP pool is: leased or reserved addresses in it."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"begin", "end"})

    def __init__(self, entry: SrmConfigEntry, ifname: str) -> None:
        """Bind the sensor to the DHCP server of one interface."""
        translation_key = NETWORK_KEYS.get(ifname, "dhcp_pool")
        super().__init__(
            entry,
            entry.runtime_data.slow,
            SensorEntityDescription(key=f"dhcp_pool_{ifname}", translation_key=translation_key),
        )
        self._ifname = ifname
        self._attr_translation_placeholders = {"network": ifname}

    @property
    def _server(self) -> DhcpServer | None:
        return dhcp_pools(self.coordinator.data).get(self._ifname)

    @property
    def available(self) -> bool:
        """Unavailable while the pool is not configured."""
        return super().available and self._server is not None

    @property
    def native_value(self) -> float | None:
        """Leased or reserved share of the pool."""
        server = self._server
        return pool_usage(self.coordinator.data, server) if server else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The pool's range."""
        server = self._server
        if server is None or server.ipv4 is None:
            return {}
        return {"begin": server.ipv4.begin, "end": server.ipv4.end}


@dataclass(frozen=True, kw_only=True)
class SrmUsbSensorDescription(SensorEntityDescription):
    """One value of a USB volume."""

    value_fn: Callable[[StorageVolume], Any]


USB_SENSORS: tuple[SrmUsbSensorDescription, ...] = (
    SrmUsbSensorDescription(
        key="usb_used",
        translation_key="usb_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=helpers.used_percent,
    ),
    SrmUsbSensorDescription(
        key="usb_free",
        translation_key="usb_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.size_free_byte,
    ),
    SrmUsbSensorDescription(
        key="usb_size",
        translation_key="usb_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda v: v.size_total_byte,
    ),
)


class SrmUsbSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """Space on one USB volume."""

    entity_description: SrmUsbSensorDescription

    def __init__(
        self,
        entry: SrmConfigEntry,
        path: str,
        volume: StorageVolume,
        description: SrmUsbSensorDescription,
    ) -> None:
        """Bind the sensor to one volume, by its path; named as in SRM, else by its folder."""
        super().__init__(
            entry,
            entry.runtime_data.slow,
            dataclasses.replace(description, key=f"{description.key}_{path}"),
        )
        self._path = path
        name = volume.display_name or path.rstrip("/").rsplit("/", 1)[-1] or path
        self._attr_translation_placeholders = {"volume": name}

    @property
    def _volume(self) -> StorageVolume | None:
        return usb_volumes(self.coordinator.data).get(self._path)

    @property
    def available(self) -> bool:
        """Unavailable while the volume is not attached."""
        return super().available and self._volume is not None

    @property
    def native_value(self) -> Any:
        """The current value."""
        volume = self._volume
        return self.entity_description.value_fn(volume) if volume else None
