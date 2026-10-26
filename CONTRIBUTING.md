# Contributing

Thanks for helping. Reports from setups that are not tested yet help most: other models, other
SRM versions, and mesh setups.

## Reporting a problem

Use the **Bug report** form and attach the integration's diagnostics (*Settings, Devices &
services, Synology SRM Router, the three dots, Download diagnostics*). They contain no addresses,
names or secrets. Never paste raw router output or unredacted logs.

## Development setup

```sh
uv sync
uv run pytest --cov
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The tests run against a fake client fed by anonymized answers of real devices; they need no
router and no running Home Assistant.

## Demo instance and screenshots

`scripts/demo/` runs Home Assistant against two stand-in devices that answer like a router and an
access point, with the anonymized test data and made-up names (no real device is involved):

```sh
uv run --no-project --with-requirements scripts/demo/requirements.txt \
    python scripts/demo/run.py            # http://127.0.0.1:8125, user demo / demo
```

The screenshots in `docs/assets/screenshots/` come from it: start it with `--empty`, then run
`scripts/demo/screenshots.py` in a second terminal (same `uv run` prefix). It sets up both devices
through the dialogs and photographs each step, the device pages and the example dashboard. Run it
again whenever the dialogs or pages change; it needs an installed Edge or Chrome
(`--browser chrome`), or `playwright install chromium` and `--browser chromium`.

## Rules for changes

- **Read only.** The integration never changes router settings.
- **Texts in two languages.** Every user-facing text goes into `strings.json`,
  `translations/en.json` and `translations/de.json`.
- **No personal data** in code, docs or test data.
- `tests/test_privacy.py` fails on MAC and IP addresses that may be real, in the files and in
  every line your unpushed commits add. Run the tests before you push: removing an address in a
  later commit leaves it in the history, so fix the commit that added it instead.
- Update the docs and [CHANGELOG.md](CHANGELOG.md) in the same pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

## Releases

Maintainers tag `vX.Y.Z` on `main`; HACS offers each GitHub release.
