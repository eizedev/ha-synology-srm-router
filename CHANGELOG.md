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

[Unreleased]: https://github.com/eizedev/ha-synology-srm-router/commits/main
