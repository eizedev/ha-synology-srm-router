"""Config flow: connect, confirm the certificate, choose the clients to track."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiosynologysrm import (
    NetworkDevices,
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmConnectionError,
    SrmError,
    SrmPermissionError,
    SrmTwoFactorRequiredError,
    get_certificate_fingerprint,
    helpers,
)
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util.ssl import get_default_no_verify_context
import probatio

from . import create_client
from .const import (
    CONF_FAST_INTERVAL,
    CONF_FINGERPRINT,
    CONF_IS_ROUTER,
    CONF_SLOW_INTERVAL,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    CONF_USE_HTTPS,
    CONF_VERIFY_CERTIFICATE,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_HTTP_PORT,
    DEFAULT_HTTPS_PORT,
    DEFAULT_SLOW_INTERVAL,
    DEFAULT_USERNAME,
    DOCS_URL,
    DOMAIN,
    LOGGER,
    MIN_FAST_INTERVAL,
    MIN_SLOW_INTERVAL,
)
from .coordinator import SrmConfigEntry


def _connection_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    host = defaults.get(CONF_HOST, probatio.UNDEFINED)
    https = defaults.get(CONF_USE_HTTPS, True)
    verify = defaults.get(CONF_VERIFY_CERTIFICATE, True)
    return probatio.Schema(
        {
            probatio.Required(CONF_HOST, default=host): TextSelector(),
            # Empty means SRM's default port for the chosen protocol.
            probatio.Optional(CONF_PORT): probatio.All(
                probatio.Coerce(int), probatio.Range(min=1, max=65535)
            ),
            probatio.Required(CONF_USE_HTTPS, default=https): BooleanSelector(),
            probatio.Required(CONF_VERIFY_CERTIFICATE, default=verify): BooleanSelector(),
        }
    )


def _with_port(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Fill in SRM's default port for the chosen protocol when none was given."""
    default = DEFAULT_HTTPS_PORT if user_input[CONF_USE_HTTPS] else DEFAULT_HTTP_PORT
    return {**user_input, CONF_PORT: user_input.get(CONF_PORT) or default}


CREDENTIALS = {
    probatio.Required(CONF_USERNAME, default=DEFAULT_USERNAME): TextSelector(),
    probatio.Required(CONF_PASSWORD): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
}


class NoSerialError(SrmError):
    """The device reports no serial number, so it cannot be told apart from others."""


def _error_key(err: Exception) -> str:  # noqa: PLR0911 - one per error class
    """Return the form error for a failed connection attempt; unexpected ones are logged."""
    if isinstance(err, NoSerialError):
        return "no_serial"
    if isinstance(err, ValueError):
        return "invalid_host"
    if isinstance(err, SrmTwoFactorRequiredError):
        return "two_factor"
    if isinstance(err, SrmAuthenticationError):
        return "invalid_auth"
    if isinstance(err, SrmPermissionError):
        return "not_admin"
    if isinstance(err, SrmBlockedError):
        return "blocked"
    if isinstance(err, SrmCertificateError):
        return "certificate"
    if isinstance(err, SrmConnectionError):
        return "cannot_connect"
    LOGGER.exception("Unexpected error while connecting", exc_info=err)
    return "unknown"


async def _fingerprint(data: Mapping[str, Any]) -> str:
    return await get_certificate_fingerprint(
        data[CONF_HOST], int(data[CONF_PORT]), ssl_context=get_default_no_verify_context()
    )


def client_options(devices: NetworkDevices | None) -> list[SelectOptionDict]:
    """List clients for the tracker choice: online first, then by name; odd MACs skipped."""
    options: list[SelectOptionDict] = []
    entries = devices.devices if devices else ()
    for device in sorted(entries, key=lambda d: (not d.is_online, d.hostname or "")):
        mac = helpers.normalize_mac(device.mac)
        if mac is not None:
            label = " / ".join(p for p in (device.hostname, device.ip_addr, mac) if p)
            options.append(SelectOptionDict(value=mac, label=label))
    return options


@dataclass(frozen=True, kw_only=True)
class Probe:
    """What one login tells about a device."""

    serial: str
    title: str
    is_router: bool
    clients: list[SelectOptionDict]


