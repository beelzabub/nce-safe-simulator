"""
Render the project package registry as a terminal-style PNG, so the offline
dependency work (#271, with #295/#296) has real deck art rather than a slide of
claims about closures nobody can see.

Prerequisite generator like capture_cli_menu.py / capture_jql_cli.py — output
(deck/screenshots/22e-vendored-packages.png) is git-ignored and rebuilt on
demand.

The listing is live: it queries the project's package registry through glab and
totals the real file sizes, so the figures on the slide are whatever is actually
vendored on the day the deck is built. Read-only — a GET against the packages
API and nothing else.

Requires: glab authenticated, plus Pillow + DejaVu Sans Mono.

Usage:
  python3 deck/capture_vendored_packages.py [--out PATH]
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from capture_cli_menu import BG, TITLEBAR, FG, DIM, FAINT, GREEN, DOTS, _font  # noqa: E402

PROJECT = "gl-demo-ultimate-lmwilliams%2Fnce-safe-simulator"
KEY = (0x8F, 0xB8, 0xF0)
GOOD = (0x6E, 0xC8, 0xB4)

#: What each vendored closure exists to feed. Keyed by package name — the
#: registry says what is stored, not why, and the why is the point of the slide.
PURPOSE = {
    "pip-wheels":          "Dockerfile runtime + diagram-builder  (pip)",
    "npm-cache":           "Dockerfile frontend-builder  (npm ci)",
    "apt-debs":            "every apt-get layer in the image",
    "weasyprint-apt-debs":  "PDF rendering system libraries",
    "quarto":              "report site generator",
}


def _api(path):
    """One paginated GET through glab, following pages until short."""
    out, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        proc = subprocess.run(
            ["glab", "api", f"{path}{sep}per_page=100&page={page}"],
            capture_output=True, text=True, timeout=180, cwd=REPO_ROOT)
        if proc.returncode != 0:
            raise RuntimeError(f"glab api failed: {proc.stderr.strip()[:200]}")
        chunk = json.loads(proc.stdout or "[]")
        out.extend(chunk)
        if len(chunk) < 100:
            return out
        page += 1


def collect():
    """[(name, version, n_files, bytes, date)] — newest version per package.

    The registry keeps every published version; a slide wants the current one,
    so versions are collapsed to the most recently created per name."""
    pkgs = _api(f"projects/{PROJECT}/packages")
    newest = {}
    for p in pkgs:
        cur = newest.get(p["name"])
        if cur is None or p["created_at"] > cur["created_at"]:
            newest[p["name"]] = p

    rows = []
    for name, p in newest.items():
        files = _api(f"projects/{PROJECT}/packages/{p['id']}/package_files")
        total = sum(f.get("size") or 0 for f in files)
        rows.append((name, p["version"], len(files), total, p["created_at"][:10]))
    return sorted(rows, key=lambda r: -r[3])


def build_rows(data):
    rows = [[("$ ", GREEN, True),
             ("glab api projects/:id/packages", FG, False),
             ("   # the enclave's only dependency source", FAINT, False)],
            [("", FG, False)],
            [(f"{'CLOSURE':<21}", DIM, True), (f"{'VERSION':<14}", DIM, True),
             (f"{'FILES':>6}", DIM, True), (f"{'SIZE':>11}", DIM, True),
             ("  FEEDS", DIM, True)],
            [("─" * 104, FAINT, False)]]

    total_bytes = 0
    for name, version, nfiles, size, _date in data:
        total_bytes += size
        rows.append([(f"{name:<21}", KEY, True),
                     (f"{version:<14}", FG, False),
                     (f"{nfiles:>6}", FG, False),
                     (f"{size/1e6:>9.1f} MB", GOOD, False),
                     ("  " + PURPOSE.get(name, ""), FAINT, False)])

    rows.append([("─" * 104, FAINT, False)])
    rows.append([(f"{'':<21}{'':<14}{'':>6}", FG, False),
                 (f"{total_bytes/1e9:>9.2f} GB", GOOD, True),
                 ("  vendored in-project", FAINT, False)])
    rows.append([("", FG, False)])
    rows.append([("Image builds resolve pip, npm and apt from here — no PyPI, no npmjs, no", FAINT, False)])
    rows.append([("Ubuntu mirror. #295 syncs an offline import by sha256; #296 guards the drift.", FAINT, False)])
    return rows


def render(rows, out_path, font_size=17, line_h=25):
    title = "package registry — the vendored dependency closures  (#271)"
    reg = _font(False, font_size)
    ch_w = reg.getbbox("M")[2]
    pad_x, top = 26, 56
    cols = max(sum(len(t) for t, _, _ in row) for row in rows) + 2
    W = pad_x * 2 + ch_w * cols
    H = top + line_h * len(rows) + 20

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 34], fill=TITLEBAR)
    for i, c in enumerate(DOTS):
        cx = 22 + i * 22
        d.ellipse([cx - 7, 10, cx + 7, 24], fill=c)
    lf = _font(False, 15)
    lw = d.textbbox((0, 0), title, font=lf)[2]
    d.text(((W - lw) // 2, 9), title, font=lf, fill=DIM)

    y = top
    for row in rows:
        x = pad_x
        for text, color, bold in row:
            f = _font(bold, font_size)
            d.text((x, y), text, font=f, fill=color)
            x += int(d.textlength(text, font=f))
        y += line_h

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "screenshots", "22e-vendored-packages.png"))
    args = ap.parse_args()
    data = collect()
    if not data:
        print("no packages found — nothing rendered", file=sys.stderr)
        return 1
    render(build_rows(data), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
