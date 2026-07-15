"""Print-ready epic-card renderer (issue #249).

Pure rendering — no GitLab coupling. Takes a list of card dicts and writes a
Letter-size PDF of cut-apart "cards" (1/2/4 per page) via WeasyPrint. The tool
that feeds it live epics lives in ImportExportMixin.export_epic_cards.

Card dict fields (all optional; missing ones render as an em dash):
    title, weight, description,
    mission_thread                 — mission-thread:: scoped value (card header)
    buckets (list[str])            — bucket labels
    main_system                    — project:: scoped value
    related_systems (list[str])    — unscoped project labels (the *other* systems)
    due_date, color                — program accent color (border-left)

Overflow is handled by truncating in Python (not by CSS clipping) so content
always fits the fixed-height card — this both shows a clear '…' cut marker and
keeps WeasyPrint off its O(n²) flex-overflow relayout path:
  * the description is trimmed to a per-layout character budget so it can never
    reach the buckets row, ending in ' …' when cut;
  * buckets past the ~two-line budget collapse into a trailing '…' chip;
  * the special bucket value ``ALL`` (buckets only) means "all buckets" and
    renders as a single ALL chip regardless of any others.
"""
from html import escape

from weasyprint import HTML

# Usable area inside the 0.4in @page margins, and inter-card gap.
_GAP = 0.28
_USABLE_W, _USABLE_H = 7.7, 10.2

# Description character budget per cards-per-page — sized so the (whitespace-
# collapsed) text fills the card's description area without reaching the buckets.
_DESC_BUDGET = {1: 3000, 2: 1000, 3: 460, 4: 460}
# Bucket chips shown before the two-line cutoff; the rest collapse into a
# trailing '…' chip. Sized to keep the shown chips + '…' within ~two rows so the
# cut marker is always visible (no CSS clipping that could hide it).
_BUCKET_MAX  = {1: 11, 2: 11, 3: 11, 4: 5}


def _truncate(text, limit):
    """Collapse whitespace and trim to <=limit chars at a word boundary, adding
    a ' …' marker when the text was actually cut. Collapsing newlines keeps the
    char budget a faithful proxy for rendered height (so nothing overflows)."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return (cut or text[:limit]) + " …"


def _text_on(bg):
    """Readable ink (#1a1a1a / #fff) for a #rrggbb background, YIQ-weighted —
    the same rule GitLab uses to pick label text color. None for bad input."""
    if not (isinstance(bg, str) and bg.startswith("#") and len(bg) == 7):
        return None
    try:
        r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None
    return "#1a1a1a" if (r * 299 + g * 587 + b * 114) / 1000 >= 140 else "#ffffff"


def _bchip(label, color, extra=""):
    """One bucket chip. When ``color`` is a live label color (#rrggbb) it fills
    the chip and picks a readable ink; otherwise the default CSS class colors it."""
    cls = "chip bucket" + (" " + extra if extra else "")
    fg = _text_on(color)
    style = f' style="background:{color};color:{fg};"' if fg else ""
    return f'<span class="{cls}"{style}>{escape(str(label))}</span>'


def _bucket_chips(buckets, per_page, colors=None):
    """Bucket chips honoring the ALL shorthand, the two-line '…' cutoff, and each
    label's live GitLab color (``colors`` maps label name -> #rrggbb)."""
    colors = colors or {}
    vals = [str(b) for b in (buckets or []) if str(b).strip()]
    if not vals:
        return ""
    allv = [v for v in vals if v.strip().upper() == "ALL"]
    if allv:                                            # ALL subsumes every other bucket
        return _bchip("ALL", colors.get(allv[0]) or colors.get("ALL"), "all")
    cap = _BUCKET_MAX.get(per_page, 11)
    chips = "".join(_bchip(v, colors.get(v)) for v in vals[:cap])
    if len(vals) > cap:
        chips += '<span class="chip bucket more">…</span>'
    return chips


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
.thread { font-size: 10.5pt; font-weight: 700; color: #444; }
.title { font-size: 18pt; font-weight: 700; line-height: 1.12; margin-top: 3px; }
.weight { font-size: 10.5pt; font-weight: 700; color: #444; white-space: nowrap;
          border: 1px solid #ccc; border-radius: 4px; padding: 1px 7px; }
.k { font-size: 7pt; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: #999; }
/* No `overflow-wrap: anywhere` here — it makes WeasyPrint weigh a break at every
   character (O(n²)); long-token safety comes from the card's own overflow:hidden. */
.desc { font-size: 10pt; line-height: 1.34; color: #333; margin: 6px 0 4px 0;
        flex: 1 1 auto; min-height: 0; overflow: hidden; word-break: break-word; }
.chiprow { display: flex; flex-wrap: wrap; align-items: center; align-content: flex-start;
           gap: 4px; margin: 2px 0; flex: 0 0 auto; }
.chiprow .k { margin-right: 3px; }
.chip { font-size: 8pt; font-weight: 600; padding: 1px 8px; border-radius: 10px; line-height: 1.5; }
.chip.bucket { background: #eef4fb; color: #24537e; }
.chip.bucket.more { background: #dfe7f1; color: #24537e; font-weight: 700; letter-spacing: .08em; }
.chip.bucket.all  { background: #e3efe3; color: #2f6f4f; font-weight: 700; letter-spacing: .04em; }
.foot { display: flex; justify-content: space-between; align-items: flex-end; flex: 0 0 auto;
        border-top: 1px solid #eee; padding-top: 5px; margin-top: 5px; font-size: 9pt; }
.sys .main { font-weight: 700; }
.sys .related { color: #666; }
.due { font-weight: 700; color: #333; white-space: nowrap; text-align: right; }
"""


def _card_html(c, dim_style="", per_page=2):
    bucket_chips = _bucket_chips(c.get("buckets"), per_page, c.get("bucket_colors"))
    bucket_block = f'<div class="chiprow buckets"><span class="k">Buckets</span>{bucket_chips}</div>' if bucket_chips else ""

    thread = c.get("mission_thread")
    thread_txt = escape(str(thread)) if thread else "—"

    desc_txt = _truncate(c.get("description") or "", _DESC_BUDGET.get(per_page, 1000))

    related = c.get("related_systems") or []
    related_txt = (" · " + " · ".join(escape(str(r)) for r in related)) if related else ""
    main = escape(str(c.get("main_system") or "—"))
    weight = c.get("weight")
    weight_txt = escape(str(weight)) if weight not in (None, "") else "—"
    return f"""
    <div class="card" style="border-left-color: {escape(str(c.get('color') or '#3b6ea5'))};{dim_style}">
      <div class="head">
        <div class="thread"><span class="k">Thread</span> {thread_txt}</div>
        <div class="weight"><span class="k">Wt</span> {weight_txt}</div>
      </div>
      <div class="title">{escape(str(c.get('title') or ''))}</div>
      <div class="desc">{escape(desc_txt)}</div>
      {bucket_block}
      <div class="foot">
        <div class="sys"><div class="k">Project / Related Systems</div><span class="main">{main}</span><span class="related">{related_txt}</span></div>
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
        sheets.append('<div class="sheet">' + "".join(_card_html(c, dim_style, per_page) for c in chunk) + "</div>")
    body = "".join(sheets) or '<div class="sheet"></div>'
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>{body}</body></html>"


def render_cards(cards, out_pdf, per_page=2):
    """Render cards to a print-ready Letter PDF at out_pdf. Returns out_pdf."""
    HTML(string=build_html(cards, per_page=per_page)).write_pdf(str(out_pdf))
    return out_pdf
