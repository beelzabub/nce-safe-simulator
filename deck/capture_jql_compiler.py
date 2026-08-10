"""
Render the JQL engine as what it structurally is — a small compiler — for the
architecture slide of epic #297.

Prerequisite generator like capture_cli_menu.py / capture_jql_internals.py;
output (deck/screenshots/22f-jql-compiler.png) is git-ignored and rebuilt on
demand. Pure drawing: no network, no engine invocation. The phase names and
module paths are the deck's claim about the design, so they are written here
rather than introspected — capture_jql_internals.py is the script that proves
the behaviour with live output.

The framing is deliberate. "Query language over GitLab" undersells it; the
interesting part is that the target is a *capability-limited* data source, so
the back end cannot emit arbitrary filters and the optimizer has to prove that
what it does emit is a sound over-approximation. That is the classic federated-
query problem, and it is why the residual-evaluation pass exists.

Usage:
  python3 deck/capture_jql_compiler.py [--out PATH]
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from capture_cli_menu import BG, FG, DIM, FAINT, _font  # noqa: E402

PANEL   = (0x23, 0x28, 0x31)
EDGE    = (0x36, 0x3D, 0x49)
ACCENT  = (0x8F, 0xB8, 0xF0)   # IR / data flowing between phases
SERVER  = (0x6E, 0xC8, 0xB4)   # what leaves for GitLab
CLIENT  = (0xE0, 0xA1, 0x5C)   # what stays behind

STAGES = [
    ("FRONT END", "syntax", [
        ("Lexical analysis",   "jql/lexer.py",   "token stream"),
        ("Recursive-descent parse", "jql/parser.py",  "AST"),
    ]),
    ("MIDDLE END", "semantics + optimisation", [
        ("Name resolution & typing", "jql/fields.py",  "typed AST"),
        ("Constant folding",   "jql/dates.py",   "-4w → a timestamp"),
        ("Predicate pushdown", "jql/planner.py", "envelope + residual"),
    ]),
    ("BACK END", "code generation + runtime", [
        ("Emit target query",  "jql/executor.py", "GraphQL document"),
        ("Residual evaluation", "mixins/query.py", "the answer"),
    ]),
]

TITLE = "The engine is a compiler — JQL in, GraphQL out"
SUB   = ("Target is a capability-limited source: GitLab's API cannot express every predicate, "
         "so the optimiser emits only what it can prove is a superset.")

FOOT = [
    ("Soundness condition  ", DIM, True),
    ("every item the full expression could match must also satisfy the emitted filter. ", FG, False),
    ("Push-down changes cost, never results.", SERVER, False),
]


#: One row height for every panel. Dividing each panel's own height by its own
#: phase count instead stretches the two-phase panels into uneven gaps and the
#: rows stop lining up across the diagram, which reads as a layout accident.
ROW_H = 104


def render(out_path):
    pad = 44
    head, foot_h = 168, 118
    W = 1600
    H = head + 96 + ROW_H * max(len(s[2]) for s in STAGES) + 18 + foot_h
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    f_title = _font(True, 30)
    f_sub   = _font(False, 17)
    f_hdr   = _font(True, 17)
    f_hsub  = _font(False, 14)
    f_phase = _font(True, 19)
    f_mod   = _font(False, 15)
    f_ir    = _font(False, 15)
    f_foot  = _font(False, 16)

    d.text((pad, 38), TITLE, font=f_title, fill=FG)
    # wrap the standfirst by hand — two lines, split on the clause boundary
    a, _, b = SUB.partition("so the optimiser")
    d.text((pad, 84), a.strip(), font=f_sub, fill=DIM)
    d.text((pad, 108), "so the optimiser " + b.strip(), font=f_sub, fill=DIM)

    top, bottom = head, H - foot_h
    gap, arrow = 30, 34
    total_arrows = arrow * (len(STAGES) - 1)
    avail = W - pad * 2 - gap * (len(STAGES) - 1) - total_arrows
    # width proportional to phase count so rows stay the same height everywhere
    counts = [len(s[2]) for s in STAGES]
    widths = [int(avail * c / sum(counts)) for c in counts]

    x = pad
    for si, ((name, sub, phases), w) in enumerate(zip(STAGES, widths)):
        d.rounded_rectangle([x, top, x + w, bottom], radius=10, fill=PANEL, outline=EDGE, width=2)

        d.text((x + 22, top + 20), name, font=f_hdr, fill=ACCENT)
        d.text((x + 22, top + 44), sub, font=f_hsub, fill=FAINT)
        d.line([x + 22, top + 74, x + w - 22, top + 74], fill=EDGE, width=2)

        for pi, (phase, module, ir) in enumerate(phases):
            ry = top + 96 + pi * ROW_H
            if pi:
                d.line([x + 30, ry - 14, x + w - 30, ry - 14], fill=EDGE, width=1)
            d.text((x + 22, ry + 4), phase, font=f_phase, fill=FG)
            d.text((x + 22, ry + 32), module, font=f_mod, fill=FAINT)
            # the IR this phase hands on — the through-line of the whole picture
            colour = SERVER if "GraphQL" in ir else (CLIENT if "answer" in ir else ACCENT)
            d.text((x + 22, ry + 56), "→ " + ir, font=f_ir, fill=colour)

        if si < len(STAGES) - 1:
            ax = x + w + gap // 2
            ay = (top + bottom) // 2
            d.line([ax, ay, ax + arrow, ay], fill=EDGE, width=3)
            d.polygon([(ax + arrow + 10, ay), (ax + arrow - 2, ay - 7), (ax + arrow - 2, ay + 7)], fill=EDGE)
        x += w + gap + arrow

    fy = bottom + 34
    fx = pad
    for text, colour, bold in FOOT:
        f = _font(bold, 16) if bold else f_foot
        d.text((fx, fy), text, font=f, fill=colour)
        fx += int(d.textlength(text, font=f))

    d.text((pad, fy + 30),
           "Unsatisfiable conjunctions fold to ⊥ at plan time and issue no request at all.",
           font=f_foot, fill=FAINT)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "screenshots", "22f-jql-compiler.png"))
    args = ap.parse_args()
    render(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
