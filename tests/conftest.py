"""A fake SRM client fed by anonymized answers of a real RT2600ac (router) and MR2200ac (AP)."""

from __future__ import annotations

from collections.abc import Generator
import dataclasses
import json
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import PropertyMock, patch

from aiosynologysrm import (
    AllowSrmFromWan,
    AutoBlock,
    CertificateNames,
    ConnectionStatus,
    DhcpClients,
    DhcpReservations,
    DhcpServers,
    EthPortInfo,
    ExternalIp,
    FirewallHitCount,
    FirewallRules,
    Ipv6Prefixes,
    NetworkDevices,
    SrmCertificateError,
    StorageVolumes,
    SystemInfo,
    Topology,
    Utilization,
    WifiDevices,
    WifiNetworks,
    WifiRadioSettings,
    WifiRadioStatus,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_srm_router.const import (
    CONF_FAST_INTERVAL,
    CONF_FINGERPRINT,
    CONF_IS_ROUTER,
    CONF_SLOW_INTERVAL,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    CONF_USE_HTTPS,
    CONF_VERIFY_CERTIFICATE,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
FINGERPRINT = "ab" * 32
ROUTER_HOST = "192.0.2.1"
AP_HOST = "192.0.2.2"
SERIALS = {"router": "ROUTER0001", "ap": "ACCESS0002"}


def load(folder: str, name: str) -> Any:
    return json.loads((FIXTURES / folder / f"{name}.json").read_text(encoding="utf-8"))


class FakeClient:
    """Answers like a router or AP; tests can set errors per getter."""

    instances: ClassVar[list[FakeClient]] = []

    def __init__(self, host: str, username: str, password: str, **kwargs: Any) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.kwargs = kwargs
        self.folder = "ap" if host == AP_HOST else "router"
        self.errors: dict[str, BaseException] = dict(ERRORS.get(host, {}))
        self.logged_in = False
        FakeClient.instances.append(self)

    def _raise(self, name: str) -> None:
        if name in self.errors:
            raise self.errors[name]

    async def login(self, otp_code: str | None = None) -> None:
        self._raise("login")
        self.logged_in = True

    async def logout(self) -> None:
        self.logged_in = False

    async def supports(self, target: Any) -> bool:
        return getattr(target, "__name__", "") not in UNSUPPORTED.get(self.host, set())

    async def get_system_info(self) -> SystemInfo:
        self._raise("get_system_info")
        info = SystemInfo.from_api(load(self.folder, "system_info"))
        return dataclasses.replace(info, serial=SERIALS[self.folder])

    async def get_topology(self) -> Topology:
        self._raise("get_topology")
        return Topology.from_api(load(self.folder, "topology"))

    async def get_utilization(self) -> Utilization:
        self._raise("get_utilization")
        return Utilization.from_api(load(self.folder, "utilization"))

    async def get_network_devices(self) -> NetworkDevices:
        self._raise("get_network_devices")
        return NetworkDevices.from_api(load(self.folder, "network_devices"))

    async def get_wifi_devices(self) -> WifiDevices:
        self._raise("get_wifi_devices")
        return WifiDevices.from_api(load(self.folder, "wifi_devices"))

    async def get_connection_status(self) -> ConnectionStatus:
        self._raise("get_connection_status")
        return ConnectionStatus.from_api(load(self.folder, "connection_status"))

    async def get_dhcp_clients(self) -> DhcpClients:
        self._raise("get_dhcp_clients")
        return DhcpClients.from_api(load(self.folder, "dhcp_clients"))

    async def get_dhcp_reservations(self) -> DhcpReservations:
        self._raise("get_dhcp_reservations")
        return DhcpReservations.from_api(load(self.folder, "dhcp_reservations"))

    async def get_external_ip(self) -> tuple[ExternalIp, ...]:
        self._raise("get_external_ip")
        return ExternalIp.list_from_api(load(self.folder, "external_ip"))

    async def get_dhcp_servers(self) -> DhcpServers:
        self._raise("get_dhcp_servers")
        return DhcpServers.from_api(load(self.folder, "dhcp_servers"))

    async def get_firewall_rules(self) -> FirewallRules:
        self._raise("get_firewall_rules")
        return FirewallRules.from_api(load(self.folder, "firewall_rules"))

    async def get_firewall_hit_counts(self) -> tuple[FirewallHitCount, ...]:
        self._raise("get_firewall_hit_counts")
        return FirewallHitCount.list_from_api(load(self.folder, "firewall_hit_counts"))

    async def get_ipv6_prefixes(self) -> Ipv6Prefixes:
        self._raise("get_ipv6_prefixes")
        return Ipv6Prefixes.from_api(load(self.folder, "ipv6_prefixes"))

    async def get_allow_srm_from_wan(self) -> AllowSrmFromWan:
        self._raise("get_allow_srm_from_wan")
        return AllowSrmFromWan.from_api(load(self.folder, "allow_srm_from_wan"))

    async def get_auto_block(self) -> AutoBlock:
        self._raise("get_auto_block")
        return AutoBlock.from_api(load(self.folder, "auto_block"))

    async def get_usb_volumes(self) -> StorageVolumes:
        self._raise("get_usb_volumes")
        return StorageVolumes.from_api(load(self.folder, "usb_volumes"))

    async def get_wifi_radio_settings(self) -> WifiRadioSettings:
        self._raise("get_wifi_radio_settings")
        return WifiRadioSettings.from_api(load(self.folder, "wifi_radio_settings"))

    async def get_wifi_radio_status(self) -> WifiRadioStatus:
        self._raise("get_wifi_radio_status")
        return WifiRadioStatus.from_api(load(self.folder, "wifi_radio_status"))

    async def get_eth_port_info(self) -> EthPortInfo:
        self._raise("get_eth_port_info")
        return EthPortInfo.from_api(load(self.folder, "eth_port_info"))

    async def get_wifi_networks(self) -> WifiNetworks:
        self._raise("get_wifi_networks")
        return WifiNetworks.from_api(load(self.folder, "wifi_networks"))


ERRORS: dict[str, dict[str, BaseException]] = {}
UNSUPPORTED: dict[str, set[str]] = {}
FINGERPRINTS: dict[str, str] = {}  # a certificate other than FINGERPRINT, per host
# Hosts whose certificate a public authority vouches for: its DNS names. Others are self-signed.
TRUSTED: dict[str, tuple[str, ...]] = {}
ISSUER = "Example CA (E1)"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components in every test."""


@pytest.fixture(autouse=True)
def no_deprecated_usage(caplog: pytest.LogCaptureFixture) -> Generator[None]:
    """Fail on Home Assistant's report of deprecated usage; it only logs it for us."""
    yield
    reports = [
        r.getMessage()
        for r in caplog.get_records("call")
        if r.name == "homeassistant.helpers.frame" and DOMAIN in r.getMessage()
    ]
    assert not reports


@pytest.fixture(autouse=True)
def fake_client() -> Generator[type[FakeClient]]:
    """Replace the library client and the fingerprint lookup."""
    FakeClient.instances = []
    ERRORS.clear()
    UNSUPPORTED.clear()
    FINGERPRINTS.clear()
    TRUSTED.clear()

    async def fingerprint(host: str, port: int, **kwargs: Any) -> str:
        if "fingerprint" in ERRORS.get(host, {}):
            raise ERRORS[host]["fingerprint"]
        name = kwargs.get("server_hostname")
        if name is not None and name not in TRUSTED.get(host, ()):
            raise SrmCertificateError("not valid for this name")
        return FINGERPRINTS.get(host, FINGERPRINT)

    async def names(host: str, port: int, **_: Any) -> CertificateNames:
        if host not in TRUSTED:
            raise SrmCertificateError("self-signed")
        return CertificateNames(names=TRUSTED[host], issuer=ISSUER)

    with (
        patch("custom_components.synology_srm_router.SrmClient", FakeClient),
        patch(
            "custom_components.synology_srm_router.config_flow.get_certificate_fingerprint",
            fingerprint,
        ),
        patch(
            "custom_components.synology_srm_router.config_flow.get_certificate_names",
            names,
        ),
        patch(
            "custom_components.synology_srm_router.diagnostics.collect_diagnostics",
            return_value={"library": "test"},
        ),
    ):
        yield FakeClient


def make_entry(kind: str = "router", **options: Any) -> MockConfigEntry:
    host = AP_HOST if kind == "ap" else ROUTER_HOST
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"{kind} ({host})",
        unique_id=SERIALS[kind],
        data={
            "host": host,
            "port": 8001,
            CONF_USE_HTTPS: True,
            "username": "homeassistant",
            "password": "secret",
            CONF_FINGERPRINT: FINGERPRINT,
            CONF_VERIFY_CERTIFICATE: True,
            CONF_IS_ROUTER: kind == "router",
        },
        options={
            CONF_TRACK_ALL: False,
            CONF_TRACKED: [],
            CONF_FAST_INTERVAL: 30,
            CONF_SLOW_INTERVAL: 300,
            **options,
        },
    )


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Create entities that are disabled by default as enabled, to test what they show."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield
