"""Changes of a router's IPv6 prefixes and firewall, compared with what was last seen.

A snapshot holds only what a change is judged by: the prefix of each local network, the rules by
their content key with name and switch, and the default policies. Lifetimes and hit counters
change on every read and are left out. The snapshot is stored, so a change made while Home
Assistant was not running is still found.
"""

from __future__ import annotations

from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import STORE_VERSION, SlowData
from .firewall import rule_label

EVENT_PREFIX_CHANGED = "prefix_changed"
EVENT_FIREWALL_CHANGED = "firewall_changed"
# SRM's local networks (measured on an RT2600ac); any other interface keeps its own name.
NETWORK_NAMES = {"lbr0": "lan", "gbr0": "guest"}


class Snapshot(TypedDict):
    """What was last seen; a part is None while it was never read."""

    prefixes: dict[str, str] | None
    rules: list[list[Any]] | None
    """[key, label, enabled] per rule, in SRM's order."""
    policy: dict[str, str] | None


def network_name(interface: str) -> str:
    """Return ``lan`` or ``guest`` for SRM's own networks, else the interface name."""
    return NETWORK_NAMES.get(interface, interface)


def used_prefixes(data: SlowData) -> dict[str, str] | None:
    """Return the delegated prefix of each local network, by network name.

    Prefixes from the delegated range that no network uses are left out.
    """
    if data.prefixes is None:
        return None
    return {
        network_name(item.lan): item.prefix
        for item in data.prefixes.prefix
        if item.lan and item.prefix
    }


def snapshot(data: SlowData, previous: Snapshot | None) -> Snapshot:
    """Take what matters from the current data; a part not read keeps its previous value."""
    prefixes = used_prefixes(data)
    rules: list[list[Any]] | None = None
    policy: dict[str, str] | None = None
    if data.firewall is not None:
        all_rules = data.firewall.rules
        rules = [
            [key, rule_label(rule, all_rules), rule.enabled is not False]
            for key, rule in data.rules.items()
        ]
        defaults = data.firewall.default_policy
        policy = {k: str(v) for k, v in (defaults.raw if defaults else {}).items() if v}
    return Snapshot(
        prefixes=prefixes if prefixes is not None else previous and previous["prefixes"],
        rules=rules if rules is not None else previous and previous["rules"],
        policy=policy if policy is not None else previous and previous["policy"],
    )


def changes(old: Snapshot, new: Snapshot) -> list[tuple[str, dict[str, Any]]]:
    """Return the events between two snapshots: at most one per kind."""
    events: list[tuple[str, dict[str, Any]]] = []
    if old["prefixes"] is not None and new["prefixes"] is not None:
        before, after = old["prefixes"], new["prefixes"]
        changed = [
            {"network": network, "prefix": after.get(network), "previous": before.get(network)}
            for network in sorted(before.keys() | after.keys())
            if before.get(network) != after.get(network)
        ]
        if changed:
            events.append((EVENT_PREFIX_CHANGED, {"changes": changed}))
    if old["rules"] is not None and new["rules"] is not None:
        firewall = _firewall_changes(old, new)
        if firewall is not None:
            events.append((EVENT_FIREWALL_CHANGED, firewall))
    return events


def _firewall_changes(old: Snapshot, new: Snapshot) -> dict[str, Any] | None:
    before = {key: (label, enabled) for key, label, enabled in old["rules"] or ()}
    after = {key: (label, enabled) for key, label, enabled in new["rules"] or ()}
    kept_before = [key for key in before if key in after]
    kept_after = [key for key in after if key in before]
    policy_before, policy_after = old["policy"] or {}, new["policy"] or {}
    result: dict[str, Any] = {
        # An edited rule has a new content key, so it shows as removed and added.
        "added": [after[k][0] for k in after if k not in before],
        "removed": [before[k][0] for k in before if k not in after],
        "enabled": [after[k][0] for k in kept_after if after[k][1] and not before[k][1]],
        "disabled": [after[k][0] for k in kept_after if before[k][1] and not after[k][1]],
        "reordered": kept_before != kept_after,
        # Read together with the rules, so both are known whenever the rules are.
        "policy": [
            {"traffic": t, "policy": policy_after.get(t), "previous": policy_before.get(t)}
            for t in sorted(policy_before.keys() | policy_after.keys())
            if policy_before.get(t) != policy_after.get(t)
        ],
    }
    return result if any(result.values()) else None


def store(hass: HomeAssistant, entry_id: str) -> Store[Snapshot]:
    """Return where an entry's last snapshot is kept."""
    return Store(hass, STORE_VERSION, f"{DOMAIN}.router_events.{entry_id}")
