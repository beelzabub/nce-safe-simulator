import marimo

__generated_with = "0.17.6"
app = marimo.App(width="full", css_file="assets/peo-c4i.css", html_head_file="assets/peo-c4i-head.html")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    import json
    from pathlib import Path

    _candidates = [
        Path("data/portfolio.json"),
        Path("../data/portfolio.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/portfolio.json").read())

    group     = d["group"]
    summary   = d["summary"]
    hierarchy = d["hierarchy"]
    return (Path, d, group, hierarchy, json, mo, summary)


@app.cell
def _(mo):
    mo.Html("""
    <p>
      <a href="/quarto/portfolio.html"
         style="display:inline-block;padding:4px 12px;background:#0a2447;color:#fff;
                border-radius:4px;font-weight:600;text-decoration:none;font-size:13px">
        📊 Static Version
      </a>
    </p>
    """)
    return


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    SAFe portfolio hierarchy — Epics, Capabilities, and Features with delivery status.
    """)
    return


@app.cell
def _(summary, mo):
    # Summary KPI boxes
    _ICON_COLOR = {"✅": "#15803d", "❌": "#dc2626", "⚠️": "#b45309"}
    _boxes = ""
    for _s in summary:
        _risk_icon = "⚠️" if _s.get("at_risk") else "✅"
        _risk_color = _ICON_COLOR.get(_risk_icon, "#374151")
        _boxes += (
            f"<div style='flex:1;min-width:180px;border:1px solid #e5e7eb;"
            f"border-radius:6px;padding:10px 14px'>"
            f"<div style='font-size:13px;font-weight:600'>{_s['icon']} {_s['type']}</div>"
            f"<div style='font-size:12px;color:#6b7280;margin-top:4px'>"
            f"Total: {_s['total']} &nbsp;|&nbsp; Open: {_s['open']} &nbsp;|&nbsp; Closed: {_s['closed']}</div>"
            f"<div style='font-size:12px;color:#6b7280'>"
            f"Avg done: {_s['avg_pct_done']}% &nbsp;|&nbsp; Blocked: {_s['blocked_by']}</div>"
            f"<div style='font-size:12px;margin-top:4px;color:{_risk_color}'>"
            f"{_risk_icon} {'At risk' if _s['at_risk'] else 'On track'}</div>"
            f"</div>"
        )
    mo.Html(f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px'>{_boxes}</div>")
    return


@app.cell
def _(mo):
    level_selector = mo.ui.multiselect(
        ["Epic", "Capability", "Feature"],
        value=["Epic", "Capability", "Feature"],
        label="SAFe Level",
    )
    mo.vstack([mo.md("## Hierarchy"), level_selector])
    return (level_selector,)


@app.cell
def _(hierarchy, level_selector, mo):
    _sel_levels = set(level_selector.value)

    if not _sel_levels:
        _out = mo.md("_Select at least one SAFe level._")
    else:
        _th   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
        _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"

        def _node_rows(nodes, depth=0):
            _rows = ""
            for _n in nodes:
                if _n["type"] not in _sel_levels:
                    _rows += _node_rows(_n.get("children", []), depth)
                    continue
                _indent = "&nbsp;" * (depth * 4)
                _link = f'<a href="{_n["url"]}" target="_blank">{_n["icon"]} {_n["title"]}</a>'
                _state_color = "color:#6b7280" if _n["state"] == "Closed" else ""
                _drift_str = f'+{_n["drift"]}' if _n["drift"] > 0 else str(_n["drift"])
                _drift_color = "color:#dc2626" if _n["drift"] < 0 else ("color:#15803d" if _n["drift"] > 0 else "")
                _blocked_cell = "🔴" if _n["blocked"] else ""
                _rows += (
                    f"<tr>"
                    f"<td style='padding:4px 10px;font-size:12px'>{_indent}{_link}</td>"
                    f"<td style='padding:4px 10px;font-size:12px;color:#6b7280'>{_n['type']}</td>"
                    f"<td style='padding:4px 10px;font-size:12px;{_state_color}'>{_n['state']}</td>"
                    f"<td style='padding:4px 10px;text-align:right;font-size:12px'>{_n['pct_done']}%</td>"
                    f"<td style='padding:4px 10px;text-align:right;font-size:12px'>{_n['planned_weight']}</td>"
                    f"<td style='padding:4px 10px;text-align:right;font-size:12px'>{_n['actual_weight']}</td>"
                    f"<td style='padding:4px 10px;text-align:right;font-size:12px;{_drift_color}'>{_drift_str}</td>"
                    f"<td style='padding:4px 10px;text-align:center;font-size:12px'>{_blocked_cell}</td>"
                    f"<td style='padding:4px 10px;text-align:center;font-size:12px'>{_n['status_icon']}</td>"
                    f"</tr>"
                )
                _rows += _node_rows(_n.get("children", []), depth + 1)
            return _rows

        _tbody = _node_rows(hierarchy)
        _out = mo.Html(f"""
        <div style="overflow-x:auto">
        <table style="border-collapse:collapse;font-size:13px;width:100%">
          <thead><tr>
            <th style="{_th}">Title</th>
            <th style="{_th}">Level</th>
            <th style="{_th}">State</th>
            <th style="{_th_r}">Done%</th>
            <th style="{_th_r}">Planned SP</th>
            <th style="{_th_r}">Actual SP</th>
            <th style="{_th_r}">Drift</th>
            <th style="{_th}">Blocked</th>
            <th style="{_th}">Status</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        </div>
        """) if _tbody else mo.md("_No items match the selected levels._")
    _out
    return


if __name__ == "__main__":
    app.run()
