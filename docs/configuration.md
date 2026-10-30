# Configuration

## Adding a device

Add the integration once for every Synology router and every access point. Each becomes its own
device in Home Assistant, named after its model (with the end of the serial number when two of the
same model are set up). Their client lists are combined automatically, so a client on an access
point is shown there.

| Field | Meaning |
| --- | --- |
| Host | Address or host name of the router or access point. With a certificate from a public authority, the name it was issued for lets Home Assistant check it by that name (see below). |
| Port | Leave empty for SRM's default: 8001 for HTTPS, 8000 for HTTP. |
| Use HTTPS | Recommended: the password travels encrypted. |
| Check the certificate | Checks the device's certificate: by the name you give when a public certificate authority vouches for it, else by its fingerprint after you confirmed it (see below). Turn off only if you accept that anyone in your network could read the password. |

Each device is recognised by its serial number. Whether it runs as router or as access point is
read at every start, so switching the operation mode in SRM needs no reconfiguration.

## Certificate

How Home Assistant checks the device depends on its certificate:

- **A certificate from a public certificate authority** (for example Let's Encrypt, which SRM
  can request for a DDNS name): Home Assistant checks every connection against the authorities
  and the name the certificate was issued for, like a browser, so renewals need nothing from you.
    - Entered that name as *Host*: nothing to confirm.
    - Entered an IP address: the dialog asks for the name, the one you open the device with in a
      browser. Home Assistant checks that the certificate is valid for it. Leave the field empty
      to pin the certificate instead; then every renewal needs a confirmation.

    Home Assistant never takes the name from the certificate itself: anyone can get a valid
    certificate for a name of their own, so only a name you know is yours proves anything. A
    check by name trusts every authority Home Assistant trusts, and does not check whether a
    certificate was revoked. A wildcard certificate (`*.example.net`) is valid for every name
    under its domain, so whoever else holds its key passes the check too; pin the certificate
    if that matters to you.
- **SRM's own certificate**, which browsers do not trust: Home Assistant shows its SHA-256
  fingerprint once and then trusts exactly that certificate (pinning). To check that you are
  talking to your device and not to something in between:

    1. Open the address shown in the dialog (for example `https://192.168.1.1:8001`) in a browser.
    2. Click the padlock or the warning next to the address and open the certificate details.
    3. Compare the SHA-256 fingerprint there with the one in the dialog. Both list the same pairs
       of characters; continue only if they match.

