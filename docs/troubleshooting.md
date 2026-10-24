# Troubleshooting

| Message | What to do |
| --- | --- |
| Wrong username or password | Check the account; SRM's Web API needs an administrator. |
| The account is not an administrator | SRM's Web API only answers administrators; use one. |
| The account uses two-factor authentication | Use an account without it; Home Assistant cannot enter codes unattended. |
| The device blocks logins from Home Assistant | After failed attempts SRM's auto block locks out Home Assistant's address. Unblock it in SRM's auto block settings, or wait until the block expires. Home Assistant shows a repair and tries to log in again every 15 minutes; each attempt counts towards the block. |
| The certificate does not match | The device presents a different certificate, usually after a renewal. Confirm the new fingerprint when Home Assistant asks; compare it with SRM first. |
| The device could not be reached | Check host and port, and that HTTPS matches SRM's settings. |
| The device reports no serial number | The device cannot be told apart from others and is not set up. Please report it with the model and firmware. |

**Diagnostics** (*Settings, Devices & services, Synology SRM Router, the three dots, Download
diagnostics*) contain the device model, firmware, which values could be read and their types, but
no addresses, names, passwords or the certificate fingerprint. Attach them to a bug report.

## Known limitations

- Mesh setups are untested; the integration was developed with a router and a standalone access
  point. Reports are welcome.
- Wired clients behind an access point's LAN port appear on the router.
- The public IPv4 address is what SRM last recorded; it can lag behind a change.

## Removing the integration

*Settings, Devices & services, Synology SRM Router*, then delete each entry. The integration only
read from the devices, so nothing needs to be undone in SRM. Remove the dedicated SRM account if
you created one.
