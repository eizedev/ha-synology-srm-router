"""Setup, reauth, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import dataclasses
from typing import Any
from unittest.mock import patch

from aiosynologysrm import (
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmConnectionError,
    SrmError,
    SrmPermissionError,
    SrmSessionError,
    SrmTwoFactorRequiredError,
)
from homeassistant.config_entries import SOURCE_USER, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synology_srm_router.const import (
    CONF_FINGERPRINT,
    CONF_SHOW_ALL,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    CONF_USE_HTTPS,
    CONF_VERIFY_CERTIFICATE,
    DOMAIN,
)

from .conftest import (
    AP_HOST,
    ERRORS,
    FINGERPRINT,
    FINGERPRINTS,
    ROUTER_HOST,
    SERIALS,
    UNSUPPORTED,
    FakeClient,
    make_entry,
)

CONNECTION = {
    "host": ROUTER_HOST,
    "port": 8001,
    CONF_USE_HTTPS: True,
    CONF_VERIFY_CERTIFICATE: True,
}
CREDENTIALS = {"username": "homeassistant", "password": "secret"}


@pytest.fixture(autouse=True)
async def finish_reloads(hass: HomeAssistant) -> AsyncGenerator[None]:
    """Let the reload that a finished reauth or reconfigure starts complete within the test."""
    yield
    await hass.async_block_till_done()


async def _start(
    hass: HomeAssistant, connection: dict[str, object] | None = None
) -> ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], connection or CONNECTION
    )


async def test_full_flow_pins_the_certificate(hass: HomeAssistant) -> None:
    result = await _start(hass)
    assert result["step_id"] == "certificate"
    placeholders = result["description_placeholders"]
    assert placeholders is not None
    assert placeholders["fingerprint"].startswith("AB:AB:")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "credentials"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["step_id"] == "clients"
    schema = result["data_schema"]
    assert schema is not None
    options = schema.schema[CONF_TRACKED].config["options"]
    assert options
    assert all(":" in o["value"] for o in options)
    chosen = options[0]["value"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: False, CONF_TRACKED: [chosen]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "RT2600ac"
    assert result["result"].unique_id == SERIALS["router"]
    assert result["data"][CONF_FINGERPRINT] == FINGERPRINT
    assert CONF_VERIFY_CERTIFICATE not in result["data"]
    assert result["options"][CONF_TRACKED] == [chosen]


async def test_plain_http_skips_the_certificate(hass: HomeAssistant) -> None:
    result = await _start(hass, {**CONNECTION, CONF_USE_HTTPS: False, "port": 8000})
    assert result["step_id"] == "credentials"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FINGERPRINT] is None
    assert result["options"][CONF_TRACK_ALL] is True


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SrmConnectionError("x"), "cannot_connect"),
        (SrmCertificateError("x"), "certificate"),
        (ValueError("bad host"), "invalid_host"),
    ],
)
async def test_fingerprint_errors(hass: HomeAssistant, error: Exception, key: str) -> None:
    ERRORS[ROUTER_HOST] = {"fingerprint": error}
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SrmAuthenticationError(400, "SYNO.API.Auth"), "invalid_auth"),
        (SrmTwoFactorRequiredError(403, "SYNO.API.Auth"), "two_factor"),
        (SrmBlockedError(407, "SYNO.API.Auth"), "blocked"),
        (SrmConnectionError("x"), "cannot_connect"),
        (SrmError("x"), "unknown"),
    ],
)
async def test_login_errors_then_success(hass: HomeAssistant, error: Exception, key: str) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    ERRORS[ROUTER_HOST] = {"login": error}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": key}
    ERRORS.clear()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["step_id"] == "clients"


async def test_same_device_twice_aborts(hass: HomeAssistant) -> None:
    make_entry().add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_with_a_new_password(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "homeassistant", "password": "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"


async def test_reauth_after_a_certificate_change(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    ERRORS[ROUTER_HOST] = {"login": SrmCertificateError("changed")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["step_id"] == "reauth_certificate"
    ERRORS.clear()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reauth_successful"


async def test_reauth_errors(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    ERRORS[ROUTER_HOST] = {"login": SrmAuthenticationError(400, "SYNO.API.Auth")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": "invalid_auth"}
    ERRORS[ROUTER_HOST] = {
        "login": SrmCertificateError("x"),
        "fingerprint": SrmConnectionError("x"),
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": "cannot_connect"}
    ERRORS[ROUTER_HOST] = {"login": SrmCertificateError("x")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["step_id"] == "reauth_certificate"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "certificate"}


async def test_reauth_on_a_different_device_aborts(hass: HomeAssistant) -> None:
    entry = make_entry("ap")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "host": ROUTER_HOST})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["reason"] == "wrong_device"


async def test_reconfigure(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    ERRORS[ROUTER_HOST] = {"fingerprint": SrmConnectionError("x")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
    assert result["errors"] == {"base": "cannot_connect"}
    ERRORS.clear()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONNECTION, CONF_VERIFY_CERTIFICATE: False}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_FINGERPRINT] is None


async def test_options(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_TRACK_ALL: True, CONF_TRACKED: [], "fast_interval": 60, "slow_interval": 600},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["fast_interval"] == 60
    assert entry.runtime_data.fast.update_interval.total_seconds() == 60


async def test_an_empty_port_means_the_default_of_the_protocol(hass: HomeAssistant) -> None:
    result = await _start(
        hass, {"host": ROUTER_HOST, CONF_USE_HTTPS: False, CONF_VERIFY_CERTIFICATE: False}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["data"]["port"] == 8000
    assert result["data"]["is_router"] is True


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SrmPermissionError(105, "SYNO.Core.System"), "not_admin"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_unexpected_and_permission_errors(
    hass: HomeAssistant, error: Exception, key: str
) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    ERRORS[ROUTER_HOST] = {"get_system_info": error}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": key}


async def test_a_device_without_serial_is_refused(hass: HomeAssistant) -> None:
    original = FakeClient.get_system_info

    async def no_serial(self: FakeClient) -> Any:
        return dataclasses.replace(await original(self), serial=None)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with patch.object(FakeClient, "get_system_info", no_serial):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["errors"] == {"base": "no_serial"}


async def test_the_same_device_at_a_new_address_updates_the_entry(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await _start(hass, {**CONNECTION, "host": "192.0.2.9"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.9"


async def test_reconfigure_confirms_a_new_certificate(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    FINGERPRINTS["192.0.2.9"] = "cd" * 32
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONNECTION, "host": "192.0.2.9"}
    )
    assert result["step_id"] == "reconfigure_certificate"
    assert entry.data[CONF_FINGERPRINT] == FINGERPRINT  # nothing is pinned before confirmation
    ERRORS["192.0.2.9"] = {"login": SrmConnectionError("x")}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "cannot_connect"}
    ERRORS.clear()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_FINGERPRINT] == "cd" * 32
    assert entry.data["host"] == "192.0.2.9"


async def test_reconfigure_with_the_same_certificate_needs_no_confirmation(
    hass: HomeAssistant,
) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONNECTION, "port": 8443}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["port"] == 8443


async def _to_clients(
    hass: HomeAssistant, connection: dict[str, object] | None = None
) -> ConfigFlowResult:
    result = await _start(hass, connection)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    return await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)


def _offered(result: ConfigFlowResult) -> list[str]:
    schema = result["data_schema"]
    assert schema is not None
    return [o["value"] for o in schema.schema[CONF_TRACKED].config["options"]]


async def test_all_known_clients_on_request(hass: HomeAssistant) -> None:
    result = await _to_clients(hass)
    relevant = _offered(result)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: False, CONF_TRACKED: [relevant[0]], CONF_SHOW_ALL: True}
    )
    assert result["step_id"] == "clients"
    assert len(_offered(result)) > len(relevant)
    assert CONF_SHOW_ALL not in result["data_schema"].schema  # type: ignore[union-attr]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: False, CONF_TRACKED: [relevant[0]]}
    )
    assert result["options"][CONF_TRACKED] == [relevant[0]]
    assert result["options"]["consider_home"] == 180


async def test_without_dhcp_fewer_clients_are_offered(hass: HomeAssistant) -> None:
    first = await _to_clients(hass)
    with_dhcp = _offered(first)
    hass.config_entries.flow.async_abort(first["flow_id"])
    UNSUPPORTED[ROUTER_HOST] = {"get_dhcp_clients", "get_dhcp_reservations"}
    without = _offered(await _to_clients(hass))
    assert len(without) < len(with_dhcp)


async def _router_loaded(hass: HomeAssistant) -> None:
    router = make_entry()
    router.add_to_hass(hass)
    await hass.config_entries.async_setup(router.entry_id)
    await hass.async_block_till_done()


async def test_an_access_point_next_to_a_router_has_no_tracker_step(hass: HomeAssistant) -> None:
    await _router_loaded(hass)
    result = await _to_clients(hass, {**CONNECTION, "host": AP_HOST})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "access_point"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "router_keeps_trackers"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_TRACKED] == []
    assert result["options"]["own_trackers"] is False
    assert result["data"]["is_router"] is False


async def test_an_access_point_may_keep_trackers_anyway(hass: HomeAssistant) -> None:
    await _router_loaded(hass)
    result = await _to_clients(hass, {**CONNECTION, "host": AP_HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "own_trackers"}
    )
    assert result["step_id"] == "clients"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: True}
    )
    assert result["options"]["own_trackers"] is True


async def test_choosing_no_client_leaves_the_trackers_to_the_router(hass: HomeAssistant) -> None:
    await _router_loaded(hass)
    result = await _to_clients(hass, {**CONNECTION, "host": AP_HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "own_trackers"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: False, CONF_TRACKED: []}
    )
    assert result["options"]["own_trackers"] is False


async def test_an_access_point_of_another_network_keeps_its_trackers(
    hass: HomeAssistant,
) -> None:
    make_entry().add_to_hass(hass)  # a router that knows none of the access point's clients
    result = await _to_clients(hass, {**CONNECTION, "host": AP_HOST})
    assert result["step_id"] == "clients"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: True}
    )
    assert result["options"]["own_trackers"] is True


async def test_the_username_stays_after_an_error(hass: HomeAssistant) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    ERRORS[ROUTER_HOST] = {"login": SrmSessionError(119, "SYNO.API.Auth")}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "someone", "password": "x"}
    )
    assert result["errors"] == {"base": "session_ended"}
    schema = result["data_schema"]
    assert schema is not None
    username = next(k for k in schema.schema if k == "username")
    assert username.description == {"suggested_value": "someone"}


async def test_a_second_device_of_the_same_model_gets_the_serial(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, title="RT2600ac", unique_id="OTHER", data={}).add_to_hass(hass)
    result = await _to_clients(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["title"] == f"RT2600ac …{SERIALS['router'][-3:]}"


async def test_options_of_an_access_point_next_to_a_router(hass: HomeAssistant) -> None:
    router, ap = make_entry(), make_entry("ap")
    for entry in (router, ap):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    menu = await hass.config_entries.options.async_init(ap.entry_id)
    assert menu["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "timings"}
    )
    assert CONF_TRACKED not in result["data_schema"].schema  # type: ignore[union-attr]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"consider_home": 60, "fast_interval": 30, "slow_interval": 300}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert ap.options["consider_home"] == 60

    menu = await hass.config_entries.options.async_init(ap.entry_id)
    result = await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "trackers"}
    )
    assert _offered(result)
    assert "fast_interval" not in result["data_schema"].schema  # type: ignore[union-attr]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TRACK_ALL: True, CONF_TRACKED: []}
    )
    await hass.async_block_till_done()
    assert ap.options["own_trackers"] is True


async def test_options_show_all_known_clients_on_request(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    relevant = _offered(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TRACK_ALL: False,
            CONF_TRACKED: [],
            CONF_SHOW_ALL: True,
            "consider_home": 60,
            "fast_interval": 30,
            "slow_interval": 300,
        },
    )
    assert result["step_id"] == "init"
    assert len(_offered(result)) > len(relevant)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TRACK_ALL: False,
            CONF_TRACKED: [],
            "consider_home": 60,
            "fast_interval": 30,
            "slow_interval": 300,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["consider_home"] == 60
