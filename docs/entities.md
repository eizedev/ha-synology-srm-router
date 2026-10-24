# Entities

## Every router and access point

| Entity | Unit | Notes |
| --- | --- | --- |
| CPU load | % | user, system and other load added up |
| Memory usage | % | |
| Download rate, Upload rate | bytes per second | the device's total traffic; measured against the kernel's counters |
| Clients | | online clients attached to this device, by Wi-Fi or cable |
| Last boot | timestamp | diagnostic |
| Load average (1, 5, 15 min) | | diagnostic, disabled by default |

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

## Device trackers

One tracker per chosen client. It is *home* while the client is on the network. Attributes:

| Attribute | Meaning |
| --- | --- |
| connected_to | the router or access point the client uses |
| connection | `wifi` or `ethernet` |
| radio, signal | for Wi-Fi clients |
| located_by | `wifi_list` (the device's own Wi-Fi list, reliable) or `device_list` (a client list, which can lag behind) |

When the router or access point a client was last on cannot be read, its tracker keeps that
location for up to 10 minutes instead of moving the client to the router or marking it away; a
location from a Wi-Fi list is taken at once. The router's entry creates the trackers (an access
point's entry only when no router is set up). Trackers of clients you no longer choose are
removed; a client's device can also be deleted by hand. Wired clients behind an access point's LAN port are shown on
the router, because access points do not report them.
