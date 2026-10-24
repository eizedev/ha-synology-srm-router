# Installation

Requires Home Assistant 2026.10 or newer and [HACS](https://hacs.xyz/).

## In HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eizedev&repository=ha-synology-srm-router&category=integration)

Or in HACS: the three dots, *Custom repositories*, add this URL with the type *Integration*:

```text
https://github.com/eizedev/ha-synology-srm-router
```

Install **Synology SRM Router**, then restart Home Assistant.

## Coming from the built-in Synology SRM integration

If your `configuration.yaml` has a `device_tracker` entry with `platform: synology_srm`, remove it
once this integration runs, or give this integration an SRM account of its own while both run:
the built-in tracker logs in every 12 seconds and never logs out, and two programs with one
account can end each other's sessions. [Details](configuration.md#coming-from-the-built-in-synology-srm-integration).

## Adding your devices

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=synology_srm_router)

Add the integration once per router and per access point (the button above, or *Settings,
Devices & services, Add integration, Synology SRM Router*). Set up the router first: it keeps the
device trackers, also for the clients on its access points.

![The first step: host, port, HTTPS and certificate checking](assets/screenshots/setup-connection.png){ width="560" }

You need an SRM **administrator** account without two-factor authentication; a dedicated account
is best ([why](configuration.md#account)). Everything else is explained in
[Configuration](configuration.md).

## Updating

HACS shows new versions; install them and restart Home Assistant. What changed is in the
[changelog](https://github.com/eizedev/ha-synology-srm-router/blob/main/CHANGELOG.md).
