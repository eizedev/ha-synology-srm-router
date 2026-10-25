"""Config flow: connect, confirm the certificate, choose the clients to track."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiosynologysrm import (
    SrmAuthenticationError,
    SrmBlockedError,
    SrmCertificateError,
    SrmConnectionError,
    SrmError,
    SrmPermissionError,
    SrmSessionError,
    SrmTwoFactorRequiredError,
    get_certificate_fingerprint,
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
from homeassistant.util import dt as dt_util
from homeassistant.util.ssl import get_default_no_verify_context
import probatio

from . import create_client, session_name
from .clients import Client, combine, dhcp_addresses, options as client_options
from .const import (
    CONF_CONSIDER_HOME,
    CONF_FAST_INTERVAL,
    CONF_FINGERPRINT,
    CONF_IS_ROUTER,
    CONF_OWN_TRACKERS,
    CONF_SHOW_ALL,
    CONF_SLOW_INTERVAL,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    CONF_USE_HTTPS,
    CONF_VERIFY_CERTIFICATE,
    DEFAULT_CONSIDER_HOME,
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
from .coordinator import SrmConfigEntry, get_hub
from .entity import url_host

# Help pages for the steps; DOCS_URL is the documentation website.
DOCS_SETUP = f"{DOCS_URL}configuration/"
DOCS_CERTIFICATE = f"{DOCS_URL}configuration/#certificate"
DOCS_ACCOUNT = f"{DOCS_URL}configuration/#account"
DOCS_TRACKERS = f"{DOCS_URL}configuration/#device-trackers"


def _connection_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    host = defaults.get(CONF_HOST, probatio.UNDEFINED)
    https = defaults.get(CONF_USE_HTTPS, True)
    verify = defaults.get(CONF_VERIFY_CERTIFICATE, True)
    return probatio.Schema(
        {
            probatio.Required(CONF_HOST, default=host): TextSelector(),
            # Empty means SRM's default port for the chosen protocol. A selector, not a plain
            # integer: the frontend focuses a plain integer field first, before the host.
            probatio.Optional(CONF_PORT): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
            ),
            probatio.Required(CONF_USE_HTTPS, default=https): BooleanSelector(),
            probatio.Required(CONF_VERIFY_CERTIFICATE, default=verify): BooleanSelector(),
        }
    )


def _with_port(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Fill in SRM's default port for the chosen protocol when none was given."""
    default = DEFAULT_HTTPS_PORT if user_input[CONF_USE_HTTPS] else DEFAULT_HTTP_PORT
    return {**user_input, CONF_PORT: int(user_input.get(CONF_PORT) or default)}


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
    if isinstance(err, SrmSessionError):
        return "session_ended"
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


@dataclass(frozen=True, kw_only=True)
class Probe:
    """What one login tells about a device."""

    serial: str
    model: str
    is_router: bool
    clients: dict[str, Client]


async def _probe(hass: HomeAssistant, data: Mapping[str, Any]) -> Probe:
    """Log in once and read what the flow needs; a device without serial is refused."""
    client = create_client(hass, dict(data), await session_name(hass, "setup"))
    try:
        await client.login()
        system = await client.get_system_info()
        topology = await client.get_topology()
        devices = await client.get_network_devices()
        is_router = topology.net_topology == "router"
        leases = reservations = None
        if is_router and await client.supports(client.get_dhcp_clients):
            leases = await client.get_dhcp_clients()
        if is_router and await client.supports(client.get_dhcp_reservations):
            reservations = await client.get_dhcp_reservations()
    finally:
        await client.logout()
    if not system.serial:
        raise NoSerialError
    return Probe(
        serial=system.serial,
        model=system.model or "SRM",
        is_router=is_router,
        clients=combine([devices], dhcp_addresses(leases, reservations), get_hub(hass).last_seen),
    )


def _title(hass: HomeAssistant, probe: Probe) -> str:
    """Return the model; with the end of the serial number when that model is set up already."""
    titles = {e.title for e in hass.config_entries.async_entries(DOMAIN)}
    return f"{probe.model} …{probe.serial[-3:]}" if probe.model in titles else probe.model


def _router_configured(hass: HomeAssistant) -> bool:
    """Whether a router is set up; it then keeps the trackers of the clients it knows."""
    return any(e.data.get(CONF_IS_ROUTER) for e in hass.config_entries.async_entries(DOMAIN))


