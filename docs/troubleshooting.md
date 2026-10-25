# Troubleshooting

| Message | What to do |
| --- | --- |
| Wrong username or password | Check the account; SRM's Web API needs an administrator. |
| SRM refused the account the rights for this | Use an administrator account; only those are tested. |
| The account uses two-factor authentication | Use an account without it; Home Assistant cannot enter codes unattended. |
| The device blocks logins from Home Assistant | SRM's auto block locks out Home Assistant's address after failed attempts; see [the repair](repairs/blocked.md). |
| The certificate does not match | The device presents a different certificate, usually after a renewal. Confirm the new fingerprint when Home Assistant asks; compare it first ([how](configuration.md#certificate)). |
| SRM refused the session right after the login | SRM does this now and then with a fresh session (error 119). Try again; if it repeats every time, check SRM's log for the account. |
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

## What is stored and who can see it

- **Config entry** (Home Assistant's `.storage/core.config_entries`, in every backup): address,
  port, account, password and the pinned certificate fingerprint, as for every integration that
  logs in somewhere.
- **`.storage/synology_srm_router.last_seen`**: when each client was last seen online, by MAC
  address, for 30 days; it decides which clients "matter". It is in every backup and is deleted
  when you remove the last router or access point.
- **Recorder** (history): the states of all entities and the trackers' attributes (IP and IPv6
  address, MAC, host name, the device and radio a client uses). The Wi-Fi signal and the lists of
  leases, reservations and firewall rules are left out; the counts are kept.
- **Visible to every user** of Home Assistant, not only administrators: every state with its
  attributes, including those lists when you enable their sensors.
- **Diagnostics** (the download for an issue): settings without address, account, password or
  fingerprint, and counts instead of client addresses.
