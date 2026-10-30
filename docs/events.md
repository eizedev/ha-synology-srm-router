# Events

Each router and access point has a **Wi-Fi events** entity. It fires when something about its
Wi-Fi changes that is worth knowing, and stays quiet otherwise:

| Event | When | Attributes |
| --- | --- | --- |
| `channel_changed` | a radio set to a **fixed** channel in SRM runs on another one; on 5 GHz usually a radar (DFS) switch. A radio on automatic channel selection changes its channel by itself, which is not an event | `band`, `channel`, `previous` |
| `network_off` | a Wi-Fi network (primary, guest, ...) was switched off | `network`, `bands` |
| `network_on` | a Wi-Fi network was switched on | `network`, `bands` |

A network switched off or on fires once, with all bands it concerns: with Smart Connect, every band
changes together. Nothing fires for the state at Home Assistant's start, and a read that fails keeps
the last values, so it does not look like a change either. The Wi-Fi values are read with the slow
update (every 5 minutes by default), so an event can come up to that late.

## Notifications

The blueprint sends a notification for the events you choose; by default to Home Assistant's
notifications, or with any action, for example to your phone.

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feizedev%2Fha-synology-srm-router%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsynology_srm_router%2Fnotify_wifi_events.yaml)

Create one automation from it per router or access point, and pick its *Wi-Fi events* entity.
