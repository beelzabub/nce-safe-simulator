"""
Build the sprint-review .pptx from the SAIC template + live metrics + capability config +
screenshots. See deck/README.md for the full pipeline.

Usage:
  python3 deck/build_deck.py [--template-s3-path s3://...] [--screenshots-dir deck/screenshots]
                             [--metrics deck/metrics.json] [--capabilities deck/capabilities.yaml]
                             [--shots deck/shots.yaml] [--out deck/dist/NCE-Safe-Simulator-Sprint-Review.pptx]

Requires deck/metrics.json (run fetch_metrics.py first) and deck/screenshots/ (run
capture_screenshots.py first, or point --screenshots-dir at an existing set).
"""
import argparse
import json
import os
import subprocess

import yaml
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEFAULT_TEMPLATE_S3 = "s3://workflow-bootstrap-20260626-055227-881490118830/x-bookmarks-obsidian/Powerpoint Template SAIC copy.pptx"

# Theme colors are read from the template's own theme XML at build time (see
# _load_theme_colors) rather than hardcoded, so a template swap doesn't silently
# mismatch the deck's palette against the new file's real brand colors.
FONT = "Gill Sans MT"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0x64, 0x69, 0x6F)
LGRAY = RGBColor(0xE1, 0xE1, 0xE1)
DARKBG = RGBColor(0x14, 0x18, 0x1C)


def _load_theme_colors(prs):
    """Pull accent colors straight from the template's theme1.xml rather than
    hardcoding hex values that could drift if the template is ever swapped."""
    from lxml import etree

    theme_part = prs.slide_masters[0].part.part_related_by(
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    )
    theme_el = etree.fromstring(theme_part.blob)
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    scheme = theme_el.find(".//a:clrScheme", ns)
    vals = {}
    for child in scheme:
        tag = child.tag.split("}")[-1]
        srgb = child.find("a:srgbClr", ns)
        if srgb is not None:
            vals[tag] = RGBColor.from_string(srgb.get("val"))
    return {
        "blue": vals.get("accent1", RGBColor(0x00, 0x6B, 0xB5)),
        "green": vals.get("accent2", RGBColor(0xBC, 0xD6, 0x3E)),
        "teal": vals.get("accent3", RGBColor(0x00, 0xAC, 0xD4)),
        "gray": vals.get("accent4", GRAY),
        "lgray": vals.get("accent5", LGRAY),
        "yellow": vals.get("accent6", RGBColor(0xFD, 0xB9, 0x13)),
    }


def _decode_concatenated_json_arrays(text):
    """glab api --paginate concatenates one JSON array per page with no separator
    (e.g. "[...][...]"), so a plain json.loads() fails past page 1. Mirrors the
    same helper in fetch_metrics.py."""
    decoder = json.JSONDecoder()
    items, idx, text = [], 0, text.strip()
    while idx < len(text):
        obj, end = decoder.raw_decode(text, idx)
        items.extend(obj)
        idx = end
    return items


