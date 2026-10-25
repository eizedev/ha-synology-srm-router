"""Firewall rules: a key that survives moving and switching a rule, labels, and table rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aiosynologysrm import FirewallRule, helpers

# A rule is identified by what it does, not by its position (``ui_id``) or switch.
RULE_IDENTITY_IGNORE = frozenset({"ui_id", "enabled"})


def rule_keys(rules: Iterable[FirewallRule]) -> dict[str, FirewallRule]:
    """Rules by a key from their content, in SRM's order; identical rules get a running number.

    Editing a rule (also its name) gives it a new key.
    """
    keyed: dict[str, FirewallRule] = {}
    for rule in rules:
        digest = helpers.config_hash([rule.raw], ignore=RULE_IDENTITY_IGNORE)[:12]
        key, number = digest, 1
        while key in keyed:
            number += 1
            key = f"{digest}_{number}"
        keyed[key] = rule
    return keyed


def rule_label(rule: FirewallRule, rules: Iterable[FirewallRule]) -> str:
    """Return the rule's name, with its IP version when another rule has the same name."""
    name = rule.name or f"#{rule.ui_id}"
    if sum(1 for other in rules if other.name == rule.name) > 1:
        version = {"v4": "IPv4", "v6": "IPv6"}.get(rule.ip_version or "")
        if version:
            return f"{name} ({version})"
    return name


def rule_rows(
    keyed: Mapping[str, FirewallRule], hits: Mapping[int, int] | None
) -> list[dict[str, Any]]:
    """One row per rule for tables, in SRM's order.

    ``duplicate`` marks a rule with the same content as an earlier one: the earlier one matches
    first, so the duplicate never does.
    """
    rows = []
    for key, rule in keyed.items():
        count = hits.get(rule.ui_id) if hits is not None and rule.ui_id is not None else None
        rows.append(
            {
                "name": rule.name,
                "label": rule_label(rule, keyed.values()),
                "enabled": rule.enabled,
                "action": rule.action,
                "ip_version": rule.ip_version,
                "protocol": rule.protocol,
                # input: to the router itself; forward: through it; both_input_forward: both.
                "chain": rule.chain,
                "in_interfaces": _interfaces(rule.in_interface_type, rule.in_interface_value),
                "out_interfaces": _interfaces(rule.out_interface_type, rule.out_interface_value),
                "source": rule.src_ip_value,
                "destination": rule.dst_ip_value,
                "ports": rule.dst_port_value,
                "hits": count,
                "duplicate": "_" in key,
            }
        )
    return rows


def _interfaces(kind: str | None, values: tuple[str, ...]) -> list[str] | None:
    """Return the interfaces a rule is limited to (``lan``, ``wan``, ...), or None for any."""
    return list(values) if kind == "specific" and values else None
