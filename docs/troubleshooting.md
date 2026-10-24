# Troubleshooting

| Message | What to do |
| --- | --- |
| Wrong username or password | Check the account; SRM's Web API needs an administrator. |
| The account is not an administrator | SRM's Web API only answers administrators; use one. |
| The account uses two-factor authentication | Use an account without it; Home Assistant cannot enter codes unattended. |
| The device blocks logins from Home Assistant | SRM's auto block locks out Home Assistant's address after failed attempts; see [the repair](repairs/blocked.md). |
| The certificate does not match | The device presents a different certificate, usually after a renewal. Confirm the new fingerprint when Home Assistant asks; compare it first ([how](configuration.md#certificate)). |
| SRM ended the session right after the login | Something else logged in with the same account under the same session name. Try again; if it repeats, check which other program uses the account. |
| The device could not be reached | Check host and port, and that HTTPS matches SRM's settings. |
| The device reports no serial number | The device cannot be told apart from others and is not set up. Please report it with the model and firmware. |

**Diagnostics** (*Settings, Devices & services, Synology SRM Router, the three dots, Download
diagnostics*) contain the device model, firmware, which values could be read and their types, but
no addresses, names, passwords or the certificate fingerprint. Attach them to a bug report.

## Known limitations

- A tracker switches between home and away: raise *Time until away* in the options. SRM marks
  idle wired clients offline for a minute now and then.
- SRM keeps clients it saw long ago; *Show all known clients* lists them, the default list does not.
- Mesh setups are untested; the integration was developed with a router and a standalone access
  point. Reports are welcome.
- Wired clients behind an access point's LAN port appear on the router.
- The public IPv4 address is what SRM last recorded; it can lag behind a change.

## Removing the integration

*Settings, Devices & services, Synology SRM Router*, then delete each entry. The integration only
read from the devices, so nothing needs to be undone in SRM. Remove the dedicated SRM account if
you created one.
