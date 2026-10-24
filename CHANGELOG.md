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
- A repair when SRM's auto block locks out Home Assistant, with a new login attempt every 15
  minutes.
- Diagnostics without addresses, names or secrets.
- English and German.
- The tracker choice offers the clients that matter first (online, named in SRM, with a DHCP lease
  or reservation, or seen in the last 30 days); all known clients on request. "Track all" covers
  exactly those, and new clients as they appear.
- Trackers carry the name given in SRM, also for clients on an access point, and count a client
  as away only after a configurable time (3 minutes by default).

[Unreleased]: https://github.com/eizedev/ha-synology-srm-router/commits/main
