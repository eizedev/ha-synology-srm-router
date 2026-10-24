# Entities

## Every router and access point

| Entity | Unit | Notes |
| --- | --- | --- |
| CPU load | % | user, system and other load added up |
| Memory usage | % | |
| Download rate, Upload rate | Mbit/s (changeable per sensor) | the device's total traffic; measured against the kernel's counters |
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

See [Configuration](configuration.md#device-trackers).
