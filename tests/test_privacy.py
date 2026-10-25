"""No real network identifiers in the repository: only placeholders and documentation addresses.

Test data, docs and the demo use locally administered MAC addresses (02:...), the IPv4
documentation ranges (RFC 5737) and 2001:db8::/32 (RFC 3849). Anything else may be copied from
a real network, so it fails here before it is published.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).parents[1]
SKIP = {"uv.lock", "tests/test_privacy.py"}  # this file holds the patterns themselves
# Addresses that are defaults or examples on every network, not anyone's own.
ALLOWED_IPV4 = {"127.0.0.1", "192.168.1.1", "255.255.255.0"}
DOC_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
]
GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")
COLON_RUN = re.compile(r"(?<![0-9a-f:])(?:[0-9a-f]{2}:){5,}[0-9a-f]{2}(?![0-9a-f:])", re.I)
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IPV6 = re.compile(r"(?<![0-9a-f:])[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,7}(?![0-9a-f:])", re.I)


def _files() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files"],  # noqa: S607 - git from PATH, as everywhere in development
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / n for n in names if n not in SKIP and (ROOT / n).is_file()]


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None  # an image or another binary file


def _mac_problem(run: str) -> str | None:
    octets = run.lower().split(":")
    if len(octets) == 6:
        mac = octets
    elif octets[:4] in (["00", "01", "00", "01"], ["00", "03", "00", "01"]):
        mac = octets[-6:]  # a DHCPv6 DUID of type LLT or LL ends with a MAC address
    else:
        return None
    if all(o == "00" for o in mac[:5]) or int(mac[0], 16) & 0x02:
        return None  # a numbered placeholder (00:00:00:00:00:NN) or locally administered
    return ":".join(mac)


def _ip_problem(text: str) -> str | None:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if str(address) in ALLOWED_IPV4 or any(address in n for n in DOC_NETWORKS):
        return None
    if address.version == 6 and address not in GLOBAL_UNICAST:
        return None  # IPv6: only global unicast addresses can be someone's own
    if address.is_loopback or address.is_link_local or address.is_unspecified:
        return None
    if address.version == 4 and int(text.split(".", maxsplit=1)[0]) == 0:
        return None
    return str(address)


def test_no_real_network_identifiers() -> None:
    found = []
    for path in _files():
        text = _text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for run in COLON_RUN.findall(line):
                if problem := _mac_problem(run):
                    found.append(f"{path.relative_to(ROOT)}:{number}: MAC {problem}")
            for candidate in [*IPV4.findall(line), *IPV6.findall(line)]:
                if problem := _ip_problem(candidate):
                    found.append(f"{path.relative_to(ROOT)}:{number}: address {problem}")
    assert not found, "\n".join(found)
