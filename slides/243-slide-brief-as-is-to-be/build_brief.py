#!/usr/bin/env python3
"""Build the #243 leadership brief: VM-based SDLC (As-Is) -> container-based SDLC (To-Be).

Self-contained: uses the repo's committed branding template
(deck/assets/template.pptx) for masters/layouts/theme, and the four reviewed
diagrams in ./diagrams/. It does NOT touch the weekly status-deck pipeline.

    python3 slides/243-slide-brief-as-is-to-be/build_brief.py

Output: ./dist/NCE-Safe-Simulator-SDLC-Modernization.pptx

House style is borrowed from deck/build_deck.py (Gill Sans MT, blue title band +
yellow rule, accent palette read from the template theme) so the brief matches
the status deck without importing its heavy, metrics-coupled machinery.
"""
import os

from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import Image
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TEMPLATE = os.path.join(REPO_ROOT, "deck", "assets", "template.pptx")
DIAGRAMS = os.path.join(HERE, "diagrams")
OUT = os.path.join(HERE, "dist", "Golden-Container-Image-SDLC-Modernization.pptx")

FONT = "Gill Sans MT"
MONO = "Consolas"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1F, 0x28, 0x33)
GRAY = RGBColor(0x64, 0x69, 0x6F)
CODE_BG = RGBColor(0x14, 0x18, 0x1C)
CODE_FG = RGBColor(0xE6, 0xED, 0xF3)
CODE_COMMENT = RGBColor(0xB4, 0xBE, 0xC8)


def load_theme_colors(prs):
    """Read accent colors from the template's own theme, same as build_deck.py."""
    theme_part = prs.slide_masters[0].part.part_related_by(
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    )
    scheme = etree.fromstring(theme_part.blob).find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme"
    )
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
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
        "lgray": vals.get("accent5", RGBColor(0xE1, 0xE1, 0xE1)),
        "yellow": vals.get("accent6", RGBColor(0xFD, 0xB9, 0x13)),
    }


