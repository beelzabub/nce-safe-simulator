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
        Path("data/pi-predictability.json"),
        Path("../data/pi-predictability.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/pi-predictability.json").read())

    group = d["group"]
    pis   = d["pis"]
    rows  = d["rows"]
    port  = d["portfolio_row"]
    return (Path, d, group, json, mo, pis, port, rows)


@app.cell
def _(mo):
    mo.Html("""
    <p>
      <a href="/quarto/pi-predictability.html"
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

    Percentage of committed Features and Capabilities delivered in each PI.
    Target ≥ 80%. Consistently at 100% may indicate sandbagging; below 60% signals a systemic problem.
    """)
    return


@app.cell
def _(pis, rows, mo):
    art_names = [r["art_name"] for r in rows]
    art_pi_lookup = {
        r["art_name"]: {c["piid"]: c for c in r["cells"]}
        for r in rows
    }

    # PIs that have at least one numeric pct (past or current)
    active_pis = [
        p for p in pis
        if any(art_pi_lookup.get(a, {}).get(p, {}).get("pct") is not None for a in art_names)
    ]

    pi_selector = mo.ui.multiselect(
        active_pis,
        value=active_pis,
        label="PI Range",
    )
    art_selector = mo.ui.multiselect(
        art_names,
        value=art_names,
        label="ARTs",
    )
    mo.vstack([
        mo.md("## 🗺️ Predictability Scorecard"),
        mo.hstack([pi_selector, art_selector], gap="2rem"),
    ])
    return (active_pis, art_names, art_pi_lookup, art_selector, pi_selector)


@app.cell
def _(art_names, art_pi_lookup, art_selector, mo, pi_selector, port, rows):
    _sel_pis  = pi_selector.value
    _sel_arts = set(art_selector.value)

    if not _sel_pis or not _sel_arts:
        _out = mo.md("_Select at least one PI and one ART._")
    else:
        _STATUS_BG = {"past": "", "current": "#fef9c3", "future": "#eff6ff", "no_data": ""}

        _th = "padding:6px 10px;text-align:center;background:#0a2447;color:#fff;white-space:nowrap"
        _th_left = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"

        _header = "".join(f"<th style='{_th}'>{p}</th>" for p in _sel_pis)
        _tbody = ""

        for _row in rows:
            if _row["art_name"] not in _sel_arts:
                continue
            _art_link = f'<a href="{_row["art_url"]}" target="_blank">{_row["art_name"]}</a>'
            _cells = ""
            for _piid in _sel_pis:
                _cell = art_pi_lookup.get(_row["art_name"], {}).get(_piid, {})
                _pct  = _cell.get("pct")
                _lbl  = _cell.get("label", "—")
                _icon = _cell.get("icon", "—")
                _bg   = _STATUS_BG.get(_cell.get("status", ""), "")
                _bg_style = f"background:{_bg};" if _bg else ""
                if _pct is None:
                    _color = ""
                elif _pct >= 80:
                    _color = "color:#15803d;font-weight:600"
                elif _pct >= 60:
                    _color = "color:#b45309;font-weight:600"
                else:
                    _color = "color:#dc2626;font-weight:600"
                _cells += f"<td style='padding:5px 10px;text-align:center;{_bg_style}{_color}'>{_icon} {_lbl}</td>"
            _tbody += f"<tr><td style='padding:5px 10px;white-space:nowrap'>{_art_link}</td>{_cells}</tr>"

        # Portfolio row
        _port_lookup = {c["piid"]: c for c in (port or [])}
        _port_cells = ""
        for _piid in _sel_pis:
            _cell = _port_lookup.get(_piid, {})
            _pct  = _cell.get("pct")
            _lbl  = _cell.get("label", "—")
            _icon = _cell.get("icon", "—")
            if _pct is None:
                _color = ""
            elif _pct >= 80:
                _color = "color:#15803d;font-weight:600"
            elif _pct >= 60:
                _color = "color:#b45309;font-weight:600"
            else:
                _color = "color:#dc2626;font-weight:600"
            _port_cells += f"<td style='padding:5px 10px;text-align:center;{_color}'>{_icon} {_lbl}</td>"
        _tbody += f"<tr style='border-top:2px solid #0a2447'><td style='padding:5px 10px;font-weight:600'>Portfolio Total</td>{_port_cells}</tr>"

        _out = mo.Html(f"""
        <div style="overflow-x:auto">
        <table style="border-collapse:collapse;font-size:13px;min-width:600px">
          <thead>
            <tr>
              <th style="{_th_left}">ART</th>
              {_header}
            </tr>
          </thead>
          <tbody>{_tbody}</tbody>
        </table>
        </div>
        <p style="font-size:12px;color:#6b7280;margin-top:6px">
          ✅ ≥80% &nbsp; ⚠️ 60–79% &nbsp; ❌ &lt;60% &nbsp;
          🟡 In progress &nbsp; 🔵 Planned &nbsp; — No data
        </p>
        """)
    _out
    return


if __name__ == "__main__":
    app.run()