def fetch_issues():
    """Pull every issue (open + closed) for the project the current git remote
    points at — same `glab api projects/:id/...` project-resolution approach as
    fetch_metrics.py, so there's no hardcoded project ID. Returns a list of
    {iid, title, state, type, assignee} dicts sorted by issue number ascending."""
    out = subprocess.run(
        ["glab", "api", "projects/:id/issues?state=all&per_page=100&order_by=created_at&sort=asc",
         "--paginate"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    rows = []
    for x in _decode_concatenated_json_arrays(out):
        issue_type = ""
        for label in x.get("labels", []):
            if label.startswith("type::"):
                issue_type = label.split("::", 1)[1]
                break
        assignee = (x.get("assignee") or {}).get("username", "")
        rows.append({"iid": x["iid"], "title": x["title"], "state": x["state"],
                     "type": issue_type, "assignee": assignee})
    rows.sort(key=lambda r: r["iid"])
    return rows


def ensure_template(s3_path, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, "template.pptx")
    if not os.path.exists(local_path):
        print(f"Fetching template from {s3_path} ...")
        subprocess.run(["aws", "s3", "cp", s3_path, local_path], check=True)
    return local_path


class DeckBuilder:
    def __init__(self, template_path, screenshots_dir, metrics, capabilities, shots):
        self.prs = Presentation(template_path)
        self.screenshots_dir = screenshots_dir
        self.metrics = metrics
        self.capabilities = capabilities
        self.shots = shots
        self.C = _load_theme_colors(self.prs)
        self.SW = self.prs.slide_width
        self.SH = self.prs.slide_height
        self.BLANK = self.prs.slide_masters[0].slide_layouts[7]
        self.COVER1 = self.prs.slide_masters[2].slide_layouts[0]
        self.TOC = self.prs.slide_masters[0].slide_layouts[8]
        self.DIVIDER1 = self.prs.slide_masters[2].slide_layouts[13]

    # -- shape helpers --------------------------------------------------
    def add_rect(self, slide, x, y, w, h, color):
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.fill.background()
        shp.shadow.inherit = False
        return shp

    def add_text(self, slide, x, y, w, h, text, size, color, bold=False,
                 align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, wrap=True):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = wrap
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = align
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = color
        r.font.name = FONT
        return tb

    def add_bullets(self, slide, x, y, w, h, items, size, color, space_after=8):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(space_after)
            r = p.add_run()
            r.text = f"▪  {item}"
            r.font.size = Pt(size)
            r.font.color.rgb = color
            r.font.name = FONT
        return tb

    def header_band(self, slide, title, subtitle=None):
        self.add_rect(slide, 0, 0, self.SW, Emu(685800), self.C["blue"])
        self.add_text(slide, Emu(320000), Emu(90000), self.SW - Emu(640000), Emu(360000), title, 22, WHITE, bold=True)
        if subtitle:
            self.add_text(slide, Emu(320000), Emu(430000), self.SW - Emu(640000), Emu(220000), subtitle, 10.5, WHITE)
        self.add_rect(slide, 0, Emu(685800), self.SW, Emu(27000), self.C["yellow"])

    def add_picture_contain(self, slide, img_path, box_x, box_y, box_w, box_h):
        with Image.open(img_path) as im:
            iw, ih = im.size
        img_ratio, box_ratio = iw / ih, box_w / box_h
        if img_ratio > box_ratio:
            w, h = box_w, int(box_w / img_ratio)
        else:
            h, w = box_h, int(box_h * img_ratio)
        x, y = box_x + (box_w - w) // 2, box_y + (box_h - h) // 2
        slide.shapes.add_picture(img_path, x, y, width=w, height=h)

    def add_picture_cover(self, slide, img_path, box_x, box_y, box_w, box_h):
        """Like add_picture_contain, but crops (non-destructively, via the
        picture's srcRect) to fill the box exactly instead of letterboxing —
        CSS background-size: cover."""
        with Image.open(img_path) as im:
            iw, ih = im.size
        img_ratio, box_ratio = iw / ih, box_w / box_h
        pic = slide.shapes.add_picture(img_path, box_x, box_y, width=box_w, height=box_h)
        if img_ratio > box_ratio:
            crop = (1 - box_ratio / img_ratio) / 2
            pic.crop_left, pic.crop_right = crop, crop
        else:
            crop = (1 - img_ratio / box_ratio) / 2
            pic.crop_top, pic.crop_bottom = crop, crop
        return pic

    def set_fill_opacity(self, shape, opacity_pct):
        """Set a solid-filled shape's fill opacity (0-100). DrawingML's alpha
        is stated in thousandths of a percent, so 45% opacity -> val=45000."""
        srgb = shape._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
        alpha = srgb.makeelement(qn("a:alpha"), {"val": str(int(opacity_pct * 1000))})
        srgb.append(alpha)

    def new_slide(self, layout=None):
        return self.prs.slides.add_slide(layout or self.BLANK)

    def capability_slide(self, title, blurb, bullets, image_path=None, caption=None):
        s = self.new_slide()
        self.header_band(s, title, blurb)
        body_y = Emu(830000)
        body_h = self.SH - body_y - Emu(120000)
        if image_path and os.path.exists(image_path):
            bullets_w = Emu(4550000)
            self.add_bullets(s, Emu(180000), body_y, bullets_w, body_h, bullets, 13,
                              RGBColor(0x2A, 0x2E, 0x32), space_after=10)
            img_x = Emu(4850000)
            img_w = self.SW - img_x - Emu(180000)
            img_h = body_h - Emu(260000)
            self.add_picture_contain(s, image_path, img_x, body_y, img_w, img_h)
            if caption:
                self.add_text(s, img_x, body_y + img_h + Emu(30000), img_w, Emu(200000), caption, 9,
                              GRAY, align=PP_ALIGN.CENTER, italic=True)
        else:
            if image_path:
                print(f"  warn: image not found, falling back to text-only: {image_path}")
            self.add_bullets(s, Emu(180000), body_y, self.SW - Emu(360000), body_h, bullets, 13,
                              RGBColor(0x2A, 0x2E, 0x32), space_after=10)
        return s

    def full_bleed_image_slide(self, title, img_path, dark=True):
        s = self.new_slide()
        bg = DARKBG if dark else RGBColor(0xF2, 0xF3, 0xF4)
        self.add_rect(s, 0, 0, self.SW, self.SH, bg)
        self.add_rect(s, 0, 0, self.SW, Emu(430000), self.C["blue"])
        self.add_text(s, Emu(220000), Emu(70000), self.SW - Emu(440000), Emu(300000), title, 14, WHITE,
                       bold=True, anchor=MSO_ANCHOR.MIDDLE)
        self.add_rect(s, 0, Emu(430000), self.SW, Emu(18000), self.C["yellow"])
        box_y = Emu(500000)
        box_h = self.SH - box_y - Emu(80000)
        self.add_picture_contain(s, img_path, Emu(120000), box_y, self.SW - Emu(240000), box_h)
        return s

    def remove_slide(self, index):
        xml_slides = self.prs.slides._sldIdLst
        slide_ids = list(xml_slides)
        doomed = slide_ids[index]
        self.prs.part.drop_rel(doomed.get(qn("r:id")))
        xml_slides.remove(doomed)

    # -- slide sections ---------------------------------------------------
    def build_cover(self):
        # slide 1 in the template is an unrelated leftover sales slide - drop it.
        if len(self.prs.slides) > 1:
            self.remove_slide(1)
        cover = self.prs.slides[0]

        # The template's "Cover 1" layout decorates the right half with two
        # groups of faceted freeform triangles instead of a photo slot. Strip
        # them from the layout (Cover 1 is only used by this one slide, so
        # this can't bleed into any other slide) and put a real fleet photo
        # in the space they occupied instead.
        layout = cover.slide_layout
        for shape in list(layout.shapes):
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                shape._element.getparent().remove(shape._element)

        # Full-bleed fleet photo behind everything, knocked back by a dark
        # scrim so the white title/subtitle stay legible over the busy image
        # (bright sky up top, dark sea below — a uniform overlay reads on both).
        csg_photo = os.path.join(REPO_ROOT, "media/login-backgrounds/csg-valiant-shield-formation.jpg")
        spTree = cover.shapes._spTree
        if os.path.exists(csg_photo):
            pic = self.add_picture_cover(cover, csg_photo, 0, 0, self.SW, self.SH)
            scrim = self.add_rect(cover, 0, 0, self.SW, self.SH, RGBColor(0x0A, 0x0E, 0x14))
            self.set_fill_opacity(scrim, 52)
            # add_picture / add_rect append to the front of the z-order; drop
            # the photo to the very back and the scrim just above it, so both
            # sit behind the title, subtitle, logo, and seal.
            for el in (pic._element, scrim._element):
                spTree.remove(el)
            spTree.insert(2, pic._element)
            spTree.insert(3, scrim._element)

        # Cover title/subtitle use the color the user set by hand: theme
        # "Background 1, darker 25%" (a light gray) rather than a fixed RGB.
        def cover_color(run):
            run.font.color.theme_color = MSO_THEME_COLOR.BACKGROUND_1
            run.font.color.brightness = -0.25

        cover.placeholders[0].text_frame.paragraphs[0].runs[0].text = "NCE Safe Simulator"
        cover_color(cover.placeholders[0].text_frame.paragraphs[0].runs[0])
        body_tf = cover.placeholders[10].text_frame
        m = self.metrics
        body_tf.paragraphs[0].runs[0].text = "Simulator Overview: SAFe GitLab Portfolio Tooling"
        cover_color(body_tf.paragraphs[0].runs[0])
        if len(body_tf.paragraphs) > 1 and body_tf.paragraphs[1].runs:
            body_tf.paragraphs[1].runs[0].text = f"Development window: {m['first_commit_date']} – {m['last_commit_date']}"
            cover_color(body_tf.paragraphs[1].runs[0])

        # White emblem (not the navy one) now that the cover reads dark.
        nce_logo = os.path.join(REPO_ROOT, "frontend/src/assets/nce-logo-white.png")
        pmw_seal = os.path.join(REPO_ROOT, "frontend/src/assets/pmw-120-seal-transparent.png")
        if os.path.exists(nce_logo):
            cover.shapes.add_picture(nce_logo, Emu(320000), Emu(220000), height=Emu(500000))
        if os.path.exists(pmw_seal):
            cover.shapes.add_picture(pmw_seal, self.SW - Emu(900000), Emu(220000), height=Emu(650000))

    def build_agenda(self):
        agenda = self.new_slide(self.TOC)
        agenda.placeholders[0].text_frame.paragraphs[0].text = "Agenda"
        items = ["Project Overview", "Architecture", "DoD Architecture Views",
                 "Deployment Methods", "CLI vs. UI",
                 "Development Process & Tools", "Technology Stack",
                 "By the Numbers — Metrics",
                 "Issues — Full Backlog",
                 f"Capability Areas ({len(self.capabilities)})",
                 "Appendix — Full UI & Report Reference"]
        tf = agenda.placeholders[1].text_frame
        tf.clear()
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = item

    def build_chrome_slides(self):
        s = os.path.join(self.screenshots_dir, "00-home_light.png")
        self.capability_slide(
            "Project Overview", "SAFe portfolio automation for GitLab",
            ["Manages the Epic → Capability/Feature → Issue hierarchy across a multi-group SAFe "
             "portfolio (Value Streams → ARTs → Teams) directly against the GitLab API.",
             "Generates realistic lorem test data, imports/exports epics & issues, and publishes a "
             "suite of portfolio-level reports (WSJF, Risk, Blocking, Capacity, Flow Metrics, Data Quality).",
             "Three-tier system: a Python automation core (GitLab REST + GraphQL via python-gitlab) fronted by a FastAPI "
             "server, driving a Vue 3 web UI and a scriptable CLI — both call the same tool registry.",
             "Reports render to three surfaces: GitLab Wiki (markdown), a Quarto static site, and Marimo "
             "WASM interactive notebooks."],
            image_path=s, caption="Web UI — job picker",
        )
        self._build_architecture_slide()
        self._build_dod_architecture_slides()
        self._build_deployment_slide()
        self.capability_slide(
            "CLI vs. UI", "Same tool registry, two front ends",
            ["CLI (NceGitLab.py): interactive numbered menu or scripted flags — built for automation and CI.",
             "Web UI (Vue 3 + FastAPI): job picker with search, parameterized tool dialogs, live streaming "
             "log viewer, session history, in-browser config editor, dark/light theme.",
             "Every dialog shows its exact CLI equivalent inline — the UI is a guided front end over the "
             "same commands, not a separate code path.",
             "UI adds guardrails CLI doesn't enforce as a step: confirmation gating on mutating tools, "
             "live status panel, auto-refreshing running-jobs list."],
            image_path=os.path.join(self.screenshots_dir, "05-import-export-import-epics_light-cli-closeup.png"),
            caption="Import Epics dialog (lower half) — every field mirrored by the generated CLI command",
        )
        m = self.metrics
        self.capability_slide(
            "Development Process & Tools", "Engineering discipline behind the build",
            ["Issue-linked branch naming (feature/NNN-, bug/NNN-, enhance/NNN-) merging into a single "
             f"develop integration branch — {m['mrs_total']} MRs, {m['mrs_merged']} merged.",
             "GitLab CI: full pytest suite on every push, plus a Quarto → GitLab Pages publish stage "
             "gated to develop.",
             "Dedicated multi-phase test-coverage program grew the suite substantially relative to the "
             "automation core it verifies (see Metrics).",
             "pytest markers (unit / integration / infra) separate fast tests from live AWS/K8s checks; "
             "Makefile standardizes the local fetch → render → publish → deploy pipeline.",
             "Dedicated security-hygiene pass: leaked token scrubbed from git history, secrets moved to "
             "environment variables.",
             "Stack: Python (python-gitlab GraphQL, boto3, FastAPI, pandas, Plotly), Vue 3, Quarto, "
             "Marimo, Docker, AWS CDK, Helm, optional Grafana."],
            image_path=os.path.join(self.screenshots_dir, "14-live-job-diagnose-03-completed.png"),
            caption="Diagnose — live API/compatibility check output",
        )

    def _build_architecture_slide(self):
        arch = self.new_slide()
        self.header_band(arch, "Architecture", "Three-tier system, three reporting surfaces")
        tiers = [
            ("Python Automation Core", "NceGitLab.py + mixins/ — GitLab REST v4 via python-gitlab,\nplus GraphQL where REST falls short (work-item/epic weight, blocking, links)"),
            ("FastAPI Server", "REST + WebSocket job runner\nstreams live logs to the browser"),
            ("Vue 3 Web UI  /  CLI", "Same tool registry exposed both ways\n(job picker + streaming UI, or scripted CLI flags)"),
        ]
        tier_w, gap, start_x, tier_y, tier_h = Emu(2850000), Emu(90000), Emu(180000), Emu(1150000), Emu(1050000)
        for i, (t, desc) in enumerate(tiers):
            x = start_x + i * (tier_w + gap)
            box = self.add_rect(arch, x, tier_y, tier_w, tier_h, RGBColor(0xF5, 0xF6, 0xF7))
            box.line.color.rgb = self.C["blue"]
            box.line.width = Pt(1.25)
            self.add_rect(arch, x, tier_y, tier_w, Emu(60000), self.C["blue"])
            self.add_text(arch, x + Emu(80000), tier_y + Emu(140000), tier_w - Emu(160000), Emu(300000), t, 13, self.C["blue"], bold=True)
            self.add_text(arch, x + Emu(80000), tier_y + Emu(460000), tier_w - Emu(160000), Emu(560000), desc, 10, GRAY)
            if i < len(tiers) - 1:
                arrow = arch.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + tier_w, tier_y + tier_h // 2 - Emu(60000), gap, Emu(120000))
                arrow.fill.solid(); arrow.fill.fore_color.rgb = self.C["yellow"]
                arrow.line.fill.background()
        self.add_text(arch, Emu(180000), Emu(2450000), self.SW - Emu(360000), Emu(300000),
                       "Three reporting surfaces, all fed by the same Python core:", 13, self.C["blue"], bold=True)
        self.add_bullets(arch, Emu(220000), Emu(2820000), self.SW - Emu(440000), Emu(1600000), [
            "GitLab Wiki — markdown pages, one per report",
            "Quarto static site — Plotly charts, published via GitLab Pages",
            "Marimo — WASM notebooks, full client-side interactivity, no server round-trip",
        ], 12, RGBColor(0x2A, 0x2E, 0x32))
        self.add_text(arch, Emu(180000), self.SH - Emu(380000), self.SW - Emu(360000), Emu(280000),
                       "Architecture is generated as code (Python `diagrams`, rendered at container build): the "
                       "simple ECS/EKS deployment views plus a DoD/DoDAF view set — OV-1, SV-1, SV-2, data flow, "
                       "DevSecOps (see next slide). Regenerate via `make ecs-diagram` / `eks-diagram` / `dod-diagrams`.",
                       8.5, GRAY, italic=True)

    def _build_dod_architecture_slides(self):
        """DoD/DoDAF architecture view set added in MR!139 — a views table plus a
        security-posture / known-gaps slide, distilled from diagrams/DOD_ARCHITECTURE.md."""
        # --- Slide 1: the DoDAF view set ---
        s = self.new_slide()
        self.header_band(s, "DoD Architecture View Set",
                         "DoDAF-aligned views generated as code — for program review / assessment packages")
        self.add_text(s, Emu(180000), Emu(760000), self.SW - Emu(360000), Emu(300000),
                      "Generated from diagrams/ scripts (Python `diagrams` library) at container build and "
                      "surfaced in the web UI architecture dialog, alongside a master DOD_ARCHITECTURE.md "
                      "(AV-1 summary, PPSM ports table, OV-6c logon/consent sequence).",
                      10, GRAY, italic=True)

        margin = Emu(180000)
        content_w = self.SW - 2 * margin
        top = Emu(1160000)
        pad = Emu(70000)
        line_h = 155000
        char_w = 58000
        body_color = RGBColor(0x2A, 0x2E, 0x32)
        cols = [("View", Emu(2750000)), ("DoDAF", Emu(1150000)), ("What it shows", Emu(4884000))]

        def cell_x(i):
            return margin + sum(c[1] for c in cols[:i])

        def est_lines(text, w):
            cpl = max(1, int((w - 2 * pad) / char_w))
            return max(1, -(-len(text) // cpl))

        rows = [
            ("Operational concept", "OV-1", "Stakeholder tiers, the system, GitLab as system of record, and the reporting surfaces"),
            ("System interfaces", "SV-1", "System boundary plus every external interface, each with its protocol and port"),
            ("Deployment topology — EKS", "SV-2", "Trust zones, CloudFront-only ALB security group, IRSA scope, EFS access points"),
            ("Deployment topology — ECS", "SV-2", "Task trust zones, task role, deploy circuit-breaker, SSM exec access"),
            ("Data flow", "SV-4", "Sources → one-pass snapshot → stores → egress; Grafana drawn as a read-only pull"),
            ("DevSecOps pipeline", "—", "CI tests on every push; cloud deploys are optional, on-demand `make` targets"),
            ("Ports, protocols & services", "PPSM", "12-row table — each source→destination flow with its port and boundary control"),
            ("Logon & consent flow", "OV-6c", "DoD Notice & Consent banner (DTM 08-060) and the sign-in / session sequence"),
        ]

        # header row
        self.add_rect(s, margin, top, content_w, Emu(300000), self.C["blue"])
        for i, (label, w) in enumerate(cols):
            self.add_text(s, cell_x(i) + pad, top, w - 2 * pad, Emu(300000),
                          label, 10.5, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        y = top + Emu(300000)
        for r, (view, vp, shows) in enumerate(rows):
            lines = max(est_lines(view, cols[0][1]), est_lines(shows, cols[2][1]))
            row_h = Emu(max(300000, lines * line_h + 110000))
            if r % 2 == 0:
                self.add_rect(s, margin, y, content_w, row_h, WHITE)
            else:
                band = self.add_rect(s, margin, y, content_w, row_h, self.C["blue"])
                self.set_fill_opacity(band, 12)
            self.add_text(s, cell_x(0) + pad, y + Emu(45000), cols[0][1] - 2 * pad, row_h, view, 9, self.C["blue"], bold=True)
            self.add_text(s, cell_x(1) + pad, y + Emu(45000), cols[1][1] - 2 * pad, row_h, vp, 9, body_color, bold=True)
            self.add_text(s, cell_x(2) + pad, y + Emu(45000), cols[2][1] - 2 * pad, row_h, shows, 9, body_color)
            y += row_h

        # --- Diagram slides: the actual rendered DoDAF views (generated from
        # diagrams/*.py into screenshots/architecture/ — see README/dod-diagrams). ---
        arch_dir = os.path.join(self.screenshots_dir, "architecture")
        diagrams = [
            ("ov1-architecture.png",      "OV-1 — Operational Concept"),
            ("sv1-architecture.png",      "SV-1 — System Interfaces"),
            ("sv2-eks-architecture.png",  "SV-2 — Deployment Topology (EKS)"),
            ("sv2-ecs-architecture.png",  "SV-2 — Deployment Topology (ECS Fargate)"),
            ("dataflow-architecture.png", "SV-4 — Data Flow"),
            ("devsecops-architecture.png", "DevSecOps Pipeline"),
        ]
        for fname, title in diagrams:
            path = os.path.join(arch_dir, fname)
            if os.path.exists(path):
                self.full_bleed_image_slide(title, path, dark=False)
            else:
                print(f"  warn: architecture diagram not found, skipping slide: {path}")

        # --- Slide 2: security posture & known gaps ---
        s2 = self.new_slide()
        self.header_band(s2, "Security Posture & Known Gaps",
                         "From the DoD architecture master document (AV-1 / PPSM / OV-6c)")
        col_w = (self.SW - Emu(540000)) // 2
        left_x, right_x = Emu(180000), Emu(180000) + col_w + Emu(180000)
        head_y, body_y = Emu(830000), Emu(1140000)
        body_h = self.SH - body_y - Emu(160000)
        self.add_rect(s2, left_x, head_y, col_w, Emu(260000), self.C["blue"])
        self.add_text(s2, left_x + Emu(80000), head_y, col_w - Emu(160000), Emu(260000),
                      "Security posture", 12, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        self.add_bullets(s2, left_x + Emu(40000), body_y, col_w - Emu(80000), body_h, [
            "TLS at CloudFront (cloud) / Caddy + Let's Encrypt (single-box); HTTP only inside the VPC/Docker network.",
            "DoD Notice & Consent banner (DTM 08-060), on by default, re-acknowledged each browser session.",
            "AuthN: none (cosmetic front door) or basic (dev credential); in-memory sessions, 12-hour TTL.",
            "Secrets: GitLab PAT in SSM SecureString (cloud) / env var (local) — never committed.",
            "Data at rest: local disk or encrypted EFS; content is synthetic portfolio data (no PII/CUI).",
            "No inbound admin ports — SSM exec only; ALB reachable solely from CloudFront.",
        ], 11, body_color, space_after=8)
        self.add_rect(s2, right_x, head_y, col_w, Emu(260000), self.C["green"])
        self.add_text(s2, right_x + Emu(80000), head_y, col_w - Emu(160000), Emu(260000),
                      "Known gaps (candidate roadmap)", 12, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        self.add_bullets(s2, right_x + Emu(40000), body_y, col_w - Emu(80000), body_h, [
            "No CAC/PIV or federated identity yet — basic is dev-only (AAA methods tracked in #152–#156).",
            "No RBAC — access is authenticated-vs-not; job conflicts use writer/read-only groups, not permissions.",
            "CI runs tests only — no SAST, dependency/container scanning, or SBOM stages; images deploy operator-driven.",
            "No per-user structured audit trail (job/stdout logs to CloudWatch, 1-month retention).",
            "Commercial us-east-1 — a GovCloud / Impact-Level target would need its own accreditation work.",
        ], 11, body_color, space_after=8)

    def _build_deployment_slide(self):
        deploy = self.new_slide()
        self.header_band(deploy, "Deployment Methods", "One Docker image, three ways to run it")
        modes = [
            ("Single-Box", "EC2 + Caddy (auto TLS)\nEventBridge start/stop schedule\nfor cost control", self.C["green"]),
            ("ECS (Fargate)", "ARM64 Fargate task\nbehind ALB + CloudFront", self.C["teal"]),
            ("EKS (Kubernetes)", "Production-recommended\nManaged ARM64 node group, ALB\nvia AWS LB Controller, EFS storage", self.C["blue"]),
        ]
        mode_w, start_x, tier_y = Emu(2850000), Emu(180000), Emu(1150000)
        gap = Emu(90000)
        for i, (t, desc, color) in enumerate(modes):
            x = start_x + i * (mode_w + gap)
            box = self.add_rect(deploy, x, tier_y, mode_w, Emu(1300000), RGBColor(0xF5, 0xF6, 0xF7))
            box.line.color.rgb = color
            box.line.width = Pt(1.5)
            self.add_rect(deploy, x, tier_y, mode_w, Emu(60000), color)
            self.add_text(deploy, x + Emu(80000), tier_y + Emu(140000), mode_w - Emu(160000), Emu(300000), t, 14, color, bold=True)
            self.add_text(deploy, x + Emu(80000), tier_y + Emu(460000), mode_w - Emu(160000), Emu(700000), desc, 10.5, GRAY)
        self.add_bullets(deploy, Emu(220000), Emu(2650000), self.SW - Emu(440000), Emu(1900000), [
            "All three modes share one CDK project (nce_ecs_stack.py / nce_eks_stack.py), one ECR image, and SSM-stored config.",
            "helm/nce-safe-simulator/ — Helm chart for the EKS path (deployment, service, ingress, PV/PVC, service account).",
            "cdk/scripts/deploy-validate-loop.sh — automated teardown → deploy → validate cycles for both AWS stacks.",
            "CI (.gitlab-ci.yml): full pytest suite on every push; Quarto → GitLab Pages publish gated to the develop branch.",
            "Optional Amazon Managed Grafana (~$9/editor/mo) — off by default, toggled per deployment.",
        ], 12, RGBColor(0x2A, 0x2E, 0x32))

    def build_metrics_slide(self):
        m = self.metrics
        metrics_s = self.new_slide()
        first, last = m["first_commit_date"], m["last_commit_date"]
        self.header_band(metrics_s, "By the Numbers", f"Development timeline: {first} – {last}  (no formal sprint cadence)")

        sloc_total = m["sloc"]["grand_total"]
        kpis = [
            (str(m["issues_total"]), f"Issues ({m['issues_closed']} closed)", self.C["blue"]),
            (str(m["mrs_total"]), f"Merge Requests ({m['mrs_merged']} merged)", self.C["teal"]),
            (str(m["commits_total"]), "Commits", self.C["green"]),
            (f"~{sloc_total / 1000:.1f}K", "Lines of Code", self.C["yellow"]),
        ]
        tile_w, gap, tile_y, tile_h = Emu(2130000), Emu(60000), Emu(830000), Emu(1000000)
        for i, (num, label, color) in enumerate(kpis):
            x = Emu(140000) + i * (tile_w + gap)
            tile = self.add_rect(metrics_s, x, tile_y, tile_w, tile_h, RGBColor(0xF5, 0xF6, 0xF7))
            tile.line.color.rgb = color
            tile.line.width = Pt(1.25)
            self.add_rect(metrics_s, x, tile_y, tile_w, Emu(70000), color)
            self.add_text(metrics_s, x + Emu(60000), tile_y + Emu(160000), tile_w - Emu(120000), Emu(420000),
                          num, 30, color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            self.add_text(metrics_s, x + Emu(60000), tile_y + Emu(620000), tile_w - Emu(120000), Emu(340000),
                          label, 10, GRAY, align=PP_ALIGN.CENTER)

        chart_y, chart_h, chart_w, chart_x = Emu(1980000), Emu(2950000), Emu(5300000), Emu(140000)
        self.add_text(metrics_s, chart_x, chart_y, chart_w, Emu(240000), "Commit Velocity by Month", 13, self.C["blue"], bold=True)
        trend = m["monthly_commit_trend"]
        chart_data = CategoryChartData()
        chart_data.categories = list(trend.keys())
        chart_data.add_series("Commits", list(trend.values()))
        gframe = metrics_s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, chart_x, chart_y + Emu(260000),
                                            chart_w, chart_h - Emu(260000), chart_data)
        chart = gframe.chart
        chart.has_legend = False
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(10)
        plot.data_labels.font.color.rgb = GRAY
        plot.series[0].format.fill.solid()
        plot.series[0].format.fill.fore_color.rgb = self.C["blue"]
        chart.category_axis.tick_labels.font.size = Pt(10)
        chart.value_axis.visible = False
        chart.value_axis.has_major_gridlines = False

        donut_x, donut_w = Emu(5580000), Emu(2320000)
        self.add_text(metrics_s, donut_x, chart_y, donut_w, Emu(240000), "Issue Status", 13, self.C["blue"], bold=True)
        donut_data = CategoryChartData()
        donut_data.categories = ["Closed", "Open"]
        donut_data.add_series("Issues", (m["issues_closed"], m["issues_open"]))
        dframe = metrics_s.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, donut_x, chart_y + Emu(260000), donut_w, Emu(1500000), donut_data)
        dchart = dframe.chart
        dchart.has_legend = True
        dchart.legend.position = XL_LEGEND_POSITION.BOTTOM
        dchart.legend.include_in_layout = False
        dchart.legend.font.size = Pt(9)
        dpoints = dchart.plots[0].series[0].points
        dpoints[0].format.fill.solid(); dpoints[0].format.fill.fore_color.rgb = self.C["blue"]
        dpoints[1].format.fill.solid(); dpoints[1].format.fill.fore_color.rgb = self.C["lgray"]

        mr_y = chart_y + Emu(1900000)
        self.add_text(metrics_s, donut_x, mr_y, donut_w, Emu(240000), "MR Status", 13, self.C["blue"], bold=True)
        mr_data = CategoryChartData()
        mr_data.categories = ["Merged", "Closed", "Open"]
        mr_data.add_series("MRs", (m["mrs_merged"], m["mrs_closed"], m["mrs_open"]))
        mframe = metrics_s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, donut_x, mr_y + Emu(220000), donut_w, Emu(1050000), mr_data)
        mchart = mframe.chart
        mchart.has_legend = False
        mplot = mchart.plots[0]
        mplot.has_data_labels = True
        mplot.data_labels.font.size = Pt(9)
        mplot.data_labels.font.color.rgb = GRAY
        mplot.series[0].format.fill.solid()
        mplot.series[0].format.fill.fore_color.rgb = self.C["teal"]
        mchart.category_axis.tick_labels.font.size = Pt(9)
        mchart.value_axis.visible = False
        mchart.value_axis.has_major_gridlines = False

        self.add_rect(metrics_s, 0, self.SH - Emu(300000), self.SW, Emu(300000), RGBColor(0xF5, 0xF6, 0xF7))
        tests_lines = m["sloc"]["by_bucket_lines"].get("tests", 0)
        core_lines = m["sloc"]["by_bucket_lines"].get("mixins", 0)
        pct = (tests_lines / core_lines * 100) if core_lines else 0
        self.add_text(metrics_s, Emu(140000), self.SH - Emu(280000), Emu(8800000), Emu(260000),
                      f"Test suite (~{tests_lines/1000:.1f}K lines) covers ~{pct:.0f}% the size of the automation "
                      f"core it verifies (~{core_lines/1000:.1f}K lines)  |  Python {m['sloc']['python_total']/1000:.1f}K "
                      f"SLOC + Vue/JS frontend {m['sloc']['frontend_total']/1000:.1f}K SLOC",
                      9, GRAY, anchor=MSO_ANCHOR.MIDDLE)

    def build_capability_slides(self):
        for cap in self.capabilities:
            image_path = None
            if cap.get("image"):
                image_path = os.path.join(self.screenshots_dir, cap["image"])
            self.capability_slide(
                f"{cap['title']}  ({cap['count']} issues)", cap["blurb"], cap["bullets"],
                image_path=image_path, caption=cap.get("caption"),
            )

    # Technology stack: (category, [(technology, what it is, purpose), ...]). Pulled
    # from the repo's real manifests (requirements.txt, frontend/package.json,
    # Dockerfile, cdk/requirements.txt, helm/, .gitlab-ci.yml).
    TECH_STACK = [
        ("Languages & Runtimes", [
            ("Python 3.11", "General-purpose programming language; the project's primary runtime.",
             "Powers the automation core, FastAPI server, AWS CDK app, and diagram generation."),
            ("JavaScript (ES2022)", "Browser scripting language.",
             "Implements the Vue single-page web UI and its interactivity."),
            ("Vue SFC / HTML / CSS", "Component markup and styling.",
             "Structure and dark/light theming of the web UI."),
            ("Bash", "Unix shell scripting.",
             "Deploy-validate loops and the local fetch → render → publish pipeline."),
            ("YAML", "Declarative configuration format.",
             "Capabilities config, GitLab CI, Helm values, and CDK context."),
        ]),
        ("Automation Core (Python)", [
            ("python-gitlab", "GitLab API client (GraphQL + REST).",
             "Drives the Epic → Feature → Issue hierarchy, labels, and wiki against GitLab."),
            ("pandas", "DataFrame / data-analysis library.",
             "Aggregates issue and MR data for the portfolio reports."),
            ("boto3", "AWS SDK for Python.",
             "Reads SSM config and talks to AWS services at runtime."),
            ("lorem", "Latin placeholder-text generator.",
             "Creates realistic lorem test data (epics and issues)."),
            ("python-dateutil", "Date/time parsing utilities.",
             "Normalizes GitLab timestamps for the flow metrics."),
            ("markdown", "Markdown → HTML renderer.",
             "Publishes generated report pages to the GitLab Wiki."),
            ("requests / httpx", "Synchronous and async HTTP clients.",
             "Auxiliary API calls and service health checks."),
        ]),
        ("Web Server & Frontend", [
            ("FastAPI", "Async Python web framework.",
             "REST + WebSocket job runner exposing the shared tool registry."),
            ("Uvicorn", "ASGI application server.",
             "Serves the FastAPI app inside the container."),
            ("websockets / python-multipart", "WebSocket protocol + multipart parsing.",
             "Streams live job logs to the browser; handles CSV/JSON upload."),
            ("Vue 3", "Reactive UI framework.",
             "The job-picker web UI with parameterized dialogs and log viewer."),
            ("Vue Router", "Single-page-app router for Vue.",
             "Client-side navigation between UI views."),
            ("Vite", "Frontend build tool and dev server.",
             "Bundles the Vue app; output is overlaid into the container image."),
        ]),
        ("Reporting & Visualization", [
            ("Plotly", "Interactive charting library.",
             "WSJF / Risk / Flow charts in the Quarto site and notebooks."),
            ("Quarto", "Scientific static-site publisher.",
             "Renders the report site, published via GitLab Pages."),
            ("Marimo", "Reactive Python notebooks (WASM).",
             "Client-side interactive report notebooks, no server round-trip."),
            ("Jupyter / nbformat", "Notebook ecosystem and file format.",
             "Notebook tooling underlying report authoring."),
            ("Diagrams + Graphviz", "Diagram-as-code library + graph layout engine.",
             "Generates the ECS/EKS architecture diagrams at image-build time."),
            ("Pillow", "Python imaging library.",
             "Screenshot processing and image handling for the deck pipeline."),
        ]),
        ("Infrastructure & DevOps", [
            ("Docker", "Multi-stage container build and runtime.",
             "One ARM64 image for the single-box, ECS, and EKS deployments."),
            ("AWS CDK", "Infrastructure-as-code in Python (aws-cdk-lib, constructs).",
             "Defines the ECS (Fargate) and EKS stacks."),
            ("Helm", "Kubernetes package manager.",
             "Chart for the EKS path — deployment, service, ingress, PV/PVC, SA."),
            ("AWS (ECS, EKS, ALB, CloudFront, ECR, EFS, SSM, EventBridge, EC2)", "Cloud platform services.",
             "Compute, load balancing, CDN, registry, storage, config, scheduling."),
            ("Caddy", "Auto-TLS reverse proxy.",
             "Fronts the single-box EC2 deployment with automatic HTTPS."),
            ("Amazon Managed Grafana", "Managed observability dashboards (optional).",
             "Optional ops dashboards, toggled per deployment and off by default."),
        ]),
        ("Testing & CI/CD", [
            ("pytest / pytest-mock", "Python test framework and mocking.",
             "Unit / integration / infra suite (markers) run on every push."),
            ("Playwright", "Browser automation and E2E testing.",
             "Frontend end-to-end tests and deck screenshot capture."),
            ("GitLab CI/CD", "Pipeline automation.",
             "Runs pytest on every push; publishes the Quarto site to Pages."),
        ]),
    ]

    def build_tech_stack(self):
        """Section divider + a paginated three-column table (Technology / What it
        is / Purpose) grouped by category, with category banner rows and zebra
        striping. Row heights grow with wrapped text; content flows onto new
        slides (header + column header repeated) whenever a row won't fit."""
        divider = self.new_slide(self.DIVIDER1)
        divider.placeholders[0].text_frame.paragraphs[0].text = (
            "Technology Stack\nLanguages, Libraries, Tools & Infrastructure")

        margin = Emu(180000)
        content_w = self.SW - 2 * margin
        top = Emu(830000)
        bottom_limit = self.SH - Emu(130000)
        pad = Emu(70000)
        line_h = Emu(155000)
        char_w = 58000  # rough EMU per char at 9pt, for wrap-line estimation
        body_color = RGBColor(0x2A, 0x2E, 0x32)

        cols = [
            ("Technology",  Emu(1950000)),
            ("What it is",  Emu(3417000)),
            ("Purpose",     Emu(3417000)),
        ]

        def cell_x(i):
            return margin + sum(c[1] for c in cols[:i])

        def est_lines(text, w):
            cpl = max(1, int((w - 2 * pad) / char_w))
            return max(1, -(-len(text) // cpl))  # ceil

        state = {"slide": None, "y": None}

        def start_page():
            s = self.new_slide()
            self.header_band(s, "Technology Stack",
                             "What each language, library, and tool is — and why it's used")
            self.add_rect(s, margin, top, content_w, Emu(300000), self.C["blue"])
            for i, (label, w) in enumerate(cols):
                self.add_text(s, cell_x(i) + pad, top, w - 2 * pad, Emu(300000),
                              label, 10.5, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
            state["slide"] = s
            state["y"] = top + Emu(300000)

        start_page()
        stripe = 0
        for category, items in self.TECH_STACK:
            cat_h = Emu(300000)
            if state["y"] + cat_h > bottom_limit:
                start_page()
            # Category banner row (solid blue bar, white bold label).
            self.add_rect(state["slide"], margin, state["y"], content_w, cat_h, self.C["blue"])
            self.add_text(state["slide"], margin + pad, state["y"], content_w - 2 * pad, cat_h,
                          category, 11, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
            state["y"] += cat_h
            stripe = 0

            for name, what, purpose in items:
                lines = max(est_lines(name, cols[0][1]), est_lines(what, cols[1][1]),
                            est_lines(purpose, cols[2][1]))
                row_h = Emu(max(300000, lines * int(line_h) + 120000))
                if state["y"] + row_h > bottom_limit:
                    start_page()
                    stripe = 0
                if stripe % 2 == 0:
                    self.add_rect(state["slide"], margin, state["y"], content_w, row_h, WHITE)
                else:
                    band = self.add_rect(state["slide"], margin, state["y"], content_w, row_h, self.C["blue"])
                    self.set_fill_opacity(band, 12)
                self.add_text(state["slide"], cell_x(0) + pad, state["y"] + Emu(50000),
                              cols[0][1] - 2 * pad, row_h, name, 9, self.C["blue"], bold=True)
                self.add_text(state["slide"], cell_x(1) + pad, state["y"] + Emu(50000),
                              cols[1][1] - 2 * pad, row_h, what, 9, body_color)
                self.add_text(state["slide"], cell_x(2) + pad, state["y"] + Emu(50000),
                              cols[2][1] - 2 * pad, row_h, purpose, 9, body_color)
                state["y"] += row_h
                stripe += 1

        n_items = sum(len(items) for _, items in self.TECH_STACK)
        print(f"  tech stack: {n_items} technologies across {len(self.TECH_STACK)} categories")

    def build_issues_table(self):
        """Full backlog as a paginated, zebra-striped table — modelled on the
        FMS sprint-review "Sprint Issues" slides (JIRA ID / Summary / Assignee /
        Status columns, banded alternating rows, split across N slides with the
        header repeated). Every issue #1..max gets a row; nothing is capped."""
        issues = fetch_issues()
        total = len(issues)

        margin = Emu(180000)
        content_w = self.SW - 2 * margin
        top = Emu(830000)
        bottom_margin = Emu(140000)
        col_hdr_h = Emu(300000)
        row_h = Emu(250000)
        avail_h = self.SH - top - bottom_margin
        rows_per_page = max(1, int((avail_h - col_hdr_h) // row_h))
        pages = (total + rows_per_page - 1) // rows_per_page

        # (label, width EMU, key, align) — Title is the wide column, mirroring
        # the FMS "Summary" column. Widths sum to content_w.
        cols = [
            ("#",        Emu(620000),  "iid",      PP_ALIGN.CENTER),
            ("Title",    Emu(4744000), "title",    PP_ALIGN.LEFT),
            ("Type",     Emu(900000),  "type",     PP_ALIGN.CENTER),
            ("Assignee", Emu(1560000), "assignee", PP_ALIGN.LEFT),
            ("Status",   Emu(960000),  "status",   PP_ALIGN.CENTER),
        ]
        pad = Emu(70000)
        body_color = RGBColor(0x2A, 0x2E, 0x32)

        def cell_x(col_idx):
            return margin + sum(c[1] for c in cols[:col_idx])

        rendered = 0
        for page in range(pages):
            chunk = issues[page * rows_per_page:(page + 1) * rows_per_page]
            s = self.new_slide()
            self.header_band(
                s, "Issues",
                f"All {total} issues (#{issues[0]['iid']}–#{issues[-1]['iid']})  ·  "
                f"page {page + 1} of {pages}",
            )

            # Column-header row: solid blue bar, white bold labels.
            self.add_rect(s, margin, top, content_w, col_hdr_h, self.C["blue"])
            for i, (label, w, _key, align) in enumerate(cols):
                self.add_text(s, cell_x(i) + pad, top, w - 2 * pad, col_hdr_h,
                              label, 10.5, GRAY, bold=True, align=align,
                              anchor=MSO_ANCHOR.MIDDLE)

            # Data rows: zebra striping — white for even rows, a low-opacity
            # SAIC-teal tint for odd rows (distinct fill RGBs per the FMS banding).
            for r, issue in enumerate(chunk):
                y = top + col_hdr_h + r * row_h
                if r % 2 == 0:
                    self.add_rect(s, margin, y, content_w, row_h, WHITE)
                else:
                    band = self.add_rect(s, margin, y, content_w, row_h, self.C["blue"])
                    self.set_fill_opacity(band, 14)

                closed = issue["state"] == "closed"
                status_txt = "Closed" if closed else "Open"
                status_color = self.C["green"] if closed else self.C["blue"]
                values = {
                    "iid": f"#{issue['iid']}",
                    "title": (issue["title"][:86] + "…") if len(issue["title"]) > 87 else issue["title"],
                    "type": issue["type"].capitalize() if issue["type"] else "Issue",
                    "assignee": "Jamie Powers" if issue["assignee"] in ("", "beelzabub") else issue["assignee"],
                    "status": status_txt,
                }
                for i, (_label, w, key, align) in enumerate(cols):
                    color = status_color if key == "status" else body_color
                    self.add_text(s, cell_x(i) + pad, y, w - 2 * pad, row_h,
                                  values[key], 9, color, bold=(key == "status"),
                                  align=align, anchor=MSO_ANCHOR.MIDDLE, wrap=False)
                rendered += 1

        print(f"  issues table: rendered {rendered} rows across {pages} slides "
              f"({rows_per_page} rows/page) — total issues {total}")
        if rendered != total:
            print(f"  WARNING: rendered {rendered} != total {total} — some issues missing!")

    def build_wrapup(self):
        m = self.metrics
        wrap = self.new_slide()
        self.header_band(wrap, "Wrap-Up & Next Steps", None)
        self.add_bullets(wrap, Emu(220000), Emu(950000), self.SW - Emu(440000), Emu(2800000), [
            f"{len(self.capabilities)} capability areas, {m['issues_total']} issues, {m['mrs_total']} MRs, "
            f"~{m['sloc']['grand_total']/1000:.1f}K lines of code, built {m['first_commit_date']} – {m['last_commit_date']}.",
            "Three deployment paths (single-box / ECS / EKS) sharing one CDK project and one Docker image.",
            "CLI and web UI are two front ends over the same tool registry — same commands, different guardrails.",
            "Full UI and report reference follows in the Appendix.",
        ], 14, RGBColor(0x2A, 0x2E, 0x32), space_after=14)

    def build_appendix(self):
        appendix_div = self.new_slide(self.DIVIDER1)
        appendix_div.placeholders[0].text_frame.paragraphs[0].text = "Appendix\nFull UI & Report Reference"

        for shot in self.shots.get("ui_shots", []):
            for variant, dark in (("dark", True), ("light", False)):
                fname = f"{shot['out']}_{variant}.png"
                path = os.path.join(self.screenshots_dir, fname)
                if os.path.exists(path):
                    self.full_bleed_image_slide(f"{shot['title']} ({variant.capitalize()})", path, dark=dark)

        for shot in self.shots.get("live_run_shots", []):
            for suffix, label in (("01-before-launch", "Before Launch"),
                                   ("02-running", "Running (streaming log)"),
                                   ("03-completed", "Completed Output")):
                fname = f"{shot['out']}-{suffix}.png"
                path = os.path.join(self.screenshots_dir, fname)
                if os.path.exists(path):
                    self.full_bleed_image_slide(f"{shot['title']}: {label}", path, dark=True)

        for shot in self.shots.get("quarto_shots", []):
            path = os.path.join(self.screenshots_dir, "reports_quarto", f"{shot['out']}.png")
            if os.path.exists(path):
                self.full_bleed_image_slide(shot["title"], path, dark=False)

    def build(self):
        self.build_cover()
        self.build_agenda()
        self.build_chrome_slides()
        self.build_tech_stack()
        self.build_metrics_slide()
        self.build_issues_table()
        self.build_capability_slides()
        self.build_wrapup()
        self.build_appendix()
        return self.prs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-s3-path", default=os.environ.get("DECK_TEMPLATE_S3", DEFAULT_TEMPLATE_S3))
    ap.add_argument("--template-cache-dir", default=os.path.join(HERE, ".template-cache"))
    ap.add_argument("--screenshots-dir", default=os.path.join(HERE, "screenshots"))
    ap.add_argument("--metrics", default=os.path.join(HERE, "metrics.json"))
    ap.add_argument("--capabilities", default=os.path.join(HERE, "capabilities.yaml"))
    ap.add_argument("--shots", default=os.path.join(HERE, "shots.yaml"))
    ap.add_argument("--out", default=os.path.join(HERE, "dist", "NCE-Safe-Simulator-Sprint-Review.pptx"))
    args = ap.parse_args()

    if not os.path.exists(args.metrics):
        raise SystemExit(f"{args.metrics} not found — run `python3 deck/fetch_metrics.py` first")
    if not os.path.isdir(args.screenshots_dir):
        raise SystemExit(f"{args.screenshots_dir} not found — run `python3 deck/capture_screenshots.py` first")

    template_path = ensure_template(args.template_s3_path, args.template_cache_dir)

    with open(args.metrics) as f:
        metrics = json.load(f)
    with open(args.capabilities) as f:
        capabilities = yaml.safe_load(f)["capabilities"]
    with open(args.shots) as f:
        shots = yaml.safe_load(f)

    builder = DeckBuilder(template_path, args.screenshots_dir, metrics, capabilities, shots)
    prs = builder.build()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    prs.save(args.out)
    print(f"Saved {args.out} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
