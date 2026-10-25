"""A stand-in for a Synology router and access point, for the demo instance and its screenshots.

It answers SRM's Web API with the anonymized test data in tests/fixtures (addresses from
192.0.2.0/24, MACs 02:00:..), with made-up readable names instead of "hostname-12". Read only, like
the integration; any account and password are accepted except the ones in REFUSE.

    python scripts/demo/fake_srm.py [--tls] [--router-port 18001] [--ap-port 18002]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
from itertools import count
import json
import math
from pathlib import Path
import random
import re
import ssl
import time
from typing import Any

from aiohttp import web

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
REFUSE = {"wrong"}  # a password that fails, to show the error in a screenshot

# (api, method) -> fixture file; versions as an SRM 1.3.2 catalog lists them.
APIS: dict[tuple[str, str], tuple[str, int, int]] = {
    ("SYNO.Core.System", "info"): ("system_info", 1, 2),
    ("SYNO.Core.System.Utilization", "get"): ("utilization", 1, 1),
    ("SYNO.Core.Network.NSM.Device", "get"): ("network_devices", 1, 5),
    ("SYNO.Core.Network.Router.Topology", "get"): ("topology", 1, 4),
    ("SYNO.Core.Network.Router.ConnectionStatus", "get"): ("connection_status", 1, 1),
    ("SYNO.Core.DDNS.ExtIP", "list"): ("external_ip", 1, 1),
    ("SYNO.Core.Network.DHCPServer.ClientList", "list"): ("dhcp_clients", 1, 2),
    ("SYNO.Core.Network.DHCPServer.Reservation", "get"): ("dhcp_reservations", 1, 2),
    ("SYNO.Wifi.Device", "get"): ("wifi_devices", 1, 1),
    ("SYNO.Core.Network.DHCPServer", "get"): ("dhcp_servers", 1, 1),
    ("SYNO.Core.Security.Firewall.Rules", "get"): ("firewall_rules", 1, 2),
    ("SYNO.Core.Security.Firewall.Rules.HitCount", "get"): ("firewall_hit_counts", 1, 1),
    ("SYNO.Core.Storage.Volume", "list"): ("usb_volumes", 1, 1),
}

# Readable firewall rule names, in the order of the router's recorded rules.
RULE_NAMES = [
    "LAN to LAN",
    "LAN to LAN",
    "Ping from home country",
    "Web server",
    "Game server",
    "Router services",
    "SRM web",
    "SRM web (HTTPS)",
    "Media server",
    "NAS",
    "NAS",
    "Game console",
    "Game console",
    "Smart home",
    "Block TV telemetry",
    "Block TV telemetry",
    "Block TV telemetry",
    "Block TV telemetry",
]
STARTED = time.time()

# Readable names by SRM's device type; numbered when a type repeats.
NAMES: dict[str, list[str]] = {
    "game": ["Game console", "Handheld console"],
    "nas": ["NAS", "Backup NAS"],
    "router": ["Access point hall", "Access point attic"],
    "printer": ["Printer"],
    "tv": ["Living room TV", "Bedroom TV"],
    "mobile": ["Phone Alex", "Phone Sam", "Tablet"],
    "computer": ["Laptop", "Desktop", "Work laptop"],
    "speaker": ["Kitchen speaker", "Living room speaker", "Bathroom speaker"],
}
OTHER = [
    "Thermostat",
    "Robot vacuum",
    "Doorbell",
    "Smart plug",
    "Weather station",
    "Coffee machine",
    "Light bridge",
    "Garden camera",
    "Hall speaker",
    "Watch",
    "E-reader",
    "Media player",
    "Phone Kim",
    "Tablet kids",
    "Smart TV kitchen",
    "Laptop guest",
    "Fridge",
    "Washing machine",
    "Dishwasher",
    "Heat pump",
    "Solar inverter",
    "Wallbox",
    "Air purifier",
    "Bedside lamp",
    "Garage door",
    "Smoke detector hall",
    "Window sensor bridge",
    "Baby monitor",
    "Printer office",
    "Streaming stick",
    "Soundbar",
    "Game console guest",
    "Phone Robin",
    "Tablet Alex",
    "Laptop Sam",
    "Desk lamp",
    "Water leak sensor",
    "Door lock",
    "Irrigation",
    "Pool pump",
    "Car",
    "Bike charger",
    "Camera door",
    "Speaker bathroom",
    "Speaker bedroom",
    "Kitchen radio",
]


# The anonymized fixtures share one placeholder serial; the integration tells devices apart by it.
SERIALS = {"router": "DEMO0R0001", "ap": "DEMO0A0002"}


def readable(folders: list[Path]) -> dict[str, str]:
    """Give every client (by MAC) its own readable name; the fixtures repeat placeholders."""
    devices = [
        d for f in folders for d in json.loads((f / "network_devices.json").read_text())["devices"]
    ]
    used: dict[str, int] = {}
    names: dict[str, str] = {}
    spare = (name if lap == 0 else f"{name} {lap + 1}" for lap in count() for name in OTHER)
    for device in sorted(devices, key=lambda d: d["mac"]):
        mac = device["mac"]
        if mac in names or not re.fullmatch(r"hostname-\d+", device.get("hostname") or ""):
            continue
        kind = device.get("dev_type") or ""
        choices = NAMES.get(kind, [])
        index = used.get(kind, 0)
        used[kind] = index + 1
        names[mac] = choices[index] if index < len(choices) else next(spare)
    return names


def rename(data: Any, names: dict[str, str]) -> Any:
    """Put each client's readable name into the entries that carry its MAC."""
    if isinstance(data, dict):
        mac = data.get("mac") or data.get("mac_address") or data.get("clid")
        renamed = {k: rename(v, names) for k, v in data.items()}
        if mac in names and "hostname" in renamed:
            renamed["hostname"] = names[mac]
        return renamed
    if isinstance(data, list):
        return [rename(v, names) for v in data]
    return data


