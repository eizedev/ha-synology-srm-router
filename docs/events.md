# Events

Each router and access point has two event entities: **Wi-Fi events** and **New clients**. Routers
also have **Router events**.

## Wi-Fi events

The **Wi-Fi events** entity fires when something about its Wi-Fi changes that is worth knowing,
and stays quiet otherwise:

| Event | When | Attributes |
| --- | --- | --- |
| `channel_changed` | a radio set to a **fixed** channel in SRM runs on another one; on 5 GHz usually a radar (DFS) switch. A radio on automatic channel selection changes its channel by itself, which is not an event | `band`, `channel`, `previous` |
| `network_off` | a Wi-Fi network (primary, guest, ...) was switched off | `network`, `bands` |
| `network_on` | a Wi-Fi network was switched on | `network`, `bands` |

A network switched off or on fires once, with all bands it concerns: with Smart Connect, every band
changes together. Nothing fires for the state at Home Assistant's start, and a read that fails keeps
the last values, so it does not look like a change either. The Wi-Fi values are read with the slow
update (every 5 minutes by default), so an event can come up to that late.

### Notifications

The Wi-Fi blueprint sends a notification for the events you choose; by default to Home Assistant's
notifications, or with any action, for example to your phone.

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feizedev%2Fha-synology-srm-router%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsynology_srm_router%2Fnotify_wifi_events.yaml)

Create one automation from it per router or access point, and pick its *Wi-Fi events* entity.

## New clients

The **New clients** entity fires `new_client` when a client is online for the first time, on the
device it is attached to: a guest's phone, a new printer, or something that should not be there.

| Attribute | Meaning |
| --- | --- |
| `name` | the name given in SRM, else the one the client reports, else its MAC address |
| `mac`, `ip` | its MAC and IPv4 address (kept out of the history) |
| `connection`, `band` | `wifi` with the band, or `ethernet` |
| `private_mac` | `true` for a locally administered (random) address, as phones and laptops use per network |

A client counts as new once: Home Assistant remembers every address it has seen
(`.storage/synology_srm_router.known_clients`). A private address is forgotten 30 days after it was
last seen, so a phone that rotates its address may come back as new; the blueprint leaves those out
unless you include them. At the integration's first start every client present is taken in without
an event, and so is a client that appears while a router or access point could not be read, since
its lists are incomplete then.

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feizedev%2Fha-synology-srm-router%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsynology_srm_router%2Fnotify_new_clients.yaml)

Create one automation per router or access point, and pick its *New clients* entity.

## Router events

The **Router events** entity of a router fires when something changes that other devices or your
security depend on:

| Event | When | Attributes |
| --- | --- | --- |
| `prefix_changed` | the IPv6 prefix of a local network changed, appeared or is gone: addresses, DNS records and firewall rules elsewhere that use the old prefix stop working | `changes`: one row per network with `network` (`lan`, `guest`, or the interface's name), `prefix` and `previous` (empty when there was none) |
| `firewall_changed` | firewall rules were added, removed, switched on or off, or moved, or a default policy changed | `added`, `removed`, `enabled`, `disabled`: rule names; `reordered`: whether the order changed; `policy`: one row per changed default policy with `traffic` (for example `ipv6_wan_to_lan`), `policy` and `previous` |

Everything that changed between two reads fires as one event, so five edited rules make one
notification. SRM gives a rule no fixed number, so an edited rule (also a renamed one) shows as
removed and added. The lifetimes of a prefix change with every read and are no change.

The router's last state is stored (`.storage/synology_srm_router.router_events.<entry>`), so a
change made while Home Assistant was off fires once it has started. The very first start only
takes in the current state, and a read that fails keeps the last one, so neither looks like a
change. Both are read with the slow update (every 5 minutes by default), so an event can come up
to that late. Removing the router's entry deletes the stored state.

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feizedev%2Fha-synology-srm-router%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsynology_srm_router%2Fnotify_router_events.yaml)

Create one automation per router, and pick its *Router events* entity.
