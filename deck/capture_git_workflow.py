"""
Render the project's development workflow as a git-graph PNG for the deck:
issue -> UI-created branch -> commits (Refs #NNN) -> tests on every push ->
MR review -> merge to develop (Closes #NNN) -> develop CI publish/deploy.

This is a prerequisite generator like capture_cli_menu.py / capture_test_log.py —
outputs are git-ignored and rebuilt on demand:

  deck/screenshots/git-workflow.png          wide, with a numbered step-card row
                                             (the dedicated "Development Workflow" slide)
  deck/screenshots/git-workflow-compact.png  graph only
                                             (the "Development Process & Tools" slide image)

The graph is illustrative but mirrors the real conventions: branches are created
from the issue in the GitLab UI (so they link to the Work Item), named
<type>/NNN-short-description, commits reference the issue, MRs target develop
(never main), and develop's CI publishes the Quarto site to Pages.

Requires: Pillow + DejaVu fonts (same as capture_cli_menu.py).

Usage:
  python3 deck/capture_git_workflow.py [--out-dir deck/screenshots]
"""
import argparse
import os

from PIL import Image, ImageDraw

from capture_cli_menu import _find_font_file
from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Deck palette (build_deck.py template colors) + neutrals for a white slide body.
BLUE   = (0x00, 0x6B, 0xB5)   # develop lane
GREEN  = (0x2E, 0x9E, 0x4F)   # issue branch lane
YELLOW = (0xFD, 0xB9, 0x13)   # accent (step numbers)
INK    = (0x2A, 0x2E, 0x32)
GRAY   = (0x6B, 0x70, 0x78)
CARD   = (0xF5, 0xF6, 0xF7)
EDGE   = (0xD5, 0xD9, 0xDD)
WHITE  = (0xFF, 0xFF, 0xFF)

LINE_W = 10
DOT_R = 16


def _font(name, size):
    path = _find_font_file(name)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.truetype(name, size)


F_TITLE = lambda s: _font("DejaVuSans-Bold.ttf", s)
F_BODY = lambda s: _font("DejaVuSans.ttf", s)
F_MONO = lambda s: _font("DejaVuSansMono.ttf", s)


def bezier(p0, p1, p2, p3, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        ))
    return pts


def commit_dot(d, x, y, color):
    d.ellipse([x - DOT_R, y - DOT_R, x + DOT_R, y + DOT_R], fill=WHITE,
              outline=color, width=6)


def step_marker(d, x, y, n):
    r = 22
    d.ellipse([x - r, y - r, x + r, y + r], fill=YELLOW)
    f = F_TITLE(26)
    tw = d.textlength(str(n), font=f)
    d.text((x - tw / 2, y - 17), str(n), font=f, fill=INK)


def chip(d, x, y, text, color, mono=False, pad=14):
    f = F_MONO(22) if mono else F_BODY(22)
    tw = d.textlength(text, font=f)
    box = [x, y, x + tw + pad * 2, y + 44]
    d.rounded_rectangle(box, radius=12, fill=WHITE, outline=color, width=3)
    d.text((x + pad, y + 8), text, font=f, fill=INK)
    return box


# The six steps of the loop — shared by the graph markers and the card row.
STEPS = [
    ("Create the issue", "A GitLab Work Item (#144)\nscopes and tracks every\nchange"),
    ("Create the branch", "From the issue, in the UI —\nso branch and issue stay\nlinked"),
    ("Do the work", "Small commits, each one\nreferencing the issue\n(“Refs #144”)"),
    ("Run the tests", "pytest locally; CI runs the\nfull suite on every push"),
    ("MR → review → merge", "Targets develop, never\nmain; “Closes #144” closes\nthe issue"),
    ("develop CI", "pytest gate + Quarto →\nPages publish, then deploy"),
]


