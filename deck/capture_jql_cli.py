"""
Run the CLI query tool (issue #301) against the live group and render its real
output as a terminal-style PNG, so build_deck.py can put an actual JQL run on the
query capability's slide rather than a UI shot standing in for the CLI.

Prerequisite generator like capture_cli_menu.py / capture_test_log.py — its
output (deck/screenshots/22c-jql-cli-query.png) is git-ignored and rebuilt on
demand. The run is genuine: it executes `-ut query` against the configured group
and excerpts the resulting table. The command shown in the prompt is the command
run.

Read-only, like every other capture: `query` is classified read-only in the tool
registry and only ever issues GraphQL reads.

Requires: a usable config.json (same as any live tool run), plus Pillow +
DejaVu Sans Mono (already needed by capture_cli_menu.py).

Usage:
  python3 deck/capture_jql_cli.py [--out deck/screenshots/22c-jql-cli-query.png]
                                  [--jql "..."] [--limit N]
"""
import argparse
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw

from capture_cli_menu import BG, TITLEBAR, FG, DIM, FAINT, GREEN, DOTS, _font

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

DEFAULT_JQL = "state = opened AND weight >= 5 ORDER BY due ASC"
DEFAULT_LIMIT = 8


def run_query(jql, limit):
    """(table_lines, stderr) — `query` is a stdout_is_data tool, so the result
    table arrives on stdout alone and the run's chrome (server banner, prompt
    echoes, log path) on stderr. Only stdout is rendered; stderr is kept so a
    failed run can say why instead of drawing an empty frame."""
    proc = subprocess.run(
        [sys.executable, "NceGitLab.py", "-ut", "query", "--jql", jql, "--limit", str(limit)],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=600,
    )
    return proc.stdout.splitlines(), proc.stderr


def excerpt(lines, jql, limit):
    """(rows, ok) — rows are (text, color, bold) lists for render(). Keeps the
    result table and its footer, dropping the interactive-prompt chrome that a
    reader of the slide has no context for."""
    display_cmd = f'python NceGitLab.py -ut query --jql "{jql}" \\\n      --limit {limit}'
    rows = [[("$ ", GREEN, True), (display_cmd.split("\n")[0], FG, False)]]
    for cont in display_cmd.split("\n")[1:]:
        rows.append([(cont, FG, False)])
    rows.append([("", FG, False)])

    started = False
    body = []
    for ln in lines:
        if not started and ln.strip().startswith("iid") and "title" in ln:
            started = True
        if started:
            body.append(ln.rstrip())

    for ln in body:
        s = ln.strip()
        if not s:
            rows.append([("", FG, False)])
        elif s.startswith("---"):
            rows.append([(ln, FAINT, False)])
        elif s.startswith("iid"):
            rows.append([(ln, DIM, True)])
        elif re.match(r"^\s*\d+ item", ln):
            rows.append([(ln, GREEN, True)])
        elif s.startswith("Truncated"):
            rows.append([(ln, FAINT, False)])
        else:
            rows.append([(ln, FG, False)])
    return rows, started


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
    label = "query — JQL against the live group"
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
    ap.add_argument("--out", default=os.path.join(HERE, "screenshots", "22c-jql-cli-query.png"))
    ap.add_argument("--jql", default=DEFAULT_JQL)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args()

    table, chrome = run_query(args.jql, args.limit)
    rows, ok = excerpt(table, args.jql, args.limit)
    if not ok:
        print("WARNING: the query produced no result table — refusing to render an "
              "empty frame. Check config.json and that the group has matching items.",
              file=sys.stderr)
        if chrome.strip():
            print(chrome.strip()[-800:], file=sys.stderr)
        return 1
    render(rows, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
