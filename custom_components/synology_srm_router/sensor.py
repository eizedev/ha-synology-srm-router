"""Sensors: load, traffic, clients, WAN, DHCP, firewall hits and USB storage of an SRM device."""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
    attributes_fn: Callable[[SlowData], dict[str, Any]] | None = None


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


def _firewall_attributes(data: SlowData) -> dict[str, Any]:
    if data.firewall is None:
        return {}
    # Changes whenever a rule is added, removed, edited, switched or moved.
    return {"config_hash": helpers.config_hash(rule.raw for rule in data.firewall.rules)}


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
        requires="get_dhcp_clients",
        router_only=True,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ipv4_count(d.leases),
    ),
    SrmSlowSensorDescription(
        key="dhcp_reservations",
        translation_key="dhcp_reservations",
        requires="get_dhcp_reservations",
        router_only=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _ipv4_count(d.reservations),
    ),
    SrmSlowSensorDescription(
        key="firewall_rules",
        translation_key="firewall_rules",
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
    entities.append(SrmClientsSensor(entry))
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

    @property
    def native_value(self) -> Any:
        """The current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra values some sensors carry, such as the firewall's configuration hash."""
        attributes_fn = self.entity_description.attributes_fn
        return attributes_fn(self.coordinator.data) if attributes_fn else None


class SrmClientsSensor(SrmEntity[SrmFastCoordinator], SensorEntity):
    """How many clients are attached to this device, by Wi-Fi or cable, across all entries."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: SrmConfigEntry) -> None:
        """Count from the shared client locations."""
        super().__init__(
            entry,
            entry.runtime_data.fast,
            SensorEntityDescription(key="clients", translation_key="clients"),
        )
        self._entry_id = entry.entry_id

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
        """Online clients whose location is this device."""
        locations = get_hub(self.hass).locations.values()
        return sum(1 for loc in locations if loc.online and loc.source == self._entry_id)


# Names of SRM's local networks; any other interface keeps its own name.
NETWORK_KEYS = {"lbr0": "dhcp_pool_lan", "gbr0": "dhcp_pool_guest"}
# A firewall rule is identified by what it does, not by its position (``ui_id``) or switch.
RULE_IDENTITY_IGNORE = frozenset({"ui_id", "enabled"})


def firewall_rules(data: SlowData) -> dict[str, FirewallRule]:
    """Rules by a key from their content; identical rules get a running number."""
    rules: dict[str, FirewallRule] = {}
    for rule in data.firewall.rules if data.firewall else ():
        digest = helpers.config_hash([rule.raw], ignore=RULE_IDENTITY_IGNORE)[:12]
        key, number = digest, 1
        while key in rules:
            number += 1
            key = f"{digest}_{number}"
        rules[key] = rule
    return rules


def rule_label(rule: FirewallRule, rules: Iterable[FirewallRule]) -> str:
    """Return the rule's name, with its IP version when another rule has the same name."""
    name = rule.name or f"#{rule.ui_id}"
    if sum(1 for other in rules if other.name == rule.name) > 1:
        version = {"v4": "IPv4", "v6": "IPv6"}.get(rule.ip_version or "")
        if version:
            return f"{name} ({version})"
    return name


def dhcp_pools(data: SlowData) -> dict[str, DhcpServer]:
    """DHCP servers with an IPv4 pool, by interface."""
    servers = data.dhcp_servers.data if data.dhcp_servers else ()
    return {s.ifname: s for s in servers if s.ifname and s.ipv4 and s.ipv4.begin and s.ipv4.end}


def pool_usage(data: SlowData, server: DhcpServer) -> float | None:
    """Share of the pool's addresses that are leased or reserved, in percent."""
    try:
        begin = ipaddress.IPv4Address(server.ipv4.begin if server.ipv4 else "")
        end = ipaddress.IPv4Address(server.ipv4.end if server.ipv4 else "")
    except ValueError:
        return None
    size = int(end) - int(begin) + 1
    if size <= 0:
        return None
    lists = [
        data.leases.client_list if data.leases else None,
        data.reservations.reservation_list if data.reservations else None,
    ]
    used: set[ipaddress.IPv4Address] = set()
    for entries in lists:
        for item in entries.ipv4 if entries else ():
            try:
                address = ipaddress.IPv4Address(item.ip or "")
            except ValueError:
                continue
            if begin <= address <= end:
                used.add(address)
    return round(100 * len(used) / size, 1)


def usb_volumes(data: SlowData) -> dict[str, StorageVolume]:
    """USB volumes by path."""
    volumes = data.usb.volumes if data.usb else ()
    return {v.volume_path: v for v in volumes if v.volume_path}


@callback
def _add_dynamic(
    hass: HomeAssistant, entry: SrmConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add sensors for firewall rules, DHCP pools and USB volumes as they appear.

    A firewall rule that is gone (deleted or edited, which gives it a new key) loses its sensor;
    a DHCP pool or a USB volume that is gone leaves its sensor unavailable, since it may return.
    """
    runtime = entry.runtime_data
    slow = runtime.slow
    added: set[str] = set()

    @callback
    def _update() -> None:
        data = slow.data
        new: list[SensorEntity] = []
        rules = firewall_rules(data) if runtime.is_router else {}
        for key, rule in rules.items():
            if f"rule_{key}" not in added:
                added.add(f"rule_{key}")
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
        if data.firewall is not None:
            _remove_rules(hass, entry, {f"{entry.unique_id}_firewall_rule_{key}" for key in rules})

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
        rules = entry.runtime_data.slow.data.firewall
        self._attr_translation_placeholders = {
            "rule": rule_label(rule, rules.rules if rules else ())
        }

    @property
    def _rule(self) -> FirewallRule | None:
        return firewall_rules(self.coordinator.data).get(self._key)

    @property
    def available(self) -> bool:
        """Unavailable while the rule is not in the last list."""
        return super().available and self._rule is not None

    @property
    def native_value(self) -> int | None:
        """The rule's packet counter."""
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
            "source": rule.src_ip_value,
            "destination": rule.dst_ip_value,
            "ports": rule.dst_port_value,
        }


class SrmDhcpPoolSensor(SrmEntity[SrmSlowCoordinator], SensorEntity):
    """How full one network's IPv4 DHCP pool is: leased or reserved addresses in it."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

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
        return {"begin": server.ipv4.begin, "end": server.ipv4.end, "enabled": server.ipv4.enable}


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
        suggested_display_precision=1,
        value_fn=lambda v: (
            100 * (v.size_total_byte - v.size_free_byte) / v.size_total_byte
            if v.size_total_byte and v.size_free_byte is not None
            else None
        ),
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
        """Bind the sensor to one volume, by its path."""
        super().__init__(
            entry,
            entry.runtime_data.slow,
            dataclasses.replace(description, key=f"{description.key}_{path}"),
        )
        self._path = path
        self._attr_translation_placeholders = {"volume": volume.display_name or path}

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
