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
        Path("data/art-feature-status.json"),
        Path("../data/art-feature-status.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/art-feature-status.json").read())

    group         = d["group"]
    value_streams = d["value_streams"]
    return (Path, d, group, json, mo, value_streams)


@app.cell
def _(mo):
    mo.Html("""
    <p>
      <a href="/quarto/art-feature-status.html"
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

    Feature delivery status by ART and team for the current PI.
    """)
    return


@app.cell
def _(value_streams, mo):
    vs_names  = [vs["vs_name"] for vs in value_streams]
    # Collect all ART names and PI IDs
    _art_set = set()
    _pi_set  = set()
    for _vs in value_streams:
        for _art in _vs["arts"]:
            _art_set.add(_art["art_name"])
            for _team in _art["teams"]:
                for _f in _team.get("features", []):
                    if _f and _f.get("piid"):
                        _pi_set.add(_f["piid"])
    art_names = sorted(_art_set)
    pi_ids    = sorted(_pi_set)

    vs_selector  = mo.ui.multiselect(vs_names,  value=vs_names,  label="Value Streams")
    art_selector = mo.ui.multiselect(art_names, value=art_names, label="ARTs")
    pi_selector  = mo.ui.multiselect(pi_ids,    value=pi_ids,    label="PIs")

    mo.vstack([
        mo.md("## ART Feature Status"),
        mo.hstack([vs_selector, art_selector, pi_selector], gap="2rem"),
    ])
    return (art_names, art_selector, pi_ids, pi_selector, vs_names, vs_selector)


@app.cell
def _(value_streams, vs_selector, art_selector, pi_selector, mo):
    _sel_vs   = set(vs_selector.value)
    _sel_arts = set(art_selector.value)
    _sel_pis  = set(pi_selector.value)

    if not _sel_vs or not _sel_arts or not _sel_pis:
        _out = mo.md("_Select at least one VS, ART, and PI._")
    else:
        _th   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
        _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"
        _sections = ""

        for _vs in value_streams:
            if _vs["vs_name"] not in _sel_vs:
                continue
            for _art in _vs["arts"]:
                if _art["art_name"] not in _sel_arts:
                    continue
                _tbody = ""
                for _team in _art["teams"]:
                    for _f in _team.get("features", []):
                        if not _f or _f.get("piid") not in _sel_pis:
                            continue
                        _f_link = f'<a href="{_f["url"]}" target="_blank">{_f["title"]}</a>' if _f.get("url") else _f["title"]
                        _pct_color = "color:#15803d;font-weight:600" if _f["pct_complete"] >= 80 else "color:#dc2626;font-weight:600"
                        _tbody += (
                            f"<tr>"
                            f"<td style='padding:4px 10px;font-size:12px'>{_f_link}</td>"
                            f"<td style='padding:4px 10px'>{_team['team_name']}</td>"
                            f"<td style='padding:4px 10px'>{_f['piid']}</td>"
                            f"<td style='padding:4px 10px'>{_f['state']}</td>"
                            f"<td style='padding:4px 10px;text-align:right;{_pct_color}'>{_f['pct_complete']}%</td>"
                            f"<td style='padding:4px 10px;text-align:right'>{_f['planned']}</td>"
                            f"<td style='padding:4px 10px;text-align:right'>{_f['actual']}</td>"
                            f"<td style='padding:4px 10px'>{_f['status']}</td>"
                            f"<td style='padding:4px 10px'>{_f.get('risk_reason','—')}</td>"
                            f"</tr>"
                        )
                if _tbody:
                    _art_href = f'<a href="{_art["art_url"]}" target="_blank" style="font-size:12px;margin-left:8px">&#8599;</a>' if _art.get("art_url") else ""
                    _sections += f"""
                    <h4 style="margin-top:20px;color:#0a2447">{_vs['vs_name']} — {_art['art_name']}{_art_href}</h4>
                    <table style="border-collapse:collapse;font-size:13px;width:100%;margin-bottom:12px">
                      <thead><tr>
                        <th style="{_th}">Feature</th>
                        <th style="{_th}">Team</th>
                        <th style="{_th}">PI</th>
                        <th style="{_th}">State</th>
                        <th style="{_th_r}">Done%</th>
                        <th style="{_th_r}">Planned SP</th>
                        <th style="{_th_r}">Actual SP</th>
                        <th style="{_th}">Status</th>
                        <th style="{_th}">Risk</th>
                      </tr></thead>
                      <tbody>{_tbody}</tbody>
                    </table>
                    """

        _out = mo.Html(f"<div>{_sections}</div>") if _sections else mo.md("_No features match the selected filters._")
    _out
    return


if __name__ == "__main__":
    app.run()
