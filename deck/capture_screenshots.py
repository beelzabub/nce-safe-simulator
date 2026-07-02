"""
Capture screenshots of the NCE Safe Simulator web UI and Quarto reports for the
sprint-review deck (deck/build_deck.py). Read-only navigation only: dialogs are opened
to photograph the form, never submitted (Launch/Save/Confirm are never clicked), with
one deliberate exception documented below.

Config: deck/shots.yaml (app_url, quarto_base_url, ui_shots, live_run_shots, quarto_shots).

Usage:
  python3 deck/capture_screenshots.py [--config deck/shots.yaml] [--out-dir deck/screenshots]
                                       [--only NAME]

--only filters by the shot's `out` name (substring match) - useful when iterating on one
shot without re-running the full ~15-minute capture pass.
"""
import argparse
import os
import sys

import yaml
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))


def _navigate(page, base_url, shot):
    page.goto(base_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1200)
    for cat in shot.get("expand", []):
        page.click(f"button.group-header:has-text('{cat}')", timeout=8000)
        page.wait_for_timeout(250)
    if shot.get("select"):
        page.click(f"li.job-item:has-text('{shot['select']}')", timeout=8000)
        page.wait_for_timeout(600)
    if shot.get("click"):
        page.click(shot["click"], timeout=8000)
        page.wait_for_timeout(600)


def capture_ui_shot(browser, base_url, shot, out_dir, viewport):
    out = shot["out"]

    page = browser.new_page(viewport=viewport)
    _navigate(page, base_url, shot)
    page.screenshot(path=os.path.join(out_dir, f"{out}_dark.png"), full_page=True)
    page.close()

    page = browser.new_page(viewport=viewport)
    page.goto(base_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    theme_btn = page.query_selector("button:has-text('Light'), button:has-text('Dark')")
    if theme_btn:
        theme_btn.click()
        page.wait_for_timeout(500)
    for cat in shot.get("expand", []):
        page.click(f"button.group-header:has-text('{cat}')", timeout=8000)
        page.wait_for_timeout(250)
    if shot.get("select"):
        page.click(f"li.job-item:has-text('{shot['select']}')", timeout=8000)
        page.wait_for_timeout(600)
    if shot.get("click"):
        page.click(shot["click"], timeout=8000)
        page.wait_for_timeout(600)
    page.screenshot(path=os.path.join(out_dir, f"{out}_light.png"), full_page=True)
    page.close()
    print(f"  ok: {out} (dark + light)")


def capture_live_run_shot(browser, base_url, shot, out_dir, viewport):
    """For parameterless, explicitly read-only tools only - selecting them launches
    immediately (there's no parameter dialog to screenshot). Captures the live run once
    (dark theme only) rather than twice, since this performs a real - if read-only -
    job execution against the target app each time it runs."""
    out = shot["out"]
    page = browser.new_page(viewport=viewport)
    page.goto(base_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    for cat in shot.get("expand", []):
        page.click(f"button.group-header:has-text('{cat}')", timeout=8000)
        page.wait_for_timeout(250)
    page.click(f"li.job-item:has-text('{shot['select']}')", timeout=8000)
    page.wait_for_timeout(600)
    page.screenshot(path=os.path.join(out_dir, f"{out}-01-before-launch.png"), full_page=True)

    launch_btn = page.query_selector("button:has-text('Launch')")
    if launch_btn:
        launch_btn.click()
    page.wait_for_timeout(1500)
    page.screenshot(path=os.path.join(out_dir, f"{out}-02-running.png"), full_page=True)

    for _ in range(25):
        body = page.inner_text("body")
        if any(m in body for m in ("Completed", "Success", "Failed", "Exit code")):
            break
        page.wait_for_timeout(1000)
    page.wait_for_timeout(1000)
    page.screenshot(path=os.path.join(out_dir, f"{out}-03-completed.png"), full_page=True)
    page.close()
    print(f"  ok: {out} (live run: before/running/completed)")


def capture_quarto_shot(browser, quarto_base_url, shot, out_dir, viewport):
    out = shot["out"]
    url = quarto_base_url.rstrip("/") + "/" + shot["path"] if shot["path"] else quarto_base_url
    page = browser.new_page(viewport=viewport)
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1000)
    page.screenshot(path=os.path.join(out_dir, "reports_quarto", f"{out}.png"), full_page=True)
    page.close()
    print(f"  ok: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "shots.yaml"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots"))
    ap.add_argument("--only", default=None, help="substring filter on shot `out` name")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "reports_quarto"), exist_ok=True)
    viewport = {"width": args.width, "height": args.height}

    def wanted(name):
        return args.only is None or args.only in name

    with sync_playwright() as p:
        browser = p.chromium.launch()

        print("UI dialog shots:")
        for shot in config.get("ui_shots", []):
            if wanted(shot["out"]):
                capture_ui_shot(browser, config["app_url"], shot, args.out_dir, viewport)

        print("Live-run shots (real read-only job execution):")
        for shot in config.get("live_run_shots", []):
            if wanted(shot["out"]):
                capture_live_run_shot(browser, config["app_url"], shot, args.out_dir, viewport)

        print("Quarto report shots:")
        for shot in config.get("quarto_shots", []):
            if wanted(shot["out"]):
                capture_quarto_shot(browser, config["quarto_base_url"], shot, args.out_dir, viewport)

        browser.close()

    print(f"\nDone. Screenshots in {args.out_dir}")


if __name__ == "__main__":
    sys.exit(main())
