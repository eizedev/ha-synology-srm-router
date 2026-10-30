# Synology SRM Router for Home Assistant

| HACS | Release | CI | License |
| ---- | ------- | -- | ------- |
| [![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5?cacheSeconds=3600)](https://hacs.xyz/docs/faq/custom_repositories/) | [![Release](https://img.shields.io/github/v/release/eizedev/ha-synology-srm-router?cacheSeconds=3600)](https://github.com/eizedev/ha-synology-srm-router/releases) | [![CI](https://github.com/eizedev/ha-synology-srm-router/actions/workflows/ci.yml/badge.svg)](https://github.com/eizedev/ha-synology-srm-router/actions/workflows/ci.yml) | [![License](https://img.shields.io/github/license/eizedev/ha-synology-srm-router?cacheSeconds=3600)](https://github.com/eizedev/ha-synology-srm-router/blob/main/LICENSE) |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/assets/header-dark.svg">
  <img alt="Synology SRM Router for Home Assistant" src="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/assets/header-light.svg" height="72">
</picture>

Shows your **Synology routers and access points** (SRM) in Home Assistant: load, traffic, WAN,
clients per Wi-Fi band, DHCP, firewall rules with their hits, USB storage, and device trackers that
tell which router or access point, and which radio, a client is connected to. Read only: it never
changes a setting.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eizedev&repository=ha-synology-srm-router&category=integration)
[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=synology_srm_router)
[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feizedev%2Fha-synology-srm-router%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsynology_srm_router%2Fnotify_wifi_events.yaml)

> **Unofficial.** Not affiliated with, endorsed by or supported by Synology Inc.

**Documentation: [ha-synology-srm-router.eize.dev](https://ha-synology-srm-router.eize.dev/)**

<p>
  <img src="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/docs/assets/screenshots/dashboard.png" alt="A dashboard with router, access point, Wi-Fi clients by radio and who is where" width="49%">
  <img src="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/docs/assets/screenshots/dashboard-firewall.png" alt="The firewall view: every rule with the devices it is about, its ports and hits" width="49%">
</p>

## What you get

- One device per router or access point: CPU load, memory, download and upload rate, clients
  (all, per Wi-Fi band and wired), last boot, USB storage, the channel of each Wi-Fi radio and
  whether each Wi-Fi network (primary, guest) is on, per band, with events (and a blueprint for
  notifications) when a fixed channel changes or a network is switched off or on.
- An event when a client joins the network for the first time, with a blueprint for notifications.
- Link and speed of every Ethernet port of routers and access points.
- On routers: WAN connection, public IPv4 and IPv6 address, whether the router is behind NAT, DHCP
  leases, reservations and pool usage, and the firewall rules with their hits. Lists behind the
  counts show who holds an address, which devices are unknown, and what each firewall rule is
  about, named after your devices (sensors you switch on); a hits sensor per rule on request.
- Device trackers that know which router or access point, connection and radio each client
  uses, named as in SRM.
- Checked certificates (by name for public certificate authorities such as Let's Encrypt, so
  renewals need nothing; pinned for SRM's own), and nothing but reading: the integration never
  changes a setting.

## Install

In HACS, add this repository as a custom repository of the type *Integration* (or use the button
above), install **Synology SRM Router** and restart Home Assistant:

```text
https://github.com/eizedev/ha-synology-srm-router
```

Then add the integration once per router and per access point, router first. Requires Home
Assistant 2026.10.3 or newer. Details: [Installation](https://ha-synology-srm-router.eize.dev/installation/).

Without HACS: download `synology_srm_router.zip` from the
[latest release](https://github.com/eizedev/ha-synology-srm-router/releases/latest) and unpack it
into `custom_components/synology_srm_router/` in your Home Assistant configuration
([details](https://ha-synology-srm-router.eize.dev/installation/#without-hacs)).

## Documentation

- [Configuration](https://ha-synology-srm-router.eize.dev/configuration/): certificate, account, device trackers, options
- [Entities](https://ha-synology-srm-router.eize.dev/entities/)
- [Events](https://ha-synology-srm-router.eize.dev/events/): new clients, Wi-Fi channel and network changes, blueprints for notifications
- [Dashboards](https://ha-synology-srm-router.eize.dev/dashboards/): who is where, by radio, DHCP leases and unknown devices, firewall rules
- [Ideas and automations](https://ha-synology-srm-router.eize.dev/ideas/): presence, internet down, offline devices, data per day
- [Troubleshooting](https://ha-synology-srm-router.eize.dev/troubleshooting/): messages, repairs, diagnostics, removal

## Roadmap

Planned work is grouped in [milestones](https://github.com/eizedev/ha-synology-srm-router/milestones):
[0.4.0](https://github.com/eizedev/ha-synology-srm-router/milestone/5) brings change events,
repairs for risky router settings and discovery. Ideas and reports
are welcome in the [issues](https://github.com/eizedev/ha-synology-srm-router/issues).

## Credits

Built on the library [aiosynologysrm](https://github.com/eizedev/aiosynologysrm). Earlier
integrations that showed what is possible:
[ha-synology-srm-plus](https://github.com/infernalK/ha-synology-srm-plus) and
[synology-srm-extended](https://github.com/Vachler/synology-srm-extended).

## License

[MIT](https://github.com/eizedev/ha-synology-srm-router/blob/main/LICENSE). The icon and header are CC BY 4.0; their source is in
[eizedev/brand](https://github.com/eizedev/brand).
