"""
Render the CLI interactive main menu (NceGitLab.py's `_run_main_menu`) into the
deck screenshots dir as a terminal-style PNG, so build_deck.py can drop it onto
the "CLI vs. UI" slide beside the UI dialog.

This is a prerequisite generator like capture_screenshots.py / capture_diagrams.py
— its output (deck/screenshots/cli-interactive-menu.png) is git-ignored and rebuilt
on demand. The real menu is interactive and prints live GitLab/server state, so a
faithful static render is used instead of driving the live TUI: the MENU rows below
mirror NceGitLab.py:_run_main_menu verbatim (keep them in sync if that menu changes),
and the status block uses representative sample values.

Requires: Pillow (in requirements-deck.txt) and DejaVu Sans Mono (system font).

Usage:
  python3 deck/capture_cli_menu.py [--out deck/screenshots/cli-interactive-menu.png]
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Terminal palette (dark). Named to read like an ANSI theme.
BG        = (0x1B, 0x1F, 0x26)
TITLEBAR  = (0x2A, 0x2F, 0x38)
FG        = (0xE6, 0xE6, 0xE6)   # default text
DIM       = (0x8A, 0x91, 0x99)   # separators / labels
FAINT     = (0x6B, 0x70, 0x78)   # [q] quit
BLUE      = (0x4A, 0xA3, 0xE0)   # heading
GREEN     = (0x4E, 0xC9, 0x72)   # $ prompt, server RUNNING
GOLD      = (0xF0, 0xB4, 0x29)   # [N] item numbers, input prompt
DOTS      = [(0xFF, 0x5F, 0x56), (0xFF, 0xBD, 0x2E), (0x27, 0xC9, 0x3F)]

# Menu rows — mirror NceGitLab.py:_run_main_menu. (number, name, description).
MENU = [
    ("1", "Reports",   "Generate wiki reports"),
    ("2", "Utilities", "Data management tools"),
    ("3", "Scaffold",  "Create SAFe group/project structure"),
    ("4", "Create",    "Populate group with lorem SAFe data"),
    ("5", "Clean",     "Delete all group data"),
    ("6", "Site",      "Build, clean, and serve the report site"),
]
# Representative status block (the real menu fills these from live gl/server state).
STATUS = [
    ("Group      ", "PlatformEngineering"),
    ("Last report", "2026-07-01 14:22"),
    ("Last tool  ", "import-epics  (2026-07-01 14:05)"),
]
SERVER = ("Server     ", "RUNNING  (port 4645)")


def _font(bold, size):
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def render(out_path):
    FS = 20                      # monospace cell: font size
    reg, bold = _font(False, FS), _font(True, FS)
    ch_w = reg.getbbox("M")[2]   # monospace advance width
    line_h = 30
    pad_x, top = 28, 58          # left pad, first body line y
    W = pad_x * 2 + ch_w * 58     # widest line is the "Site" menu row (~56 cols)
    H = top + line_h * 20

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Title bar with traffic-light dots + centered label.
    d.rectangle([0, 0, W, 34], fill=TITLEBAR)
    for i, c in enumerate(DOTS):
        cx = 22 + i * 22
        d.ellipse([cx - 7, 10, cx + 7, 24], fill=c)
    label = "NceGitLab.py — CLI"
    lf = _font(False, 15)
    lw = d.textbbox((0, 0), label, font=lf)[2]
    d.text(((W - lw) // 2, 9), label, font=lf, fill=DIM)

    y = top

    def line(segments, dy=line_h):
        nonlocal y
        x = pad_x
        for text, color, b in segments:
            f = bold if b else reg
            d.text((x, y), text, font=f, fill=color)
            x += int(d.textlength(text, font=f))
        y += dy

    line([("$ ", GREEN, True), ("python NceGitLab.py", FG, False)])
    line([("", FG, False)])
    line([("NCE GitLab SAFe Tooling", BLUE, True)])
    line([("=" * 38, DIM, False)])
    for label_txt, val in STATUS:
        line([(f"  {label_txt} : ", DIM, False), (val, FG, False)])
    line([(f"  {SERVER[0]} : ", DIM, False), (SERVER[1], GREEN, False)])
    line([("", FG, False)])
    for num, name, desc in MENU:
        line([(f"  [{num}] ", GOLD, True), (f"{name:<11}", FG, True), (desc, DIM, False)])
    line([("  [q] ", FAINT, False), ("quit", FAINT, False)])
    line([("", FG, False)])
    line([("Select [1-6] or q: ", GOLD, True), ("█", FG, False)])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "screenshots", "cli-interactive-menu.png"))
    args = ap.parse_args()
    render(args.out)


if __name__ == "__main__":
    main()
