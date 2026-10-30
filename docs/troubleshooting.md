# Troubleshooting

The messages as Home Assistant shows them in English; the German texts say the same.

| Message | What to do |
| --- | --- |
| Wrong username or password, or the account may not log in. | Check the account; SRM's Web API needs an administrator. |
| This account lacks the rights for this in SRM; use an administrator account. | Use an administrator account; only those are tested. |
| The account uses two-factor authentication. Use an account without it. | Use an account without it; Home Assistant cannot enter codes unattended. |
| The device blocks logins from Home Assistant after failed attempts. Unblock the address in SRM's auto block settings, or wait until the block expires. | SRM's auto block locks out Home Assistant's address after failed attempts; see [the repair](repairs/blocked.md). |
| The certificate is not the trusted one. Check the address, then confirm the new certificate. | The device presents a certificate Home Assistant does not trust: a pinned one that was renewed, or one from an authority that expired or is no longer valid for the name you gave. Confirm the new certificate when Home Assistant asks; compare it first ([how](configuration.md#certificate)). |
| The certificate is not valid for this name. Check the name, or clear the field to pin the certificate instead. | The name you entered is not one the certificate was issued for. Enter the name you open the device with in a browser, or clear the field to pin the certificate ([how](configuration.md#certificate)). |
| SRM refused the session right after the login. This happens now and then; try again. | SRM does this now and then with a fresh session (error 119). Try again; if it repeats every time, check SRM's log for the account. |
| The device could not be reached. | Check host and port, and that HTTPS matches SRM's settings. |
| The device reports no serial number, so it cannot be set up. | The device cannot be told apart from others and is not set up. Please report it with the model and firmware. |

**Diagnostics** (*Settings, Devices & services, Synology SRM Router, the three dots, Download
diagnostics*) contain the device model, firmware, which values could be read and their types, but
no addresses, names, passwords or the certificate fingerprint. Attach them to a bug report.

## Known limitations

- A tracker switches between home and away: raise *Time until away* in the options. SRM marks
  idle wired clients offline for a minute now and then.
- A few values are unknown for a minute now and then: SRM did not answer one of the reads, while
  the others worked. The log names the read and the device at info level, once when it fails and
  once when it works again. On an RT2600ac this happened around SRM's own updates of its GeoIP
  database and IP block list.
- SRM keeps clients it saw long ago; *Show all known clients* lists them, the default list does not.
- Mesh setups are untested; the integration was developed with a router and a standalone access
  point. Reports are welcome.
- Wired clients behind an access point's LAN port appear on the router.
- The public IPv4 address is what SRM last recorded; it can lag behind a change.

## Removing the integration

*Settings, Devices & services, Synology SRM Router*, then delete each entry. The integration only
read from the devices, so nothing needs to be undone in SRM. Remove the dedicated SRM account if
you created one.

## What is stored and who can see it

- **Config entry** (Home Assistant's `.storage/core.config_entries`, in every backup): address,
  port, account, password and the pinned certificate fingerprint or the certificate's name, as
  for every integration that logs in somewhere.
- **`.storage/synology_srm_router.last_seen`**: when each client was last seen online, by MAC
  address, for 30 days; it decides which clients "matter". It is in every backup and is deleted
  when you remove the last router or access point.
- **Recorder** (history): the states of all entities and the trackers' attributes (IP and IPv6
  address, MAC, host name, the device and radio a client uses). The Wi-Fi signal, the SSIDs and
  the lists of leases, reservations and firewall rules are left out; the counts are kept. Wi-Fi
  passwords never reach Home Assistant: the library leaves them out of what it reads.
- **Visible to every user** of Home Assistant, not only administrators: every state with its
  attributes, including those lists when you enable their sensors.
- **Diagnostics** (the download for an issue): settings without address, account, password,
  fingerprint or certificate name, and counts instead of client addresses.
