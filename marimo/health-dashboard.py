import marimo

__generated_with = "0.17.6"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    # DATA LOADING PATTERN (copy for each notebook):
    # 1. Try local file paths for `marimo edit` dev workflow.
    # 2. Fall back to HTTP fetch for WASM context (Pyodide patches urllib.request).
    #    The WASM page is served from public/interactive/, data from public/data/,
    #    so the relative URL resolves correctly at runtime.
    import json
    from pathlib import Path

    _candidates = [
        Path("data/health-dashboard.json"),
        Path("../data/health-dashboard.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("../data/health-dashboard.json").read())

    group   = d["group"]
    pi      = d["pi"]
    port    = d["portfolio"]
    vs_rows = d["vs_rows"]
    blocked = d["top_blocked"]
    at_risk = d["at_risk_epics"]
    return (at_risk, blocked, d, group, json, mo, pi, port, vs_rows)


@app.cell
def _(d, group, mo, pi):
    pi_label   = pi["current"] or "—"
    pi_elapsed = f"{pi['pct_elapsed']}% elapsed" if pi["pct_elapsed"] else "Not started"
    pi_range   = f"{pi['start']} – {pi['end']}" if pi["start"] and pi["end"] else "—"

    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    **Current PI:** {pi_label} &nbsp;|&nbsp;
    **PI Period:** {pi_range} &nbsp;|&nbsp;
    **PI Elapsed:** {pi_elapsed}
    """)
    return (pi_elapsed, pi_label, pi_range)


@app.cell
def _(port, mo, pi):
    tl  = port["tl_schedule"]
    pct = pi["pct_elapsed"]
    rows = [
        ("Total Epics (all PIs)",          port["epics_total"]),
        ("Epics in Current PI",            port["pi_epics_count"]),
        (f"Current PI Progress {tl}",      f"{port['pct_done']}% done ({pct}% elapsed)"),
        ("Blocked Epics (current PI)",     port["blocked_total"]),
        ("Epics with Active ROAM Risks",   port["risk_epics"]),
        ("Unassigned to PI",               port["unassigned"]),
    ]
    if port["capacity_str"] not in ("—", ""):
        rows.append(("Story Points (current PI)", port["capacity_str"]))

    _rows_html = "".join(
        f"<tr><td style='padding:4px 8px'>{l}</td><td style='padding:4px 8px'><strong>{v}</strong></td></tr>"
        for l, v in rows
    )
    mo.Html(f"""
    <h3>Portfolio Summary</h3>
    <table style="border-collapse:collapse;max-width:500px">
      <thead>
        <tr style="background:#f3f4f6">
          <th style="padding:4px 8px;text-align:left">Metric</th>
          <th style="padding:4px 8px;text-align:left">Value</th>
        </tr>
      </thead>
      <tbody>{_rows_html}</tbody>
    </table>
    """)
    return (rows, tl)


@app.cell
def _(vs_rows, mo):
    vs_names     = [r["vs"]["name"] for r in vs_rows]
    vs_selector  = mo.ui.multiselect(
        vs_names,
        value=vs_names,
        label="Value Streams",
    )
    mo.vstack([mo.md("## Value Stream Status"), vs_selector])
    return (vs_names, vs_selector)


@app.cell
def _(vs_rows, vs_selector, mo):
    _selected = set(vs_selector.value)
    _filtered = [r for r in vs_rows if r["vs"]["name"] in _selected]

    if _filtered:
        _rows_html = ""
        for _row in _filtered:
            _vs      = _row["vs"]
            _vs_link = f'<a href="{_vs["web_url"]}" target="_blank">{_vs["name"]}</a>'
            _rows_html += (
                f"<tr>"
                f"<td style='padding:4px 8px'>{_vs_link}</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_row['overall']}</td>"
                f"<td style='padding:4px 8px'>{_row['tl_sched']} {_row['sched_detail']}</td>"
                f"<td style='padding:4px 8px'>{_row['tl_cap']} {_row['cap_detail']}</td>"
                f"<td style='padding:4px 8px'>{_row['tl_risk']} {_row['risk_detail']}</td>"
                f"<td style='padding:4px 8px'>{_row['tl_block']} {_row['block_detail']}</td>"
                f"<td style='padding:4px 8px'>{_row['pi_epics']} in PI / {_row['epics_total']} total</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_row['unassigned']}</td>"
                f"</tr>"
            )
        _th = "padding:6px 8px;text-align:left;background:#f3f4f6;border-bottom:2px solid #e5e7eb"
        _table = mo.Html(f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr>
              <th style="{_th}">Value Stream</th>
              <th style="{_th}">Status</th>
              <th style="{_th}">Schedule</th>
              <th style="{_th}">Capacity</th>
              <th style="{_th}">Risk</th>
              <th style="{_th}">Blocking</th>
              <th style="{_th}">Epics</th>
              <th style="{_th}">Unassigned</th>
            </tr>
          </thead>
          <tbody>{_rows_html}</tbody>
        </table>
        """)
    else:
        _table = mo.md("_No Value Streams selected._")
    _table
    return


@app.cell
def _(blocked, at_risk, mo):
    ICONS = {"Epic": "🏆", "Capability": "🧩", "Feature": "🛠️"}

    # Blocked epics
    if blocked:
        _rows_html = ""
        for _item in blocked:
            _icon = ICONS.get(_item["type"], "🏆")
            _link = (
                f'<a href="{_item["url"]}" target="_blank">{_icon} {_item["title"]}</a>'
                if _item["url"] else f'{_icon} {_item["title"]}'
            )
            _rows_html += (
                f"<tr>"
                f"<td style='padding:4px 8px'>{_link}</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_item['n_blockers']}</td>"
                f"<td style='padding:4px 8px'>{_item['piid']}</td>"
                f"</tr>"
            )
        _blocked_table = mo.Html(f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#f3f4f6">
              <th style="padding:6px 8px;text-align:left">Epic</th>
              <th style="padding:6px 8px">Blockers</th>
              <th style="padding:6px 8px;text-align:left">PI</th>
            </tr>
          </thead>
          <tbody>{_rows_html}</tbody>
        </table>
        """)
    else:
        _blocked_table = mo.md("✅ No blocked epics found.")

    # At-risk epics
    if at_risk:
        _rows_html = ""
        for _item in at_risk:
            _icon = ICONS.get(_item["type"], "🏆")
            _link = (
                f'<a href="{_item["url"]}" target="_blank">{_icon} {_item["title"]}</a>'
                if _item["url"] else f'{_icon} {_item["title"]}'
            )
            _rows_html += (
                f"<tr>"
                f"<td style='padding:4px 8px'>{_link}</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_item['pct_done']}%</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_item['pct_elapsed']}%</td>"
                f"<td style='padding:4px 8px;text-align:center'>{_item['gap']}pp</td>"
                f"<td style='padding:4px 8px'>{_item['weight_str']}</td>"
                f"<td style='padding:4px 8px'>{_item['piid']}</td>"
                f"</tr>"
            )
        _risk_table = mo.Html(f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#f3f4f6">
              <th style="padding:6px 8px;text-align:left">Epic</th>
              <th style="padding:6px 8px">Done</th>
              <th style="padding:6px 8px">PI Elapsed</th>
              <th style="padding:6px 8px">Gap</th>
              <th style="padding:6px 8px;text-align:left">Weight</th>
              <th style="padding:6px 8px;text-align:left">PI</th>
            </tr>
          </thead>
          <tbody>{_rows_html}</tbody>
        </table>
        """)
    else:
        _risk_table = mo.md("✅ No epics significantly behind schedule.")

    mo.vstack([
        mo.md("## Needs Attention"),
        mo.md("### ⛔ Blocked Epics"),
        _blocked_table,
        mo.md("### 🟡 At-Risk Epics (behind schedule)"),
        _risk_table,
    ])
    return (ICONS,)


if __name__ == "__main__":
    app.run()
