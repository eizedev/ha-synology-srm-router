# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Old trackers can be deleted in Home Assistant. With *Track all clients*, a tracker of a client
  that no longer matters is no longer provided at setup, unless you chose its client or changed the
  tracker or its device (name, area, label, icon, category, alias, hidden, used by a person). Home
  Assistant then shows it as unavailable and offers *Delete*; until now it said away and could not
  be deleted. It comes back with the same entity ID when its client does.
  [#14](https://github.com/eizedev/ha-synology-srm-router/issues/14),
  [#45](https://github.com/eizedev/ha-synology-srm-router/issues/45)
- A client device left without its tracker is removed at the next setup. Devices of other
  integrations for the same client stay.

### Changed

- Automations, templates and dashboards that read such an old tracker see `unavailable` instead of
  `not_home`.

## [0.1.3] - 2026-10-30

### Fixed

- No more warning from Home Assistant about `DeviceEntry.config_entries` when a tracker names its
  device; that access stops working in Home Assistant 2027.10.

### Changed

- Every tracker is the main entity of a device of its own, which carries the client's name from
  SRM and its MAC address, as Home Assistant 2026.11 expects; it warned that trackers without
  device info stop working in 2028.11. On Home Assistant 2026.10 this adds a device for each
  tracked client; until now only clients another integration knows had one. Entity IDs stay; a
  name you gave a tracker's device stays too. [#47](https://github.com/eizedev/ha-synology-srm-router/issues/47)
- When a single read fails while the others work (the values it feeds show as unknown), the log
  says so once at info level, naming the read and the device, and again when it works. Before, only
  the debug log showed it.

## [0.1.2] - 2026-10-26

### Fixed

- A tracker's device keeps the client's name from SRM. When another integration knows the same
  MAC address (a Sonos speaker, a vacuum), Home Assistant renamed it to the host name the client
  reports on every load, and the tracker showed as `<host name> <name>`. Names you gave in Home
  Assistant stay. [#30](https://github.com/eizedev/ha-synology-srm-router/issues/30)

### Changed

- Release notes show the zip's SHA-256 in a block of its own, readable on phones.
- Docs: which entity IDs differ when Home Assistant runs in German, for the example dashboard; a
  roadmap in the README.

## [0.1.1] - 2026-10-26

### Fixed

- The icon is readable on light themes: transparent, with a variant for dark themes.
- Smaller screenshots in the README, side by side.

## [0.1.0] - 2026-10-26

### Added

- First version: one device per Synology router or access point (SRM), configured in the UI with
  certificate pinning, reauthentication and reconfiguration. Without a checked certificate the
  account step warns before the password is entered; adding a pinned device again keeps its pin.
  A certificate from a public authority (for example Let's Encrypt) is checked against the
  authorities and a name the user gives (the host name, or a name entered for a device added by
  its IP address; never a name read from the certificate), so its renewals need no
  confirmation; SRM's own certificate is pinned, and pinning stays available for the other kind.
  Reauthentication and *Reconfigure* name what was trusted so far and never switch between name
  and pin on their own. A checked device whose name or fingerprint is missing is refused and
  asks to confirm the certificate again, instead of connecting unchecked. *Reconfigure* warns
  before a checked device is switched to an unchecked certificate or to HTTP.
- Sensors for CPU load, memory, download and upload rate, clients (all, per Wi-Fi band and wired)
  and last boot; on routers WAN connection, public IPv4 and IPv6 address, WAN address type and
  whether the router is behind NAT.
- Device trackers that combine the client lists of all routers and access points, with the
  device, connection and radio a client uses; they keep their last reliable location for a while
  when the device a client was on cannot be read. After a restart, trackers of clients SRM no
  longer lists come back as away, with their last name.
- A repair when SRM's auto block locks out Home Assistant, also during setup (at the login or
  the first update), with a new login attempt every 15 minutes; it goes away with the entry.
- On routers: DHCP leases and reservations, the usage of each network's DHCP pool, and the number
  of firewall rules with a hash that changes with every rule change; the lists behind them as
  attributes (who holds an address and whether it is unknown, reservations not seen for 30 days,
  the rule table with hits and duplicates) on sensors that are disabled by default, with Markdown
  card templates that escape names from the devices (line breaks included), and dashboard views. A
  hits sensor per firewall rule on request (option *Sensor per firewall rule*). On every device:
  used and free space per USB volume.
- Diagnostics without addresses, names or secrets; the docs list what is stored and who can see
  it.
- English and German.
- Documentation website at https://ha-synology-srm-router.eize.dev/, with one page per repair
  (linked from the repair) and Markdown card templates for dashboards; screenshots and an example
  dashboard to download; a page of ideas and tested example automations.
- The tracker choice offers the clients that matter first (online, named in SRM, with an IPv4 DHCP
  lease or reservation, or seen in the last 30 days); all known clients on request. "Track all" covers
  exactly those, and new clients as they appear.
- Trackers carry the name given in SRM, also for clients on an access point, and count a client
  as away only after a configurable time (3 minutes by default), also right after a restart of
  Home Assistant. The Wi-Fi signal is left out of the recorded history, so the database does not
  grow with every change of a few dB.
- "Last seen" keeps clients for 30 days and is deleted with the last router or access point.
- Routers of separate networks each keep the trackers of their own clients; an access point keeps
  trackers when no configured router knows its clients, or when chosen in its menu.
- Trackers carry the client's IPv6 address (`ip6_address`, not link-local), and both addresses
  fall back to the router's DHCP leases and reservations: SRM's client list leaves out many
  addresses its own DHCP server handed out.
- Each Home Assistant installation logs in under its own session name, so its sessions can be told
  apart in SRM.

[Unreleased]: https://github.com/eizedev/ha-synology-srm-router/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/eizedev/ha-synology-srm-router/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/eizedev/ha-synology-srm-router/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/eizedev/ha-synology-srm-router/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/eizedev/ha-synology-srm-router/releases/tag/v0.1.0
