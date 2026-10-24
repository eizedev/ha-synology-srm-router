# Synology SRM Router for Home Assistant

| HACS | Release | CI | License |
| ---- | ------- | -- | ------- |
| [![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5?cacheSeconds=3600)](https://hacs.xyz/docs/faq/custom_repositories/) | [![Release](https://img.shields.io/github/v/release/eizedev/ha-synology-srm-router?cacheSeconds=3600)](https://github.com/eizedev/ha-synology-srm-router/releases) | [![CI](https://github.com/eizedev/ha-synology-srm-router/actions/workflows/ci.yml/badge.svg)](https://github.com/eizedev/ha-synology-srm-router/actions/workflows/ci.yml) | [![License](https://img.shields.io/github/license/eizedev/ha-synology-srm-router?cacheSeconds=3600)](LICENSE) |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/assets/header-dark.svg">
  <img alt="Synology SRM Router for Home Assistant" src="https://raw.githubusercontent.com/eizedev/ha-synology-srm-router/main/assets/header-light.svg" height="72">
</picture>

Shows your **Synology routers and access points** (SRM) in Home Assistant: load, memory, traffic,
WAN state and addresses, and device trackers that tell which router or access point, and which
radio, a client is connected to. Read only: it never changes a setting.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eizedev&repository=ha-synology-srm-router&category=integration)
[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=synology_srm_router)

> **Unofficial.** Not affiliated with, endorsed by or supported by Synology Inc.

**Documentation: [ha-synology-srm-router.eize.dev](https://ha-synology-srm-router.eize.dev/)**

![A dashboard with router, access point, Wi-Fi clients by radio and who is where](docs/assets/screenshots/dashboard.png)

## What you get

- One device per router or access point: CPU load, memory, download and upload rate, clients,
  last boot; on routers WAN connection, public IPv4 and IPv6 address, and whether the router is
  behind NAT.
- Device trackers that know which router or access point, connection and radio each client
  uses, named as in SRM.
- Certificate pinning, and nothing but reading: the integration never changes a setting.

## Install

In HACS, add this repository as a custom repository of the type *Integration* (or use the button
above), install **Synology SRM Router** and restart Home Assistant:

```text
https://github.com/eizedev/ha-synology-srm-router
```

Then add the integration once per router and per access point, router first. Requires Home
Assistant 2026.10 or newer. Details: [Installation](https://ha-synology-srm-router.eize.dev/installation/).

## Documentation

- [Configuration](https://ha-synology-srm-router.eize.dev/configuration/): certificate, account, device trackers, options
- [Entities](https://ha-synology-srm-router.eize.dev/entities/)
- [Dashboards](https://ha-synology-srm-router.eize.dev/dashboards/): who is where, by device and by radio
- [Troubleshooting](https://ha-synology-srm-router.eize.dev/troubleshooting/): messages, repairs, diagnostics, removal

## Credits

Built on the library [aiosynologysrm](https://github.com/eizedev/aiosynologysrm). Earlier
integrations that showed what is possible:
[ha-synology-srm-plus](https://github.com/infernalK/ha-synology-srm-plus) and
[synology-srm-extended](https://github.com/Vachler/synology-srm-extended).

## License

[MIT](LICENSE). The icon and header are CC BY 4.0; their source is in
[eizedev/brand](https://github.com/eizedev/brand).
