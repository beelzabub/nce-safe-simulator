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
        Path("data/team-backlog.json"),
        Path("../data/team-backlog.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import js
        import pyodide.http
        d = json.loads(pyodide.http.open_url(f"{js.self.location.origin}/data/team-backlog.json").read())

    group = d["group"]
    teams = d["teams"]
    return (Path, d, group, json, mo, teams)


@app.cell
def _(d, group, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    All team backlog issues grouped by parent feature epic.
    """)
    return


@app.cell
def _(teams, mo):
    team_names = [f"{t['art_name']} / {t['team_name']}" for t in teams]
    team_selector = mo.ui.dropdown(
        team_names,
        value=team_names[0] if team_names else None,
        label="Team",
    )
    mo.vstack([mo.md("## Team Backlogs"), team_selector])
    return (team_names, team_selector)


@app.cell
def _(teams, team_names, team_selector, mo):
    _sel = team_selector.value
    if _sel is None:
        _out = mo.md("_No team selected._")
    else:
        _idx  = team_names.index(_sel)
        _team = teams[_idx]

        _team_link = f'<a href="{_team["team_url"]}" target="_blank">{_team["team_name"]}</a>'
        _backlog_link = (
            f' &nbsp;|&nbsp; <a href="{_team["backlog_url"]}" target="_blank">Backlog Project</a>'
            if _team.get("has_backlog_project") and _team.get("backlog_url") else ""
        )
        _summary = (
            f"<strong>VS:</strong> {_team['vs_name']} &nbsp;|&nbsp; "
            f"<strong>ART:</strong> {_team['art_name']} &nbsp;|&nbsp; "
            f"<strong>Team:</strong> {_team_link}{_backlog_link}<br>"
            f"<strong>Total issues:</strong> {_team['total']} &nbsp;|&nbsp; "
            f"<strong>Open:</strong> {_team['open']} &nbsp;|&nbsp; "
            f"<strong>Closed:</strong> {_team['closed']} &nbsp;|&nbsp; "
            f"<strong>Done:</strong> {_team['pct_done']}% &nbsp;|&nbsp; "
            f"<strong>Weight:</strong> {_team['closed_weight']}/{_team['total_weight']} SP"
        )

        _th   = "padding:5px 10px;text-align:left;background:#f3f4f6"
        _th_r = "padding:5px 10px;text-align:right;background:#f3f4f6"

        _feature_sections = ""
        for _feat in _team.get("by_feature", []):
            _feat_link = f'<a href="{_feat["epic_url"]}" target="_blank">{_feat["epic_title"]}</a>'
            _feat_state = _feat["epic_state"]
            _feat_pct   = _feat["pct_done"]
            _issues = _feat.get("issues", [])
            _issue_rows = "".join(
                f"<tr>"
                f"<td style='padding:3px 10px 3px 24px;font-size:12px'>"
                f"<a href='{iss['url']}' target='_blank'>#{iss['iid']} {iss['title']}</a></td>"
                f"<td style='padding:3px 10px;font-size:12px'>{iss['state']}</td>"
                f"<td style='padding:3px 10px;text-align:right;font-size:12px'>{iss.get('weight','—')}</td>"
                f"</tr>"
                for iss in _issues
            )
            _feature_sections += (
                f"<tr style='background:#f8fafc'>"
                f"<td style='padding:5px 10px;font-weight:500'>{_feat_link}</td>"
                f"<td style='padding:5px 10px'>{_feat_state}</td>"
                f"<td style='padding:5px 10px;text-align:right'>{_feat_pct}%</td>"
                f"</tr>"
                + _issue_rows
            )

        _unlinked = _team.get("unlinked", [])
        if _unlinked:
            _unlinked_rows = "".join(
                f"<tr>"
                f"<td style='padding:3px 10px;font-size:12px'>"
                f"<a href='{iss['url']}' target='_blank'>#{iss['iid']} {iss['title']}</a></td>"
                f"<td style='padding:3px 10px;font-size:12px'>{iss['state']}</td>"
                f"<td style='padding:3px 10px;text-align:right;font-size:12px'>{iss.get('weight','—')}</td>"
                f"</tr>"
                for iss in _unlinked
            )
            _unlinked_section = f"""
            <h5 style="margin-top:16px">Unlinked Issues</h5>
            <table style="border-collapse:collapse;font-size:13px;width:100%">
              <thead><tr>
                <th style="{_th}">Issue</th>
                <th style="{_th}">State</th>
                <th style="{_th_r}">Weight</th>
              </tr></thead>
              <tbody>{_unlinked_rows}</tbody>
            </table>
            """
        else:
            _unlinked_section = ""

        _out = mo.Html(f"""
        <p style="font-size:13px;margin-bottom:12px">{_summary}</p>
        <table style="border-collapse:collapse;font-size:13px;width:100%">
          <thead><tr>
            <th style="{_th}">Feature / Issue</th>
            <th style="{_th}">State</th>
            <th style="{_th_r}">Done% / Weight</th>
          </tr></thead>
          <tbody>{_feature_sections}</tbody>
        </table>
        {_unlinked_section}
        """)
    _out
    return


if __name__ == "__main__":
    app.run()
