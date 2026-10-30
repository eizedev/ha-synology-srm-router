"""Ethernet ports of one SRM device, as the entities show them."""

from __future__ import annotations

import re

from aiosynologysrm import EthPort

from .coordinator import FastData

_LAN = re.compile(r"lp(\d+)")


def port_label(port: str) -> str:
    """Return a port as printed on the device: ``wp1`` is WAN, ``lp2`` is LAN 2."""
    if port == "wp1":
        return "WAN"
    if match := _LAN.fullmatch(port):
        return f"LAN {match[1]}"
    return port


def own_ports(data: FastData) -> dict[str, EthPort]:
    """Return the device's own ports by SRM's name; in a mesh, other nodes are left out.

    The device itself is node 0: a standalone router or access point lists only itself, a mesh
    router lists its mesh points too, which are separate devices.
    """
    if data.ports is None:
        return {}
    node = next((n for n in data.ports.nodes if n.node_id == 0), None)
    if node is None:
        return {}
    return {p.port: p for p in node.eth_port_info if p.port}
