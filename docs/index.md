---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

<p class="hero-kicker">Home Assistant · HACS · read only</p>

# Synology SRM Router

<p class="hero-lead">Your <strong>Synology routers and access points</strong> in Home Assistant: load, traffic, WAN state and addresses, and device trackers that know which router or access point, and which radio, each client uses.</p>

[Install](installation.md){ .md-button .md-button--primary }
[Source on GitHub](https://github.com/eizedev/ha-synology-srm-router){ .md-button }

</div>

<div class="cards" markdown>

- [**Installation**](installation.md)<br>HACS, the first device, the account to use.
- [**Configuration**](configuration.md)<br>Certificate, device trackers, options.
- [**Entities**](entities.md)<br>Sensors of routers and access points.
- [**Dashboards**](dashboards.md)<br>Who is where, by device and by radio.
- [**Troubleshooting**](troubleshooting.md)<br>Messages, repairs, diagnostics, removal.
- [**Source code**](https://github.com/eizedev/ha-synology-srm-router)<br>Issues, discussions, contributing.

</div>

## What you get

- One device per router or access point, with CPU load, memory, download and upload rate, the
  number of clients on it, and the last boot.
- On routers: WAN connection, public IPv4 and IPv6 address, and whether the router sits behind
  another router or the provider's carrier-grade NAT.
- Device trackers for the clients you choose (or all that matter). Each says whether the client is
  home and which device, connection and radio it uses. Clients on a standalone access point are
  found there, even though the router itself reports them as wired; names are the ones given in
  SRM.
- Certificate pinning: the device's certificate is shown once for you to confirm, then trusted
  exactly.
- It only reads: the integration never changes a setting in SRM.

Built on [aiosynologysrm](https://aiosynologysrm.eize.dev/).

> **Unofficial.** Not affiliated with, endorsed by or supported by Synology Inc.
