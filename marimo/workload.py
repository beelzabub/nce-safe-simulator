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
        Path("data/workload.json"),
        Path("../data/workload.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/workload.json").read())

    group = d["group"]
    pis   = d["pis"]
    return (Path, d, group, json, mo, pis)


@app.cell
def _(mo):
    mo.Html("""
    <p>
      <a href="/quarto/workload.html"
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

    Epic delivery workload by ART/team for a selected PI.
    """)
    return


@app.cell
def _(pis, mo):
    pi_ids = [p["piid"] for p in pis]
    # Collect all group names across all PIs
    _seen = set()
    for _pi in pis:
        for _g in _pi.get("groups", []):
            _seen.add(_g["name"])
    group_names = sorted(_seen)

    pi_selector = mo.ui.dropdown(
        pi_ids,
        value=pi_ids[-1] if pi_ids else None,
        label="PI",
    )
    group_selector = mo.ui.multiselect(
        group_names,
        value=group_names,
        label="ART / Team",
    )
    mo.vstack([
        mo.md("## ART-Team Workload"),
        mo.hstack([pi_selector, group_selector], gap="2rem"),
    ])
    return (group_names, group_selector, pi_ids, pi_selector)


@app.cell
def _(pis, pi_selector, group_selector, mo):
    _sel_pi     = pi_selector.value
    _sel_groups = set(group_selector.value)
    _pi_data    = next((p for p in pis if p["piid"] == _sel_pi), None)

    if _pi_data is None or not _sel_groups:
        _out = mo.md("_Select a PI and at least one group._")
    else:
        _groups = [g for g in _pi_data.get("groups", []) if g["name"] in _sel_groups]
        _meta   = f"{_pi_data['start']} – {_pi_data['end']} &nbsp;|&nbsp; PI {_pi_data['pct_pi']}% elapsed"

        if not _groups:
            _out = mo.Html(f"<p style='color:#6b7280;font-size:13px'>{_meta}</p><p><em>No matching groups for this PI.</em></p>")
        else:
            _th   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
            _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"
            _tbody = ""
            for _g in _groups:
                _name_link = f'<a href="{_g["url"]}" target="_blank">{_g["name"]}</a>'
                _epics_link = f'<a href="{_g["epics_url"]}" target="_blank">{_g["epic_count"]}</a>' if _g.get("epics_url") else str(_g["epic_count"])
                _delta_str = f'+{_g["delta"]}' if _g["delta"] > 0 else str(_g["delta"])
                _pct_color = "color:#15803d;font-weight:600" if _g["avg_pct"] >= 80 else "color:#dc2626;font-weight:600"
                _tbody += (
                    f"<tr>"
                    f"<td style='padding:4px 10px'>{_name_link}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_epics_link}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_g['planned']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_g['actual']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_delta_str}</td>"
                    f"<td style='padding:4px 10px;text-align:right;{_pct_color}'>{_g['avg_pct']}%</td>"
                    f"<td style='padding:4px 10px'>{_g['status']}</td>"
                    f"</tr>"
                )
            _out = mo.Html(f"""
            <p style="font-size:13px;color:#374151">{_meta}</p>
            <table style="border-collapse:collapse;font-size:13px">
              <thead><tr>
                <th style="{_th}">ART / Team</th>
                <th style="{_th_r}">Epics</th>
                <th style="{_th_r}">Planned SP</th>
                <th style="{_th_r}">Actual SP</th>
                <th style="{_th_r}">Delta</th>
                <th style="{_th_r}">Avg Done%</th>
                <th style="{_th}">Status</th>
              </tr></thead>
              <tbody>{_tbody}</tbody>
            </table>
            """)
    _out
    return


if __name__ == "__main__":
    app.run()