class Brief:
    def __init__(self):
        self.prs = Presentation(TEMPLATE)
        self.SW = self.prs.slide_width
        self.SH = self.prs.slide_height
        self.C = load_theme_colors(self.prs)
        self.BLANK = self.prs.slide_layouts[7]  # '1_Blank'

    # -- primitives (mirrors deck/build_deck.py) --------------------------------
    def add_rect(self, slide, x, y, w, h, color):
        from pptx.enum.shapes import MSO_SHAPE
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

    def add_bullets(self, slide, x, y, w, h, items, size, color, space_after=8,
                    bullet="▪"):
        """items: str, or (label, body) for a bolded lead-in, or list of (text, bold)."""
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(space_after)
            if isinstance(item, str):
                segs = [(f"{bullet}  {item}", False)]
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], str):
                segs = [(f"{bullet}  {item[0]} ", True), (item[1], False)]
            else:
                segs = item
            for j, (text, bold) in enumerate(segs):
                r = p.add_run()
                r.text = text
                r.font.size = Pt(size)
                r.font.bold = bold
                r.font.color.rgb = color
                r.font.name = FONT
        return tb

    def header_band(self, slide, title, subtitle=None):
        self.add_rect(slide, 0, 0, self.SW, Emu(685800), self.C["blue"])
        tsize = 22 if len(title) <= 46 else (18 if len(title) <= 60 else 15)
        self.add_text(slide, Emu(320000), Emu(90000), self.SW - Emu(640000), Emu(360000),
                      title, tsize, WHITE, bold=True,
                      anchor=MSO_ANCHOR.MIDDLE if not subtitle else MSO_ANCHOR.TOP, wrap=False)
        if subtitle:
            self.add_text(slide, Emu(320000), Emu(430000), self.SW - Emu(640000),
                          Emu(220000), subtitle, 10.5, WHITE)
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

    def new_slide(self):
        return self.prs.slides.add_slide(self.BLANK)

    # -- slide templates --------------------------------------------------------
    def cover(self, kicker, title, subtitle, footer):
        s = self.new_slide()
        # Explicit colors — the template's theme slots resolve oddly (its
        # "yellow" is black, "lgray" is magenta), so set them directly here.
        AMBER = RGBColor(0xFD, 0xB9, 0x13)
        SOFT = RGBColor(0xE8, 0xF3, 0xF8)
        self.add_rect(s, 0, 0, self.SW, self.SH, self.C["blue"])
        self.add_rect(s, 0, Emu(2700000), self.SW, Emu(20000), AMBER)
        self.add_text(s, Emu(520000), Emu(1150000), self.SW - Emu(1040000), Emu(300000),
                      kicker, 13, AMBER, bold=True)
        self.add_text(s, Emu(520000), Emu(1500000), self.SW - Emu(1040000), Emu(1100000),
                      title, 34, WHITE, bold=True)
        self.add_text(s, Emu(520000), Emu(2820000), self.SW - Emu(1040000), Emu(600000),
                      subtitle, 15, WHITE)
        self.add_text(s, Emu(520000), self.SH - Emu(560000), self.SW - Emu(1040000),
                      Emu(360000), footer, 10.5, SOFT)
        return s

    def diagram_slide(self, title, subtitle, img, caption):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        top = Emu(820000)
        cap_h = Emu(430000)
        bmargin = Emu(230000)   # lift the caption a little off the bottom edge
        box_h = self.SH - top - cap_h - bmargin - Emu(60000)
        self.add_picture_contain(s, os.path.join(DIAGRAMS, img),
                                 Emu(240000), top, self.SW - Emu(480000), box_h)
        cy = self.SH - cap_h - bmargin
        bar_h = Emu(300000)
        self.add_rect(s, Emu(240000), cy + (cap_h - bar_h) // 2, Emu(70000), bar_h,
                      self.C["teal"])
        self.add_text(s, Emu(380000), cy, self.SW - Emu(620000), cap_h,
                      caption, 12, INK, anchor=MSO_ANCHOR.MIDDLE)
        return s

    def bullets_slide(self, title, subtitle, items, size=14, space_after=11):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        self.add_bullets(s, Emu(430000), Emu(940000), self.SW - Emu(860000),
                         self.SH - Emu(1200000), items, size, INK, space_after=space_after)
        return s

    def two_col_slide(self, title, subtitle, left_head, left, right_head, right):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        colw = (self.SW - Emu(430000) * 2 - Emu(300000)) // 2
        lx = Emu(430000)
        rx = lx + colw + Emu(300000)
        for x, head, items in ((lx, left_head, left), (rx, right_head, right)):
            self.add_rect(s, x, Emu(900000), colw, Emu(340000), self.C["blue"])
            self.add_text(s, x + Emu(140000), Emu(900000), colw - Emu(240000),
                          Emu(340000), head, 13, WHITE, bold=True,
                          anchor=MSO_ANCHOR.MIDDLE)
            self.add_bullets(s, x, Emu(1330000), colw, self.SH - Emu(1560000),
                             items, 12.5, INK, space_after=9)
        return s

    def closing(self, title, subtitle, lines):
        AMBER = RGBColor(0xFD, 0xB9, 0x13)
        s = self.new_slide()
        self.add_rect(s, 0, 0, self.SW, self.SH, self.C["blue"])
        self.add_rect(s, Emu(520000), Emu(1980000), Emu(1500000), Emu(20000), AMBER)
        self.add_text(s, Emu(520000), Emu(1150000), self.SW - Emu(1040000), Emu(700000),
                      title, 30, WHITE, bold=True)
        self.add_text(s, Emu(520000), Emu(2120000), self.SW - Emu(1040000), Emu(400000),
                      subtitle, 15, AMBER, bold=True)
        self.add_bullets(s, Emu(520000), Emu(2680000), self.SW - Emu(1040000),
                         Emu(1600000), lines, 13, WHITE, space_after=10)
        return s

    # -- code + table primitives -----------------------------------------------
    def code_panel(self, slide, x, y, w, h, lines, size=11):
        """A dark terminal-style panel. Each line is a list of (text, style) runs;
        style is one of code/sh/comment/note/key -> a fixed color."""
        from pptx.enum.shapes import MSO_SHAPE
        # Explicit terminal-bright colors on the dark panel. NOT the template's
        # theme accents — this template's accent slots resolve to unexpected
        # values (its "yellow" is #000000 black, "green" is gray), which would
        # render syntax highlights invisibly dark on the panel.
        colors = {
            "code": CODE_FG,                          # light foreground
            "sh": RGBColor(0x7E, 0xE7, 0x87),         # prompt — bright green
            "comment": CODE_COMMENT,                  # light gray
            "note": RGBColor(0xF2, 0xC4, 0x4C),       # callouts/results — amber
            "key": RGBColor(0x6F, 0xD3, 0xE6),        # highlights — bright cyan
        }
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
        panel.fill.solid()
        panel.fill.fore_color.rgb = CODE_BG
        panel.line.color.rgb = self.C["gray"]
        panel.line.width = Pt(0.75)
        panel.shadow.inherit = False
        tf = panel.text_frame
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = tf.margin_right = Emu(150000)
        tf.margin_top = tf.margin_bottom = Emu(130000)
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.LEFT   # autoshape para[0] defaults to CENTER
            p.space_after = Pt(2)
            p.line_spacing = 1.12
            segs = [(line, "code")] if isinstance(line, str) else line
            for text, style in segs:
                r = p.add_run()
                r.text = text
                r.font.name = MONO
                r.font.size = Pt(size)
                r.font.bold = style == "key"
                r.font.color.rgb = colors.get(style, CODE_FG)
        return panel

    def code_slide(self, title, subtitle, code_lines, bullets, code_size=11):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        cx, cy = Emu(320000), Emu(940000)
        cw = Emu(4820000)
        ch = self.SH - cy - Emu(360000)
        self.code_panel(s, cx, cy, cw, ch, code_lines, size=code_size)
        bx = cx + cw + Emu(240000)
        self.add_bullets(s, bx, cy + Emu(60000), self.SW - bx - Emu(300000),
                         ch, bullets, 12.5, INK, space_after=10)
        return s

    def add_label_text(self, slide, x, y, w, h, label, rest, size, color=INK,
                       anchor=MSO_ANCHOR.MIDDLE):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        r = p.add_run(); r.text = label
        r.font.name = FONT; r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = color
        r2 = p.add_run(); r2.text = rest
        r2.font.name = FONT; r2.font.size = Pt(size); r2.font.color.rgb = color
        return tb

    def dockerfile_slide(self, title, subtitle, code_lines, intro, deploy, dev,
                         takeaway):
        """Dockerfile code panel (left) with Deploy/Dev callouts on the right,
        each joined by a block arrow to its `# DEPLOY` / `# DEV` code line."""
        from pptx.enum.shapes import MSO_SHAPE
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        cx, cy = Emu(320000), Emu(940000)
        cw = Emu(4820000)
        ch = self.SH - cy - Emu(360000)
        self.code_panel(s, cx, cy, cw, ch, code_lines, size=11)
        bx = cx + cw + Emu(320000)
        bw = self.SW - bx - Emu(300000)
        AMBER = RGBColor(0xF2, 0xC4, 0x4C)
        # y-centers aligned to the `# DEPLOY` (line 3) and `# DEV` (line 7) rows
        content_top = cy + Emu(130000)
        line_adv = Emu(191000)
        deploy_y = content_top + line_adv * 3 + line_adv // 2
        dev_y = content_top + line_adv * 7 + line_adv // 2
        self.add_text(s, bx, cy + Emu(10000), bw, Emu(520000), intro, 12.5, INK)
        from pptx.enum.shapes import MSO_CONNECTOR
        from pptx.oxml.ns import qn
        tail_x = bx - Emu(30000)
        # Angled arrows: tail at the callout (right), head angled DOWN-LEFT to the
        # `# DEPLOY` / `# DEV` code line. head_x/drop tuned for PowerPoint (Consolas);
        # drop = the vertical offset measured in PowerPoint (0.5" / 0.75").
        for (label, rest), yc, head_x, drop in (
                (deploy, deploy_y, Emu(3820000), Emu(457200)),
                (dev, dev_y, Emu(3600000), Emu(685800))):
            conn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, tail_x, yc,
                                          head_x, yc + drop)
            conn.line.color.rgb = AMBER
            conn.line.width = Pt(2.75)
            conn.shadow.inherit = False
            ln = conn.line._get_or_add_ln()
            ln.append(ln.makeelement(qn("a:tailEnd"),
                                     {"type": "triangle", "w": "lg", "len": "lg"}))
            self.add_label_text(s, bx, yc - Emu(220000), bw, Emu(440000),
                                label, rest, 12.5)
        self.add_text(s, bx, self.SH - Emu(900000), bw, Emu(560000), takeaway, 12.5,
                      RGBColor(0x00, 0x6B, 0xB5), bold=True)
        return s

    def two_ways_slide(self, title, subtitle, left_head, left_code, left_bul,
                       right_head, right_code, right_bul, note=None):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        colw = (self.SW - Emu(320000) * 2 - Emu(280000)) // 2
        lx = Emu(320000)
        rx = lx + colw + Emu(280000)
        top = Emu(900000)
        head_h = Emu(480000)
        code_y = top + head_h + Emu(120000)
        code_h = Emu(1450000)
        bul_y = code_y + code_h + Emu(120000)
        for x, head, code, bul in ((lx, left_head, left_code, left_bul),
                                   (rx, right_head, right_code, right_bul)):
            self.add_rect(s, x, top, colw, head_h, self.C["blue"])
            self.add_text(s, x + Emu(160000), top, colw - Emu(280000), head_h,
                          head, 13, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
            self.code_panel(s, x, code_y, colw, code_h, code, size=10.5)
            self.add_bullets(s, x, bul_y, colw, self.SH - bul_y - Emu(560000),
                             bul, 11.5, INK, space_after=7)
        if note:
            ny = self.SH - Emu(500000)
            self.add_rect(s, Emu(320000), ny, self.SW - Emu(640000), Emu(6000),
                          self.C["lgray"])
            self.add_text(s, Emu(320000), ny + Emu(70000), self.SW - Emu(640000),
                          Emu(400000), note, 11, self.C["blue"], italic=True)
        return s

    def roles_slide(self, title, subtitle, intro, cards, banner):
        """Show one Dockerfile/image driving three roles (dev/build/CI)."""
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        # centered intro pill: the single source of truth
        pill_w = Emu(5600000)
        px = (self.SW - pill_w) // 2
        py = Emu(870000)
        self.add_rect(s, px, py, pill_w, Emu(420000), RGBColor(0x14, 0x18, 0x1C))
        self.add_text(s, px, py, pill_w, Emu(420000), intro, 14, WHITE, bold=True,
                      align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # three role cards
        n = len(cards)
        margin = Emu(320000)
        gap = Emu(260000)
        cw = (self.SW - margin * 2 - gap * (n - 1)) // n
        cy = Emu(1450000)
        ch = Emu(2320000)
        for i, (name, tag, body, cmd, color) in enumerate(cards):
            cx = margin + i * (cw + gap)
            self.add_rect(s, cx, cy, cw, ch, RGBColor(0xF2, 0xF5, 0xF8))  # card body
            self.add_rect(s, cx, cy, cw, Emu(560000), color)             # header strip
            self.add_text(s, cx, cy + Emu(70000), cw, Emu(290000), name, 16, WHITE,
                          bold=True, align=PP_ALIGN.CENTER)
            self.add_text(s, cx, cy + Emu(360000), cw, Emu(190000), tag, 10.5, WHITE,
                          align=PP_ALIGN.CENTER)
            self.add_text(s, cx + Emu(150000), cy + Emu(660000), cw - Emu(300000),
                          Emu(820000), body, 12, INK)
            self.code_panel(s, cx + Emu(90000), cy + ch - Emu(640000),
                            cw - Emu(180000), Emu(560000), cmd, size=10)
        by = cy + ch + Emu(170000)
        self.add_rect(s, margin, by, self.SW - margin * 2, Emu(6000),
                      RGBColor(0xC8, 0xD0, 0xD8))
        self.add_text(s, margin, by + Emu(70000), self.SW - margin * 2, Emu(560000),
                      banner, 12.5, RGBColor(0x00, 0x6B, 0xB5), italic=True)
        return s

    def add_links_line(self, slide, x, y, w, label, links, size=11.5):
        """A line of clickable hyperlinks: 'label  name1 | name2 | ...'."""
        LINK = RGBColor(0x00, 0x6B, 0xB5)
        tb = slide.shapes.add_textbox(x, y, w, Emu(340000))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        if label:
            r = p.add_run()
            r.text = label + "   "
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.bold = True
            r.font.color.rgb = INK
        for i, (name, url) in enumerate(links):
            if i:
                sep = p.add_run()
                sep.text = "     |     "
                sep.font.name = FONT
                sep.font.size = Pt(size)
                sep.font.color.rgb = GRAY
            r = p.add_run()
            r.text = name
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.color.rgb = LINK
            r.font.underline = True
            r.hyperlink.address = url
        return tb

    def add_link_rows(self, slide, x, y, w, label, links, size=12):
        """A label line, then one row per link showing the full (hyperlinked)
        URL as visible text — so it's obviously a link and is copy-pasteable
        even in a viewer that doesn't follow clicks."""
        LINK = RGBColor(0x00, 0x6B, 0xB5)
        tb = slide.shapes.add_textbox(x, y, w, Emu(1150000))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p0 = tf.paragraphs[0]
        p0.space_after = Pt(6)
        r = p0.add_run(); r.text = label
        r.font.name = FONT; r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = INK
        for name, url in links:
            p = tf.add_paragraph(); p.space_after = Pt(4)
            rn = p.add_run(); rn.text = f"{name}   "
            rn.font.name = FONT; rn.font.size = Pt(size); rn.font.bold = True
            rn.font.color.rgb = INK
            ru = p.add_run(); ru.text = url.replace("https://", "")
            ru.font.name = FONT; ru.font.size = Pt(size); ru.font.color.rgb = LINK
            ru.font.underline = True
            ru.hyperlink.address = url
        return tb

    def table_slide(self, title, subtitle, headers, rows, note=None, links=None):
        s = self.new_slide()
        self.header_band(s, title, subtitle)
        from pptx.util import Emu as E
        x, y = Emu(360000), Emu(1020000)
        w = self.SW - Emu(720000)
        h = Emu(2600000)
        gf = s.shapes.add_table(len(rows) + 1, len(headers), x, y, w, h)
        tbl = gf.table
        # column widths: first col wider (toolchain), rest even
        tbl.columns[0].width = Emu(1750000)
        rest = (w - Emu(1750000)) // (len(headers) - 1)
        for c in range(1, len(headers)):
            tbl.columns[c].width = rest
        def cell(rc, cc, text, bold=False, color=INK, fill=None, size=11):
            c = tbl.cell(rc, cc)
            c.margin_left = c.margin_right = Emu(90000)
            c.margin_top = c.margin_bottom = Emu(50000)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            if fill is not None:
                c.fill.solid(); c.fill.fore_color.rgb = fill
            else:
                c.fill.solid(); c.fill.fore_color.rgb = WHITE
            tfc = c.text_frame
            tfc.word_wrap = True
            p = tfc.paragraphs[0]
            r = p.add_run(); r.text = text
            r.font.name = FONT; r.font.size = Pt(size)
            r.font.bold = bold; r.font.color.rgb = color
        for cc, htext in enumerate(headers):
            cell(0, cc, htext, bold=True, color=WHITE, fill=self.C["blue"], size=11.5)
        for ri, row in enumerate(rows, start=1):
            band = WHITE if ri % 2 else RGBColor(0xEF, 0xF3, 0xF7)
            for cc, val in enumerate(row):
                cell(ri, cc, val, bold=(cc == 0), color=INK, fill=band,
                     size=11 if cc else 11.5)
        ny = y + h + Emu(180000)
        if note:
            self.add_text(s, x, ny, w, Emu(360000), note, 12, self.C["blue"], italic=True)
            ny += Emu(430000)
        if links:
            self.add_link_rows(s, x, ny, w,
                               "Step-by-step walkthroughs (README) — open in a browser:", links)
        return s

    def save(self):
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        self.prs.save(OUT)


def build():
    b = Brief()

    b.cover(
        "",
        "From Hand-Built VMs to a Golden Container Image",
        "Modernizing the development SDLC:  As-Is → To-Be",
        "One reproducible image for dev, build, and CI",
    )

    b.bullets_slide(
        "The problem: a build we depend on but no longer understand",
        "The build works today — but the knowledge of how it works has been lost",
        [
            ("The build works — but it’s a black box.", "The team has a build server and build VMs that produce releases today, yet the knowledge of how they were provisioned and how the build actually runs has been lost."),
            ("Nothing describes the environment.", "There’s no written, reproducible definition of what’s installed on the build server or how the pipeline is wired — it exists only inside the running machines."),
            ("That concentrates risk.", "If the build server fails, needs an upgrade, or has to move, no one can confidently rebuild or modify it."),
            ("So, change gets avoided, not managed.", "Because the process isn’t understood, people are reluctant to touch it — the gap widens and the system ages in place."),
            ("Onboarding and audit suffer.", "New engineers can’t learn an undocumented process, and we can’t clearly show how our software is built."),
            ("The fix is also the documentation.", "Capturing the build as a golden container image forces us to discover how it really works — turning tribal knowledge into a versioned, readable Dockerfile anyone can inspect."),
        ],
        size=13, space_after=9,
    )

    b.diagram_slide(
        "As-Is — a build that works, but no one can explain",
        "The build server runs today, but how it was provisioned and how it runs is undocumented",
        "asis-vm-sdlc.png",
        "The build produces releases today — but it’s a black box. Nothing describes how the build server was provisioned or how the build runs, so it can’t be safely changed, recovered, or explained.",
    )

    b.diagram_slide(
        "To-Be — container-based SDLC",
        "One golden image is dev, build, and CI; developers keep their local IDE",
        "tobe-container-sdlc.png",
        "A single golden image in the GitLab Container Registry is the source of truth. Developers pull it, volume-mount their working tree, and edit in their own IDE — dev == build == CI.",
    )

    b.diagram_slide(
        "Developer workflow — inner and outer loops",
        "Fast local iteration and full-scale CI, both in the same image",
        "container-dev-workflow.png",
        "Inner loop: edit locally, build and unit-test in the dev container for fast feedback. Outer loop: GitLab CI runs the full suite in the same image and republishes it on merge to develop.",
    )

    b.diagram_slide(
        "One pattern, any toolchain",
        "A golden dev/build image per team — same loop for Python, Java, or C/C++",
        "tobe-container-sdlc-v2-multitoolchain.png",
        "The workflow is language-agnostic: only the image contents change. Python is shipped today (#244); Java and C/C++ images are the next demos on the identical pull → mount → develop → CI loop.",
    )

    # -- developer deep-dive: the Dockerfile and the local-dev loop -----------
    b.dockerfile_slide(
        "One Dockerfile — one definition of the environment",
        "A multi-stage build: the dev image, the build, and the deploy image all come from one file",
        [
            [("FROM ", "key"), ("node:20-slim     ", "code"), ("AS frontend-builder", "comment")],
            [("FROM ", "key"), ("python:3.11-slim ", "code"), ("AS diagram-builder", "comment")],
            [("", "code")],
            [("FROM ", "key"), ("python:3.11-slim ", "code"), ("AS runtime", "key"), ("   # DEPLOY", "note")],
            [("  EXPOSE ", "code"), ("80", "code")],
            [('  ENTRYPOINT ["python","NceGitLab.py","--serve"]', "code")],
            [("", "code")],
            [("FROM ", "key"), ("runtime          ", "code"), ("AS dev", "key"), ("       # DEV", "note")],
            [("  RUN ", "code"), ("apt-get install make git nodejs …", "code")],
            [("  ENTRYPOINT ", "code"), ("[]", "code"), ("   ", "code"), ("# drop to a shell", "comment")],
            [('  CMD ["bash"]', "code"), ("   # source mounted at run time", "comment")],
        ],
        "Two stages, one file — the deploy image and the dev image share one base.",
        ("Deploy env — ", "the slim runtime image CI pushes to the registry and production runs."),
        ("Dev env — ", "the toolchain you develop in; it drops to a shell with your source mounted."),
        "Same base ⇒ dev == build == CI: the image you develop in is the one that ships.",
    )

    b.roles_slide(
        "One image, three roles — dev · build · CI",
        "The same golden image is your dev environment, your build, and your CI — so they can’t drift",
        "One Dockerfile   →   one golden image",
        [
            ("DEV", "you, interactively",
             "Pull the image, mount your source, and run the fast inner loop — edit, build, test, repeat.",
             [[("docker run -it \\", "code")], [('  -v "$PWD":/app  …:dev', "code")]],
             RGBColor(0x00, 0x6B, 0xB5)),
            ("BUILD", "produce the deliverable",
             "The same toolchain compiles and packages the app into the slim deploy image.",
             [[("docker build .", "code")], [("  → runtime image", "note")]],
             RGBColor(0x00, 0x83, 0x8F)),
            ("CI", "automated, every merge",
             "Runs the tests, then rebuilds and publishes both images to the registry.",
             [[(".gitlab-ci.yml", "code")], [("  kaniko → push", "note")]],
             RGBColor(0x2E, 0x7D, 0x32)),
        ],
        "One Dockerfile is the single source of truth: the image you develop in is the image CI ships. "
        "dev == build == CI — a person or the pipeline, identical environment, no “works on my machine.”",
    )

    b.code_slide(
        "Local development — mount the source, exec in, build",
        "Pull the golden image, bind-mount your working tree, run the whole pipeline",
        [
            [("# pull the dev image, mount your tree, build", "comment")],
            [("$ ", "sh"), ("docker run --rm -it \\", "code")],
            [("    -v ", "code"), ('"$PWD":/app', "code"), ("  ", "code"), ("← source repo mounted", "note")],
            [("    -w /app \\", "code")],
            [("    -p ", "code"), ("4645:80", "code"), ("  ", "code"), ("← host 4645 → app :80", "note")],
            [("    nce-safe-simulator:dev", "code")],
            [("", "code")],
            [("# now inside the container:", "comment")],
            [("$ ", "sh"), ("pytest tests/", "code")],
            [("$ ", "sh"), ("make build", "code")],
            [("$ ", "sh"), ("python3 NceGitLab.py --serve", "code")],
            [("      → http://localhost:4645", "note")],
        ],
        [
            ("Source is mounted, not baked.", "-v \"$PWD\":/app puts your working tree in the container — edits in your local IDE are visible instantly."),
            ("Exec in and build.", "The dev image opens a shell; run the full pipeline (tests, build, serve) with zero toolchain on the host."),
            ("Rebuild only on toolchain change.", "The image changes only when tools or dependencies bump — day to day you just mount and go."),
        ],
        code_size=11,
    )

    b.two_ways_slide(
        "Two ways the work reaches the host",
        "The container builds it; the developer uses it on the host in one of two ways",
        "A  ·  Serve on a port",
        [
            [("-p ", "code"), ("4645:80", "key")],
            [("$ ", "sh"), ("… --serve", "code"), ("   ", "code"), ("(app :80)", "comment")],
            [("→ http://localhost:4645", "note")],
        ],
        [
            ("The build runs a server inside the container (this app on :80).", ""),
            ("Publish the port to the host — open it in a normal browser.", ""),
            ("Live today: the Python app serves its UI this way.", ""),
        ],
        "B  ·  Build an artifact, run on the host",
        [
            [("-v ", "code"), ('"$PWD/out":/app/out', "key")],
            [("$ ", "sh"), ("make package", "code")],
            [("# host:", "comment"), (" ./out/app.jar", "code")],
        ],
        [
            ("The build emits a jar / exe into a bind-mounted output dir.", ""),
            ("The artifact lands on the host filesystem.", ""),
            ("Run and test it natively on the host before pushing.", ""),
        ],
        note="Native binaries (C/C++) are architecture- and libc-specific: build a static binary, "
             "or run it inside the container, to use it on a non-matching host. A Java jar is "
             "portable given a host JRE.",
    )

    b.table_slide(
        "Local dev across toolchains — one loop, any stack",
        "Same pull → mount → exec → build loop; only the image and how the result reaches the host change",
        ["Toolchain", "Dev image", "Build command", "Result", "Reaches the host via"],
        [
            ["Python", "python-app/dev", "make build · --serve", "Web app on a port", "-p 4645:80 → browser"],
            ["Java", "java-app/dev", "mvn package · run", "NMEA/GPS stream on :8080", "-p 8080:8080 → curl -N"],
            ["C / C++", "cpp-app/dev", "cmake --build", "Native executable", "-v ./out → run on host"],
        ],
        links=[
            ("python", "https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator"),
            ("java-app", "https://gitlab.com/gl-demo-ultimate-lmwilliams/powers-devops-demos/java-app"),
            ("cpp-app", "https://gitlab.com/gl-demo-ultimate-lmwilliams/powers-devops-demos/cpp-app"),
        ],
    )

    b.two_col_slide(
        "As-Is → To-Be transition",
        "How an organization moves its programs from hand-built VMs to the golden-image workflow",
        "Migration playbook — per program",
        [
            ("1.", "Inventory the current build: capture what’s on the build server/VMs and how the build actually runs."),
            ("2.", "Encode that toolchain as a golden dev/build Dockerfile — the image becomes the documentation."),
            ("3.", "Publish the golden image to the shared Container Registry."),
            ("4.", "Wire CI to build, test, and republish the image on merge to <default-branch>."),
            ("5.", "Onboard developers: docker pull → mount source → develop → push, keeping their own IDE."),
            ("6.", "Retire that program’s hand-built VMs once its image is the build."),
        ],
        "Rolling out across the organization",
        [
            ("Prove it once.", "Migrate one program end to end to establish the pattern — dev == build == CI."),
            ("Replicate.", "Every other program follows the identical playbook; only the image contents differ."),
            ("Toolchain-agnostic.", "The same loop covers any stack — Python, Java, C/C++, and beyond."),
            ("Standardize.", "A shared registry gives every team a governed, versioned image to pull."),
            ("Decommission.", "Legacy build servers retire once CI is the system of record everywhere."),
        ],
    )

    b.bullets_slide(
        "Why it matters — advantages",
        "What the golden-image SDLC buys us",
        [
            ("Recovers lost knowledge.", "Capturing the build as a Dockerfile forces us to discover and record how the build server actually works — the image becomes living documentation."),
            ("Reproducible and versioned.", "The environment is pinned in the registry and rebuilt automatically on every merge — no more undocumented, unrecoverable build box."),
            ("One environment for dev, build, and CI.", "The same image runs everywhere, so builds are consistent and there’s no separate mystery build server or dev VM."),
            ("Onboarding is a single docker pull.", "Minutes to a working environment instead of inheriting an unexplained VM."),
            ("Developers keep their own IDE.", "Only the toolchain moves into the container; the local edit experience is unchanged."),
            ("It scales to any language.", "Python today, Java and C/C++ next — same workflow, different image contents."),
        ],
    )

    b.closing(
        "One image. Dev, build, and CI.",
        "From opaque build servers to one reproducible image",
        [
            "One golden image per program — the single source of truth for dev, build, and CI.",
            "Developers keep their own IDE; the toolchain lives in a versioned, reproducible image.",
            "The result: reproducible builds, fast onboarding, and the end of “works on my machine.”",
        ],
    )

    b.save()
    print(f"Wrote {OUT}  ({len(b.prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    build()
