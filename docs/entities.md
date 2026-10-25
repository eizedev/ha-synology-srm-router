# Entities

![A router's device page](assets/screenshots/device-router.png)

## Every router and access point

| Entity | Unit | Notes |
| --- | --- | --- |
| CPU load | % | user, system and other load added up |
| Memory usage | % | |
| Download rate, Upload rate | Mbit/s (changeable per sensor) | the device's total traffic; measured against the kernel's counters |
| Clients | | online clients attached to this device, by Wi-Fi or cable |
| Wi-Fi clients 2.4 GHz, Wi-Fi clients 5 GHz, Wired clients | | the same, by band and cable (all clients, also those without a tracker) |
| Last boot | timestamp | diagnostic |
| Load average (1, 5, 15 min) | | diagnostic, disabled by default |
| *volume* used, *volume* free space | %, GB | per USB volume, by its name in SRM (else its folder); unavailable while the drive is not attached, and kept until you delete them |
| *volume* size | GB | per USB volume; diagnostic, disabled by default |

Entities whose value the device's firmware does not offer are not created.

## Routers only

| Entity | Notes |
| --- | --- |
| WAN connection | connectivity |
| Public IPv4 address | the address the internet sees, as SRM last recorded it (can be out of date) |
| IPv6 address | the WAN interface's address, read live |
| WAN IPv4 address | the WAN interface's own address; diagnostic, disabled by default |
| WAN address type | public, private (another router in front) or carrier-grade NAT; diagnostic |
| Behind NAT | on when nothing on the internet can reach the router over IPv4 directly (port forwards will not work over IPv4); diagnostic |
| DHCP leases | IPv4 leases SRM lists; attribute `leases`: one row per lease (see below) |
| DHCP reservations | fixed IPv4 addresses set up in SRM; diagnostic; attribute `reservations` (see below) |
| DHCP pool usage LAN, guest network | share of the pool's IPv4 addresses that are leased or reserved, per network; attributes `begin`, `end`. The names LAN and guest network are those of SRM's usual interfaces (`lbr0`, `gbr0`, seen on an RT2600ac and an MR2200ac); other pools are named after their interface. A switched-off DHCP server gets no pool sensor; one that is switched off later leaves its sensor unavailable |
| Firewall rules | how many rules SRM has; diagnostic. `config_hash` changes whenever a rule is added, removed, edited, switched on or off, or moved; `rules`: the rule table (see below) |
| Firewall hits *rule* | only with the option *Sensor per firewall rule*: packets a rule matched since SRM last built its firewall (after a change or a restart the counter starts again; statistics handle that). Unknown while the counters cannot be read. Switched-off rules start disabled |

The lists behind the counts are kept out of the recorder (history and statistics keep the
numbers only) and change every slow update (5 minutes by default). Like every state, they are
visible to all users of your Home Assistant, not only to administrators:

| Attribute | One row per | Fields |
| --- | --- | --- |
| `leases` | IPv4 lease, online clients first | `name`, `ip`, `mac`, `online`, `reserved`, `unknown` (neither reserved nor named in SRM), `expires_in_min` (none for reserved addresses) |
| `reservations` | IPv4 reservation | `name`, `ip`, `mac`, `online`, `last_seen` (date Home Assistant last saw it online), `stale` (offline and not seen for 30 days, or never since the integration runs), `in_pool` (the address lies inside a dynamic pool) |
| `rules` | firewall rule, in SRM's order | `name`, `label`, `enabled`, `action`, `ip_version`, `protocol`, `chain` (`input`: to the router, `forward`: through it, `both_input_forward`: both), `in_interfaces`, `out_interfaces`, `source`, `destination`, `ports`, `hits`, `duplicate` (same as an earlier rule, which matches first) |

[Dashboards](dashboards.md) has Markdown cards that turn these into tables.

A firewall rule is recognised by what it does, not by its place in the list: moving or switching
it keeps its hits sensor. Editing it (also renaming) gives it a new sensor, the old one is
removed, and the long-term statistics stay with the old one. Rules with the same name show their
IP version, for example *Firewall hits Block (IPv4)*. Names are set when a sensor is created.

## Device trackers

See [Configuration](configuration.md#device-trackers).