def _router_clients(hass: HomeAssistant) -> frozenset[str]:
    """Return the clients the configured routers know."""
    hub = get_hub(hass)
    routers = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_IS_ROUTER)]
    return frozenset().union(*(hub.known(e.entry_id) for e in routers))


class SrmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one Synology router or access point."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing known."""
        self._data: dict[str, Any] = {}
        self._probe: Probe | None = None
        self._show_all = False
        self._own_trackers = False
        self._from_menu = False

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
            description_placeholders={"docs": DOCS_SETUP},
        )

    async def async_step_certificate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the fingerprint; continuing means the user trusts it."""
        if user_input is not None:
            return await self.async_step_credentials()
        return self.async_show_form(
            step_id="certificate",
            description_placeholders=_certificate_placeholders(self._data),
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
                if not self._probe.is_router and _router_configured(self.hass):
                    # No client in common with the routers: a network of its own.
                    if not set(self._probe.clients) & _router_clients(self.hass):
                        self._own_trackers = True
                        return await self.async_step_clients()
                    return await self.async_step_access_point()
                return await self.async_step_clients()
        keep = {CONF_USERNAME: user_input[CONF_USERNAME]} if user_input else {}
        return self.async_show_form(
            step_id="credentials",
            data_schema=self.add_suggested_values_to_schema(probatio.Schema(CREDENTIALS), keep),
            errors=errors,
            description_placeholders={"docs": DOCS_ACCOUNT},
        )

    async def async_step_clients(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the clients to track: none, some, or all."""
        probe = self._probe
        if probe is None:  # pragma: no cover - the flow only gets here after a probe
            return self.async_abort(reason="unknown")
        if user_input is not None:
            if user_input.pop(CONF_SHOW_ALL, False) and not self._show_all:
                self._show_all = True  # the same form again, with every known client
            else:
                return self._create(probe, user_input)
        choice = client_options(
            probe.clients,
            dt_util.utcnow(),
            show_all=self._show_all,
            keep=(user_input or {}).get(CONF_TRACKED, []),
        )
        schema = _clients_schema(choice, user_input or {}, show_all=self._show_all)
        # Coming from the access point's menu: flows have no "back", so the page says how to get
        # the router's choice anyway (pick nothing).
        return self.async_show_form(
            step_id="own_clients" if self._from_menu else "clients",
            data_schema=schema,
            description_placeholders={"docs": DOCS_TRACKERS},
        )

    async def async_step_own_clients(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose clients of this access point; the same as the clients step."""
        return await self.async_step_clients(user_input)

    async def async_step_access_point(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Say that the router keeps the trackers; the access point may keep its own anyway."""
        return self.async_show_menu(
            step_id="access_point",
            menu_options=["router_keeps_trackers", "own_trackers"],
            description_placeholders={"docs": DOCS_TRACKERS},
        )

    async def async_step_router_keeps_trackers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish: the router keeps the trackers of this access point's clients."""
        probe = self._probe
        if probe is None:  # pragma: no cover - the flow only gets here after a probe
            return self.async_abort(reason="unknown")
        return self._create(probe, {})

    async def async_step_own_trackers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose clients of this access point to track here."""
        self._own_trackers = self._from_menu = True
        return await self.async_step_clients()

    def _create(self, probe: Probe, choice: Mapping[str, Any]) -> ConfigFlowResult:
        options = {
            CONF_TRACK_ALL: choice.get(CONF_TRACK_ALL, False),
            CONF_TRACKED: choice.get(CONF_TRACKED, []),
            # Choosing nothing leaves the trackers to the router (dialogs have no "back").
            CONF_OWN_TRACKERS: self._own_trackers
            and bool(choice.get(CONF_TRACK_ALL) or choice.get(CONF_TRACKED)),
            CONF_CONSIDER_HOME: DEFAULT_CONSIDER_HOME.seconds,
            CONF_FAST_INTERVAL: DEFAULT_FAST_INTERVAL.seconds,
            CONF_SLOW_INTERVAL: DEFAULT_SLOW_INTERVAL.seconds,
        }
        data = {k: v for k, v in self._data.items() if k != CONF_VERIFY_CERTIFICATE}
        data[CONF_IS_ROUTER] = probe.is_router
        return self.async_create_entry(title=_title(self.hass, probe), data=data, options=options)

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
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(CREDENTIALS), {CONF_USERNAME: self._data.get(CONF_USERNAME)}
            ),
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
            description_placeholders=_certificate_placeholders(self._data),
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
            description_placeholders=_certificate_placeholders(self._data),
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
    """Show a fingerprint the way browsers do: pairs separated by colons."""
    return ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)).upper()


def _certificate_placeholders(data: Mapping[str, Any]) -> dict[str, str]:
    """Return the fingerprint, the address to compare it in a browser, and the help page."""
    host = url_host(str(data[CONF_HOST]))
    return {
        "fingerprint": _pretty(data[CONF_FINGERPRINT]),
        "url": f"https://{host}:{data[CONF_PORT]}",
        "docs": DOCS_CERTIFICATE,
    }


def _clients_schema(
    choice: list[SelectOptionDict], current: Mapping[str, Any], *, show_all: bool
) -> probatio.Schema:
    fields: dict[Any, Any] = {
        probatio.Required(
            CONF_TRACK_ALL, default=current.get(CONF_TRACK_ALL, False)
        ): BooleanSelector(),
        probatio.Optional(CONF_TRACKED, default=current.get(CONF_TRACKED, [])): SelectSelector(
            SelectSelectorConfig(options=choice, multiple=True, mode=SelectSelectorMode.DROPDOWN)
        ),
    }
    if not show_all:
        fields[probatio.Optional(CONF_SHOW_ALL, default=False)] = BooleanSelector()
    return probatio.Schema(fields)


def _seconds(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum, max=maximum, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
        )
    )


class SrmOptionsFlow(OptionsFlowWithReload):
    """The clients to track, when a client counts as away, and the polling intervals.

    An access point next to a router gets a menu: its timings, or trackers of its own.
    """

    def __init__(self) -> None:
        """Start with the relevant clients."""
        self._show_all = False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the settings, or the menu of an access point next to a router."""
        entry: SrmConfigEntry = self.config_entry
        if not entry.data.get(CONF_IS_ROUTER) and _router_configured(self.hass):
            return await self.async_step_access_point()
        return await self._form("init", user_input, trackers=True, timings=True)

    async def async_step_access_point(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer an access point next to a router its timings or trackers of its own."""
        return self.async_show_menu(
            step_id="access_point",
            menu_options=["timings", "trackers"],
            description_placeholders={"docs": DOCS_TRACKERS},
        )

    async def async_step_timings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """When a client counts as away, and the polling intervals."""
        return await self._form("timings", user_input, trackers=False, timings=True)

    async def async_step_trackers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Trackers kept by this access point; choosing none leaves all to the router."""
        return await self._form("trackers", user_input, trackers=True, timings=False)

    async def _form(
        self, step_id: str, user_input: dict[str, Any] | None, *, trackers: bool, timings: bool
    ) -> ConfigFlowResult:
        entry: SrmConfigEntry = self.config_entry
        current = {**entry.options, **(user_input or {})}
        if user_input is not None:
            if user_input.pop(CONF_SHOW_ALL, False) and not self._show_all:
                self._show_all = True  # the same form again, with every known client
            else:
                data = {**entry.options, **user_input}
                if step_id == "trackers":
                    data[CONF_OWN_TRACKERS] = bool(
                        data.get(CONF_TRACK_ALL) or data.get(CONF_TRACKED)
                    )
                return self.async_create_entry(data=data)
        fields: dict[Any, Any] = {}
        if trackers:
            hub = get_hub(self.hass)
            own = hub.known(entry.entry_id)
            clients = {mac: c for mac, c in hub.clients.items() if mac in own}
            choice = client_options(
                clients,
                dt_util.utcnow(),
                show_all=self._show_all,
                keep=current.get(CONF_TRACKED, []),
            )
            fields.update(_clients_schema(choice, current, show_all=self._show_all).schema)
        if timings:
            defaults = {
                CONF_CONSIDER_HOME: DEFAULT_CONSIDER_HOME.seconds,
                CONF_FAST_INTERVAL: DEFAULT_FAST_INTERVAL.seconds,
                CONF_SLOW_INTERVAL: DEFAULT_SLOW_INTERVAL.seconds,
            }
            limits = {
                CONF_CONSIDER_HOME: (0, 3600),
                CONF_FAST_INTERVAL: (MIN_FAST_INTERVAL, 3600),
                CONF_SLOW_INTERVAL: (MIN_SLOW_INTERVAL, 86400),
            }
            for key, (low, high) in limits.items():
                fields[probatio.Required(key, default=current.get(key, defaults[key]))] = _seconds(
                    low, high
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=probatio.Schema(fields),
            description_placeholders={"docs": DOCS_TRACKERS},
        )
