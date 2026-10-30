"""The integration against the real library client: the parts the fake client stands in for."""

from __future__ import annotations

import inspect

from aiosynologysrm import SrmClient
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.synology_srm_router import GETTERS
from custom_components.synology_srm_router.coordinator import SLOW_READS

from .conftest import FakeClient

APIS = (
    "SYNO.Core.System",
    "SYNO.Core.System.Utilization",
    "SYNO.Core.Network.NSM.Device",
    "SYNO.Core.Network.Router.Topology",
    "SYNO.Core.Network.Router.ConnectionStatus",
    "SYNO.Core.DDNS.ExtIP",
    "SYNO.Core.Network.DHCPServer",
    "SYNO.Core.Network.DHCPServer.ClientList",
    "SYNO.Core.Network.DHCPServer.Reservation",
    "SYNO.Core.Security.Firewall.Rules",
    "SYNO.Core.Security.Firewall.Rules.HitCount",
    "SYNO.Core.Network.IPv6.Router.Prefix",
    "SYNO.Core.Security.Firewall.AllowSrmFromWan",
    "SYNO.Core.Security.AutoBlock",
    "SYNO.Core.Storage.Volume",
    "SYNO.Wifi.Device",
    "SYNO.Wifi.Radio.Setting",
    "SYNO.Wifi.Radio.Status",
    "SYNO.Wifi.Network.Setting",
    "SYNO.Mesh.Network.EthPortInfo",
)
HOST, PORT = "192.0.2.1", 8000


def _catalog(*missing: str) -> dict[str, object]:
    entries = {
        api: {"minVersion": 1, "maxVersion": 5, "path": "entry.cgi"}
        for api in APIS
        if api not in missing
    }
    return {"success": True, "data": entries}


def _client(hass: HomeAssistant) -> SrmClient:
    return SrmClient(
        HOST, "user", "secret", session=async_get_clientsession(hass), port=PORT, use_https=False
    )


def _reads() -> list[str]:
    return [*GETTERS, *(getter for _, getter, _ in SLOW_READS), "get_system_info", "get_topology"]


def test_the_fake_client_offers_what_the_real_one_does() -> None:
    # Every read the integration uses exists on the real client, as a coroutine, and the fake
    # client in conftest.py stands in for each of them.
    for name in _reads():
        assert inspect.iscoroutinefunction(getattr(SrmClient, name)), name
        assert inspect.iscoroutinefunction(getattr(FakeClient, name)), name


async def test_supports_resolves_every_read_by_name(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    # The integration asks `supports(client.get_x)` for each read; the real client finds the read
    # by the getter's name, so a renamed getter would show here, not only on a router.
    aioclient_mock.post(f"http://{HOST}:{PORT}/webapi/query.cgi", json=_catalog())
    client = _client(hass)
    for name in _reads():
        assert await client.supports(getattr(client, name)), name


async def test_a_missing_api_is_not_supported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"http://{HOST}:{PORT}/webapi/query.cgi",
        json=_catalog("SYNO.Core.Security.Firewall.Rules", "SYNO.Core.Storage.Volume"),
    )
    client = _client(hass)
    assert not await client.supports(client.get_firewall_rules)
    assert not await client.supports(client.get_usb_volumes)
    assert await client.supports(client.get_network_devices)
