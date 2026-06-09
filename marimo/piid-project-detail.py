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
        Path("data/piid-project-detail.json"),
        Path("../data/piid-project-detail.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/piid-project-detail.json").read())

    group          = d["group"]
    project_labels = d["project_labels"]
    pis            = d["pis"]
    return (Path, d, group, json, mo, pis, project_labels)


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    Detailed story-point delivery per project label for a selected PI.
    """)
    return


@app.cell
def _(pis, mo):
    pi_ids = [p["piid"] for p in pis]
    pi_selector = mo.ui.dropdown(
        pi_ids,
        value=pi_ids[-1] if pi_ids else None,
        label="PI",
    )
    mo.vstack([mo.md("## Program PI Detail"), pi_selector])
    return (pi_ids, pi_selector)


@app.cell
def _(pis, pi_selector, mo):
    _sel = pi_selector.value
    _pi_data = next((p for p in pis if p["piid"] == _sel), None)

    if _pi_data is None:
        _out = mo.md("_No PI selected._")
    else:
        _meta = f"{_pi_data.get('phase_icon','') } {_pi_data['phase']} &nbsp;|&nbsp; {_pi_data['start']} – {_pi_data['end']} &nbsp;|&nbsp; PI {_pi_data['pct_pi']}% elapsed"
        _projects = _pi_data.get("projects", [])
        _has_data = [p for p in _projects if p.get("has_data")]

        if not _has_data:
            _out = mo.Html(f"<p><em>{_meta}</em></p><p>No project data for this PI.</p>")
        else:
            _th   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
            _th_r = "padding:6px 10px;text-align:right;background:#0a2447;color:#fff"
            _tbody = ""
            for _p in _projects:
                if not _p["has_data"]:
                    continue
                _board = f'<a href="{_p["board_url"]}" target="_blank">{_p["project"]}</a>' if _p.get("board_url") else _p["project"]
                _delta_str = f'+{_p["delta"]}' if _p["delta"] > 0 else str(_p["delta"])
                _pct_color = "color:#15803d;font-weight:600" if _p["avg_pct"] >= 80 else "color:#dc2626;font-weight:600"
                _tbody += (
                    f"<tr>"
                    f"<td style='padding:4px 10px'>{_board}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_p['total']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_p['open']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_p['planned']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_p['actual']}</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_delta_str}</td>"
                    f"<td style='padding:4px 10px;text-align:right;{_pct_color}'>{_p['avg_pct']}%</td>"
                    f"<td style='padding:4px 10px;text-align:right'>{_p['blocked']}</td>"
                    f"<td style='padding:4px 10px'>{_p['status']}</td>"
                    f"</tr>"
                )
            _out = mo.Html(f"""
            <p style="font-size:13px;color:#374151">{_meta}</p>
            <table style="border-collapse:collapse;font-size:13px">
              <thead><tr>
                <th style="{_th}">Project</th>
                <th style="{_th_r}">Total</th>
                <th style="{_th_r}">Open</th>
                <th style="{_th_r}">Planned SP</th>
                <th style="{_th_r}">Actual SP</th>
                <th style="{_th_r}">Delta</th>
                <th style="{_th_r}">Avg Done%</th>
                <th style="{_th_r}">Blocked</th>
                <th style="{_th}">Status</th>
              </tr></thead>
              <tbody>{_tbody}</tbody>
            </table>
            """)
    _out
    return


if __name__ == "__main__":
    app.run()
