"""
Run the Test Coverage Program's unit tests (issues #24-#26: report / tool /
pipeline tests) and render an excerpt of the real pytest output as a
terminal-style PNG, so build_deck.py can put an actual test log on the
"Test Coverage Program" capability slide instead of an unrelated UI shot.

This is a prerequisite generator like capture_cli_menu.py — its output
(deck/screenshots/pytest-run.png) is git-ignored and rebuilt on demand. The
log is genuine: the script runs pytest live and excerpts its output (header,
the first and last few verbose test lines with an elision marker between,
and the summary line). The command shown in the prompt is the command run.

Requires: Pillow + DejaVu Sans Mono (both already needed by capture_cli_menu.py).

Usage:
  python3 deck/capture_test_log.py [--out deck/screenshots/pytest-run.png]
"""
import argparse
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw

from capture_cli_menu import BG, TITLEBAR, FG, DIM, FAINT, GREEN, GOLD, DOTS, _font

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

# The coverage-program scope: pipeline (#26), tools (#25), and report (#24)
# unit tests. Shown verbatim in the rendered prompt line.
PYTEST_ARGS = ["tests/test_pipeline.py", "tests/test_tools.py"]
PYTEST_GLOB = "tests/test_*_report.py"
DISPLAY_CMD = "python -m pytest tests/test_pipeline.py tests/test_tools.py \\\n      tests/test_*_report.py -v"

HEAD_TESTS = 7    # verbose test lines shown from the start of the run
TAIL_TESTS = 5    # ... and from the end, before the summary line
RED = (0xE8, 0x5D, 0x5D)


def run_pytest():
    import glob as _glob
    files = PYTEST_ARGS + sorted(_glob.glob(os.path.join(REPO_ROOT, PYTEST_GLOB)))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *files, "-v", "--no-header"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=600,
    )
    return proc.stdout.splitlines()


def excerpt(lines):
    """(segments, ok) — segments are (text, color, bold) row lists for render().
    Header/collected lines, HEAD_TESTS + TAIL_TESTS real test rows around an
    elision marker, then the final summary bar."""
    test_re = re.compile(r"^(tests/\S+::\S+)\s+(PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)\s+(\[\s*\d+%\])$")
    tests, header, summary = [], [], None
    for ln in lines:
        m = test_re.match(ln)
        if m:
            tests.append(m.groups())
        elif ln.startswith("collecting") or ln.startswith("collected"):
            header.append(ln)
        elif re.match(r"^=+ .*(passed|failed|error).* =+$", ln):
            summary = ln
    ok = summary is not None and "failed" not in summary and "error" not in summary

    rows = [[("$ ", GREEN, True), (DISPLAY_CMD.split("\n")[0], FG, False)]]
    for cont in DISPLAY_CMD.split("\n")[1:]:
        rows.append([(cont, FG, False)])
    rows.append([("", FG, False)])
    for h in header:
        rows.append([(h, DIM, False)])
    rows.append([("", FG, False)])

    def test_row(t):
        name, verdict, pct = t
        col = GREEN if verdict == "PASSED" else (GOLD if verdict == "SKIPPED" else RED)
        return [(name + " ", FG, False), (verdict, col, True), ("  " + pct, FAINT, False)]

    for t in tests[:HEAD_TESTS]:
        rows.append(test_row(t))
    if len(tests) > HEAD_TESTS + TAIL_TESTS:
        rows.append([(f"   … {len(tests) - HEAD_TESTS - TAIL_TESTS} more tests …", FAINT, False)])
        for t in tests[-TAIL_TESTS:]:
            rows.append(test_row(t))
    rows.append([("", FG, False)])
    if summary:
        rows.append([(summary, GREEN if ok else RED, True)])
    return rows, ok


def render(rows, out_path):
    FS = 18
    reg = _font(False, FS)
    ch_w = reg.getbbox("M")[2]
    line_h = 27
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
    label = "pytest — unit tests"
    lf = _font(False, 15)
    lw = d.textbbox((0, 0), label, font=lf)[2]
    d.text(((W - lw) // 2, 9), label, font=lf, fill=DIM)

    y = top
    for row in rows:
        x = pad_x
        for text, color, bold in row:
            f = _font(bold, FS)
            d.text((x, y), text, font=f, fill=color)
            x += int(d.textlength(text, font=f))
        y += line_h

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "screenshots", "pytest-run.png"))
    args = ap.parse_args()
    rows, ok = excerpt(run_pytest())
    if not ok:
        print("WARNING: this pytest run did not pass cleanly — the rendered log "
              "will show the failure. Fix the tests (or scope) before shipping the deck.")
    render(rows, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
