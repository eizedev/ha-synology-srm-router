---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

<p class="hero-kicker">Home Assistant · HACS · read only</p>

# Synology SRM Router

<p class="hero-lead">Your <strong>Synology routers and access points</strong> in Home Assistant: load, traffic, WAN, clients per Wi-Fi band, DHCP, firewall rules with their hits, USB storage, and device trackers that know which router or access point, and which radio, each client uses.</p>

[Install](installation.md){ .md-button .md-button--primary }
[Source on GitHub](https://github.com/eizedev/ha-synology-srm-router){ .md-button }

</div>

<div class="cards" markdown>

- [**Installation**](installation.md)<br>HACS, the first device, the account to use.
- [**Configuration**](configuration.md)<br>Certificate, device trackers, options.
- [**Entities**](entities.md)<br>Sensors of routers and access points.
- [**Dashboards**](dashboards.md)<br>Who is where, by radio, DHCP leases and unknown devices, firewall rules.
- [**Ideas and automations**](ideas.md)<br>Presence, internet down, offline devices, data per day.
- [**Troubleshooting**](troubleshooting.md)<br>Messages, repairs, diagnostics, removal.

</div>

## What you get

- One device per router or access point, with CPU load, memory, download and upload rate, the
  number of clients on it (all, per Wi-Fi band and wired), the last boot, used and free space
  per USB volume, the channel of each Wi-Fi radio, and whether each Wi-Fi network (primary,
  guest) is on, per band.
- On routers: WAN connection, public IPv4 and IPv6 address, and whether the router sits behind
  another router or the provider's carrier-grade NAT; DHCP leases, reservations and how full
  each network's pool is; the firewall's rules with their hits. The lists behind these counts
  show who holds an address, which devices are unknown, and what each rule is about, named after
  your devices, on sensors you switch on; a sensor per rule that counts its hits is an option.
- Device trackers for the clients you choose (or all that matter). Each says whether the client is
  home and which device, connection and radio it uses. Clients on a standalone access point are
  found there, even though the router itself reports them as wired; names are the ones given in
  SRM.
- Checked certificates: a certificate from a public authority (such as Let's Encrypt) is checked
  by its name, so renewals need nothing; SRM's own certificate is shown once for you to confirm,
  then trusted exactly.
- It only reads: the integration never changes a setting in SRM.

Built on [aiosynologysrm](https://aiosynologysrm.eize.dev/).

> **Unofficial.** Not affiliated with, endorsed by or supported by Synology Inc.
