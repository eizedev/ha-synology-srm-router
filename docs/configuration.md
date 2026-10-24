# Configuration

## Adding a device

Add the integration once for every Synology router and every access point. Each becomes its own
device in Home Assistant. Their client lists are combined automatically, so a client on an access
point is shown there.

| Field | Meaning |
| --- | --- |
| Host | Address or host name of the router or access point. |
| Port | Leave empty for SRM's default: 8001 for HTTPS, 8000 for HTTP. |
| Use HTTPS | Recommended: the password travels encrypted. |
| Check the certificate | Shows the certificate's SHA-256 fingerprint for you to confirm, then trusts exactly that certificate. Turn off only if you accept that anyone in your network could read the password. |
| Username, password | An SRM **administrator** account (SRM's Web API answers nothing else) without two-factor authentication. A dedicated account is best. |
| Clients to track | The clients that get a device tracker; or *Track all clients*. Their trackers are enabled. |

Compare the fingerprint with the certificate shown in SRM's settings before you continue.

Each device is recognised by its serial number. Whether it runs as router or as access point is
read at every start, so switching the operation mode in SRM needs no reconfiguration.

## Options

*Settings, Devices & services, Synology SRM Router, Configure*:

| Option | Default | Meaning |
| --- | --- | --- |
| Track all clients | off | A tracker for every client, including new ones later. |
| Clients to track | none | Only these clients get a tracker. |
| Fast polling interval | 30 s | Clients, Wi-Fi, load and WAN. |
| Slow polling interval | 300 s | System information (firmware, last boot). |

Each update reads several values from the device; SRM devices answer slowly (about half a second
per call on an RT2600ac), so intervals much below the defaults mostly add load.

## Changing the connection or signing in again

- *Reconfigure* changes host, port, HTTPS and certificate checking. A certificate that differs
  from the trusted one is shown for you to confirm first.
- Adding a device that is already set up, at a new address, updates the address of the existing
  entry instead.
- When the password changed, or the device presents a new certificate (for example after a
  renewal), Home Assistant asks you to sign in again and shows the new fingerprint for you to
  confirm.
