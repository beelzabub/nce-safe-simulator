"""
Render the JQL engine's internals as terminal-style PNGs, so the parser, the
field registry and the planner get real deck art instead of a bulleted slide
with nothing on it (issues #298, #299, #300).

Prerequisite generator like capture_cli_menu.py / capture_jql_cli.py — output
lands in deck/screenshots/ (git-ignored, rebuilt on demand):

  22a-jql-parser.png   #298  a parsed query as an AST, plus a real parse error
  22b-jql-fields.png   #299  field -> GitLab filter mapping, from the registry
  22d-jql-planner.png  #300  JQL -> pushed GraphQL variables, and the residue

Everything drawn is produced by the engine at render time: the tree comes from
jql.parse(), the error text and offset from the parser's own exception, the
mapping rows from FieldRegistry.from_config(config.json), and the variables
from jql.plan_query(). Nothing here is transcribed by hand, so the slides
cannot drift away from the code the way a pasted sample would.

No network and no GitLab token needed — the whole package is pure Python up to
the point of execution, which is exactly what these three issues delivered.

Requires: Pillow + DejaVu Sans Mono (already needed by capture_cli_menu.py).

Usage:
  python3 deck/capture_jql_internals.py [--out-dir deck/screenshots]
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO_ROOT)

from capture_cli_menu import BG, TITLEBAR, FG, DIM, FAINT, GREEN, DOTS, _font  # noqa: E402

import jql  # noqa: E402
from jql import ast as jast  # noqa: E402
from jql.fields import FieldRegistry  # noqa: E402

#: Pushed-to-the-server rows read in the same accent as a successful command;
#: client-side rows read in the warning accent. The pairing is the whole point
#: of the planner slide, so it stays consistent across all three images.
SERVER = (0x6E, 0xC8, 0xB4)
CLIENT = (0xE0, 0xA1, 0x5C)
KEY    = (0x8F, 0xB8, 0xF0)


def _config():
    with open(os.path.join(REPO_ROOT, "config.json")) as f:
        return json.load(f)


# --------------------------------------------------------------------------
# 22a — the parser
# --------------------------------------------------------------------------

def _tree_rows(node, prefix="", is_last=True, rows=None):
    """Pretty-print an AST node as a box-drawing tree.

    The dataclass repr is exhaustive and unreadable on a slide; this keeps the
    structure (which is the point — precedence and grouping) and drops the
    positional bookkeeping."""
    rows = [] if rows is None else rows
    branch = "└─ " if is_last else "├─ "
    stem = "   " if is_last else "│  "

    if isinstance(node, jast.Comparison):
        val = node.value
        shown = getattr(val, "value", val)
        if isinstance(shown, str):
            shown = f'"{shown}"'
        rows.append([(prefix + branch, FAINT, False),
                     ("Comparison ", DIM, False),
                     (f"{node.field} ", KEY, True),
                     (f"{node.op} ", FG, True),
                     (f"{shown}", GREEN, False)])
        return rows

    name = type(node).__name__
    kids = list(getattr(node, "operands", ()) or ())
    if not kids and hasattr(node, "operand"):
        kids = [node.operand]
    rows.append([(prefix + branch, FAINT, False), (name, FG, True)])
    for i, kid in enumerate(kids):
        _tree_rows(kid, prefix + stem, i == len(kids) - 1, rows)
    return rows


def build_parser_rows():
    good = 'state = opened AND (weight >= 5 OR labels = "epic::feature") ORDER BY due ASC'
    bad = "state = opened AND weigt >== 5"

    rows = [[("$ ", GREEN, True), ("jql.parse(", FG, False), (f'"{good}"', GREEN, False), (")", FG, False)],
            [("", FG, False)]]

    q = jql.parse(good)
    rows.append([("Query", FG, True)])
    sub = _tree_rows(q.where, "", not q.order_by)
    # re-root: the where subtree hangs off Query, and ORDER BY follows it
    rows.extend(sub)
    if q.order_by:
        keys = ", ".join(f"{k.field} {k.direction}" for k in q.order_by)
        rows.append([("└─ ", FAINT, False), ("order_by ", DIM, False), (keys, KEY, True)])

    rows.append([("", FG, False)])
    rows.append([("Precedence is NOT > AND > OR, so the parenthesised OR stays a single operand.",
                  FAINT, False)])
    rows.append([("", FG, False)])
    # The caret has to clear the echoed call, not just the query — the reported
    # offset indexes the query string, which starts this far into the line.
    lead = '$ jql.parse("'
    rows.append([("$ ", GREEN, True), ("jql.parse(", FG, False), (f'"{bad}"', GREEN, False), (")", FG, False)])

    try:
        jql.parse(bad)
        rows.append([("(no error — unexpected)", CLIENT, True)])
    except Exception as exc:                                       # noqa: BLE001
        offset = getattr(exc, "offset", None)
        if offset is None:                        # fall back to the message's own offset
            import re
            m = re.search(r"offset (\d+)", str(exc))
            offset = int(m.group(1)) if m else 0
        rows.append([(" " * (len(lead) + offset) + "^", CLIENT, True)])
        rows.append([(f"{type(exc).__name__}: {exc}", CLIENT, False)])
    return rows, "jql.parse — query text to AST  (#298)"


# --------------------------------------------------------------------------
# 22b — the field registry
# --------------------------------------------------------------------------

FIELD_ROWS = ["state", "type", "weight", "assignee", "updated", "due",
              "piid", "epic_type", "roam", "business_value", "summary", "status"]


def _mapping_for(spec):
    """(target, note, colour) — how this field reaches GitLab, read off the spec."""
    if spec.label_prefix:
        return f'labelName: ["{spec.label_prefix}::<value>"]', "scoped label", SERVER
    if spec.date_bound_args:
        return f"{spec.date_bound_args[0]} / {spec.date_bound_args[1]}", "date bounds", SERVER
    if spec.search_in:
        return f'search + in: [{", ".join(spec.search_in)}]', "text search", SERVER
    if spec.kind == "custom":
        return "— (widget in selection set)", "post-filter only", CLIENT
    if spec.graphql_arg:
        return f"{spec.graphql_arg}:", "native argument", SERVER
    if spec.wildcard_arg:
        # A deliberate correctness choice rather than a missing filter: these
        # fields match username *or* display name, so pushing the username
        # argument would silently drop display-name matches. IS EMPTY has no
        # such ambiguity and still pushes.
        return f"{spec.wildcard_arg}: NONE", "IS EMPTY pushes; equality local", CLIENT
    return "— (evaluated locally)", "post-filter by choice", CLIENT


def build_fields_rows():
    reg = FieldRegistry.from_config(_config())
    rows = [[("$ ", GREEN, True),
             ("FieldRegistry.from_config(config.json)  ", FG, False),
             ("# vocabulary is closed and generated", FAINT, False)],
            [("", FG, False)],
            [(f"{'FIELD':<16}", DIM, True), (f"{'KIND':<9}", DIM, True),
             (f"{'COMPILES TO':<40}", DIM, True), ("NOTE", DIM, True)],
            [("─" * 96, FAINT, False)]]

    for name in FIELD_ROWS:
        spec = reg.resolve(name)
        target, note, colour = _mapping_for(spec)
        alias = " (alias)" if name.lower() not in (spec.name.lower(),) else ""
        rows.append([(f"{name + alias:<16}", KEY, True),
                     (f"{spec.kind:<9}", DIM, False),
                     (f"{target:<40}", colour, False),
                     (note, FAINT, False)])

    rows.append([("", FG, False)])
    rows.append([("An unknown value fails locally, before any request, and lists the valid set:", FAINT, False)])
    try:
        jql.plan_query(jql.parse("piid = PI-3"), reg)
    except Exception as exc:                                       # noqa: BLE001
        msg = str(exc)
        head, _, tail = msg.partition("Valid values:")
        rows.append([("  " + head.strip(), CLIENT, False)])
        if tail:
            wrapped, line = [], "  Valid values:"
            for tok in tail.strip().split():
                if len(line) + len(tok) + 1 > 92:
                    wrapped.append(line)
                    line = "    " + tok
                else:
                    line += " " + tok
            wrapped.append(line)
            for w in wrapped:
                rows.append([(w, FAINT, False)])
    return rows, "jql.fields — one vocabulary over labels, columns and custom fields  (#299)"


# --------------------------------------------------------------------------
# 22d — the planner
# --------------------------------------------------------------------------

PLAN_EXAMPLES = [
    'state = opened AND labels = "epic::feature" AND weight >= 5 ORDER BY due ASC',
    "type = epic AND piid = 2026Q3 AND updated >= -4w ORDER BY weight DESC",
    "type = task AND state = opened",
]


def _fmt_value(v):
    """A plan variable as it should read on a slide: JSON for lists, quoted for
    strings, and timestamps trimmed to whole seconds."""
    from datetime import datetime
    if isinstance(v, datetime):
        return f'"{v.replace(microsecond=0).isoformat()}Z"'
    if isinstance(v, str):
        return f'"{v.split(".")[0] if _looks_like_ts(v) else v}"'
    return json.dumps(v, default=str)


def _looks_like_ts(s):
    return len(s) > 19 and s[:4].isdigit() and s[4] == "-" and "." in s


def _residue(query, plan, reg):
    """Fields whose predicate found no home in the pushed variables.

    Determined by asking each comparison's own spec where it *would* push and
    checking whether that key actually landed — so the annotation tracks the
    planner rather than a hand-written assumption about it."""
    out, seen = [], set()

    def walk(node):
        if isinstance(node, jast.Comparison):
            if node.field in seen:
                return
            seen.add(node.field)
            try:
                spec = reg.resolve(node.field)
            except Exception:                                      # noqa: BLE001
                return
            keys = set()
            if spec.graphql_arg:
                keys.add(spec.graphql_arg)
            if spec.date_bound_args:
                keys.update(spec.date_bound_args)
            if spec.label_prefix:
                vals = plan.variables.get("labelName") or []
                if any(str(v).lower().startswith(spec.label_prefix.lower() + "::") for v in vals):
                    return
                out.append(node.field)
                return
            if not keys or not (keys & set(plan.variables)):
                out.append(node.field)
            return
        for kid in (getattr(node, "operands", ()) or ()):
            walk(kid)
        if hasattr(node, "operand"):
            walk(node.operand)

    walk(query.where)
    return out


def build_planner_rows():
    reg = FieldRegistry.from_config(_config())
    rows = []
    for n, q in enumerate(PLAN_EXAMPLES):
        if n:
            rows.append([("", FG, False)])
            rows.append([("─" * 96, FAINT, False)])
            rows.append([("", FG, False)])
        rows.append([("$ ", GREEN, True), ("plan_query(", FG, False), (f'"{q}"', GREEN, False), (")", FG, False)])
        rows.append([("", FG, False)])

        parsed = jql.parse(q)
        plan = jql.plan_query(parsed, reg)

        if getattr(plan, "empty", False):
            rows.append([("  → ", FAINT, False),
                         ("no request issued", CLIENT, True),
                         ("  — the type constraint falls entirely outside the", FAINT, False)])
            rows.append([("     epic+issue scope, so the result is empty by construction.", FAINT, False)])
            continue

        rows.append([("  pushed to GitLab", SERVER, True)])
        for k in sorted(plan.variables):
            # plan.sort is already carried inside plan.variables["sort"]; print
            # it once, and trim resolved timestamps to seconds — the planner
            # keeps microseconds it never needs, and they only cost slide width.
            v = _fmt_value(plan.variables[k])
            rows.append([("    ", FG, False), (f"{k}: ", KEY, True), (v, FG, False)])

        res = _residue(parsed, plan, reg)
        rows.append([("  evaluated locally", CLIENT, True)])
        if res:
            for f in res:
                rows.append([("    ", FG, False), (f, CLIENT, False),
                             ("  — no server-side filter expresses this", FAINT, False)])
        else:
            rows.append([("    nothing — the envelope covers the whole query", FAINT, False)])
    return rows, "jql.planner — the conjunctive envelope pushed down  (#300)"


# --------------------------------------------------------------------------

def render(rows, title, out_path, font_size=17, line_h=25):
    reg = _font(False, font_size)
    ch_w = reg.getbbox("M")[2]
    pad_x, top = 26, 56
    cols = max(sum(len(t) for t, _, _ in row) for row in rows) + 2
    W = pad_x * 2 + ch_w * cols
    H = top + line_h * len(rows) + 20

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 34], fill=TITLEBAR)
    for i, c in enumerate(DOTS):
        cx = 22 + i * 22
        d.ellipse([cx - 7, 10, cx + 7, 24], fill=c)
    lf = _font(False, 15)
    lw = d.textbbox((0, 0), title, font=lf)[2]
    d.text(((W - lw) // 2, 9), title, font=lf, fill=DIM)

    y = top
    for row in rows:
        x = pad_x
        for text, color, bold in row:
            f = _font(bold, font_size)
            d.text((x, y), text, font=f, fill=color)
            x += int(d.textlength(text, font=f))
        y += line_h

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    print(f"OK   {out_path}  ({W}x{H})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots"))
    args = ap.parse_args()

    for builder, name in ((build_parser_rows, "22a-jql-parser.png"),
                          (build_fields_rows, "22b-jql-fields.png"),
                          (build_planner_rows, "22d-jql-planner.png")):
        rows, title = builder()
        render(rows, title, os.path.join(args.out_dir, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
