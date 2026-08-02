"""
Render the CI recipe router (issue #283) as deck PNGs:

  deck/screenshots/ci-recipe-router.png        the router flow — the unchanged
                                               default pipeline vs. RECIPE=<name>
                                               selecting a child pipeline
  deck/screenshots/security-scan-findings.png  the security suite's first verified
                                               sweep (child pipeline 2717082866,
                                               2026-07-30) as a findings panel

Like capture_git_workflow.py these are faithful static renders, not screenshots:
the router graphic mirrors .gitlab-ci.yml + ci-recipes/ (keep the CATALOG list in
step with that directory), and the findings panel shows the numbers recorded on
the wiki's Security-scanning page for the first verified `security-all` run —
update SCANNERS when a newer sweep becomes the one the deck should cite.

Requires: Pillow + DejaVu fonts (same as capture_cli_menu.py).

Usage:
  python3 deck/capture_ci_router.py [--out-dir deck/screenshots]
"""
import argparse
import os

from PIL import Image, ImageDraw

from capture_cli_menu import _find_font_file
from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Deck palette (build_deck.py template colors) + neutrals for a white slide body.
BLUE   = (0x00, 0x6B, 0xB5)   # default pipeline
VIOLET = (0x6B, 0x4F, 0xA0)   # recipe / child-pipeline path
GREEN  = (0x2E, 0x9E, 0x4F)   # passing jobs
YELLOW = (0xFD, 0xB9, 0x13)   # accent
INK    = (0x2A, 0x2E, 0x32)
GRAY   = (0x6B, 0x70, 0x78)
CARD   = (0xF5, 0xF6, 0xF7)
EDGE   = (0xD5, 0xD9, 0xDD)
WHITE  = (0xFF, 0xFF, 0xFF)

# Severity colors (GitLab-adjacent, tuned to the deck neutrals).
SEV = {
    "Critical": (0x8E, 0x24, 0x28),
    "High":     (0xD9, 0x53, 0x4F),
    "Medium":   (0xE0, 0x9B, 0x2D),
    "Low":      (0x6B, 0x70, 0x78),
    "Info":     (0x00, 0x6B, 0xB5),
}


def _font(name, size):
    path = _find_font_file(name)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.truetype(name, size)


F_TITLE = lambda s: _font("DejaVuSans-Bold.ttf", s)
F_BODY = lambda s: _font("DejaVuSans.ttf", s)
F_MONO = lambda s: _font("DejaVuSansMono.ttf", s)


