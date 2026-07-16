"""Print-ready epic-card renderer (issue #249).

Pure rendering — no GitLab coupling. Takes a list of card dicts and writes a
PDF via WeasyPrint: by default a Letter-size sheet of cut-apart "cards" (1/2/4
per page), or — for a large-format plotter "wall" (#241) — an arbitrary
``page_size`` (preset or WxH inches) with a ``grid`` of many cards tiled per
sheet. The tool that feeds it live epics lives in ImportExportMixin.export_epic_cards.

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
import re
from html import escape

from weasyprint import HTML

# Page geometry. Orientation is a render option (#254); portrait is the default
# and preserves the original Letter layout. Landscape just rotates the sheet —
# each per_page card AREA is orientation-invariant (the sheet is rotated, not
# reshaped), so the description/bucket budgets below carry over unchanged.
_MARGIN = 0.4
_GAP    = 0.28
_PORTRAIT_PAGE  = (8.5, 11.0)
_LANDSCAPE_PAGE = (11.0, 8.5)

# Named large-format sheet sizes for plotter output (#241), stored portrait
# (w <= h); orientation swaps them. Plotter/architectural + ANSI engineering rolls.
_PAGE_PRESETS = {
    "letter":  (8.5, 11.0),
    "tabloid": (11.0, 17.0),   # a.k.a. ledger
    "ledger":  (11.0, 17.0),
    "arch-a":  (9.0, 12.0),
    "arch-b":  (12.0, 18.0),
    "arch-c":  (18.0, 24.0),
    "arch-d":  (24.0, 36.0),
    "arch-e":  (36.0, 48.0),
    "ansi-c":  (17.0, 22.0),
    "ansi-d":  (22.0, 34.0),
    "ansi-e":  (34.0, 44.0),
}


def _page_dims(orientation):
    """(page_w, page_h, usable_w, usable_h) in inches for ``orientation``.

    Anything other than ``"landscape"`` (case-insensitive) — including ``None``
    and an unset param — falls back to portrait, so existing callers and the
    default path are unchanged.
    """
    page_w, page_h = (_LANDSCAPE_PAGE if str(orientation).lower() == "landscape"
                      else _PORTRAIT_PAGE)
    return page_w, page_h, page_w - 2 * _MARGIN, page_h - 2 * _MARGIN


def _parse_page_size(page_size, orientation="portrait"):
    """(page_w, page_h) in inches for a preset name or an explicit ``WxH`` (e.g.
    ``"36x48"``, ``"36 x 48in"``), or ``None`` for blank/unrecognized input.

    Presets are stored portrait; ``orientation="landscape"`` swaps them. An
    explicit ``WxH`` is taken verbatim (the caller already stated the dimensions).
    """
    if not page_size:
        return None
    key = str(page_size).strip().lower()
    if key in _PAGE_PRESETS:
        w, h = _PAGE_PRESETS[key]
        return (h, w) if str(orientation).lower() == "landscape" else (w, h)
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:in|in\.|inch|inches)?\s*$", key)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w > 0 and h > 0:
            return (w, h)
    return None


def _resolve_page(page_size, orientation):
    """(page_w, page_h, usable_w, usable_h) from an explicit/preset ``page_size``
    when given, else the Letter portrait/landscape default (#254 path)."""
    dims = _parse_page_size(page_size, orientation)
    if dims is None:
        return _page_dims(orientation)
    page_w, page_h = dims
    return page_w, page_h, page_w - 2 * _MARGIN, page_h - 2 * _MARGIN


def _parse_grid(grid):
    """(cols, rows) positive ints from ``"COLSxROWS"`` (e.g. ``"6x8"``), else None.
    Used for the large-format 'wall' layout (#241) — many cards tiled per sheet."""
    if not grid:
        return None
    m = re.match(r"^\s*(\d+)\s*[x×]\s*(\d+)\s*$", str(grid).strip().lower())
    if not m:
        return None
    cols, rows = int(m.group(1)), int(m.group(2))
    return (cols, rows) if cols > 0 and rows > 0 else None

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


def _bucket_chips(buckets, per_page=None, colors=None, cap=None):
    """Bucket chips honoring the ALL shorthand, the two-line '…' cutoff, and each
    label's live GitLab color (``colors`` maps label name -> #rrggbb).

    ``cap`` is the max chips before the trailing '…'. When omitted it is derived
    from ``per_page`` (the legacy cut-apart path); the large-format grid path
    passes ``cap`` directly since it isn't tied to a 1/2/4 layout.
    """
    colors = colors or {}
    vals = [str(b) for b in (buckets or []) if str(b).strip()]
    if not vals:
        return ""
    allv = [v for v in vals if v.strip().upper() == "ALL"]
    if allv:                                            # ALL subsumes every other bucket
        return _bchip("ALL", colors.get(allv[0]) or colors.get("ALL"), "all")
    if cap is None:
        cap = _BUCKET_MAX.get(per_page, 11)
    chips = "".join(_bchip(v, colors.get(v)) for v in vals[:cap])
    if len(vals) > cap:
        chips += '<span class="chip bucket more">…</span>'
    return chips


# Legacy cards-per-page counts expressed as (cols, rows) grids, so the cut-apart
# path and the large-format 'wall' path (#241) share one card-sizing routine.
_PER_PAGE_GRID = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2)}


