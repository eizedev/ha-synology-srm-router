"""Clients across all entries: their best name, whether they matter, and when they were last seen.

SRM keeps every client it ever saw in its device list, without a "last seen" time. A client
matters (is offered first and tracked by "all") when it is online, has a name given in SRM, has a
DHCP lease or reservation, or was seen online by this integration within RECENTLY_SEEN.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import ipaddress

from aiosynologysrm import DhcpClients, DhcpReservations, NetworkDevices, helpers
from homeassistant.helpers.selector import SelectOptionDict

from .const import RECENTLY_SEEN


@dataclass(frozen=True, kw_only=True)
class Client:
    """One client as all entries together know it."""

    mac: str
    name: str | None
    ip: str | None
    ip6: str | None
    """An IPv6 address other than link-local, when SRM knows one."""
    online: bool
    named: bool
    """The name was given in SRM (not reported by the client itself)."""
    dhcp: bool
    """The router has a DHCP lease or reservation for it."""
    last_seen: datetime | None

    def relevant(self, now: datetime) -> bool:
        """Whether the client is offered first and tracked by "all"."""
        recent = self.last_seen is not None and now - self.last_seen <= RECENTLY_SEEN
        return self.online or self.named or self.dhcp or recent


def dhcp_macs(clients: DhcpClients | None, reservations: DhcpReservations | None) -> frozenset[str]:
    """MAC addresses with an IPv4 lease or reservation (for IPv4, SRM's ``clid`` is the MAC)."""
    leases = clients.client_list.ipv4 if clients and clients.client_list else ()
    fixed = (
        reservations.reservation_list.ipv4 if reservations and reservations.reservation_list else ()
    )
    clids = [e.clid for e in leases] + [e.clid for e in fixed]
    return frozenset(mac for clid in clids if (mac := helpers.normalize_mac(clid)))


def usable_ipv6(value: str | None) -> str | None:
    """Return an IPv6 address other hosts can reach (not link-local), or None."""
    try:
        address = ipaddress.IPv6Address((value or "").split("/")[0].strip())
    except ValueError:
        return None
    if address.is_link_local or address.is_loopback or address.is_unspecified:
        return None
    return str(address)


def combine(
    lists: Iterable[NetworkDevices | None],
    dhcp: frozenset[str],
    last_seen: Mapping[str, datetime],
) -> dict[str, Client]:
    """Merge the device lists of all entries, routers first.

    A name given in SRM wins wherever it is set, then the first reported host name: an access
    point only sees what a client reports about itself, the router also the names given there.
    """
    found: dict[str, dict[str, object]] = {}
    for devices in lists:
        for device in devices.devices if devices else ():
            mac = helpers.normalize_mac(device.mac)
            if mac is None:
                continue
            item = found.setdefault(
                mac, {"name": None, "ip": None, "ip6": None, "online": False, "named": False}
            )
            if device.is_manual_hostname and device.hostname and not item["named"]:
                item["name"], item["named"] = device.hostname, True
            if item["name"] is None:
                item["name"] = device.hostname
            item["ip"] = item["ip"] or device.ip_addr
            item["ip6"] = item["ip6"] or usable_ipv6(device.ip6_addr)
            item["online"] = bool(item["online"] or device.is_online)
    return {
        mac: Client(
            mac=mac,
            name=item["name"],  # type: ignore[arg-type]
            ip=item["ip"],  # type: ignore[arg-type]
            ip6=item["ip6"],  # type: ignore[arg-type]
            online=bool(item["online"]),
            named=bool(item["named"]),
            dhcp=mac in dhcp,
            last_seen=last_seen.get(mac),
        )
        for mac, item in found.items()
    }


def options(
    clients: Mapping[str, Client], now: datetime, *, show_all: bool, keep: Iterable[str] = ()
) -> list[SelectOptionDict]:
    """Return the choice of clients: relevant ones (or all), online first, then by name.

    ● marks a client online now, ○ one that is not; the date says when it was last seen online.
    Clients in ``keep`` (already chosen) are always listed.
    """
    kept = set(keep)
    shown = [c for c in clients.values() if show_all or c.relevant(now) or c.mac in kept]
    result = []
    for client in sorted(shown, key=lambda c: (not c.online, (c.name or "~").lower(), c.mac)):
        parts = [client.name, client.ip, client.mac]
        if not client.online and client.last_seen:
            parts.append(client.last_seen.date().isoformat())
        label = ("● " if client.online else "○ ") + " / ".join(p for p in parts if p)
        result.append(SelectOptionDict(value=client.mac, label=label))
    known = {c.mac for c in shown}
    result += [SelectOptionDict(value=mac, label=f"○ {mac}") for mac in sorted(kept - known)]
    return result
