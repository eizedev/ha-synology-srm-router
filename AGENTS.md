# AGENTS.md

Instructions for AI coding agents working on this repository. People should read
[CONTRIBUTING.md](CONTRIBUTING.md) first; this file adds what an agent tends to get wrong.

## What this is

A Home Assistant custom integration (domain `synology_srm_router`) for Synology routers and
access points running SRM. It reads only, through the library
[aiosynologysrm](https://github.com/eizedev/aiosynologysrm); every call to the router goes through
that library.

## Commands

```sh
uv sync                       # environment from uv.lock (Home Assistant and its test harness)
uv run pytest --cov           # coverage must stay at 100 %
uv run ruff check . && uv run ruff format --check .
uv run mypy                   # strict
```

hassfest and the HACS check run in CI only.

## Rules that matter here

- **One config entry per SRM device.** Client locations are combined across all entries in
  `coordinator.LocationHub` with `aiosynologysrm.helpers.locate_clients()`. Do not query other
  entries' devices from an entry.
- **Coordinators poll, entities never do.** Fast coordinator: load, clients, Wi-Fi clients, WAN.
  Slow coordinator: system information. One failing fast read leaves its part empty; only when
  every read fails does the update fail. Reads the device does not offer are skipped, with their
  entities.
- **Trackers**: routers own them (access points only without a router), in a fixed order, so the
  load order does not matter. A tracker holds its location for `LOCATION_GRACE` while the device
  it was on is missing.
- **Errors**: authentication, two-factor, missing admin rights and certificate errors raise
  `ConfigEntryAuthFailed` (reauth confirms a new fingerprint); SRM's auto block raises a repair
  and is retried every `BLOCKED_RETRY`; everything else is `UpdateFailed` or
  `ConfigEntryNotReady`. A failed setup always logs out. Messages come from `strings.json` (`exceptions`).
- **Texts**: every user-facing text is in `strings.json` and in both `translations/en.json` and
  `translations/de.json`. Do not name SRM menu paths you have not checked on a device.
- **Schemas use `probatio`** (Home Assistant 2026.10), not voluptuous.
- **No personal data** in code, docs or tests. Test data comes from aiosynologysrm's anonymized
  fixtures in `tests/fixtures/`.
- **Docs describe the current state**: update `README.md`, `docs/` and `CHANGELOG.md` (Keep a
  Changelog, under `[Unreleased]`) in the same change. Commit messages follow Conventional
  Commits.
- **Website**: `docs/` and `zensical.toml` are https://ha-synology-srm-router.eize.dev/, built by
  `.github/workflows/docs.yml` with the shared design from eizedev/brand (`docs-site/`);
  `docs/assets/site.css` is copied in at build time and not committed. Every repair has a page in
  `docs/repairs/`, linked from the repair with `learn_more_url`; help links in the config flow
  point to sections of `docs/configuration.md` (`DOCS_*` in `config_flow.py`).
- **Screenshots** come from the demo instance in `scripts/demo/` (CONTRIBUTING.md, "Demo instance
  and screenshots"); regenerate them when dialogs or pages change, never take them from a real
  network. The example dashboard lives once, in `docs/assets/example-dashboard.yaml`.

## Don'ts

- Don't contact real devices from tests; use `tests/conftest.py`'s `FakeClient`.
- Don't add write actions (services, switches, buttons that change the router).
- Don't edit `uv.lock` by hand.
