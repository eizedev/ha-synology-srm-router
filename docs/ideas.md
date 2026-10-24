# Ideas and automations

What you can do with the entities and trackers, with examples to copy. Each example is a
[package](https://www.home-assistant.io/docs/configuration/packages/): put the file into a
`packages` folder next to `configuration.yaml` and add

```yaml
homeassistant:
  packages: !include_dir_named packages
```

once, then restart. Or create the same automation in the editor (*Settings, Automations*, three
dots, *Edit in YAML*) from the part below `automation:`. Replace `rt2600ac` and `mr2200ac` with
your devices' entity ID prefixes, and `notify.mobile_app_phone` with your phone's notify action.

## Presence: who is home

A tracker is *home* while the client is on the network, so a phone's tracker can make a person
home or away: *Settings, People*, choose the person, and add the phone's tracker. The *time until
away* in the options (3 minutes by default) keeps a phone that sleeps briefly from leaving.

Phones use a private Wi-Fi address that can change, and a changed address is a new client to the
router. On an iPhone, iPad or Mac, set *Private Wi-Fi Address* of your home network to *Fixed*
(or *Off*), not *Rotating* ([Apple](https://support.apple.com/en-nz/102509)). Android phones have
a similar per-network setting whose name depends on the maker, for example *MAC address type*.

## Internet down, and for how long

```yaml
--8<-- "docs/assets/ideas/internet_down.yaml"
```

## Public address changed

```yaml
--8<-- "docs/assets/ideas/public_ip.yaml"
```

Behind carrier-grade NAT the public address is shared and changes without notice; see
[Entities](entities.md).

## Router or access point restarted

```yaml
--8<-- "docs/assets/ideas/restarted.yaml"
```

## An important device is offline

```yaml
--8<-- "docs/assets/ideas/device_offline.yaml"
```

A device that barely talks to the router, for example a managed switch with a fixed address, can
appear offline in SRM's client list although it works. For such devices, Home Assistant's
[Ping](https://www.home-assistant.io/integrations/ping/) integration is the better source.

## Weak Wi-Fi

```yaml
--8<-- "docs/assets/ideas/weak_wifi.yaml"
```

## Clients per band

Three sensors that count the clients at home by band and cable; with their history you see how
many still use 2.4 GHz.

```yaml
--8<-- "docs/assets/ideas/clients_by_band.yaml"
```

## Data per day and month

```yaml
--8<-- "docs/assets/ideas/data_volume.yaml"
```

The examples are tested: the [demo instance](https://github.com/eizedev/ha-synology-srm-router/blob/main/CONTRIBUTING.md#demo-instance-and-screenshots)
loads them at every start.
