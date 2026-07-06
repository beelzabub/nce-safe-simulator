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
The font is resolved across distros/macOS (known dirs, a recursive scan, then
fontconfig's `fc-match`); if it is genuinely absent the run fails with an
install hint rather than a hardcoded-path error.

Usage:
  python3 deck/capture_cli_menu.py [--out deck/screenshots/cli-interactive-menu.png]
"""
import argparse
import glob
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Directories that ship DejaVu Sans Mono across the platforms we build on.
# Debian/Ubuntu, Fedora/RHEL, Arch, and macOS (Homebrew + system) all differ.
_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",      # Debian/Ubuntu
    "/usr/share/fonts/dejavu",               # Fedora/RHEL
    "/usr/share/fonts/dejavu-sans-mono-fonts",
    "/usr/share/fonts/TTF",                  # Arch
    "/opt/homebrew/share/fonts",             # macOS (Apple Silicon Homebrew)
    "/usr/local/share/fonts",                # macOS (Intel Homebrew) / misc Linux
    os.path.expanduser("~/.local/share/fonts"),
    os.path.expanduser("~/Library/Fonts"),   # macOS user fonts
    "/Library/Fonts",                        # macOS system fonts
]
_FONT_CACHE = {}


def _find_font_file(name):
    """Resolve a DejaVu font filename to an absolute path across distros/macOS.

    Tries the known font directories first, then a recursive scan of the
    common font roots, then `fc-match` (fontconfig) if available. Returns None
    if the font cannot be located, so the caller can fall back to PIL's own
    name-based lookup or a clear error.
    """
    if name in _FONT_CACHE:
        return _FONT_CACHE[name]
    # 1) Known per-distro/OS directories.
    for d in _FONT_DIRS:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate):
            _FONT_CACHE[name] = candidate
            return candidate
    # 2) Recursive scan of the common font roots (catches unusual layouts).
    for root in ("/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.local/share/fonts")):
        if os.path.isdir(root):
            hits = glob.glob(os.path.join(root, "**", name), recursive=True)
            if hits:
                _FONT_CACHE[name] = hits[0]
                return hits[0]
    # 3) fontconfig — ask it for the family and verify the file exists.
    if shutil.which("fc-match"):
        family = "DejaVu Sans Mono:bold" if "Bold" in name else "DejaVu Sans Mono"
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                capture_output=True, text=True, timeout=5,
            )
            path = out.stdout.strip()
            if path and os.path.isfile(path):
                _FONT_CACHE[name] = path
                return path
        except (subprocess.SubprocessError, OSError):
            pass
    _FONT_CACHE[name] = None
    return None

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
    path = _find_font_file(name)
    if path:
        return ImageFont.truetype(path, size)
    # Fall back to PIL's own name-based lookup (searches some system dirs and
    # honours the bundled font), then surface a clear, actionable error.
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        raise OSError(
            f"DejaVu Sans Mono not found ({name}). Install it — Debian/Ubuntu: "
            "`apt-get install fonts-dejavu`, macOS: `brew install font-dejavu`."
        )


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
