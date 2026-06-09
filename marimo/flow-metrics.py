import marimo

__generated_with = "0.17.6"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    import json
    from pathlib import Path

    _candidates = [
        Path("data/flow-metrics.json"),
        Path("../data/flow-metrics.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/flow-metrics.json").read())

    group    = d["group"]
    velocity = d["velocity"]
    load     = d["load"]
    dist     = d["distribution"]
    ft       = d["flow_time"]
    pred     = d["predictability"]
    return (Path, d, dist, ft, group, json, load, mo, pred, velocity)


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})
    """)
    return


@app.cell
def _(velocity, mo):
    all_pis = [r["piid"] for r in velocity]
    pi_selector = mo.ui.multiselect(
        all_pis,
        value=all_pis,
        label="PI Range",
    )
    mo.vstack([mo.md("### Filter"), pi_selector])
    return (all_pis, pi_selector)


@app.cell
def _(velocity, pi_selector, mo):
    _sel = set(pi_selector.value)
    _rows = [r for r in velocity if r["piid"] in _sel]

    if not _rows:
        _out = mo.md("_No PIs selected._")
    else:
        _th = "padding:6px 10px;text-align:left;background:#f3f4f6"
        _th_r = "padding:6px 10px;text-align:right;background:#f3f4f6"
        _tbody = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px'>{r['piid']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('features', 0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('capabilities', 0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'><strong>{r['total']}</strong></td>"
            f"</tr>"
            for r in _rows
        )
        _out = mo.Html(f"""
        <h3>📈 Flow Velocity — Delivered per PI</h3>
        <table style="border-collapse:collapse;font-size:13px">
          <thead><tr>
            <th style="{_th}">PI</th>
            <th style="{_th_r}">Features</th>
            <th style="{_th_r}">Capabilities</th>
            <th style="{_th_r}">Total</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        """)
    _out
    return


@app.cell
def _(load, pi_selector, mo):
    _sel = set(pi_selector.value)
    _rows = [r for r in load if r["piid"] in _sel]

    if not _rows:
        _out = mo.md("_No PIs selected._")
    else:
        _th = "padding:6px 10px;text-align:left;background:#f3f4f6"
        _th_r = "padding:6px 10px;text-align:right;background:#f3f4f6"
        _tbody = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px'>{r['piid']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('features', 0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('capabilities', 0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('epics', 0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'><strong>{r['total']}</strong></td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('planned_weight', '—')}</td>"
            f"</tr>"
            for r in _rows
        )
        _out = mo.Html(f"""
        <h3>📦 Flow Load — Work in Progress</h3>
        <table style="border-collapse:collapse;font-size:13px">
          <thead><tr>
            <th style="{_th}">PI</th>
            <th style="{_th_r}">Features</th>
            <th style="{_th_r}">Capabilities</th>
            <th style="{_th_r}">Epics</th>
            <th style="{_th_r}">Total Items</th>
            <th style="{_th_r}">Planned Weight</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        """)
    _out
    return


@app.cell
def _(pred, pi_selector, mo):
    _sel = set(pi_selector.value)
    _rows = [r for r in pred if r["piid"] in _sel]

    if not _rows:
        _out = mo.md("_No PIs selected._")
    else:
        _th = "padding:6px 10px;text-align:left;background:#f3f4f6"
        _th_r = "padding:6px 10px;text-align:right;background:#f3f4f6"
        _tbody = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px'>{r['piid']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('committed', '—')}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('delivered', '—')}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['icon']} {r['pct']}%</td>"
            f"</tr>"
            for r in _rows
        )
        _out = mo.Html(f"""
        <h3>🎯 Flow Predictability</h3>
        <table style="border-collapse:collapse;font-size:13px">
          <thead><tr>
            <th style="{_th}">PI</th>
            <th style="{_th_r}">Committed</th>
            <th style="{_th_r}">Delivered</th>
            <th style="{_th_r}">Predictability</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        <p style="font-size:12px;color:#6b7280;margin-top:4px">
          ✅ ≥80% &nbsp; 🟡 60–79% &nbsp; ❌ &lt;60%
        </p>
        """)
    _out
    return


@app.cell
def _(dist, mo):
    _by_type = dist.get("by_type", [])
    if not _by_type:
        _out = mo.md("_No distribution data._")
    else:
        _th = "padding:6px 10px;text-align:left;background:#f3f4f6"
        _th_r = "padding:6px 10px;text-align:right;background:#f3f4f6"
        _tbody = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px'>{r['type']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['count']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['pct_items']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('planned_weight', '—')}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r.get('pct_weight', '—')}</td>"
            f"</tr>"
            for r in _by_type
        )
        _out = mo.Html(f"""
        <h3>🔀 Flow Distribution — By SAFe Hierarchy Level</h3>
        <p style="font-size:12px;color:#6b7280">All-time totals — not filtered by PI range.</p>
        <table style="border-collapse:collapse;font-size:13px">
          <thead><tr>
            <th style="{_th}">Type</th>
            <th style="{_th_r}">Items</th>
            <th style="{_th_r}">% Items</th>
            <th style="{_th_r}">Planned Weight</th>
            <th style="{_th_r}">% Weight</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        """)
    _out
    return


@app.cell
def _(ft, mo):
    _th = "padding:6px 10px;text-align:left;background:#f3f4f6"
    _th_r = "padding:6px 10px;text-align:right;background:#f3f4f6"

    def _age_table(title, rows):
        if not rows:
            return f"<p><em>No {title.lower()} data.</em></p>"
        _tbody = "".join(
            f"<tr>"
            f"<td style='padding:4px 10px'>{r['type']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['count']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['avg_days']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['min_days']}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{r['max_days']}</td>"
            f"</tr>"
            for r in rows
        )
        return f"""
        <h4>{title}</h4>
        <table style="border-collapse:collapse;font-size:13px;margin-bottom:16px">
          <thead><tr>
            <th style="{_th}">Type</th>
            <th style="{_th_r}">Count</th>
            <th style="{_th_r}">Avg Days</th>
            <th style="{_th_r}">Min Days</th>
            <th style="{_th_r}">Max Days</th>
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        """

    _open_html   = _age_table("Age of Open Items (days since created)", ft.get("open_ages", []))
    _closed_html = _age_table("Cycle Time — Closed Items", ft.get("closed_cycles", [])) if ft.get("has_closed_data") else ""

    mo.Html(f"""
    <h3>⏱ Flow Time — Cycle Time Analysis</h3>
    <p style="font-size:12px;color:#6b7280">All-time aggregate — not filtered by PI range.</p>
    {_open_html}
    {_closed_html}
    """)
    return


if __name__ == "__main__":
    app.run()
