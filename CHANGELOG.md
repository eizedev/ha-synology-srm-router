# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- First version: one device per Synology router or access point (SRM), configured in the UI with
  certificate pinning, reauthentication and reconfiguration.
- Sensors for CPU load, memory, download and upload rate, clients and last boot; on routers WAN
  connection, public IPv4 and IPv6 address, WAN address type and whether the router is behind NAT.
- Device trackers that combine the client lists of all routers and access points, with the
  device, connection and radio a client uses; they keep their last reliable location for a while
  when the device a client was on cannot be read.
- A repair when SRM's auto block locks out Home Assistant, also during setup, with a new login
  attempt every 15 minutes; it goes away with the entry.
- On routers: DHCP leases and reservations, the usage of each network's DHCP pool, the number of
  firewall rules with a hash that changes with every rule change, and a hits sensor per firewall
  rule; on every device: used and free space per USB volume.
- Diagnostics without addresses, names or secrets.
- English and German.
- Documentation website at https://ha-synology-srm-router.eize.dev/, with one page per repair
  (linked from the repair) and Markdown card templates for dashboards; screenshots and an example
  dashboard to download; a page of ideas and tested example automations.
- The tracker choice offers the clients that matter first (online, named in SRM, with a DHCP lease
  or reservation, or seen in the last 30 days); all known clients on request. "Track all" covers
  exactly those, and new clients as they appear.
- Trackers carry the name given in SRM, also for clients on an access point, and count a client
  as away only after a configurable time (3 minutes by default), also right after a restart of
  Home Assistant. The Wi-Fi signal is left out of the recorded history, so the database does not
  grow with every change of a few dB.
- "Last seen" keeps clients for 30 days, so rotating private MAC addresses do not pile up.
- Routers of separate networks each keep the trackers of their own clients; an access point keeps
  trackers when no configured router knows its clients, or when chosen in its menu.
- Trackers carry the client's IPv6 address (`ip6_address`, not link-local), and both addresses
  fall back to the router's DHCP leases and reservations: SRM's client list leaves out many
  addresses its own DHCP server handed out.
- Each Home Assistant installation logs in under its own session name, because SRM ends a session
  when the same account logs in again under the same name.

[Unreleased]: https://github.com/eizedev/ha-synology-srm-router/commits/main