async def _probe(hass: HomeAssistant, data: Mapping[str, Any]) -> Probe:
    """Log in once and read what the flow needs; a device without serial is refused."""
    client = create_client(hass, dict(data))
    try:
        await client.login()
        system = await client.get_system_info()
        topology = await client.get_topology()
        devices = await client.get_network_devices()
    finally:
        await client.logout()
    if not system.serial:
        raise NoSerialError
    return Probe(
        serial=system.serial,
        title=f"{system.model or 'SRM'} ({data[CONF_HOST]})",
        is_router=topology.net_topology == "router",
        clients=client_options(devices),
    )


class SrmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one Synology router or access point."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing known."""
        self._data: dict[str, Any] = {}
        self._probe: Probe | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: SrmConfigEntry) -> SrmOptionsFlow:
        """Intervals and tracked clients."""
        return SrmOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask where the device is and how to reach it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = {**_with_port(user_input), CONF_FINGERPRINT: None}
            if user_input[CONF_USE_HTTPS] and user_input[CONF_VERIFY_CERTIFICATE]:
                try:
                    self._data[CONF_FINGERPRINT] = await _fingerprint(self._data)
                except Exception as err:  # the form shows the error; unexpected ones are logged
                    errors["base"] = _error_key(err)
                else:
                    return await self.async_step_certificate()
            else:
                return await self.async_step_credentials()
        schema = self.add_suggested_values_to_schema(_connection_schema({}), user_input or {})
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"docs": DOCS_URL},
        )

    async def async_step_certificate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the fingerprint; continuing means the user trusts it."""
        if user_input is not None:
            return await self.async_step_credentials()
        return self.async_show_form(
            step_id="certificate",
            description_placeholders={"fingerprint": _pretty(self._data[CONF_FINGERPRINT])},
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the administrator account and test it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._data, **user_input}
            try:
                self._probe = await _probe(self.hass, data)
            except Exception as err:  # the form shows the error; unexpected ones are logged
                errors["base"] = _error_key(err)
            else:
                await self.async_set_unique_id(self._probe.serial)
                # The same device at a new address: take the address that was just verified.
                self._abort_if_unique_id_configured(
                    updates={k: data[k] for k in (CONF_HOST, CONF_PORT, CONF_USE_HTTPS)}
                    | {CONF_FINGERPRINT: data[CONF_FINGERPRINT]}
                )
                self._data = data
                return await self.async_step_clients()
        return self.async_show_form(
            step_id="credentials",
            data_schema=probatio.Schema(CREDENTIALS),
            errors=errors,
            description_placeholders={"docs": DOCS_URL},
        )

    async def async_step_clients(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the clients to track: none, some, or all."""
        probe = self._probe
        if probe is None:  # pragma: no cover - the flow only gets here after a probe
            return self.async_abort(reason="unknown")
        if user_input is not None:
            options = {
                CONF_TRACK_ALL: user_input.get(CONF_TRACK_ALL, False),
                CONF_TRACKED: user_input.get(CONF_TRACKED, []),
                CONF_FAST_INTERVAL: DEFAULT_FAST_INTERVAL.seconds,
                CONF_SLOW_INTERVAL: DEFAULT_SLOW_INTERVAL.seconds,
            }
            data = {k: v for k, v in self._data.items() if k != CONF_VERIFY_CERTIFICATE}
            data[CONF_IS_ROUTER] = probe.is_router
            return self.async_create_entry(title=probe.title, data=data, options=options)
        return self.async_show_form(
            step_id="clients", data_schema=_clients_schema(probe.clients, {})
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start again after a changed password, a needed code or a changed certificate."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again; a new certificate is shown for confirmation first."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._data, **user_input}
            try:
                probe = await _probe(self.hass, data)
            except SrmCertificateError:
                try:
                    self._data = {**data, CONF_FINGERPRINT: await _fingerprint(data)}
                except Exception as err:  # the form shows the error; unexpected ones are logged
                    errors["base"] = _error_key(err)
                else:
                    return await self.async_step_reauth_certificate()
            except Exception as err:  # the form shows the error; unexpected ones are logged
                errors["base"] = _error_key(err)
            else:
                return await self._finish(self._get_reauth_entry(), data, probe)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(CREDENTIALS),
            errors=errors,
            description_placeholders={"host": str(self._data.get(CONF_HOST))},
        )

    async def async_step_reauth_certificate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a new certificate; it is trusted only after confirmation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                probe = await _probe(self.hass, self._data)
            except Exception as err:  # the form shows the error; unexpected ones are logged
                errors["base"] = _error_key(err)
            else:
                return await self._finish(self._get_reauth_entry(), self._data, probe)
        return self.async_show_form(
            step_id="reauth_certificate",
            errors=errors,
            description_placeholders={"fingerprint": _pretty(self._data[CONF_FINGERPRINT])},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change address, port or certificate checking of an existing device.

        A certificate that differs from the pinned one is shown for confirmation first.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **_with_port(user_input), CONF_FINGERPRINT: None}
            data.pop(CONF_VERIFY_CERTIFICATE, None)
            pin = user_input[CONF_USE_HTTPS] and user_input[CONF_VERIFY_CERTIFICATE]
            try:
                if pin:
                    data[CONF_FINGERPRINT] = await _fingerprint(data)
                if data[CONF_FINGERPRINT] == entry.data.get(CONF_FINGERPRINT) or not pin:
                    probe: Probe | None = await _probe(self.hass, data)
                else:
                    probe = None  # a new certificate: confirm it before it is used
            except Exception as err:  # the form shows the error; unexpected ones are logged
                errors["base"] = _error_key(err)
            else:
                if probe is None:
                    self._data = data
                    return await self.async_step_reconfigure_certificate()
                return await self._finish(entry, data, probe)
        defaults = {
            **entry.data,
            CONF_VERIFY_CERTIFICATE: entry.data.get(CONF_FINGERPRINT) is not None,
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(_connection_schema(defaults), defaults),
            errors=errors,
        )

    async def async_step_reconfigure_certificate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the certificate found at the new address; it is pinned only after confirmation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                probe = await _probe(self.hass, self._data)
            except Exception as err:  # the form shows the error; unexpected ones are logged
                errors["base"] = _error_key(err)
            else:
                return await self._finish(self._get_reconfigure_entry(), self._data, probe)
        return self.async_show_form(
            step_id="reconfigure_certificate",
            errors=errors,
            description_placeholders={"fingerprint": _pretty(self._data[CONF_FINGERPRINT])},
        )

    async def _finish(
        self, entry: SrmConfigEntry, data: dict[str, Any], probe: Probe
    ) -> ConfigFlowResult:
        """Store verified data of the same device and reload it."""
        await self.async_set_unique_id(probe.serial)
        self._abort_if_unique_id_mismatch(reason="wrong_device")
        return self.async_update_reload_and_abort(
            entry, data={**data, CONF_IS_ROUTER: probe.is_router}
        )


