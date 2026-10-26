"""Diagnostics: what the device offers and answers, without addresses, names or secrets."""

from __future__ import annotations

from typing import Any

from aiosynologysrm.diagnostics import collect_diagnostics
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_CERTIFICATE_NAME, CONF_FINGERPRINT, CONF_TRACKED
from .coordinator import SrmConfigEntry, get_hub

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_FINGERPRINT, CONF_CERTIFICATE_NAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SrmConfigEntry
) -> dict[str, Any]:
    """Report the entry's settings and the library's value-free diagnostics."""
    runtime = entry.runtime_data
    options = dict(entry.options)
    options[CONF_TRACKED] = len(options.get(CONF_TRACKED, []))  # how many, not which
    locations = get_hub(hass).locations.values()
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": options},
        "topology": runtime.topology.net_topology,
        "supported": sorted(runtime.supported),
        "fast_update_ok": runtime.fast.last_update_success,
        "slow_update_ok": runtime.slow.last_update_success,
        "locations": {
            "here": sum(1 for loc in locations if loc.source == entry.entry_id and loc.online),
            "incomplete": any(loc.incomplete for loc in locations),
        },
        "device": await collect_diagnostics(runtime.client, counts=True),
    }