When the certificate no longer passes the check (a pinned one was renewed, or one checked by
name expired or no longer fits the name), Home Assistant stops reading the device and asks you to
sign in again. The dialog then names what was trusted so far and shows the new certificate. It
never switches between a name and a pin on its own: to pin instead of a name, clear the name
field. Home Assistant raises a repair for this;
[Ideas](ideas.md#sign-in-again-or-confirm-a-certificate) shows how to get it on your phone.

A device set up with a checked certificate never connects unchecked: if its stored name or
fingerprint is missing, Home Assistant asks you to confirm the certificate again. Without a
checked certificate, or over HTTP, the account step says so before you enter the password. Adding
a device again that is already set up with a checked certificate keeps it; to change how it is
checked, use *Reconfigure*.

![The certificate step with the fingerprint and how to compare it](assets/screenshots/setup-certificate.png){ width="560" }

## Account

Use an SRM **administrator** account (only those are tested) without two-factor
authentication; Home Assistant cannot enter codes unattended. A dedicated account for Home
Assistant is best: it shows up on its own in SRM's logs, and you can change its password without
touching anything else.

Each Home Assistant installation logs in under a session name of its own (`HomeAssistant-` and the
start of its instance ID), so its sessions can be told apart. Several programs or installations can
use one account side by side. Now and then SRM refuses a session right after the login (error 119,
measured on an MR2200ac); the integration then logs in again.

## Device trackers

A tracker is *home* while the client is on the network. Each router offers the clients it knows,
and keeps the trackers of the ones you choose. An access point next to a router leaves its clients
to the router; its setup and its options offer a menu to choose trackers of its own instead. An
access point whose clients no configured router knows (a network of its own) offers them right
away. So two routers of separate networks, for example one for work and one at home, each keep
their own trackers. A client known to several devices gets one tracker, from the first device
that wants it, routers first.

![An access point next to a router: finish, or choose trackers for it](assets/screenshots/setup-access-point.png){ width="560" }

The list to choose from shows the clients that matter: those online now (●), those with a name
given in SRM, those with an IPv4 DHCP lease or reservation, and those Home Assistant saw online in
the last 30 days (with the date, ○). SRM keeps every client it ever saw, so *Show all known clients*
lists the rest as well. *Track all clients* covers exactly the clients that matter, and new ones as
they appear; one gone for good does not get a tracker.

![The tracker step: track all, choose clients, show all known clients](assets/screenshots/setup-trackers.png){ width="560" }

Each tracker is the main entity of a device of its own, which stands for the client: identified
by its MAC address and named after the name given in SRM, wherever it is set; otherwise after the
name the client reports. A new name in SRM reaches Home Assistant with the next update; a name you
give the device in Home Assistant stays. The tracker shows the device's name. Its attributes:

| Attribute | Meaning |
| --- | --- |
| connected_to | the router or access point the client uses |
| connection | `wifi` or `ethernet` |
| radio, signal | for Wi-Fi clients |
| located_by | `wifi_list` (the device's own Wi-Fi list, reliable) or `device_list` (a client list, which can lag behind) |
| ip6_address | the client's IPv6 address (not link-local): from the client lists, else from the router's DHCPv6 lease or reservation |

A client counts as away only after it was missing for the *time until away* (3 minutes by
default): SRM marks idle wired clients offline for a minute now and then. When the router or
access point a client was last on cannot be read, its tracker keeps that location for up to 10
minutes instead of moving the client to the router. Wired clients behind an access point's LAN
port are shown on the router, because access points do not report them.

Trackers also help Home Assistant discover devices: integrations that recognise a device by its
host name or address (a PlayStation, a printer, ...) offer themselves under *Discovered*.

## Options

*Settings, Devices & services, Synology SRM Router, the gear icon*:

| Option | Default | Meaning |
| --- | --- | --- |
| Track all clients | off | Trackers for the clients that matter, and new ones as they appear. |
| Clients to track | none | These clients get a tracker, whether or not they matter. |
| Time until away | 180 s | How long a client must be missing before its tracker says away. |
| Sensor per firewall rule | off | Routers only: a sensor per rule that counts its hits, for graphs and automations. Also offered when you add a router. The rule table (see [Dashboards](dashboards.md#firewall-rules)) shows the hits without it. Switching it off removes these sensors. |
| Fast polling interval | 30 s | Clients, Wi-Fi, load, Ethernet ports and WAN. |
| Slow polling interval | 300 s | System information (firmware, last boot) and USB storage; on routers also DHCP and the firewall. |

Each update reads several values from the device; SRM devices answer slowly (about half a second
per call on an RT2600ac), so intervals much below the defaults mostly add load.

### Old trackers

Trackers of clients you no longer choose are removed. With *Track all clients*, none are removed,
and a client that no longer matters keeps its tracker. Devices with private (rotating) MAC
addresses collect such trackers over time, since each new address is a new client.

From the next restart or reload, a tracker of a client that no longer matters is still kept, but
not provided by the integration if you did not change it. Home Assistant then shows it as
unavailable instead of away, and offers to delete it, also several at once from the entity list.
Deleting the tracker's device deletes the tracker with it. If you delete only the tracker, the
integration removes its empty device at the next restart or reload. If the client comes back, it
gets its tracker back with the same entity ID.

A tracker stays provided, and says away, when any of these holds:

- you chose its client under *Clients to track*;
- you gave the tracker or its device a name, an area or a label, or the tracker an icon, a
  category or an alias, or hid it;
- a person uses it.

Known limits:

- A tracker that you only gave a new entity ID, for an automation, does not count as changed.
  Once its client no longer matters, it shows unavailable until the client is back.
- A client with a name or a DHCP reservation in SRM still matters, so its tracker stays. To let it
  go, remove the name or the reservation in SRM.
- If a client mattered only through the router's DHCP list and that list could not be read when
  Home Assistant started, its tracker shows unavailable until the next restart or reload.

## Coming from the built-in Synology SRM integration

Home Assistant's built-in `synology_srm` device tracker is set up in `configuration.yaml`. Once
this integration runs, remove its block:

```yaml
device_tracker:
  - platform: synology_srm   # remove this entry
```

and restart Home Assistant. Its entries in `known_devices.yaml` can go as well. If you keep both
for a while, both can use the same account; the built-in tracker asks the router every 12 seconds
(the default of YAML device trackers), which is load you can save once this integration runs.

## Changing the connection or signing in again

- *Reconfigure* changes host, port, HTTPS and certificate checking. A certificate that differs
  from the pinned one is shown for you to confirm first; one from a public authority is always
  shown, so you can switch between its name and a pin. Switching a checked device to an
  unchecked certificate or to HTTP asks for confirmation before the password is sent.
- Adding a device that is already set up, at a new address, updates the address of the existing
  entry instead.
- When the password changed, or the certificate no longer passes the check, Home Assistant asks
  you to sign in again and shows the new certificate for you to confirm.