# Clients that leave and come back: away during the second half of every COMINGS_AND_GOINGS.
COMINGS_AND_GOINGS = 600  # seconds
TRAVELLERS = 2


def wave(period: float, phase: float = 0) -> float:
    """0..1, slowly up and down, so values change believably between updates."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * (time.time() / period + phase))


def jitter(value: float, share: float, low: float = 0, high: float | None = None) -> int:
    """Move the value by up to +-share of it, kept within low..high."""
    moved = value * (1 + random.uniform(-share, share))  # noqa: S311 - not for security
    return int(max(low, moved if high is None else min(high, moved)))


def liven(key: tuple[str, str], data: Any, travellers: frozenset[str]) -> Any:
    """Let the recorded answer move: load, memory, traffic, signal, and clients that are away."""
    data = copy.deepcopy(data)
    away = time.time() % COMINGS_AND_GOINGS > COMINGS_AND_GOINGS / 2
    if key == ("SYNO.Core.System.Utilization", "get"):
        busy = 0.4 + 1.2 * wave(900)
        cpu = data["cpu"]
        for field in ("user_load", "system_load", "other_load"):
            cpu[field] = jitter(cpu[field] * busy, 0.2, 0, 100)
        for field, period in (("1min_load", 300), ("5min_load", 900), ("15min_load", 1800)):
            cpu[field] = jitter(cpu[field] * (0.6 + 0.8 * wave(period)), 0.1)
        data["memory"]["real_usage"] = jitter(data["memory"]["real_usage"], 0.06, 1, 99)
        for net in data["network"]:
            for field in ("rx", "tx"):
                net[field] = jitter(net[field] * (0.2 + 3 * wave(1200, 0.3)), 0.5)
    if key == ("SYNO.Wifi.Device", "get"):
        data["device_list"] = [
            {**d, "signal": jitter(d["signal"], 0.08, 5, 100)}
            for d in data["device_list"]
            if not (away and d["mac_address"] in travellers)
        ]
    if key == ("SYNO.Core.Security.Firewall.Rules.HitCount", "get"):
        minutes = (time.time() - STARTED) / 60
        for item in data:  # counters that matched before keep matching
            if item["hit_count"]:
                item["hit_count"] += int(minutes * (1 + item["ui_id"] % 7) * 3)
    if key == ("SYNO.Core.Network.NSM.Device", "get") and away:
        for device in data["devices"]:
            if device["mac"] in travellers:
                device["is_online"] = False
    return data


def device_app(folder: Path, names: dict[str, str]) -> web.Application:
    """Build the Web API of one device from its fixture folder."""
    answers = {
        key: rename(json.loads((folder / f"{name}.json").read_text()), names)
        for key, (name, _, _) in APIS.items()
    }
    answers[("SYNO.Core.System", "info")]["serial"] = SERIALS[folder.name]
    # Readable stand-ins for anonymized values that show in screenshots: the USB volume's name,
    # and DHCP pools wide enough to hold the recorded leases.
    for volume in answers[("SYNO.Core.Storage.Volume", "list")]["volumes"]:
        volume["display_name"] = "USB drive"
    for server in answers[("SYNO.Core.Network.DHCPServer", "get")]["data"]:
        if server.get("ifname") == "lbr0" and server.get("ipv4"):
            server["ipv4"].update(begin="192.0.2.1", end="192.0.2.200")
    rules = answers[("SYNO.Core.Security.Firewall.Rules", "get")]["rules"]
    for rule, name in zip(rules, RULE_NAMES, strict=False):
        rule["name"] = name
    wifi = answers[("SYNO.Wifi.Device", "get")]["device_list"]
    travellers = frozenset(d["mac_address"] for d in wifi[:TRAVELLERS])
    catalog = {
        "SYNO.API.Auth": {"minVersion": 1, "maxVersion": 3, "path": "auth.cgi"},
        "SYNO.API.Info": {"minVersion": 1, "maxVersion": 1, "path": "query.cgi"},
        **{
            api: {"minVersion": lo, "maxVersion": hi, "path": "entry.cgi"}
            for (api, _), (_, lo, hi) in APIS.items()
        },
    }
    sids: set[str] = set()

    def ok(data: Any) -> web.Response:
        return web.json_response({"success": True, "data": data})

    def fail(code: int) -> web.Response:
        return web.json_response({"success": False, "error": {"code": code}})

    async def handle(request: web.Request) -> web.Response:
        form = {k: str(v) for k, v in (await request.post()).items()}
        cgi = request.match_info["cgi"]
        if cgi == "query.cgi":
            return ok(catalog)
        if cgi == "auth.cgi":
            if form.get("method") == "logout":
                sids.discard(form.get("_sid", ""))
                return ok({})
            if form.get("passwd") in REFUSE:
                return fail(400)
            sid = f"demo-{len(sids) + 1}-{form.get('session', '')}"
            sids.add(sid)
            return ok({"sid": sid})
        if form.get("_sid") not in sids:
            return fail(119)
        key = (form.get("api", ""), form.get("method", ""))
        return ok(liven(key, answers[key], travellers)) if key in answers else fail(103)

    app = web.Application()
    app.router.add_post("/webapi/{cgi}", handle)
    return app


def tls_context() -> ssl.SSLContext:
    """Make a self-signed certificate for 127.0.0.1 (cryptography comes with Home Assistant)."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415 - only needed with --tls
    import ipaddress  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synology.demo")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with tempfile.TemporaryDirectory() as tmp:
        cert_file, key_file = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert_file, key_file)
    return context


async def serve(args: argparse.Namespace) -> None:
    """Serve the router and the access point until stopped."""
    context = tls_context() if args.tls else None
    runners = []
    for folder, port in ((FIXTURES / "router", args.router_port), (FIXTURES / "ap", args.ap_port)):
        names = readable([FIXTURES / "router", FIXTURES / "ap"])
        runner = web.AppRunner(device_app(folder, names))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port, ssl_context=context).start()
        runners.append(runner)
        print(f"{folder.name}: {'https' if context else 'http'}://127.0.0.1:{port}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        for runner in runners:
            await runner.cleanup()


def main() -> None:
    """Parse the arguments and serve."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tls", action="store_true", help="serve HTTPS with a self-signed cert")
    parser.add_argument("--router-port", type=int, default=18001)
    parser.add_argument("--ap-port", type=int, default=18002)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
