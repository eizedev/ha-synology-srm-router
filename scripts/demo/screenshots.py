r"""Take the documentation's screenshots from a demo instance started with run.py --empty.

    uv run --no-project --with-requirements scripts/demo/requirements.txt \\
        python scripts/demo/screenshots.py [--browser msedge|chromium] [--scheme dark|light]

It sets up the router and the access point through the dialogs, as a user would, and saves the
pictures to docs/assets/screenshots/. With --browser chromium, run `playwright install chromium`
once; msedge and chrome use an installed browser.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright
import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "docs" / "assets" / "screenshots"
BASE = "http://127.0.0.1:8125"
ROUTER, AP = 18001, 18002

DASHBOARD = HERE.parents[1] / "docs" / "assets" / "example-dashboard.yaml"
# A made-up day of traffic (bytes per second at its peak) for the graphs, imported as statistics.
HISTORY = {
    "sensor.rt2600ac_download_rate": 4_000_000,
    "sensor.rt2600ac_upload_rate": 900_000,
    "sensor.mr2200ac_download_rate": 600_000,
    "sensor.mr2200ac_upload_rate": 150_000,
}


async def shoot(page: Page, name: str, target: Locator | None = None) -> None:
    """Save the page, or one element of it, as docs/assets/screenshots/<name>.png."""
    await page.wait_for_timeout(1200)  # let animations and values settle
    path = OUT / f"{name}.png"
    if target is not None:
        await target.screenshot(path=path)
    else:
        await page.screenshot(path=path)
    print("saved", path.relative_to(HERE.parents[1]), flush=True)


async def login(page: Page) -> None:
    """Log in through the login page, as a user would."""
    await page.goto(f"{BASE}/")
    await page.get_by_label("Username").fill("demo")
    await page.get_by_role("textbox", name="Password").fill("demo")
    await page.keyboard.press("Enter")
    await page.wait_for_url("**/home/**", timeout=60000)
    confirm = page.get_by_role("button", name="Confirm")  # the new HTTP settings, once
    if await confirm.count():
        await confirm.first.click()


async def dialog_button(page: Page, name: str) -> None:
    """Press a button of the open dialog and let the next step load."""
    await page.get_by_role("button", name=name, exact=True).last.click()
    await page.wait_for_timeout(2500)


async def add_device(page: Page, port: int, prefix: str) -> None:
    """Run the setup dialog and photograph each step (prefix "" skips the pictures)."""
    await page.goto(f"{BASE}/config/integrations/dashboard/add?domain=synology_srm_router")
    dialog = page.get_by_role("dialog")
    await page.get_by_role("button", name="OK", exact=True).click()  # "Set up ...?"
    await page.wait_for_timeout(2500)
    fields = page.locator("dialog-data-entry-flow ha-form input")  # in shadow DOM, by order
    await fields.nth(0).fill("127.0.0.1")
    await fields.nth(1).fill(str(port))
    if prefix:
        await shoot(page, f"{prefix}-connection", dialog)
    await dialog_button(page, "Next")
    if prefix:
        await shoot(page, f"{prefix}-certificate", dialog)
    await dialog_button(page, "Trust")
    await fields.nth(0).fill("homeassistant")
    await fields.nth(1).fill("demo")
    if prefix:
        await shoot(page, f"{prefix}-account", dialog)
    await dialog_button(page, "Next")


async def main(args: argparse.Namespace) -> None:
    """Open a browser and take the tour."""
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel=None if args.browser == "chromium" else args.browser
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 860},
            device_scale_factor=2,
            color_scheme=args.scheme,
            locale="en-US",
        )
        page = await context.new_page()
        try:
            await tour(page)
        except Exception:
            await page.screenshot(path=OUT / "failed.png")  # where it stopped; not committed
            raise
        finally:
            await browser.close()


async def tour(page: Page) -> None:
    """Set up both devices through the dialogs and photograph the documented pages."""
    if True:
        await login(page)

        # Router: every step of the dialog, the client list open, then "track all".
        await add_device(page, ROUTER, "setup")
        dialog = page.get_by_role("dialog")
        await shoot(page, "setup-trackers", dialog)
        await page.get_by_role("button", name="Clients to track").click()
        await shoot(page, "setup-client-list")
        await page.keyboard.press("Escape")
        await page.locator("dialog-data-entry-flow ha-form ha-switch").first.click()  # track all
        await dialog_button(page, "Finish")
        await dialog_button(page, "Skip and finish")  # name and area

        # Access point next to the router: the menu.
        await add_device(page, AP, "")
        await shoot(page, "setup-access-point", page.get_by_role("dialog"))
        await page.get_by_text("Finish: the router keeps the trackers").click()  # the menu
        await page.wait_for_timeout(2500)
        await dialog_button(page, "Skip and finish")

        await page.goto(f"{BASE}/config/integrations/integration/synology_srm_router")
        await shoot(page, "integration")

        hass = "document.querySelector('home-assistant').hass"
        ids = await page.evaluate(
            f"""async () => {{
                const id = (e) => {hass}.entities[e]?.device_id;
                return [id('sensor.rt2600ac_cpu_load'), id('sensor.mr2200ac_cpu_load')];
            }}"""
        )
        for device_id, name in zip(ids, ("device-router", "device-access-point"), strict=True):
            await page.goto(f"{BASE}/config/devices/device/{device_id}")
            await shoot(page, name)

        await page.evaluate(
            f"""async (series) => {{
                for (const [id, peak] of Object.entries(series)) {{
                    const stats = [];
                    const now = new Date(); now.setMinutes(0, 0, 0);
                    for (let h = 24; h >= 1; h--) {{
                        const start = new Date(now - h * 3600e3);
                        // quiet at night, busy in the evening
                        const hour = start.getHours();
                        const day = Math.max(0.05, Math.sin(Math.PI * Math.max(0, hour - 6) / 17));
                        const mean = peak * day * (0.8 + 0.4 * Math.random());
                        stats.push({{start: start.toISOString(), mean,
                            min: mean * 0.3, max: mean * 1.8}});
                    }}
                    await {hass}.callWS({{type: 'recorder/import_statistics', stats,
                        metadata: {{statistic_id: id, source: 'recorder', name: null,
                            has_sum: false, mean_type: 1, unit_class: 'data_rate',
                            unit_of_measurement: 'B/s'}}}});
                }}
            }}""",
            HISTORY,
        )
        await page.evaluate(
            f"""async (config) => {{
                await {hass}.callWS({{type: 'lovelace/dashboards/create', url_path: 'srm-network',
                    title: 'Network', icon: 'mdi:lan', mode: 'storage', require_admin: false,
                    show_in_sidebar: true}});
                await {hass}.callWS({{type: 'lovelace/config/save',
                    url_path: 'srm-network', config}});
            }}""",
            yaml.safe_load(DASHBOARD.read_text()),
        )
        await page.set_viewport_size({"width": 1700, "height": 1100})  # all three columns
        await page.goto(f"{BASE}/srm-network/0")
        await shoot(page, "dashboard")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--browser", default="msedge", choices=["msedge", "chrome", "chromium"])
    parser.add_argument("--scheme", default="dark", choices=["dark", "light"])
    asyncio.run(main(parser.parse_args()))
