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

## Rules for changes

- **Read only.** The integration never changes router settings.
- **Texts in two languages.** Every user-facing text goes into `strings.json`,
  `translations/en.json` and `translations/de.json`.
- **No personal data** in code, docs or test data.
- Update the docs and [CHANGELOG.md](CHANGELOG.md) in the same pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

## Releases

Maintainers tag `vX.Y.Z` on `main`; HACS offers each GitHub release.
