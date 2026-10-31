"""Repairs for router settings that weaken it; read only, each explains what to change in SRM."""

from __future__ import annotations

from collections.abc import Callable, Collection

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOCS_URL, DOMAIN
from .coordinator import SlowData

# Traffic from the internet that no firewall rule matches; "allow" lets it in. Recorded routers
# answer "allow" or "deny"; any other value counts as not allowing.
WAN_POLICIES = ("ipv4_wan_to_lan", "ipv4_wan_to_srm", "ipv6_wan_to_lan", "ipv6_wan_to_srm")


def _srm_from_internet(data: SlowData) -> bool | None:
    return data.allow_wan.enable if data.allow_wan else None


def _auto_block_off(data: SlowData) -> bool | None:
    if data.auto_block is None or data.auto_block.enable is None:
        return None
    return not data.auto_block.enable


def _firewall_open(data: SlowData) -> bool | None:
    policy = data.firewall.default_policy if data.firewall else None
    if policy is None:
        return None
    return any(getattr(policy, name) == "allow" for name in WAN_POLICIES)


# Whether each risk applies; None while the setting is not known, which keeps the repair as it is.
RISKS: dict[str, Callable[[SlowData], bool | None]] = {
    "srm_from_internet": _srm_from_internet,
    "auto_block_off": _auto_block_off,
    "firewall_open": _firewall_open,
}
# The read each risk comes from; without it (an access point, or firmware that lacks the read)
# the risk is not checked and its repair goes.
READS = {
    "srm_from_internet": "get_allow_srm_from_wan",
    "auto_block_off": "get_auto_block",
    "firewall_open": "get_firewall_rules",
}


def _issue_id(key: str, entry: ConfigEntry) -> str:
    return f"{key}_{entry.entry_id}"


def update_risk_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: SlowData,
    *,
    is_router: bool,
    supported: Collection[str],
) -> None:
    """Raise a repair for each risky setting, and remove it once the setting is safe.

    A repair stays while its setting cannot be read, so one the user ignored stays ignored. Only
    routers are checked: a device switched to access point loses its repairs.
    """
    for key, check in RISKS.items():
        risky = check(data) if is_router and READS[key] in supported else False
        if risky is None:
            continue
        if risky:
            ir.async_create_issue(
                hass,
                DOMAIN,
                _issue_id(key, entry),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders={"name": entry.title},
                learn_more_url=f"{DOCS_URL}repairs/{key.replace('_', '-')}/",
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, _issue_id(key, entry))


def delete_risk_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove every risk repair of an entry; done when the entry is removed."""
    for key in RISKS:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(key, entry))
