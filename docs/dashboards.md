# Dashboards

The trackers carry where a client is (`connected_to`), how (`connection`) and on which radio
(`radio`, `signal`). A Markdown card turns that into lists, with nothing to install: add a card
of the type *Markdown* and paste one of the templates below as its content.

## Who is where

Every client at home, grouped by the router or access point it uses:

```jinja
{% set ts = states.device_tracker
   | selectattr('state', 'eq', 'home')
   | selectattr('attributes.connected_to', 'defined')
   | list %}
{% for g in ts | groupby('attributes.connected_to') %}
**{{ g.grouper }}** ({{ g.list | count }})
{% for s in g.list | sort(attribute='name') %}
- [{{ s.name }}](/history?entity_id={{ s.entity_id }}) · {{ s.attributes.connection }}{% if s.attributes.radio %} {{ s.attributes.radio }}, signal {{ s.attributes.signal }}{% endif %}
{% endfor %}
{% endfor %}
```

Each name links to the client's history.

## By radio

Wi-Fi clients by band, with the device they use; useful to see what still uses 2.4 GHz:

```jinja
{% set ts = states.device_tracker
   | selectattr('state', 'eq', 'home')
   | selectattr('attributes.radio', 'defined')
   | selectattr('attributes.radio', 'ne', none)
   | list %}
{% for g in ts | groupby('attributes.radio') %}
**{{ g.grouper }}** ({{ g.list | count }})
{% for s in g.list | sort(attribute='name') %}
- {{ s.name }} · {{ s.attributes.connected_to }}, signal {{ s.attributes.signal }}
{% endfor %}
{% endfor %}
```

The radio names are SRM's: `2.4G`, `5G`, and `5G-2` for a second 5 GHz radio.

## Devices

A dashboard of the [sections](https://www.home-assistant.io/dashboards/sections/) type with a
*Gauge* card for CPU load and memory, *Tile* cards for clients, last boot and the WAN entities, and
a *Statistics graph* of the download and upload rate gives a quick overview per device.
