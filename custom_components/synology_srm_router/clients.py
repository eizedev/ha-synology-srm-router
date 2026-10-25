"""Clients across all entries: their best name, whether they matter, and when they were last seen.

SRM keeps every client it ever saw in its device list, without a "last seen" time. A client
matters (is offered first and tracked by "all") when it is online, has a name given in SRM, has an
IPv4 DHCP lease or reservation, or was seen online by this integration within RECENTLY_SEEN.
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
    """The router has an IPv4 DHCP lease or reservation for its MAC address.

    DHCPv6 does not count: the MAC inside a DUID of type LLT is the one the client had when it
    created the DUID, possibly of another interface, so it can name an old entry of the device.
    """
    last_seen: datetime | None

    def relevant(self, now: datetime) -> bool:
        """Whether the client is offered first and tracked by "all"."""
        recent = self.last_seen is not None and now - self.last_seen <= RECENTLY_SEEN
        return self.online or self.named or self.dhcp or recent


@dataclass(frozen=True, kw_only=True)
class DhcpAddress:
    """What SRM's DHCP server knows about a client: lease first, else reservation."""

    ip: str | None = None
    ip6: str | None = None


# DHCPv6 DUIDs that carry the MAC (RFC 8415): type and hardware type (1 = Ethernet), then the MAC.
DUID_LLT_ETHERNET, DUID_LLT_LENGTH = b"\x00\x01\x00\x01", 14  # with 4 bytes of time
DUID_LL_ETHERNET, DUID_LL_LENGTH = b"\x00\x03\x00\x01", 10


def duid_mac(duid: str | None) -> str | None:
    """Return the MAC address inside a DHCPv6 DUID of type LLT or LL (Ethernet), else None.

    LLT: 00:01, hardware type 00:01, 4 bytes of time, the MAC; LL: 00:03, 00:01, the MAC. A DUID
    is created once, so for LLT this can be the MAC of another or an earlier interface (RFC 8415).
    """
    try:
        raw = bytes.fromhex((duid or "").replace(":", "").replace("-", ""))
    except ValueError:
        return None
    if raw[:4] == DUID_LLT_ETHERNET and len(raw) == DUID_LLT_LENGTH:
        return helpers.normalize_mac(raw[8:].hex())
    if raw[:4] == DUID_LL_ETHERNET and len(raw) == DUID_LL_LENGTH:
        return helpers.normalize_mac(raw[4:].hex())
    return None


def dhcp_addresses(
    clients: DhcpClients | None, reservations: DhcpReservations | None
) -> dict[str, DhcpAddress]:
    """Addresses by MAC from leases and reservations (IPv4 by MAC, IPv6 by the MAC in the DUID).

    SRM's client list leaves out many addresses its own DHCP server handed out; these fill in.
    """
    found: dict[str, dict[str, str | None]] = {}
    lists = [
        (clients.client_list if clients else None),
        (reservations.reservation_list if reservations else None),
    ]
    for entries in lists:  # leases first: they are what the client really uses
        if entries is None:
            continue
        for entry in entries.ipv4:
            if (mac := helpers.normalize_mac(entry.clid)) and entry.ip:
                found.setdefault(mac, {}).setdefault("ip", entry.ip)
        for entry in entries.ipv6:
            if (mac := duid_mac(entry.clid)) and (ip6 := usable_ipv6(entry.ip)):
                found.setdefault(mac, {}).setdefault("ip6", ip6)
    return {mac: DhcpAddress(ip=a.get("ip"), ip6=a.get("ip6")) for mac, a in found.items()}


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
    dhcp: Mapping[str, DhcpAddress],
    last_seen: Mapping[str, datetime],
) -> dict[str, Client]:
    """Merge the device lists of all entries, routers first.

    A name given in SRM wins wherever it is set, then the first reported host name: an access
    point only sees what a client reports about itself, the router also the names given there.
    Addresses the lists leave out come from the router's DHCP leases and reservations.
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
    none = DhcpAddress()
    return {
        mac: Client(
            mac=mac,
            name=item["name"],  # type: ignore[arg-type]
            ip=item["ip"] or dhcp.get(mac, none).ip,  # type: ignore[arg-type]
            ip6=item["ip6"] or dhcp.get(mac, none).ip6,  # type: ignore[arg-type]
            online=bool(item["online"]),
            named=bool(item["named"]),
            dhcp=dhcp.get(mac, none).ip is not None,
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
