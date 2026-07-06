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
import glob
import json
import os
import subprocess
from datetime import datetime

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
        """Each item is a string, or a list of (text, italic) segments for
        mixed formatting within one bullet (e.g. italicized dates)."""
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(space_after)
            segs = [(item, False)] if isinstance(item, str) else item
            for j, (text, italic) in enumerate(segs):
                r = p.add_run()
                r.text = f"▪  {text}" if j == 0 else text
                r.font.size = Pt(size)
                r.font.italic = italic
                r.font.color.rgb = color
                r.font.name = FONT
        return tb

    def header_band(self, slide, title, subtitle=None):
        self.add_rect(slide, 0, 0, self.SW, Emu(685800), self.C["blue"])
        # Auto-shrink long titles so they stay on one line inside the band.
        tsize = 22 if len(title) <= 46 else (18 if len(title) <= 60 else 15)
        self.add_text(slide, Emu(320000), Emu(90000), self.SW - Emu(640000), Emu(360000), title, tsize,
                      WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE if not subtitle else MSO_ANCHOR.TOP, wrap=False)
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

    def _resolve_asset(self, rel):
        """Resolve a capability image path: first under the screenshots dir
        (captures / diagrams / quarto), then repo-relative (so capabilities can
        point at curated media/ imagery). Returns the first existing path, or the
        screenshots-relative path unchanged so the caller's exists() check fails
        cleanly."""
        p = os.path.join(self.screenshots_dir, rel)
        if os.path.exists(p):
            return p
        p2 = os.path.join(REPO_ROOT, rel)
        return p2 if os.path.exists(p2) else p

    def _ensure_version_closeup(self):
        """Crop + upscale the deployed-version badge from the home screenshot into
        a legible chip, so the web-frontend capability slide can call out the build
        string the UI stamps (issue #186). Anchored to the badge's bottom-right
        position; returns the path, or None if the source shot is missing."""
        src = os.path.join(self.screenshots_dir, "00-home_dark.png")
        out = os.path.join(self.screenshots_dir, "00-home-version-closeup.png")
        if not os.path.exists(src):
            return None
        try:
            with Image.open(src) as im:
                W, H = im.size
                crop = im.crop((W - 96, H - 33, W - 6, H - 8))
                crop = crop.resize((crop.width * 6, crop.height * 6), Image.LANCZOS)
                crop.save(out)
            return out
        except Exception as e:
            print(f"  warn: version closeup skipped ({e})")
            return None

    def _add_image_inset(self, slide, inset, img_x, img_y, img_w, img_h):
        """A magnifier-style closeup chip in the bottom-right of a slide's main
        image, with a small label above it — calls out a detail that's tiny at
        slide scale (e.g. the UI's deployed-version badge)."""
        path, label = inset
        if not path or not os.path.exists(path):
            return
        with Image.open(path) as im:
            aw, ah = im.size
        chip_w = Emu(1750000)
        chip_h = int(chip_w * ah / aw)
        cx = img_x + img_w - chip_w - Emu(40000)
        cy = img_y + img_h - chip_h - Emu(60000)
        card = self.add_rect(slide, cx - Emu(36000), cy - Emu(36000),
                              chip_w + Emu(72000), chip_h + Emu(72000), WHITE)
        card.line.color.rgb = self.C["blue"]
        card.line.width = Pt(1.25)
        self.add_picture_contain(slide, path, cx, cy, chip_w, chip_h)
        if label:
            self.add_text(slide, cx - Emu(36000), cy - Emu(250000), chip_w + Emu(72000), Emu(220000),
                          label, 9, self.C["blue"], bold=True, align=PP_ALIGN.CENTER)

    def capability_slide(self, title, blurb, bullets, image_path=None, caption=None, inset=None):
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
            if inset:
                self._add_image_inset(s, inset, img_x, body_y, img_w, img_h)
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

    def report_segments_slide(self, title, seg_paths):
        """A report page too long to read at full-bleed, shown instead as a few
        readable crops taken down the page (capture_screenshots.py) and laid out
        as a centered, equal-height row of cards — like columns of the document
        read left-to-right (issue #144)."""
        s = self.new_slide()
        self.add_rect(s, 0, 0, self.SW, self.SH, RGBColor(0xF2, 0xF3, 0xF4))
        self.add_rect(s, 0, 0, self.SW, Emu(430000), self.C["blue"])
        self.add_text(s, Emu(220000), Emu(70000), self.SW - Emu(440000), Emu(300000),
                       f"{title}  —  read left → right", 14, WHITE, bold=True,
                       anchor=MSO_ANCHOR.MIDDLE)
        self.add_rect(s, 0, Emu(430000), self.SW, Emu(18000), self.C["yellow"])

        n = len(seg_paths)
        gap = Emu(110000)
        area_x, area_y = Emu(150000), Emu(560000)
        area_w = self.SW - 2 * area_x
        area_h = self.SH - area_y - Emu(110000)

        # Size every crop to the same height (fill the band); if the resulting
        # row is wider than the area, scale all of them down uniformly to fit —
        # so the crops stay the same height and read as aligned columns.
        ratios = []
        for p in seg_paths:
            with Image.open(p) as im:
                iw, ih = im.size
            ratios.append(iw / ih)
        h = area_h
        widths = [int(h * r) for r in ratios]
        row_w = sum(widths) + gap * (n - 1)
        if row_w > area_w:
            scale = (area_w - gap * (n - 1)) / sum(widths)
            widths = [int(w * scale) for w in widths]
            h = int(h * scale)
            row_w = sum(widths) + gap * (n - 1)

        x = area_x + (area_w - row_w) // 2
        y = area_y + (area_h - h) // 2
        for p, w in zip(seg_paths, widths):
            card = self.add_rect(s, x - Emu(14000), y - Emu(14000),
                                 w + Emu(28000), h + Emu(28000), WHITE)
            card.line.color.rgb = RGBColor(0xD5, 0xD9, 0xDD)
            card.line.width = Pt(0.75)
            # box matches the crop's ratio, so contain fills it with no letterbox
            self.add_picture_contain(s, p, x, y, w, h)
            x += w + gap
        return s

    def remove_slide(self, index):
        xml_slides = self.prs.slides._sldIdLst
        slide_ids = list(xml_slides)
        doomed = slide_ids[index]
        self.prs.part.drop_rel(doomed.get(qn("r:id")))
        xml_slides.remove(doomed)

    # -- slide sections ---------------------------------------------------
    def _add_oval(self, slide, x, y, w, h, color):
        shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, w, h)
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.fill.background()
        shp.shadow.inherit = False
        return shp

    def _cover_timeline(self, slide, x, y, w, first_iso, last_iso):
        """Compact development-timeline graphic for the cover: an accent line
        with end dots, the first/last commit dates, and the elapsed span — a
        visual replacement for the old plain "Development window:" text line."""
        d0 = datetime.strptime(first_iso, "%Y-%m-%d")
        d1 = datetime.strptime(last_iso, "%Y-%m-%d")
        weeks = max(1, round((d1 - d0).days / 7))
        fmt = lambda d: f"{d.strftime('%b')} {d.day}, {d.year}"
        accent = self.C["blue"]                 # cyan — reads bright on the dark cover
        light = RGBColor(0xEA, 0xED, 0xF0)
        dim = RGBColor(0xA8, 0xB0, 0xB8)

        self.add_text(slide, x, y, Emu(3000000), Emu(200000), "DEVELOPMENT TIMELINE", 9, accent, bold=True)
        self.add_text(slide, x, y, w, Emu(200000), f"~{weeks} weeks", 10.5, light, bold=True, align=PP_ALIGN.RIGHT)

        line_y = y + Emu(330000)
        line_h = Emu(24000)
        self.add_rect(slide, x, line_y, w, line_h, accent)
        dia = Emu(104000)
        dot_y = line_y + line_h // 2 - dia // 2
        self._add_oval(slide, x, dot_y, dia, dia, light)
        self._add_oval(slide, x + w - dia, dot_y, dia, dia, light)

        lbl_y = line_y + Emu(150000)
        self.add_text(slide, x, lbl_y, Emu(2600000), Emu(280000), fmt(d0), 12.5, light, bold=True)
        self.add_text(slide, x + w - Emu(2600000), lbl_y, Emu(2600000), Emu(280000), fmt(d1), 12.5, light,
                      bold=True, align=PP_ALIGN.RIGHT)
        self.add_text(slide, x, lbl_y + Emu(300000), Emu(2600000), Emu(220000), "first commit", 8.5, dim)
        self.add_text(slide, x + w - Emu(2600000), lbl_y + Emu(300000), Emu(2600000), Emu(220000),
                      "latest commit", 8.5, dim, align=PP_ALIGN.RIGHT)

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

        # Title stays in the template's cover placeholder (large Gill Sans MT).
        # The light-gray color is the "Background 1, darker 25%" the user set.
        def cover_color(run):
            run.font.color.theme_color = MSO_THEME_COLOR.BACKGROUND_1
            run.font.color.brightness = -0.25

        cover.placeholders[0].text_frame.paragraphs[0].runs[0].text = "NCE Safe Simulator"
        cover_color(cover.placeholders[0].text_frame.paragraphs[0].runs[0])

        # The template subtitle placeholder held a vague "Simulator Overview:"
        # line. Remove it entirely (an *emptied* placeholder renders PowerPoint's
        # dotted prompt box + the template's sample "Gill Sans MT" prompt text);
        # the tagline/blurb/timeline below are drawn as custom textboxes instead.
        body_ph = cover.placeholders[10]
        body_ph._element.getparent().remove(body_ph._element)

        left = Emu(340000)
        white_hi = RGBColor(0xF2, 0xF4, 0xF6)   # bright — the tagline stands out
        light = RGBColor(0xC8, 0xCC, 0xD0)
        self.add_text(cover, left, Emu(2560000), Emu(7000000), Emu(430000),
                      "SAFe portfolio automation for GitLab", 21, white_hi, bold=True)
        self.add_text(cover, left, Emu(3030000), Emu(6650000), Emu(760000),
                      "Generates realistic SAFe portfolios in GitLab — the full Epic / Feature / Issue "
                      "hierarchy — with WSJF, business-value, and risk reporting, driven from a CLI or a "
                      "Vue web UI.", 12.5, light, italic=True)

        m = self.metrics
        self._cover_timeline(cover, left, Emu(4020000), Emu(4360000),
                             m["first_commit_date"], m["last_commit_date"])

        # White emblem (not the navy one) now that the cover reads dark.
        nce_logo = os.path.join(REPO_ROOT, "frontend/src/assets/nce-logo-white.png")
        pmw_seal = os.path.join(REPO_ROOT, "frontend/src/assets/pmw-120-seal-transparent.png")
        if os.path.exists(nce_logo):
            cover.shapes.add_picture(nce_logo, Emu(320000), Emu(220000), height=Emu(500000))
        if os.path.exists(pmw_seal):
            cover.shapes.add_picture(pmw_seal, self.SW - Emu(900000), Emu(220000), height=Emu(650000))

        # Live-simulator QR, bottom-right, balancing the timeline on the left.
        self._add_cover_qr(cover)

    def _agenda_number(self, p, color):
        """Give an agenda paragraph a visible auto-number. The TOC layout numbers
        the list but colors the digits schemeClr bg1 (white) — invisible on the
        light agenda background — so override just the bullet color while keeping
        the arabic-period auto-numbering."""
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", "228600")
        pPr.set("indent", "-228600")
        for tag in ("a:buClr", "a:buFont", "a:buNone", "a:buAutoNum", "a:buChar"):
            for el in pPr.findall(qn(tag)):
                pPr.remove(el)
        buClr = pPr.makeelement(qn("a:buClr"), {})
        buClr.append(buClr.makeelement(qn("a:srgbClr"), {"val": str(color)}))
        pPr.append(buClr)
        pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": "+mj-lt"}))
        pPr.append(pPr.makeelement(qn("a:buAutoNum"), {"type": "arabicPeriod"}))

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
            self._agenda_number(p, RGBColor(0x00, 0x6B, 0xB5))

    def build_chrome_slides(self):
        s = os.path.join(self.screenshots_dir, "00-home_light.png")
        self.capability_slide(
            "Project Overview", "SAFe portfolio automation for GitLab",
            ["Manages the Epic → Capability/Feature → Issue hierarchy across a multi-group SAFe "
             "portfolio (Value Streams → ARTs → Teams) directly against the GitLab API.",
             "Generates realistic lorem test data, imports/exports epics & issues, and publishes a "
             "suite of portfolio-level reports (WSJF, Risk, Blocking, Capacity, Flow Metrics, Data Quality).",
             "Three-tier system: a Python automation core (GitLab REST v4 via python-gitlab, plus direct GraphQL calls), frontend by a FastAPI "
             "server, driving a Vue 3 web UI and a scriptable CLI — both call the same tool registry.",
             "Reports render to three surfaces: GitLab Wiki (markdown), a Quarto static site, and Marimo "
             "WASM interactive notebooks."],
            image_path=s, caption="Web UI — job picker",
        )
        self._build_architecture_slide()
        self._build_dod_architecture_slides()
        self._build_deployment_slide()
        self._build_make_slide()
        self._build_cli_vs_ui_slide()
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
             "Dedicated security-hygiene pass: after a GitLab token leaked into a commit, the entire "
             "repository history was rewritten so no commit anywhere retains the token, and all secrets "
             "were moved to environment variables.",
             "Stack: Python (python-gitlab REST + GraphQL, boto3, FastAPI, pandas, Plotly), Vue 3, Quarto, "
             "Marimo, Docker, AWS CDK, Helm, optional Grafana."],
            image_path=os.path.join(self.screenshots_dir, "git-workflow-compact.png"),
            caption="The branch-per-issue loop — detailed on the next slide",
        )
        self._build_dev_workflow_slide()

    def _build_dev_workflow_slide(self):
        """Full-width git-graph of the actual development loop (issue → UI-created
        branch → Refs-#NNN commits → tests per push → MR review → merge to develop
        → develop CI publish/deploy), rendered by capture_git_workflow.py."""
        path = os.path.join(self.screenshots_dir, "git-workflow.png")
        if not os.path.exists(path):
            print("  warn: git-workflow.png missing (run deck/capture_git_workflow.py) — "
                  "skipping the Development Workflow slide")
            return
        s = self.new_slide()
        self.header_band(s, "Development Workflow",
                         "Every change takes the same path from issue to deploy")
        body_y = Emu(830000)
        self.add_picture_contain(s, path, Emu(180000), body_y,
                                 self.SW - Emu(360000), self.SH - body_y - Emu(220000))

    def _build_architecture_slide(self):
        arch = self.new_slide()
        self.header_band(arch, "Architecture", "Three-tier system, three reporting surfaces")
        tiers = [
            ("Python Automation Core", "NceGitLab.py + mixins/ — GitLab REST v4 via python-gitlab,\nplus GraphQL where REST falls short (work-item/epic weight, blocking, links)"),
            ("FastAPI Server", "REST + WebSocket job runner\nstreams live logs to the browser"),
            ("Vue 3 Web UI  /  CLI", "Same tool registry exposed both ways\n(job picker + streaming UI, or scripted CLI flags)"),
        ]
        tier_w, gap, start_x, tier_y, tier_h = Emu(2850000), Emu(90000), Emu(180000), Emu(1150000), Emu(1130000)
        for i, (t, desc) in enumerate(tiers):
            x = start_x + i * (tier_w + gap)
            box = self.add_rect(arch, x, tier_y, tier_w, tier_h, RGBColor(0xF5, 0xF6, 0xF7))
            box.line.color.rgb = self.C["blue"]
            box.line.width = Pt(1.25)
            self.add_rect(arch, x, tier_y, tier_w, Emu(60000), self.C["blue"])
            self.add_text(arch, x + Emu(80000), tier_y + Emu(130000), tier_w - Emu(160000), Emu(300000), t, 13, self.C["blue"], bold=True)
            self.add_text(arch, x + Emu(80000), tier_y + Emu(440000), tier_w - Emu(160000), Emu(660000), desc, 9, GRAY)
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

    def _build_make_slide(self):
        """Build & deploy automation — the two Makefiles (repo-root build pipeline
        and cdk/ deploy orchestration)."""
        s = self.new_slide()
        self.header_band(s, "Build & Deploy Automation",
                         "Two Makefiles: a repo-root build pipeline and a cdk/ deploy orchestrator")
        margin, gap = Emu(180000), Emu(160000)
        panel_w = (self.SW - 2 * margin - gap) // 2
        lx, rx = margin, margin + panel_w + gap
        head_y, body_y = Emu(820000), Emu(1150000)
        body_h = self.SH - body_y - Emu(160000)
        body_color = RGBColor(0x2A, 0x2E, 0x32)

        self.add_rect(s, lx, head_y, panel_w, Emu(260000), self.C["blue"])
        self.add_text(s, lx + Emu(80000), head_y, panel_w - Emu(160000), Emu(260000),
                      "Top-level  Makefile  — build & run", 12, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        self.add_bullets(s, lx + Emu(40000), body_y, panel_w - Emu(80000), body_h, [
            "make build — full pipeline: data → interactive → static.",
            "make data — NceGitLab.py --report all (fetch report data from GitLab).",
            "make interactive — export the Marimo WASM notebooks (build_interactive.py).",
            "make static — quarto render (build the Quarto report site).",
            "make serve — serve the built site locally on :4645.",
            "make deploy-local / redeploy — single-box EC2 bring-up (image + app + Caddy TLS), then hot-swap the app container.",
            "make deck-screenshots / deck — regenerate this sprint-review deck.",
        ], 10.5, body_color, space_after=7)

        self.add_rect(s, rx, head_y, panel_w, Emu(260000), self.C["green"])
        self.add_text(s, rx + Emu(80000), head_y, panel_w - Emu(160000), Emu(260000),
                      "cdk/Makefile  — deploy orchestration", 12, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        self.add_bullets(s, rx + Emu(40000), body_y, panel_w - Emu(80000), body_h, [
            "Setup (once): install, bootstrap, set-vpc, set-efs.",
            "ECS/Fargate: ecs-deploy, ecs-redeploy, ecs-logs, ecs-exec, ecs-destroy, ecs-full-(re)deploy.",
            "EKS/K8s: eks-deploy, eks-helm-install, eks-lb-controller, eks-cloudfront-deploy, eks-redeploy, eks-destroy.",
            "Diagrams: ecs-diagram, eks-diagram, dod-diagrams (regenerate architecture PNGs).",
            "Grafana: grafana-setup, ecs-/eks-grafana-deploy (Infinity plugin + dashboards).",
            "seed-config (config.json → SSM SecureString), ecr-push, audit.",
            "*-full-redeploy targets run unattended: teardown → deploy → validate.",
        ], 10.5, body_color, space_after=7)

    def _build_cli_vs_ui_slide(self):
        """CLI vs. UI — side-by-side: the CLI interactive menu and the UI dialog
        that generates the equivalent CLI command."""
        s = self.new_slide()
        self.header_band(s, "CLI vs. UI",
                         "Same tool registry, two front ends — every UI dialog builds its exact CLI command live")
        margin, gap = Emu(180000), Emu(160000)
        panel_w = (self.SW - 2 * margin - gap) // 2
        lx, rx = margin, margin + panel_w + gap
        label_y, img_y, img_h = Emu(820000), Emu(1150000), Emu(2820000)
        cap_y = img_y + img_h + Emu(30000)

        self.add_text(s, lx, label_y, panel_w, Emu(280000), "CLI — interactive numbered menu", 13,
                      self.C["blue"], bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        menu = os.path.join(self.screenshots_dir, "cli-interactive-menu.png")
        if os.path.exists(menu):
            self.add_picture_contain(s, menu, lx, img_y, panel_w, img_h)
        self.add_text(s, lx, cap_y, panel_w, Emu(220000),
                      "NceGitLab.py — this menu, or scripted flags for CI", 9, GRAY,
                      align=PP_ALIGN.CENTER, italic=True)

        self.add_text(s, rx, label_y, panel_w, Emu(280000), "Web UI — guided dialog", 13,
                      self.C["blue"], bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        ui = os.path.join(self.screenshots_dir, "05-import-export-import-epics_light-cli-closeup.png")
        if not os.path.exists(ui):
            # #185 renders the equivalent command inside the dialog itself, so the
            # full dialog shot now carries it — fall back to that when no
            # hand-cropped closeup is present.
            ui = os.path.join(self.screenshots_dir, "05-import-export-import-epics_light.png")
        if os.path.exists(ui):
            self.add_picture_contain(s, ui, rx, img_y, panel_w, img_h)
        self.add_text(s, rx, cap_y, panel_w, Emu(220000),
                      "Import Epics dialog — the equivalent command, built live in-dialog with Copy", 9, GRAY,
                      align=PP_ALIGN.CENTER, italic=True)

        self.add_text(s, margin, self.SH - Emu(400000), self.SW - 2 * margin, Emu(320000),
                      "Both front ends call the same tool registry — the UI is a guided layer over the same "
                      "commands, adding confirmation gating, a live status panel, streaming logs, and the exact "
                      "CLI command built live inside every dialog to copy or script.",
                      11, RGBColor(0x2A, 0x2E, 0x32), align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    def _kpi_tiles(self, slide, m):
        sloc_total = m["sloc"]["grand_total"]
        kpis = [
            (str(m["issues_total"]), f"Issues ({m['issues_closed']} closed)", self.C["blue"]),
            (str(m["mrs_total"]), f"Merge Requests ({m['mrs_merged']} merged)", self.C["teal"]),
            (str(m["commits_total"]), "Commits", self.C["green"]),
            (f"~{sloc_total / 1000:.1f}K", "Lines of Code", self.C["yellow"]),
        ]
        tile_w, gap, tile_y, tile_h = Emu(2130000), Emu(60000), Emu(830000), Emu(980000)
        for i, (num, label, color) in enumerate(kpis):
            x = Emu(140000) + i * (tile_w + gap)
            tile = self.add_rect(slide, x, tile_y, tile_w, tile_h, RGBColor(0xF5, 0xF6, 0xF7))
            tile.line.color.rgb = color
            tile.line.width = Pt(1.25)
            self.add_rect(slide, x, tile_y, tile_w, Emu(70000), color)
            self.add_text(slide, x + Emu(60000), tile_y + Emu(150000), tile_w - Emu(120000), Emu(420000),
                          num, 30, color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
            self.add_text(slide, x + Emu(60000), tile_y + Emu(600000), tile_w - Emu(120000), Emu(340000),
                          label, 10, GRAY, align=PP_ALIGN.CENTER)

    def _footer_note(self, slide, text):
        self.add_rect(slide, 0, self.SH - Emu(300000), self.SW, Emu(300000), RGBColor(0xF5, 0xF6, 0xF7))
        self.add_text(slide, Emu(140000), self.SH - Emu(280000), Emu(8800000), Emu(260000),
                      text, 9, GRAY, anchor=MSO_ANCHOR.MIDDLE)

    def build_metrics_slide(self):
        """Two slides: (1) KPI tiles + commit velocity + SLOC-by-week growth,
        (2) issue-status donut and MR-status bar with value labels. Split from
        one crowded slide so every chart has room and actually renders."""
        m = self.metrics
        first, last = m["first_commit_date"], m["last_commit_date"]

        # ---- Slide 1: activity & code growth ----
        s1 = self.new_slide()
        self.header_band(s1, "By the Numbers", f"Development activity & code growth · {first} – {last}")
        self._kpi_tiles(s1, m)

        cy, ch = Emu(2020000), Emu(2360000)
        lx, lw = Emu(140000), Emu(4340000)
        self.add_text(s1, lx, cy, lw, Emu(240000), "Commit Velocity by Month", 13, self.C["blue"], bold=True)
        trend = m["monthly_commit_trend"]
        cd = CategoryChartData()
        cd.categories = list(trend.keys())
        cd.add_series("Commits", list(trend.values()))
        g = s1.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, lx, cy + Emu(280000), lw, ch, cd).chart
        g.has_legend = False
        gp = g.plots[0]
        gp.has_data_labels = True
        gp.data_labels.show_value = True
        gp.data_labels.font.size = Pt(10)
        gp.data_labels.font.color.rgb = GRAY
        gp.series[0].format.fill.solid()
        gp.series[0].format.fill.fore_color.rgb = self.C["blue"]
        g.category_axis.tick_labels.font.size = Pt(10)
        g.value_axis.visible = False
        g.value_axis.has_major_gridlines = False

        rx, rw = Emu(4660000), Emu(4340000)
        self.add_text(s1, rx, cy, rw, Emu(240000), "Source Lines of Code by Week", 13, self.C["blue"], bold=True)
        weekly = m.get("sloc_by_week") or {}
        if weekly:
            sd = CategoryChartData()
            sd.categories = list(weekly.keys())
            sd.add_series("SLOC", list(weekly.values()))
            sg = s1.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, rx, cy + Emu(280000), rw, ch, sd).chart
            sg.has_legend = False
            sser = sg.plots[0].series[0]
            sser.format.line.color.rgb = self.C["blue"]
            sser.format.line.width = Pt(2.25)
            sg.category_axis.tick_labels.font.size = Pt(8)
            sg.value_axis.tick_labels.font.size = Pt(9)
            sg.value_axis.has_major_gridlines = True
        else:
            self.add_text(s1, rx, cy + Emu(280000), rw, Emu(400000),
                          "(run fetch_metrics.py to populate weekly SLOC)", 10, GRAY, italic=True)

        tests_lines = m["sloc"]["by_bucket_lines"].get("tests", 0)
        core_lines = m["sloc"]["by_bucket_lines"].get("mixins", 0)
        pct = (tests_lines / core_lines * 100) if core_lines else 0
        self._footer_note(s1,
                          f"Test suite (~{tests_lines/1000:.1f}K lines) covers ~{pct:.0f}% the size of the automation "
                          f"core it verifies (~{core_lines/1000:.1f}K lines)  |  Python {m['sloc']['python_total']/1000:.1f}K "
                          f"SLOC + Vue/JS frontend {m['sloc']['frontend_total']/1000:.1f}K SLOC")

        # ---- Slide 2: issues & merge requests ----
        s2 = self.new_slide()
        self.header_band(s2, "By the Numbers", "Issues & merge requests")
        open_gray = RGBColor(0x9A, 0xA0, 0xA6)   # mid gray so white value labels stay legible

        dx, dw = Emu(360000), Emu(3960000)
        self.add_text(s2, dx, Emu(900000), dw, Emu(260000), "Issue Status", 14, self.C["blue"], bold=True)
        dd = CategoryChartData()
        dd.categories = ["Closed", "Open"]
        dd.add_series("Issues", (m["issues_closed"], m["issues_open"]))
        dchart = s2.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, dx, Emu(1220000), dw, Emu(3050000), dd).chart
        dchart.has_legend = True
        dchart.legend.position = XL_LEGEND_POSITION.BOTTOM
        dchart.legend.include_in_layout = False
        dchart.legend.font.size = Pt(11)
        dplot = dchart.plots[0]
        dplot.has_data_labels = True
        dlbl = dplot.data_labels
        dlbl.show_value = True
        dlbl.number_format = "0"
        dlbl.number_format_is_linked = False
        dlbl.font.size = Pt(13)
        dlbl.font.bold = True
        dlbl.font.color.rgb = WHITE
        dpts = dplot.series[0].points
        dpts[0].format.fill.solid(); dpts[0].format.fill.fore_color.rgb = self.C["blue"]
        dpts[1].format.fill.solid(); dpts[1].format.fill.fore_color.rgb = open_gray

        mx, mw = Emu(4760000), Emu(4180000)
        self.add_text(s2, mx, Emu(900000), mw, Emu(260000), "Merge Request Status", 14, self.C["blue"], bold=True)
        md = CategoryChartData()
        md.categories = ["Merged", "Closed", "Open"]
        md.add_series("MRs", (m["mrs_merged"], m["mrs_closed"], m["mrs_open"]))
        mchart = s2.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, mx, Emu(1220000), mw, Emu(3050000), md).chart
        mchart.has_legend = False
        mp = mchart.plots[0]
        mp.has_data_labels = True
        mp.data_labels.show_value = True
        mp.data_labels.font.size = Pt(12)
        mp.data_labels.font.bold = True
        mp.data_labels.font.color.rgb = GRAY
        mp.series[0].format.fill.solid()
        mp.series[0].format.fill.fore_color.rgb = self.C["blue"]
        mchart.category_axis.tick_labels.font.size = Pt(11)
        mchart.value_axis.visible = False
        mchart.value_axis.has_major_gridlines = False

        self._footer_note(s2,
                          f"{m['issues_closed']} of {m['issues_total']} issues closed ({m['issues_open']} open)  |  "
                          f"{m['mrs_merged']} of {m['mrs_total']} merge requests merged "
                          f"({m['mrs_open']} open, {m['mrs_closed']} closed)")

    def build_capability_slides(self):
        # Generate the version-badge closeup up front so any capability that
        # references it as an inset resolves to a real file.
        self._ensure_version_closeup()
        for cap in self.capabilities:
            image_path = self._resolve_asset(cap["image"]) if cap.get("image") else None
            inset = None
            if cap.get("inset_image"):
                ip = self._resolve_asset(cap["inset_image"])
                if os.path.exists(ip):
                    inset = (ip, cap.get("inset_label", ""))
            self.capability_slide(
                f"{cap['title']}  ({cap['count']} issues)", cap["blurb"], cap["bullets"],
                image_path=image_path, caption=cap.get("caption"), inset=inset,
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

    def _section_divider(self, title, subtitle=None):
        """Standard section-break slide using the template's Divider layout."""
        d = self.new_slide(self.DIVIDER1)
        text = f"{title}\n{subtitle}" if subtitle else title
        d.placeholders[0].text_frame.paragraphs[0].text = text
        return d

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
        # Reuse the single fetch from build() so this matches the metrics KPI;
        # fall back to a live fetch if called standalone.
        issues = getattr(self, "issues", None) or fetch_issues()
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

    def _qr_png(self):
        """Generate the live-simulator QR once and return its path, or None if
        segno isn't available. Encodes shots.yaml's app_url."""
        url = self.shots.get("app_url", "https://nce-safe-sim.com/app/")
        try:
            import segno
            qr_path = os.path.join(self.screenshots_dir, "qr-live-sim.png")
            segno.make(url, error="h").save(qr_path, scale=20, border=2,
                                            dark="#14181C", light="#FFFFFF")
            return qr_path
        except Exception as e:
            print(f"  warn: live-simulator QR skipped ({e})")
            return None

    def _qr_card(self, slide, qr_path, x, y, size):
        """Place the QR on a white contrast card at [x, y], square `size` — the
        white border keeps it scannable over dark backgrounds (e.g. the cover)."""
        card = self.add_rect(slide, x - Emu(90000), y - Emu(90000),
                              size + Emu(180000), size + Emu(180000), WHITE)
        card.line.color.rgb = RGBColor(0xD5, 0xD9, 0xDD)
        card.line.width = Pt(0.75)
        self.add_picture_contain(slide, qr_path, x, y, size, size)

    def _add_cover_qr(self, cover):
        """A compact 'scan to try it live' QR at the cover's bottom-right, sitting
        in the same vertical band as the development timeline on the left so the
        two balance across the foot of the cover."""
        qr_path = self._qr_png()
        if not qr_path:
            return
        accent = self.C["blue"]
        light = RGBColor(0xEA, 0xED, 0xF0)
        dim = RGBColor(0xA8, 0xB0, 0xB8)
        # Align the visible white card with the timeline's text band on the left
        # (_cover_timeline at y=4.02M): card top = top of the "DEVELOPMENT
        # TIMELINE" glyphs (add_text uses zero insets, so that's the box top),
        # card bottom = baseline of the 8.5pt "latest commit" label (box top
        # 4.80M + ~115k ascent; the label has no descenders). The card pads the
        # QR by 90k per side (_qr_card), so the image shrinks by that much.
        band_top = Emu(4020000)
        band_bottom = Emu(4915000)
        pad = Emu(90000)
        size = band_bottom - band_top - 2 * pad
        qr_x = self.SW - Emu(340000) - pad - size   # card right edge 340k off the slide edge
        qr_y = band_top + pad
        caption_w = Emu(2500000)
        caption_x = qr_x - pad - Emu(180000) - caption_w
        self.add_text(cover, caption_x, band_top + Emu(150000), caption_w, Emu(320000),
                      "Try it live", 14, accent, bold=True, align=PP_ALIGN.RIGHT)
        self.add_text(cover, caption_x, band_top + Emu(520000), caption_w, Emu(260000),
                      "scan to open on your phone →", 9.5, dim, italic=True,
                      align=PP_ALIGN.RIGHT)
        self._qr_card(cover, qr_path, qr_x, qr_y, size)

    def build_live_cta_slide(self):
        """Standalone 'try me live' call-to-action: one big centered QR to the
        running deployment, sitting between the wrap-up and the appendix."""
        s = self.new_slide()
        self.header_band(s, "Try Me — Live", "The running simulator, on your phone")
        url = self.shots.get("app_url", "https://nce-safe-sim.com/app/")
        display = url.split("://", 1)[-1].rstrip("/")
        size = Emu(2500000)
        qr_x = (self.SW - size) // 2
        qr_y = Emu(1250000)
        qr_path = self._qr_png()
        if qr_path:
            self._qr_card(s, qr_path, qr_x, qr_y, size)
        base_y = qr_y + size
        self.add_text(s, 0, base_y + Emu(240000), self.SW, Emu(360000),
                      "Scan to open the live NCE Safe Simulator", 18, self.C["blue"],
                      bold=True, align=PP_ALIGN.CENTER)
        self.add_text(s, 0, base_y + Emu(620000), self.SW, Emu(300000),
                      display, 14, RGBColor(0x2A, 0x2E, 0x32), bold=True,
                      align=PP_ALIGN.CENTER)
        self.add_text(s, 0, base_y + Emu(940000), self.SW, Emu(300000),
                      "Runs live on AWS — point your phone camera at the code to explore it.",
                      11.5, GRAY, italic=True, align=PP_ALIGN.CENTER)

    def build_wrapup(self):
        m = self.metrics
        wrap = self.new_slide()
        self.header_band(wrap, "Wrap-Up & Next Steps", None)
        self.add_bullets(wrap, Emu(220000), Emu(950000), Emu(8700000), Emu(4200000), [
            # The build window is the headline take-away — italicize the dates so
            # they stand apart from the counts around them.
            [(f"{len(self.capabilities)} capability areas, {m['issues_total']} issues, {m['mrs_total']} MRs, "
              f"~{m['sloc']['grand_total']/1000:.1f}K lines of code, built ", False),
             (f"{m['first_commit_date']} – {m['last_commit_date']}", True),
             (".", False)],
            "Three deployment paths (single-box / ECS / EKS) sharing one CDK project and one Docker image.",
            "CLI and web UI are two front ends over the same tool registry — same commands, different guardrails.",
            "Full UI and report reference follows in the Appendix.",
        ], 14, RGBColor(0x2A, 0x2E, 0x32), space_after=14)
        # The live-simulator QR now lives on the cover and its own CTA slide
        # (build_live_cta_slide), not here — it overflowed this two-column layout.

    def build_appendix(self):
        appendix_div = self.new_slide(self.DIVIDER1)
        appendix_div.placeholders[0].text_frame.paragraphs[0].text = "Appendix\nFull UI & Report Reference"

        # Grouped by theme, not by tool: all the dark-theme captures first, then
        # all the light-theme ones — so the two never alternate on adjacent pages.

        # ── Dark group: login front door + every UI dialog (dark) + the live run.
        # (No "Appendix —" prefix: the appendix divider immediately precedes these.)
        self._section_divider("Dark Theme", "Login, UI dialogs, and the live job run")
        for shot in self.shots.get("login_shots", []):
            path = os.path.join(self.screenshots_dir, f"{shot['out']}.png")
            if os.path.exists(path):
                self.full_bleed_image_slide(shot["title"], path, dark=True)

        for shot in self.shots.get("ui_shots", []):
            path = os.path.join(self.screenshots_dir, f"{shot['out']}_dark.png")
            if os.path.exists(path):
                self.full_bleed_image_slide(f"{shot['title']} (Dark)", path, dark=True)

        for shot in self.shots.get("live_run_shots", []):
            for suffix, label in (("01-before-launch", "Before Launch"),
                                   ("02-running", "Running (streaming log)"),
                                   ("03-completed", "Completed Output")):
                fname = f"{shot['out']}-{suffix}.png"
                path = os.path.join(self.screenshots_dir, fname)
                if os.path.exists(path):
                    self.full_bleed_image_slide(f"{shot['title']}: {label}", path, dark=True)

        # ── Light group: every UI dialog (light) + the Quarto report pages.
        self._section_divider("Light Theme", "The same UI dialogs in light")
        for shot in self.shots.get("ui_shots", []):
            path = os.path.join(self.screenshots_dir, f"{shot['out']}_light.png")
            if os.path.exists(path):
                self.full_bleed_image_slide(f"{shot['title']} (Light)", path, dark=False)

        # ── Quarto group: the published report site gets its own section.
        self._section_divider("Quarto Reports", "The published report site, page by page")
        for shot in self.shots.get("quarto_shots", []):
            base = os.path.join(self.screenshots_dir, "reports_quarto", shot["out"])
            segs = sorted(glob.glob(f"{base}__seg*.png"),
                          key=lambda p: int(p.rsplit("__seg", 1)[1].split(".")[0]))
            if segs:
                # Long report page: readable crops laid out side by side.
                self.report_segments_slide(shot["title"], segs)
            elif os.path.exists(f"{base}.png"):
                # Short page: the single full-page image reads fine full-bleed.
                self.full_bleed_image_slide(shot["title"], f"{base}.png", dark=False)

    def build(self):
        # Single-source the issue list so the "By the Numbers" KPI and the
        # Issues table can never disagree: fetch once here and reconcile the
        # metrics counts, since metrics.json can be staler than a live fetch.
        self.issues = fetch_issues()
        self.metrics["issues_total"] = len(self.issues)
        self.metrics["issues_closed"] = sum(1 for i in self.issues if i["state"] == "closed")
        self.metrics["issues_open"] = self.metrics["issues_total"] - self.metrics["issues_closed"]

        self.build_cover()
        self.build_agenda()
        self.build_chrome_slides()
        self.build_tech_stack()
        self._section_divider("By the Numbers", "Project Metrics")
        self.build_metrics_slide()
        self._section_divider("Issues", "Full Backlog — every issue by number")
        self.build_issues_table()
        self._section_divider("Capability Areas", "The same work, grouped by capability area")
        self.build_capability_slides()
        self.build_wrapup()
        self.build_live_cta_slide()
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
