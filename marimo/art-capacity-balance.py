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
        Path("data/art-capacity-balance.json"),
        Path("../data/art-capacity-balance.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/art-capacity-balance.json").read())

    group = d["group"]
    arts  = d["arts"]
    return (Path, arts, d, group, json, mo)


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    Planned vs actual story-point load per team per PI.
    🔴 Over-loaded (>110%) &nbsp; 🟡 Under-loaded (<70%) &nbsp; ✅ Balanced (70–110%)
    """)
    return


@app.cell
def _(arts, mo):
    art_names = [a["art_name"] for a in arts]

    # Collect all PI IDs across all ARTs, sorted chronologically
    _seen = set()
    for _art in arts:
        for _pi in _art["pis"]:
            _seen.add(_pi["piid"])
    all_pis = sorted(_seen)

    art_selector = mo.ui.multiselect(
        art_names,
        value=art_names,
        label="ARTs",
    )
    pi_selector = mo.ui.dropdown(
        all_pis,
        value=all_pis[-1] if all_pis else None,
        label="PI",
    )
    mo.vstack([
        mo.md("## 📊 Capacity vs Load"),
        mo.hstack([art_selector, pi_selector], gap="2rem"),
    ])
    return (all_pis, art_names, art_selector, pi_selector)


@app.cell
def _(arts, art_selector, pi_selector, mo):
    _sel_arts = set(art_selector.value)
    _sel_pi   = pi_selector.value

    if not _sel_arts or not _sel_pi:
        _out = mo.md("_Select at least one ART and a PI._")
    else:
        _th = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
        _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"
        _sections = ""

        for _art in arts:
            if _art["art_name"] not in _sel_arts:
                continue

            _pi_data = next((p for p in _art["pis"] if p["piid"] == _sel_pi), None)
            if _pi_data is None:
                _sections += f"<h4><a href='{_art['art_url']}' target='_blank'>{_art['art_name']}</a></h4><p><em>No data for {_sel_pi}.</em></p>"
                continue

            _teams = _pi_data["teams"]
            if not _teams:
                _sections += f"<h4>{_art['art_name']}</h4><p><em>No team rows.</em></p>"
                continue

            _tbody = ""
            for _t in _teams:
                _pct = _t.get("load_pct", 0)
                if _pct > 110:
                    _pct_color = "color:#dc2626;font-weight:600"
                elif _pct < 70:
                    _pct_color = "color:#b45309;font-weight:600"
                else:
                    _pct_color = "color:#15803d;font-weight:600"
                _team_link = f'<a href="{_t["url"]}" target="_blank">{_t["name"]}</a>'
                _delta_str = f'+{_t["delta"]}' if _t["delta"] > 0 else str(_t["delta"])
                _tbody += (
                    f"<tr>"
                    f"<td style='padding:4px 10px'>{_team_link}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_t['planned']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_t['actual']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_delta_str}</td>"
                    f"<td style='padding:4px 10px;text-align:right;{_pct_color}'>{_pct}%</td>"
                    f"<td style='padding:4px 10px'>{_t['status']}</td>"
                    f"</tr>"
                )

            _date = _pi_data.get("date_range", "")
            _art_link = f'<a href="{_art["art_url"]}" target="_blank" style="color:#fff">{_art["art_name"]}</a>'
            _sections += f"""
            <h4 style="margin-top:20px">{_art_link} — VS: {_art['vs_name']}</h4>
            <p style="font-size:12px;color:#6b7280">{_sel_pi} &nbsp;|&nbsp; {_date}</p>
            <table style="border-collapse:collapse;font-size:13px;margin-bottom:16px">
              <thead><tr>
                <th style="{_th}">Team</th>
                <th style="{_th_r}">Planned SP</th>
                <th style="{_th_r}">Actual SP</th>
                <th style="{_th_r}">Delta</th>
                <th style="{_th_r}">Load%</th>
                <th style="{_th}">Status</th>
              </tr></thead>
              <tbody>{_tbody}</tbody>
            </table>
            """

        _out = mo.Html(f"<div>{_sections}</div>") if _sections else mo.md("_No data._")
    _out
    return


if __name__ == "__main__":
    app.run()