def job_pill(d, x, y, text, color, w=None, h=64, mono=True, fill=WHITE):
    """A GitLab-pipeline-style job pill with a status ring on the left."""
    f = F_MONO(24) if mono else F_BODY(24)
    tw = d.textlength(text, font=f)
    w = w or int(tw + 110)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=fill,
                        outline=color, width=4)
    cx, cy, r = x + h // 2 + 6, y + h // 2, 17
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=5)
    d.line([(cx - 8, cy + 1), (cx - 2, cy + 8), (cx + 9, cy - 7)], fill=color, width=5)
    d.text((x + h + 18, y + h // 2 - 16), text, font=f, fill=INK)
    return x + w


def arrow(d, x0, y0, x1, y1, color, width=8):
    d.line([(x0, y0), (x1 - 26, y1)], fill=color, width=width)
    d.polygon([(x1 - 30, y1 - 16), (x1 - 30, y1 + 16), (x1, y1)], fill=color)


# ci-recipes/*.yml — keep in step with the directory (security-all last, it's
# the one the flow below expands).
CATALOG = [
    ("smoke", "router plumbing check"),
    ("all-reports", "full report suite → artifact"),
    ("epic-cards-deck", "epic-cards PDF → artifact"),
    ("kaniko-runner-diag", "containerize diagnostics"),
    ("security-sast", "static analysis (Semgrep)"),
    ("security-secret-detection", "leaked credentials (Gitleaks)"),
    ("security-dependency-scanning", "vulnerable packages + SBOM"),
    ("security-container-scanning", "image CVEs (Trivy)"),
    ("security-iac", "IaC misconfigurations (KICS)"),
    ("security-all", "all five scanners, one run"),
]


def render_router(out_path):
    W, H = 2460, 1420
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    x0 = 90

    # --- The router file, feeding both paths. ---
    rc_x, rc_y, rc_w, rc_h = x0, 560, 470, 200
    d.rounded_rectangle([rc_x, rc_y, rc_x + rc_w, rc_y + rc_h], radius=18,
                        fill=CARD, outline=INK, width=4)
    d.text((rc_x + 30, rc_y + 34), ".gitlab-ci.yml", font=F_MONO(30), fill=INK)
    d.text((rc_x + 30, rc_y + 90), "the recipe router — written once,", font=F_BODY(22), fill=GRAY)
    d.text((rc_x + 30, rc_y + 126), "never edited per run (#283)", font=F_BODY(22), fill=GRAY)

    # --- Top path: no variable → the baseline pipeline, unchanged. ---
    top_y = 330
    d.text((780, top_y - 84), "no RECIPE variable — every push & merge", font=F_TITLE(24), fill=BLUE)
    arrow(d, rc_x + rc_w, rc_y + 40, 780, top_y + 32, BLUE)
    px = job_pill(d, 780, top_y, "test — pytest, every push", BLUE)
    arrow(d, px, top_y + 32, px + 90, top_y + 32, BLUE)
    px = job_pill(d, px + 90, top_y, "containerize — develop only", BLUE)
    d.text((780, top_y + 94), "the baseline is the default path, not a recipe — recipes never slow it down",
           font=F_BODY(22), fill=GRAY)

    # --- Bottom path: RECIPE=<name> → trigger job → child pipeline. ---
    bot_y = 890
    arrow(d, rc_x + rc_w, rc_y + rc_h - 40, 780, bot_y + 32, VIOLET)
    d.text((rc_x + 30, rc_y + rc_h + 60), "RECIPE=security-all", font=F_MONO(26), fill=VIOLET)
    d.text((rc_x + 30, rc_y + rc_h + 104), "Run-pipeline form, glab ci run,", font=F_BODY(22), fill=GRAY)
    d.text((rc_x + 30, rc_y + rc_h + 140), "or a weekly pipeline schedule", font=F_BODY(22), fill=GRAY)

    px = job_pill(d, 780, bot_y, "recipe ▸ trigger", VIOLET)
    d.text((780, bot_y + 90), "baseline jobs sit out;", font=F_BODY(22), fill=GRAY)
    d.text((780, bot_y + 126), "the child's result is the run's result", font=F_BODY(22), fill=GRAY)
    arrow(d, px, bot_y + 32, px + 90, bot_y + 32, VIOLET)

    # Child pipeline frame with the five scanner jobs.
    fx, fy = px + 90, 700
    fw, fh = W - 90 - fx, 490
    d.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=18, fill=CARD,
                        outline=VIOLET, width=4)
    d.text((fx + 30, fy + 24), "child pipeline — ci-recipes/security-all.yml",
           font=F_TITLE(24), fill=VIOLET)
    scan_jobs = [
        "semgrep-sast", "secret_detection (full history)",
        "dependency-scanning", "container-scanning", "kics-iac-sast",
    ]
    col_w = (fw - 90) // 2
    for i, name in enumerate(scan_jobs):
        cx = fx + 30 + (i % 2) * (col_w + 30)
        cy = fy + 90 + (i // 2) * 90
        job_pill(d, cx, cy, name, GREEN, w=col_w)
    d.text((fx + 30, fy + fh - 60), "one recipe file = one self-contained pipeline — own stages, own images",
           font=F_BODY(22), fill=GRAY)

    # --- The catalog, top right. ---
    cat_x, cat_y = 1450, 60
    cat_w = W - 90 - cat_x
    d.text((cat_x, cat_y - 10), "ci-recipes/ — ten recipes on the shelf", font=F_TITLE(24), fill=INK)
    f = F_MONO(20)
    for i, (name, desc) in enumerate(CATALOG[:4]):
        d.text((cat_x, cat_y + 40 + i * 34), f"{name:<22}{desc}", font=f, fill=GRAY)
    d.text((cat_x, cat_y + 40 + 4 * 34), f"{'security-*  (×6)':<22}the scanning suite ↓", font=f, fill=VIOLET)

    # --- Take-away captions, color-keyed to the paths. ---
    notes = [
        (BLUE, "Default path untouched: pushes and merges run test + containerize exactly as always."),
        (VIOLET, "RECIPE=<name> swaps in any recipe — reports, diagnostics, security — nothing copied into CI config, nothing reverted after."),
        (GREEN, "Extra variables forward into the child, so recipes take parameters; schedule RECIPE=security-all for a recurring audit."),
    ]
    ny = H - 190
    for color, text in notes:
        d.ellipse([x0, ny + 8, x0 + 20, ny + 28], fill=color)
        d.text((x0 + 40, ny), text, font=F_BODY(24), fill=INK)
        ny += 52

    img.save(out_path)


# The first verified sweep — wiki Security-scanning page, child pipeline
# 2717082866 on task/283-create-cicd-recipes-to-explorer, 2026-07-30.
SCANNERS = [
    ("SAST", "Semgrep — Python + Vue/JS source", 52,
     [("High", 2), ("Medium", 6), ("Low", 44)],
     "the two Highs lead the triage queue"),
    ("Secret Detection", "Gitleaks — code + full git history", 0,
     [],
     "clean — verifies the #111 token-scrub end to end"),
    ("Dependency Scanning", "requirements.txt + frontend lockfiles", 7,
     [("High", 5), ("Medium", 2)],
     "fixed versions listed for every finding"),
    ("Container Scanning", "Trivy — published runtime image", 205,
     [("Critical", 5), ("High", 31), ("Medium/Low", 169)],
     "typical for a slim Debian base; rebuilds clear fix-available CVEs"),
    ("IaC Scanning", "KICS — cdk/, helm/, Dockerfile", 33,
     [("Critical", 2), ("Medium", 13), ("Info", 18)],
     "misconfiguration checks over the deploy code"),
]


def sev_chip(d, x, y, label, count, h=44):
    color = SEV.get(label, SEV["Medium"] if "/" in label else SEV["Low"])
    if label == "Medium/Low":
        color = SEV["Low"]
    f = F_TITLE(22)
    text = f"{count} {label}"
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 36, y + h], radius=10, fill=color)
    d.text((x + 18, y + 9), text, font=f, fill=WHITE)
    return x + tw + 36 + 16