def _card_dims(cols, rows, usable_w, usable_h):
    """(card_width, card_height) in inches for a ``cols`` x ``rows`` grid within
    the usable sheet, accounting for the inter-card ``_GAP`` (which matches the
    ``.sheet`` flex ``gap``, so exactly cols x rows cards tile per sheet)."""
    w = (usable_w - (cols - 1) * _GAP) / cols
    h = (usable_h - (rows - 1) * _GAP) / rows
    return w, h


def _dims(per_page, usable_w, usable_h):
    """(card_width, card_height) in inches for a cards-per-page count, within the
    ``usable_w`` x ``usable_h`` sheet (orientation-dependent, #254).

    Fixed dimensions + flexbox tile predictably in WeasyPrint, whose CSS-grid
    support is unreliable.
    """
    cols, rows = _PER_PAGE_GRID.get(per_page, (1, 2))
    return _card_dims(cols, rows, usable_w, usable_h)


def _area_budget(w, h):
    """Description character budget for an arbitrary card size (the large-format
    grid path). A proxy for how much text fits without overflow — proportional to
    card area, calibrated to the tuned per-page budgets (~22 chars/in²) and
    clamped. Slightly conservative on purpose: undershooting only shows less
    text, never overflows the card (which also has overflow:hidden)."""
    return max(150, min(3000, int(w * h * 22)))


_CSS_STATIC = """
* { box-sizing: border-box; }
html { font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }
.sheet { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 0.28in;
         page-break-after: always; }
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


def _css(page_w, page_h, usable_w, usable_h):
    """Full stylesheet, with the orientation-dependent @page size and .sheet
    dimensions injected ahead of the static rules (#254)."""
    return (
        f"@page {{ size: {page_w:g}in {page_h:g}in; margin: {_MARGIN:g}in; }}\n"
        f".sheet {{ width: {usable_w:.3f}in; height: {usable_h:.3f}in; }}\n"
        + _CSS_STATIC
    )


def _card_html(c, dim_style="", desc_budget=1000, bucket_cap=11):
    bucket_chips = _bucket_chips(c.get("buckets"), colors=c.get("bucket_colors"), cap=bucket_cap)
    bucket_block = f'<div class="chiprow buckets"><span class="k">Buckets</span>{bucket_chips}</div>' if bucket_chips else ""

    thread = c.get("mission_thread")
    thread_txt = escape(str(thread)) if thread else "—"

    desc_txt = _truncate(c.get("description") or "", desc_budget)

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


def build_html(cards, per_page=2, orientation="portrait", page_size=None, grid=None):
    """Return the full HTML document for the given cards (testable without PDF).

    ``orientation`` is ``"portrait"`` (default) or ``"landscape"`` (#254).

    Large-format 'wall' output (#241):
      * ``page_size`` — a preset (letter/tabloid/arch-c…e/ansi-c…e) or ``"WxH"``
        inches (e.g. ``"36x48"``); blank keeps Letter.
      * ``grid`` — ``"COLSxROWS"`` (e.g. ``"6x8"``) tiles that many cards per
        sheet at a shared readable size, overriding ``per_page``; extra cards
        flow onto further sheets.
    Invalid ``page_size``/``grid`` values fall back to the Letter / per-page path.
    """
    page_w, page_h, usable_w, usable_h = _resolve_page(page_size, orientation)

    g = _parse_grid(grid)
    if g:
        cols, rows = g
        per_sheet   = cols * rows
        w, h        = _card_dims(cols, rows, usable_w, usable_h)
        desc_budget = _area_budget(w, h)
        bucket_cap  = 11 if w >= 3.3 else 5
    else:
        per_sheet   = per_page
        w, h        = _dims(per_page, usable_w, usable_h)
        desc_budget = _DESC_BUDGET.get(per_page, 1000)
        bucket_cap  = _BUCKET_MAX.get(per_page, 11)

    dim_style = f"width: {w:.3f}in; height: {h:.3f}in;"
    sheets = []
    for i in range(0, len(cards), per_sheet):
        chunk = cards[i:i + per_sheet]
        sheets.append('<div class="sheet">' + "".join(_card_html(c, dim_style, desc_budget, bucket_cap) for c in chunk) + "</div>")
    body = "".join(sheets) or '<div class="sheet"></div>'
    css = _css(page_w, page_h, usable_w, usable_h)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def render_cards(cards, out_pdf, per_page=2, orientation="portrait", page_size=None, grid=None):
    """Render cards to a print-ready PDF at out_pdf. Returns out_pdf.

    ``orientation`` selects portrait (default) or landscape (#254); ``page_size``
    and ``grid`` drive the large-format plotter 'wall' output (#241) — see
    ``build_html``.
    """
    HTML(string=build_html(cards, per_page=per_page, orientation=orientation,
                           page_size=page_size, grid=grid)).write_pdf(str(out_pdf))
    return out_pdf
