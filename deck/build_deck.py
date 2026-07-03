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
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
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
        cover.placeholders[0].text_frame.paragraphs[0].runs[0].text = "NCE Safe Simulator"
        body_tf = cover.placeholders[10].text_frame
        m = self.metrics
        body_tf.paragraphs[0].runs[0].text = "Sprint Review — SAFe GitLab Portfolio Tooling"
        if len(body_tf.paragraphs) > 1 and body_tf.paragraphs[1].runs:
            body_tf.paragraphs[1].runs[0].text = f"Development window: {m['first_commit_date']} – {m['last_commit_date']}"
        nce_logo = os.path.join(REPO_ROOT, "frontend/src/assets/nce-logo-navy.png")
        pmw_seal = os.path.join(REPO_ROOT, "frontend/src/assets/pmw-120-seal.png")
        if os.path.exists(nce_logo):
            cover.shapes.add_picture(nce_logo, Emu(320000), Emu(220000), height=Emu(500000))
        if os.path.exists(pmw_seal):
            cover.shapes.add_picture(pmw_seal, self.SW - Emu(900000), Emu(220000), height=Emu(650000))

    def build_agenda(self):
        agenda = self.new_slide(self.TOC)
        agenda.placeholders[0].text_frame.paragraphs[0].text = "Agenda"
        items = ["Project Overview", "Architecture", "Deployment Methods", "CLI vs. UI",
                 "Development Process & Tools", "By the Numbers — Metrics",
                 f"Capability Areas ({len(self.capabilities)})",
                 "Appendix — Full UI & Report Reference"]
        tf = agenda.placeholders[1].text_frame
        tf.clear()
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = item

    def build_chrome_slides(self):
        s = os.path.join(self.screenshots_dir, "00-home_dark.png")
        self.capability_slide(
            "Project Overview", "SAFe portfolio automation for GitLab",
            ["Manages the Epic → Capability/Feature → Issue hierarchy across a multi-group SAFe "
             "portfolio (Value Streams → ARTs → Teams) directly against the GitLab API.",
             "Generates realistic lorem test data, imports/exports epics & issues, and publishes a "
             "suite of portfolio-level reports (WSJF, Risk, Blocking, Capacity, Flow Metrics, Data Quality).",
             "Three-tier system: a Python automation core (GraphQL against GitLab) fronted by a FastAPI "
             "server, driving a Vue 3 web UI and a scriptable CLI — both call the same tool registry.",
             "Reports render to three surfaces: GitLab Wiki (markdown), a Quarto static site, and Marimo "
             "WASM interactive notebooks."],
            image_path=s, caption="Web UI — job picker",
        )
        self._build_architecture_slide()
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
            image_path=os.path.join(self.screenshots_dir, "05-import-export-import-epics_dark.png"),
            caption="Import Epics dialog — form + generated CLI command",
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
            ("Python Automation Core", "NceGitLab.py + mixins/ — GraphQL calls to GitLab\n(groups, epics, issues, labels, wiki, reports)"),
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
                       "Architecture diagrams for ECS/EKS are generated on demand from live infra "
                       "(diagrams/ecs_architecture.py, diagrams/eks_architecture.py) — regenerate via "
                       "`make ecs-diagram` / `make eks-diagram`.", 8.5, GRAY, italic=True)

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
        self.build_metrics_slide()
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
