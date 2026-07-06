"""
Capture screenshots of the NCE Safe Simulator web UI and Quarto reports for the
sprint-review deck (deck/build_deck.py). Read-only navigation only: dialogs are opened
to photograph the form, never submitted (Launch/Save/Confirm are never clicked), with
one deliberate exception documented below.

Config: deck/shots.yaml (app_url, quarto_base_url, ui_shots, live_run_shots, quarto_shots,
login_shots).

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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

HERE = os.path.dirname(os.path.abspath(__file__))

# The deployed app sits behind the login front door (epic #135): a DoD Notice &
# Consent banner plus a session gate (frontend useAuthGate.js). The live auth
# method is "none", so no credentials are needed — seeding the same per-session
# flags the router guard checks lets the capture reach the authenticated views
# (job picker, parameter dialogs), exactly as the e2e suite's seedAuthedSession
# does. Read-only: sets nothing on the server. Without this, /app/ redirects to
# /app/login and every job-list click times out.
_SEED_AUTH_JS = """
try {
  sessionStorage.setItem('nce.auth.accepted', '1');
  sessionStorage.setItem('nce.auth.dodBannerAccepted', '1');
  sessionStorage.setItem('nce.auth.wasAuthenticated', '1');
} catch (e) {}
"""


def _new_app_page(browser, viewport):
    """A page pre-seeded to clear the login gate, for authenticated app views."""
    page = browser.new_page(viewport=viewport)
    page.add_init_script(_SEED_AUTH_JS)
    return page


def _click_steps(page, shot):
    """Run a shot's `click` — a raw Playwright selector, or a list of them
    clicked in order (e.g. open the Analysis tab, then pick an analysis)."""
    clicks = shot.get("click")
    if not clicks:
        return
    for sel in [clicks] if isinstance(clicks, str) else clicks:
        page.click(sel, timeout=8000)
        page.wait_for_timeout(600)


def _navigate(page, base_url, shot):
    page.goto(base_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1200)
    for cat in shot.get("expand", []):
        page.click(f"button.group-header:has-text('{cat}')", timeout=8000)
        page.wait_for_timeout(250)
    if shot.get("select"):
        page.click(f"li.job-item:has-text('{shot['select']}')", timeout=8000)
        page.wait_for_timeout(600)
    _click_steps(page, shot)


def capture_ui_shot(browser, base_url, shot, out_dir, viewport):
    out = shot["out"]

    page = _new_app_page(browser, viewport)
    _navigate(page, base_url, shot)
    page.screenshot(path=os.path.join(out_dir, f"{out}_dark.png"), full_page=True)
    page.close()

    page = _new_app_page(browser, viewport)
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
    _click_steps(page, shot)
    page.screenshot(path=os.path.join(out_dir, f"{out}_light.png"), full_page=True)
    page.close()
    print(f"  ok: {out} (dark + light)")


def capture_login_shot(browser, base_url, shot, out_dir, viewport):
    """Capture the /login front door with the background slideshow and its nav
    chevrons (issue #187) visible.

    Deliberately the inverse of the app shots: it does NOT seed the auth gate —
    it lands on the real unauthenticated /login slideshow — but it DOES pre-ack
    the DoD banner (sessionStorage flag only), which otherwise sits over the
    slideshow and hides the chevrons, exactly as the login-slideshow e2e does.
    Seeding the auth flags here would send the router guard away from /login.
    Read-only: sets nothing on the server."""
    login_url = base_url.rstrip("/") + "/login"
    page = browser.new_page(viewport=viewport)
    page.add_init_script(
        "try { sessionStorage.setItem('nce.auth.dodBannerAccepted', '1'); } catch (e) {}"
    )
    page.goto(login_url, wait_until="networkidle", timeout=30000)
    # The chevrons appear (v-show) only once a second background has preloaded
    # into the rotation pool; wait for that so the shot proves the feature.
    try:
        page.wait_for_selector(".slide-nav--next", state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        print(f"  warn: {shot['out']} — nav chevrons never appeared "
              "(single background, or #187 not deployed?)")
    page.wait_for_timeout(1500)   # let the active background fully paint in
    out = shot["out"]
    page.screenshot(path=os.path.join(out_dir, f"{out}.png"), full_page=True)
    page.close()
    print(f"  ok: {out}")


def capture_live_run_shot(browser, base_url, shot, out_dir, viewport):
    """For parameterless, explicitly read-only tools only - selecting them launches
    immediately (there's no parameter dialog to screenshot). Captures the live run once
    (dark theme only) rather than twice, since this performs a real - if read-only -
    job execution against the target app each time it runs."""
    out = shot["out"]
    page = _new_app_page(browser, viewport)
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


# Report pages are long, scrollable documents. A single full_page screenshot
# crammed onto one slide is unreadable, so tall pages are ALSO captured as a
# handful of readable, viewport-height crops taken down the page (build_deck.py
# lays them out side by side). Capture in a portrait frame at 2x device scale so
# the text stays crisp and each crop shows a tall slice of content.
QUARTO_CAP_W, QUARTO_CAP_H = 1200, 1600
QUARTO_SCALE = 2
QUARTO_SEG_MIN_RATIO = 1.25   # only segment pages taller than this * frame height


def _segment_offsets(scroll_h, frame_h, n):
    """n scroll offsets evenly spanning top -> bottom (first shows the top,
    last shows the tail); some overlap between adjacent crops is fine."""
    if n <= 1:
        return [0]
    span = max(0, scroll_h - frame_h)
    return [round(i * span / (n - 1)) for i in range(n)]


def _quarto_segment_count(shot, scroll_h):
    """How many crops to take: an explicit per-shot `segments` (int, or False to
    force a single full-page image) overrides; otherwise auto from page height,
    clamped to 2-4 for pages that scroll well past one frame."""
    override = shot.get("segments")
    if override is False:
        return 1
    if isinstance(override, int):
        return max(1, min(4, override))
    if scroll_h > QUARTO_CAP_H * QUARTO_SEG_MIN_RATIO:
        return max(2, min(4, round(scroll_h / QUARTO_CAP_H)))
    return 1


def capture_quarto_shot(browser, quarto_base_url, shot, out_dir, viewport):
    out = shot["out"]
    url = quarto_base_url.rstrip("/") + "/" + shot["path"] if shot["path"] else quarto_base_url
    qdir = os.path.join(out_dir, "reports_quarto")
    page = browser.new_page(viewport={"width": QUARTO_CAP_W, "height": QUARTO_CAP_H},
                            device_scale_factor=QUARTO_SCALE)
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1200)

    # Full page: the capability-slide thumbnail and the fallback for short pages.
    page.screenshot(path=os.path.join(qdir, f"{out}.png"), full_page=True)

    scroll_h = page.evaluate(
        "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
    n = _quarto_segment_count(shot, scroll_h)

    seg = 0
    if n > 1:
        for i, y in enumerate(_segment_offsets(scroll_h, QUARTO_CAP_H, n), 1):
            page.evaluate("(y) => window.scrollTo(0, y)", y)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(qdir, f"{out}__seg{i}.png"))  # viewport-clipped
            seg += 1
    page.close()
    print(f"  ok: {out}" + (f" (+{seg} readable segments)" if seg else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "shots.yaml"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots"))
    ap.add_argument("--only", default=None, help="substring filter on shot `out` name")
    ap.add_argument("--section", default="all", choices=["all", "ui", "live", "quarto", "login"],
                    help="capture only one section (e.g. --section quarto to refresh just "
                         "the report pages without re-running the UI/live shots)")
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

    def section(name):
        return args.section in ("all", name)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        if section("login"):
            print("Login front-door shots:")
            for shot in config.get("login_shots", []):
                if wanted(shot["out"]):
                    capture_login_shot(browser, config["app_url"], shot, args.out_dir, viewport)

        if section("ui"):
            print("UI dialog shots:")
            for shot in config.get("ui_shots", []):
                if wanted(shot["out"]):
                    capture_ui_shot(browser, config["app_url"], shot, args.out_dir, viewport)

        if section("live"):
            print("Live-run shots (real read-only job execution):")
            for shot in config.get("live_run_shots", []):
                if wanted(shot["out"]):
                    capture_live_run_shot(browser, config["app_url"], shot, args.out_dir, viewport)

        if section("quarto"):
            print("Quarto report shots:")
            for shot in config.get("quarto_shots", []):
                if wanted(shot["out"]):
                    capture_quarto_shot(browser, config["quarto_base_url"], shot, args.out_dir, viewport)

        browser.close()

    print(f"\nDone. Screenshots in {args.out_dir}")


if __name__ == "__main__":
    sys.exit(main())
