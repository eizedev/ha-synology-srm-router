r"""Start a Home Assistant demo instance with the integration and two stand-in devices.

The devices are scripts/demo/fake_srm.py (anonymized test data, made-up names); nothing touches a
real network device. Run from the repository root:

    uv run --no-project --with-requirements scripts/demo/requirements.txt \\
        python scripts/demo/run.py [--port 8125] [--keep] [--empty]

The first start takes a few minutes: Home Assistant installs what its built-in components need.
Then open http://127.0.0.1:8125 and log in as demo / demo. The configuration lives in
scripts/demo/.config and is created from scratch unless --keep is given; --empty leaves the
router and access point to be added by hand (or by screenshots.py). Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from http import HTTPStatus
import json
from pathlib import Path
import shutil
import signal
import sys
from typing import Any

import aiohttp

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONFIG = HERE / ".config"
USER = {"name": "Demo", "username": "demo", "password": "demo", "language": "en"}
ROUTER, AP = 18001, 18002
CONFIGURATION = """\
homeassistant:
  name: Home
  unit_system: metric
  time_zone: Europe/Berlin
  currency: EUR
  country: DE
  # The examples of the "Ideas and automations" page, so every demo start checks them.
  packages: !include_dir_named ideas
frontend:
config:
history:
logbook:
http:
  server_host: 127.0.0.1
  server_port: {port}
logger:
  default: warning
"""


async def wait_for(url: str, seconds: float = 180) -> None:
    """Wait until Home Assistant's web server answers (a first start installs packages)."""
    async with aiohttp.ClientSession() as session:
        for _ in range(int(seconds * 2)):
            with contextlib.suppress(aiohttp.ClientError):
                async with session.get(url) as response:
                    if response.status < HTTPStatus.INTERNAL_SERVER_ERROR:
                        return
            await asyncio.sleep(0.5)
    raise SystemExit(f"{url} did not answer")


async def onboard(base: str) -> str:
    """Create the user and finish onboarding; return an access token."""
    client_id = f"{base}/"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base}/api/onboarding/users", json={**USER, "client_id": client_id}
        ) as response:
            code = (await response.json())["auth_code"]
        async with session.post(
            f"{base}/auth/token",
            data={"grant_type": "authorization_code", "code": code, "client_id": client_id},
        ) as response:
            token = (await response.json())["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for step, body in (
            ("core_config", {}),
            ("analytics", {}),
            ("integration", {"client_id": client_id, "redirect_uri": f"{base}/?auth_callback=1"}),
        ):
            async with session.post(f"{base}/api/onboarding/{step}", json=body, headers=headers):
                pass
    return token


async def add_device(session: aiohttp.ClientSession, base: str, port: int, *, track: bool) -> None:
    """Run the config flow like a user: address, certificate, account, trackers."""
    flows = f"{base}/api/config/config_entries/flow"
    async with session.post(flows, json={"handler": "synology_srm_router"}) as response:
        flow: dict[str, Any] = await response.json()
    answers: list[dict[str, Any]] = [
        {"host": "127.0.0.1", "port": port, "use_https": True, "verify_certificate": True},
        {},  # trust the certificate
        {"username": "homeassistant", "password": "demo"},
    ]
    for answer in answers:
        async with session.post(f"{flows}/{flow['flow_id']}", json=answer) as response:
            flow = await response.json()
    if flow.get("type") == "menu":  # an access point next to the router
        answer = {"next_step_id": "router_keeps_trackers"}
    else:
        answer = {"track_all": track, "tracked": []}
    async with session.post(f"{flows}/{flow['flow_id']}", json=answer) as response:
        flow = await response.json()
    if flow.get("type") != "create_entry":
        raise SystemExit(f"setup of port {port} ended with {json.dumps(flow)[:300]}")


async def main(args: argparse.Namespace) -> None:
    """Start the stand-in devices and Home Assistant; onboard and set up on a first run."""
    if not args.keep and CONFIG.exists():
        shutil.rmtree(CONFIG)
    first_run = not CONFIG.exists()
    (CONFIG / "custom_components").mkdir(parents=True, exist_ok=True)
    link = CONFIG / "custom_components" / "synology_srm_router"
    if not link.exists():
        link.symlink_to(REPO / "custom_components" / "synology_srm_router")
    ideas = CONFIG / "ideas"
    if not ideas.exists():
        ideas.symlink_to(REPO / "docs" / "assets" / "ideas")
    (CONFIG / "configuration.yaml").write_text(CONFIGURATION.format(port=args.port))

    devices = await asyncio.create_subprocess_exec(
        sys.executable,
        str(HERE / "fake_srm.py"),
        "--tls",
        "--router-port",
        str(ROUTER),
        "--ap-port",
        str(AP),
    )
    hass = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "homeassistant", "--config", str(CONFIG)
    )
    base = f"http://127.0.0.1:{args.port}"
    try:
        await wait_for(f"{base}/manifest.json")
        if first_run:
            token = await onboard(base)
        if first_run and not args.empty:
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession(headers=headers) as session:
                await add_device(session, base, ROUTER, track=True)
                await add_device(session, base, AP, track=False)
        print(f"\nDemo running: {base}  (user demo, password demo). Ctrl+C stops it.\n", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
    finally:
        for process in (hass, devices):
            if process.returncode is None:
                process.terminate()
                await process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--keep", action="store_true", help="keep the existing configuration")
    parser.add_argument("--empty", action="store_true", help="do not add the devices")
    asyncio.run(main(parser.parse_args()))
