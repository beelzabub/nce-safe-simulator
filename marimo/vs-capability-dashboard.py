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
        Path("data/vs-capability-dashboard.json"),
        Path("../data/vs-capability-dashboard.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/vs-capability-dashboard.json").read())

    group         = d["group"]
    value_streams = d["value_streams"]
    return (Path, d, group, json, mo, value_streams)


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    Capability and direct-feature delivery by Value Stream and PI.
    """)
    return


@app.cell
def _(value_streams, mo):
    vs_names = [vs["vs_name"] for vs in value_streams]
    _pi_set  = set()
    for _vs in value_streams:
        for _pi in _vs.get("pis", []):
            _pi_set.add(_pi["piid"])
    pi_ids = sorted(_pi_set)

    vs_selector = mo.ui.multiselect(vs_names, value=vs_names, label="Value Streams")
    pi_selector = mo.ui.dropdown(
        pi_ids,
        value=pi_ids[-1] if pi_ids else None,
        label="PI",
    )
    mo.vstack([
        mo.md("## VS Capability Dashboard"),
        mo.hstack([vs_selector, pi_selector], gap="2rem"),
    ])
    return (pi_ids, pi_selector, vs_names, vs_selector)


@app.cell
def _(value_streams, vs_selector, pi_selector, mo):
    _sel_vs = set(vs_selector.value)
    _sel_pi = pi_selector.value

    if not _sel_vs or not _sel_pi:
        _out = mo.md("_Select at least one VS and a PI._")
    else:
        _th   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
        _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"
        _sections = ""

        def _items_table(items):
            if not items:
                return "<p><em>None.</em></p>"
            _tbody = "".join(
                f"<tr>"
                f"<td style='padding:4px 10px;font-size:12px'>"
                f"<a href='{it['url']}' target='_blank'>{it['title']}</a></td>"
                f"<td style='padding:4px 10px'>{it['state']}</td>"
                f"<td style='padding:4px 10px;text-align:right'>{it['pct_complete']}%</td>"
                f"<td style='padding:4px 10px;text-align:right'>{it['planned']}</td>"
                f"<td style='padding:4px 10px;text-align:right'>{it['actual']}</td>"
                f"<td style='padding:4px 10px'>{it['status']}</td>"
                f"<td style='padding:4px 10px'>{it.get('risk_reason','—')}</td>"
                f"</tr>"
                for it in items
            )
            return (
                f"<table style='border-collapse:collapse;font-size:13px;width:100%;margin-bottom:8px'>"
                f"<thead><tr>"
                f"<th style='{_th}'>Title</th><th style='{_th}'>State</th>"
                f"<th style='{_th_r}'>Done%</th><th style='{_th_r}'>Planned SP</th>"
                f"<th style='{_th_r}'>Actual SP</th><th style='{_th}'>Status</th>"
                f"<th style='{_th}'>Risk</th>"
                f"</tr></thead><tbody>{_tbody}</tbody></table>"
            )

        for _vs in value_streams:
            if _vs["vs_name"] not in _sel_vs:
                continue
            _pi_data = next((p for p in _vs.get("pis", []) if p["piid"] == _sel_pi), None)
            _vs_link = f'<a href="{_vs["vs_url"]}" target="_blank">{_vs["vs_name"]}</a>'
            if _pi_data is None:
                _sections += f"<h4 style='margin-top:20px'>{_vs_link}</h4><p><em>No data for {_sel_pi}.</em></p>"
                continue

            _caps    = _pi_data.get("capabilities", [])
            _directs = _pi_data.get("direct_features", [])
            _date    = _pi_data.get("date_range", "")

            _cap_html  = ""
            for _art_group in _caps:
                _art_link = f'<a href="{_art_group["art_url"]}" target="_blank">{_art_group["art_name"]}</a>'
                _cap_html += f"<p style='margin:8px 0 4px;font-weight:500'>{_art_link} — {_art_group['status']}</p>"
                _cap_html += _items_table(_art_group.get("items", []))

            _dir_html  = ""
            for _art_group in _directs:
                _art_link = f'<a href="{_art_group["art_url"]}" target="_blank">{_art_group["art_name"]}</a>'
                _dir_html += f"<p style='margin:8px 0 4px;font-weight:500'>{_art_link} — {_art_group['status']}</p>"
                _dir_html += _items_table(_art_group.get("items", []))

            _sections += f"""
            <h4 style="margin-top:24px">{_vs_link} &nbsp;|&nbsp; {_sel_pi} &nbsp;|&nbsp; {_date}</h4>
            <h5 style="margin:8px 0 4px">🧩 Capabilities</h5>
            {_cap_html if _cap_html else '<p><em>None.</em></p>'}
            <h5 style="margin:12px 0 4px">🛠️ Direct Features</h5>
            {_dir_html if _dir_html else '<p><em>None.</em></p>'}
            """

        _out = mo.Html(f"<div>{_sections}</div>") if _sections else mo.md("_No data._")
    _out
    return


if __name__ == "__main__":
    app.run()