def draw_graph(d, W, top):
    """The git-graph band. `top` is the y of the develop lane."""
    dev_y = top
    feat_y = top + 300
    x0, x1 = 90, W - 90
    branch_x, merge_x = 470, 1950

    # develop lane with an arrowhead.
    d.line([(x0, dev_y), (x1 - 30, dev_y)], fill=BLUE, width=LINE_W)
    d.polygon([(x1 - 34, dev_y - 22), (x1 - 34, dev_y + 22), (x1 + 6, dev_y)], fill=BLUE)
    d.text((x0, dev_y - 78), "develop", font=F_TITLE(30), fill=BLUE)
    d.text((x0 + 150, dev_y - 72), "— integration branch, merge-only", font=F_BODY(22), fill=GRAY)

    # Issue chip feeding the branch point (step 1).
    step_marker(d, branch_x - 310, dev_y - 165, 1)
    chip(d, branch_x - 270, dev_y - 188, "Issue #144 · GitLab Work Item", BLUE)
    d.line([(branch_x, dev_y - 140), (branch_x, dev_y - 24)], fill=EDGE, width=4)

    # Branch out / merge back curves (step 2 / 5).
    d.line(bezier((branch_x, dev_y), (branch_x + 90, dev_y), (branch_x + 60, feat_y), (branch_x + 150, feat_y)),
           fill=GREEN, width=LINE_W, joint="curve")
    d.line([(branch_x + 150, feat_y), (merge_x - 150, feat_y)], fill=GREEN, width=LINE_W)
    d.line(bezier((merge_x - 150, feat_y), (merge_x - 60, feat_y), (merge_x - 90, dev_y), (merge_x, dev_y)),
           fill=GREEN, width=LINE_W, joint="curve")

    d.text((branch_x + 170, feat_y + 34), "enhance/144-powerpoint-polish", font=F_MONO(24), fill=GREEN)
    step_marker(d, branch_x + 40, (dev_y + feat_y) // 2, 2)

    # Commits on develop and on the branch.
    for x in (200, branch_x):
        commit_dot(d, x, dev_y, BLUE)
    feat_commits = (branch_x + 350, branch_x + 650, branch_x + 950)
    for x in feat_commits:
        commit_dot(d, x, feat_y, GREEN)
    d.text((feat_commits[0] - 90, feat_y - 70), "commits · “Refs #144”", font=F_BODY(22), fill=GRAY)
    step_marker(d, feat_commits[1], feat_y - 90, 3)

    # Tests on every push (step 4).
    ci_x = feat_commits[2] - 60
    step_marker(d, ci_x - 40, feat_y + 90, 4)
    chip(d, ci_x, feat_y + 68, "✓ CI · pytest on every push", GREEN)

    # MR / merge (step 5) and the develop CI after it (step 6).
    commit_dot(d, merge_x, dev_y, BLUE)
    step_marker(d, merge_x - 250, dev_y - 165, 5)
    chip(d, merge_x - 210, dev_y - 188, "MR → review · “Closes #144”", BLUE)
    d.line([(merge_x, dev_y - 140), (merge_x, dev_y - 24)], fill=EDGE, width=4)

    step_marker(d, merge_x + 88, dev_y + 90, 6)
    chip(d, merge_x + 128, dev_y + 68, "✓ CI · pytest + Quarto → Pages", BLUE)


def render(out_path, with_cards):
    W = 2460
    graph_top = 250
    graph_h = 560
    cards_h = 330 if with_cards else 0
    H = graph_top + graph_h + cards_h

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    draw_graph(d, W, graph_top)

    if with_cards:
        n = len(STEPS)
        gap = 24
        card_w = (W - 180 - gap * (n - 1)) // n
        y = graph_top + graph_h
        for i, (title, caption) in enumerate(STEPS):
            x = 90 + i * (card_w + gap)
            d.rounded_rectangle([x, y, x + card_w, y + 270], radius=16, fill=CARD,
                                outline=EDGE, width=2)
            step_marker(d, x + 38, y + 44, i + 1)
            d.text((x + 72, y + 32), title, font=F_TITLE(22), fill=INK)
            d.multiline_text((x + 24, y + 96), caption, font=F_BODY(21), fill=GRAY, spacing=11)

    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    render(os.path.join(args.out_dir, "git-workflow.png"), with_cards=True)
    render(os.path.join(args.out_dir, "git-workflow-compact.png"), with_cards=False)


if __name__ == "__main__":
    main()
