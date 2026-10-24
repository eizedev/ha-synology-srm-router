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

## What you get

- One device per router or access point, with CPU load, memory, download and upload rate, the
  number of clients on it, and the last boot.
- On routers: WAN connection, public IPv4 and IPv6 address, and whether the router sits behind
  another router or the provider's carrier-grade NAT.
- Device trackers for the clients you choose (or all). Each says whether the client is home and
  which device, connection and radio it uses. Clients on a standalone access point are found
  there, even though the router itself reports them as wired.
- Certificate pinning: the router's certificate is shown once for you to confirm, then trusted
  exactly.

## Install

1. Use the button above, or in HACS open the three dots, *Custom repositories*, and add this
   URL with the type *Integration*:

   ```text
   https://github.com/eizedev/ha-synology-srm-router
   ```

   Then install **Synology SRM Router**.
2. Restart Home Assistant.
3. Add the integration once per router and per access point (button above, or *Settings, Devices
   & services, Add integration*). Use an SRM administrator account without two-factor
   authentication; a dedicated account is best.

Requires Home Assistant 2026.10 or newer.

## Documentation

- [Configuration and options](docs/configuration.md)
- [Entities](docs/entities.md)
- [Troubleshooting and removal](docs/troubleshooting.md)

## Credits

Built on the library [aiosynologysrm](https://github.com/eizedev/aiosynologysrm). Earlier
integrations that showed what is possible:
[ha-synology-srm-plus](https://github.com/infernalK/ha-synology-srm-plus) and
[synology-srm-extended](https://github.com/Vachler/synology-srm-extended).

## License

[MIT](LICENSE). The icon and header are CC BY 4.0; their source is in
[eizedev/brand](https://github.com/eizedev/brand).
