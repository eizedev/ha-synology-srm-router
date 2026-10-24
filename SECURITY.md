# Security Policy

## Scope

This integration only reads from Synology SRM routers and access points, through the library
[aiosynologysrm](https://github.com/eizedev/aiosynologysrm). In scope: anything in this repository
that could leak credentials, session data or the certificate fingerprint, change router settings,
or let a malicious router answer harm Home Assistant. Problems in the library itself are best
reported there.

Vulnerabilities in SRM itself belong to [Synology](https://www.synology.com/security).

## Reporting a vulnerability

Please report privately via GitHub's
[Report a vulnerability](https://github.com/eizedev/ha-synology-srm-router/security/advisories/new)
(`Security` tab, `Advisories`, `Report a vulnerability`), not in a public issue. This opens a
private discussion until a fix is released. If you cannot use GitHub, email `oss@eize.dev`
instead.

Please include the integration and Home Assistant versions, your router model and SRM version, and how to reproduce it.
Do not include passwords, session ids or unredacted router output.

## Supported versions

Only the [latest release](https://github.com/eizedev/ha-synology-srm-router/releases/latest) receives
fixes.

## What to expect

This is a community-maintained project without a service level. Reports are read and taken
seriously; confirmed vulnerabilities are fixed and released as soon as practical.