def _pretty(fingerprint: str) -> str:
    """Show a fingerprint the way SRM and browsers do: pairs separated by colons."""
    return ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)).upper()


def _clients_schema(clients: list[SelectOptionDict], current: Mapping[str, Any]) -> probatio.Schema:
    known = {c["value"] for c in clients}
    extra = [
        SelectOptionDict(value=mac, label=mac)
        for mac in current.get(CONF_TRACKED, [])
        if mac not in known
    ]
    return probatio.Schema(
        {
            probatio.Required(
                CONF_TRACK_ALL, default=current.get(CONF_TRACK_ALL, False)
            ): BooleanSelector(),
            probatio.Optional(CONF_TRACKED, default=current.get(CONF_TRACKED, [])): SelectSelector(
                SelectSelectorConfig(
                    options=[*clients, *extra], multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
        }
    )


class SrmOptionsFlow(OptionsFlowWithReload):
    """Polling intervals and the clients to track."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the current settings."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        entry: SrmConfigEntry = self.config_entry
        runtime = getattr(entry, "runtime_data", None)  # absent while the entry is not loaded
        data = runtime.fast.data if runtime else None
        clients = client_options(data.devices if data else None)
        options = entry.options
        schema = _clients_schema(clients, options).extend(
            {
                probatio.Required(
                    CONF_FAST_INTERVAL,
                    default=options.get(CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL.seconds),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_FAST_INTERVAL,
                        max=3600,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                probatio.Required(
                    CONF_SLOW_INTERVAL,
                    default=options.get(CONF_SLOW_INTERVAL, DEFAULT_SLOW_INTERVAL.seconds),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SLOW_INTERVAL,
                        max=86400,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
