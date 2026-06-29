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
        Path("data/issue-blocking.json"),
        Path("../data/issue-blocking.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import js
        import pyodide.http
        d = json.loads(pyodide.http.open_url(f"{js.self.location.origin}/data/issue-blocking.json").read())

    group         = d["group"]
    summary       = d["summary"]
    blocked_items = d["blocked_items"]
    return (Path, blocked_items, d, group, json, mo, summary)


@app.cell
def _(d, group, summary, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{group['name']}]({group['url']})

    Issue-to-issue `is_blocked_by` relationships across the portfolio.

    **Blocked issues:** {summary['total_blocked']} &nbsp;|&nbsp;
    **Total blocking relationships:** {summary['total_relationships']}
    """)
    return


@app.cell
def _(blocked_items, mo):
    if not blocked_items:
        _out = mo.md("✅ _No blocked issues found._")
    else:
        _th   = "padding:5px 10px;text-align:left;background:#f3f4f6"

        _rows = ""
        for _item in blocked_items:
            _ilink = (
                f'<a href="{_item["url"]}" target="_blank">⛔ {_item["title"]}</a>'
                if _item["url"] else f'⛔ {_item["title"]}'
            )
            _proj = _item.get("project_path") or "—"
            _epic = _item.get("epic_title") or "—"
            _blockers = _item.get("blockers", [])
            _blocked_by = "<br>".join(
                f'🔒 <a href="{_b["url"]}" target="_blank">{_b["title"]}</a>'
                if _b["url"] else f'🔒 {_b["title"]}'
                for _b in _blockers
            ) or "—"
            _rows += (
                f"<tr>"
                f"<td style='padding:5px 10px'>{_ilink}</td>"
                f"<td style='padding:5px 10px;font-size:12px'>{_proj}</td>"
                f"<td style='padding:5px 10px;font-size:12px'>{_epic}</td>"
                f"<td style='padding:5px 10px;font-size:12px'>{_blocked_by}</td>"
                f"</tr>"
            )

        _out = mo.Html(f"""
        <h3>Blocked Issues</h3>
        <table style="border-collapse:collapse;font-size:13px;width:100%">
          <thead><tr>
            <th style="{_th}">Blocked Issue</th>
            <th style="{_th}">Project</th>
            <th style="{_th}">Epic</th>
            <th style="{_th}">Blocked By</th>
          </tr></thead>
          <tbody>{_rows}</tbody>
        </table>
        """)
    _out
    return


if __name__ == "__main__":
    app.run()