def render_findings(out_path):
    W, H = 2460, 1420
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    x0, x1 = 90, W - 90

    # Header band.
    d.rounded_rectangle([x0, 60, x1, 210], radius=18, fill=CARD, outline=EDGE, width=3)
    d.text((x0 + 40, 88), "RECIPE=security-all — first verified sweep", font=F_TITLE(34), fill=INK)
    d.text((x0 + 40, 150), "2026-07-30 · child pipeline 2717082866 · six scanner jobs, all green",
           font=F_BODY(24), fill=GRAY)
    total = sum(s[2] for s in SCANNERS)
    tf = F_TITLE(52)
    ttext = f"{total} findings"
    d.text((x1 - 60 - d.textlength(ttext, font=tf), 100), ttext, font=tf, fill=BLUE)

    # One row per scanner.
    row_y, row_h = 270, 176
    for name, sub, count, sevs, note in SCANNERS:
        d.rounded_rectangle([x0, row_y, x1, row_y + row_h - 24], radius=14,
                            fill=WHITE, outline=EDGE, width=3)
        d.text((x0 + 40, row_y + 24), name, font=F_TITLE(28), fill=INK)
        d.text((x0 + 40, row_y + 74), sub, font=F_MONO(21), fill=GRAY)
        d.text((x0 + 40, row_y + 112), note, font=F_BODY(21), fill=GRAY)

        cf = F_TITLE(44)
        ctext = str(count)
        d.text((x0 + 900 - d.textlength(ctext, font=cf), row_y + 44), ctext,
               font=cf, fill=(GREEN if count == 0 else INK))
        cx = x0 + 960
        if sevs:
            for label, n in sevs:
                cx = sev_chip(d, cx, row_y + 52, label, n)
        else:
            f = F_TITLE(22)
            d.rounded_rectangle([cx, row_y + 52, cx + 130, row_y + 96], radius=10, fill=GREEN)
            d.text((cx + 18, row_y + 61), "clean", font=f, fill=WHITE)
        row_y += row_h

    # Where the findings surface.
    d.text((x0, row_y + 10), "Where to explore them", font=F_TITLE(24), fill=INK)
    notes = [
        (BLUE, "Pipeline → Security tab — every finding of that run, with a detail drawer into the exact file/line or package."),
        (VIOLET, "Secure → Vulnerability report — the standing register once scans run on develop; dismiss / confirm / create-issue triage."),
        (GREEN, "MR security widget + gl-*-report.json artifacts — shift-left view per MR, machine-readable export per job."),
    ]
    ny = row_y + 58
    for color, text in notes:
        d.ellipse([x0, ny + 8, x0 + 20, ny + 28], fill=color)
        d.text((x0 + 40, ny), text, font=F_BODY(24), fill=INK)
        ny += 50

    img.save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    router = os.path.join(args.out_dir, "ci-recipe-router.png")
    render_router(router)
    print(f"wrote {router}")

    findings = os.path.join(args.out_dir, "security-scan-findings.png")
    render_findings(findings)
    print(f"wrote {findings}")


if __name__ == "__main__":
    main()
