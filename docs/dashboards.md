# Dashboards

The trackers carry where a client is (`connected_to`), how (`connection`) and on which radio
(`radio`, `signal`). A Markdown card turns that into lists, with nothing to install: add a card
of the type *Markdown* and paste one of the templates below as its content. Names come from the
devices themselves, so the templates escape what Markdown would read as a table, a link or an
image, and turn line breaks into spaces. A name that is itself a web address can still show as a
link to that address, as it reads.

## Who is where

Every client at home, grouped by the router or access point it uses:

```jinja
--8<-- "docs/assets/cards/where.jinja"
```

Each name links to the client's history.

## By radio

Wi-Fi clients by band, with the device they use; useful to see what still uses 2.4 GHz:

```jinja
--8<-- "docs/assets/cards/radio.jinja"
```

The radio names are SRM's: `2.4G`, `5G`, and `5G-2` for a second 5 GHz radio.

## Who has an address

![The DHCP view of the example dashboard: every lease, online first, reserved or unknown](assets/screenshots/dashboard-dhcp.png)

Every IPv4 lease of the router, online devices first: reserved, unknown (neither reserved nor
named in SRM), or when the lease runs out. The template finds the router's *DHCP leases* sensor
by itself; enable that sensor first (it is disabled by default, see [Entities](entities.md)). The
DHCP and firewall templates work the same way with *DHCP reservations* and *Firewall rules*.

```jinja
--8<-- "docs/assets/cards/leases.jinja"
```

## Unknown devices

The question to ask now and then: who is this? Devices with an address that you have neither
reserved nor named in SRM:

```jinja
--8<-- "docs/assets/cards/unknown.jinja"
```

## Reservations to tidy up

Reservations whose device Home Assistant has not seen online for 30 days. Right after installing
the integration that is every reservation of a device that is offline; give it a month.

```jinja
--8<-- "docs/assets/cards/reservations.jinja"
```

## Firewall rules

![The firewall view of the example dashboard: rules in SRM's order with direction, ports and hits](assets/screenshots/dashboard-firewall.png)

The rule table in SRM's order: what a rule allows or blocks, from where to where, and how often
it matched. *never hit* and *duplicate* point to rules that do nothing.

```jinja
--8<-- "docs/assets/cards/firewall.jinja"
```

On a phone a table this wide does not fit. This one lists the same, two lines per rule:

```jinja
--8<-- "docs/assets/cards/firewall-list.jinja"
```

The example dashboard shows the table on wide screens and the list on narrow ones, with two
*Conditional* cards and a *Screen* condition (`(min-width: 900px)` and `(max-width: 899px)`).

Hits count since SRM last built its firewall, so they start again after a rule change or a
restart. For hits over time, switch on *Sensor per firewall rule* in the router's options and add
a *Statistics graph* card with the rules you care about, for example the blocking ones:

```yaml
type: statistics-graph
title: Blocked per hour
entities:
  - sensor.rt2600ac_firewall_hits_block_telemetry   # your rules' sensors
days_to_show: 1
period: hour
stat_types: [change]
chart_type: line
```

*change* is the number of hits per hour. Prefer lines to bars here: with several rules, bars of one
hour stand side by side and spread over the time axis, which reads like hits at other times.
Statistics start with the first full hour after a sensor was added.

## A complete dashboard

![The example dashboard's first view: router, access point, by radio, who is where](assets/screenshots/dashboard.png)

Router and access point with gauges, tiles and a traffic graph, the client lists above, and views for DHCP and the firewall.
[Download it](assets/example-dashboard.yaml) or copy it from here; the comment at the top says
where to paste it and which entity IDs to adjust.

### Entity IDs in other languages

Home Assistant builds an entity ID from the entity's name in the language it had when the entity
was created, for German and a number of other languages; for the rest it uses English. The
example uses the English IDs. In German, these differ (the device prefix stays the model name):

| English | German |
|---|---|
| `sensor.<device>_cpu_load` | `sensor.<device>_cpu_last` |
| `sensor.<device>_memory_usage` | `sensor.<device>_speicherauslastung` |
| `binary_sensor.<device>_wan_connection` | `binary_sensor.<device>_wan_verbindung` |
| `sensor.<device>_public_ipv4_address` | `sensor.<device>_offentliche_ipv4_adresse` |
| `sensor.<device>_dhcp_pool_usage_lan` | `sensor.<device>_dhcp_pool_belegt_lan` |
| `sensor.<device>_dhcp_reservations` | `sensor.<device>_dhcp_reservierungen` |
| `sensor.<device>_firewall_rules` | `sensor.<device>_firewall_regeln` |
| `sensor.<device>_wired_clients` | `sensor.<device>_kabel_clients` |
| `sensor.<device>_wi_fi_clients_5_ghz` | `sensor.<device>_wlan_clients_5_ghz` |
| `sensor.<device>_last_boot` | `sensor.<device>_letzter_start` |

`clients`, `download_rate`, `upload_rate` and `dhcp_leases` are the same in both. The Markdown
templates find their sensors by attribute, not by ID, and work in every language. Every
entity's ID is shown in its settings.

```yaml
--8<-- "docs/assets/example-dashboard.yaml"
```
