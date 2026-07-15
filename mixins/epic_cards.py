"""Print-ready epic-card renderer (issue #249).

Pure rendering — no GitLab coupling. Takes a list of card dicts and writes a
Letter-size PDF of cut-apart "cards" (1/2/4 per page) via WeasyPrint. The tool
that feeds it live epics lives in ImportExportMixin.export_epic_cards.

Card dict fields (all optional; missing ones render as an em dash):
    title, weight, description, mission_thread, phase,
    actions (list[str])            — activity labels
    main_system                    — project:: scoped value
    related_systems (list[str])    — unscoped project labels (the *other* systems)
    due_date, color                — program accent color (border-left)
"""
from html import escape

from weasyprint import HTML

# Usable area inside the 0.4in @page margins, and inter-card gap.
_GAP = 0.28
_USABLE_W, _USABLE_H = 7.7, 10.2


def _dims(per_page):
    """(card_width, card_height) in inches for a given cards-per-page count.

    Fixed dimensions + flexbox tile predictably in WeasyPrint, whose CSS-grid
    support is unreliable.
    """
    if per_page == 1:
        return (_USABLE_W, _USABLE_H)
    if per_page == 4:
        return ((_USABLE_W - _GAP) / 2, (_USABLE_H - _GAP) / 2)   # 2x2
    if per_page == 3:
        return (_USABLE_W, (_USABLE_H - 2 * _GAP) / 3)            # 3 stacked
    return (_USABLE_W, (_USABLE_H - _GAP) / 2)                    # 2 stacked (default)


_CSS = """
@page { size: 8.5in 11in; margin: 0.4in; }
* { box-sizing: border-box; }
html { font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }
.sheet { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 0.28in;
         width: 7.7in; height: 10.2in; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.card {
  border: 1.5px dashed #9a9a9a; border-left-width: 0.16in; border-left-style: solid;
  border-radius: 6px; padding: 0.2in 0.26in; overflow: hidden;
  display: flex; flex-direction: column; min-height: 0;
}
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.2in; }
.title { font-size: 18pt; font-weight: 700; line-height: 1.12; }
.weight { font-size: 10.5pt; font-weight: 700; color: #444; white-space: nowrap;
          border: 1px solid #ccc; border-radius: 4px; padding: 1px 7px; }
.k { font-size: 7pt; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: #999; }
.desc { font-size: 10pt; line-height: 1.34; color: #333; margin: 6px 0 4px 0;
        flex: 1 1 auto; min-height: 0; overflow: hidden; overflow-wrap: anywhere; }
.chiprow { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin: 2px 0; }
.chiprow .k { margin-right: 3px; }
.chip { font-size: 8pt; font-weight: 600; padding: 1px 8px; border-radius: 10px; }
.chip.action { background: #eef4fb; color: #24537e; }
.chip.thread { background: #f0ece1; color: #6b5a2e; }
.chip.phase  { background: #e6e0d0; color: #6b5a2e; }
.foot { display: flex; justify-content: space-between; align-items: flex-end;
        border-top: 1px solid #eee; padding-top: 5px; margin-top: 5px; font-size: 9pt; }
.sys .main { font-weight: 700; }
.sys .related { color: #666; }
.due { font-weight: 700; color: #333; white-space: nowrap; text-align: right; }
"""


def _chips(cls, values):
    return "".join(f'<span class="chip {cls}">{escape(str(v))}</span>' for v in values if v)


def _card_html(c, dim_style=""):
    actions = _chips("action", c.get("actions") or [])
    action_block = f'<div class="chiprow"><span class="k">Action</span>{actions}</div>' if actions else ""

    thread = c.get("mission_thread")
    if thread:
        bits = f'<span class="chip thread">{escape(str(thread))}</span>'
        if c.get("phase"):
            bits += f'<span class="chip phase">Phase: {escape(str(c["phase"]))}</span>'
        thread_block = f'<div class="chiprow"><span class="k">Thread</span>{bits}</div>'
    else:
        thread_block = ""

    related = c.get("related_systems") or []
    related_txt = (" · " + " · ".join(escape(str(r)) for r in related)) if related else ""
    main = escape(str(c.get("main_system") or "—"))
    weight = c.get("weight")
    weight_txt = escape(str(weight)) if weight not in (None, "") else "—"
    return f"""
    <div class="card" style="border-left-color: {escape(str(c.get('color') or '#3b6ea5'))};{dim_style}">
      <div class="head">
        <div class="title">{escape(str(c.get('title') or ''))}</div>
        <div class="weight"><span class="k">Wt</span> {weight_txt}</div>
      </div>
      <div class="desc">{escape(str(c.get('description') or ''))}</div>
      {action_block}
      {thread_block}
      <div class="foot">
        <div class="sys"><div class="k">Systems</div><span class="main">{main}</span><span class="related">{related_txt}</span></div>
        <div class="due"><div class="k">Due</div>{escape(str(c.get('due_date') or '—'))}</div>
      </div>
    </div>"""


def build_html(cards, per_page=2):
    """Return the full HTML document for the given cards (testable without PDF)."""
    w, h = _dims(per_page)
    dim_style = f"width: {w:.3f}in; height: {h:.3f}in;"
    sheets = []
    for i in range(0, len(cards), per_page):
        chunk = cards[i:i + per_page]
        sheets.append('<div class="sheet">' + "".join(_card_html(c, dim_style) for c in chunk) + "</div>")
    body = "".join(sheets) or '<div class="sheet"></div>'
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>{body}</body></html>"


def render_cards(cards, out_pdf, per_page=2):
    """Render cards to a print-ready Letter PDF at out_pdf. Returns out_pdf."""
    HTML(string=build_html(cards, per_page=per_page)).write_pdf(str(out_pdf))
    return out_pdf
