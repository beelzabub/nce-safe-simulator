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
        Path("data/piid-project.json"),
        Path("../data/piid-project.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/piid-project.json").read())

    group          = d["group"]
    project_labels = d["project_labels"]
    piid_labels    = d["piid_labels"]
    piid_meta      = d["piid_meta"]
    cells          = d["cells"]
    return (Path, cells, d, group, json, mo, piid_labels, piid_meta, project_labels)


@app.cell
def _(mo):
    mo.Html("""
    <p>
      <a href="/quarto/piid-project.html"
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

    Story-point delivery by project label × PI. Each cell shows completion status for
    all epics tagged with both labels.
    """)
    return


@app.cell
def _(piid_labels, piid_meta, project_labels, mo):
    pi_selector = mo.ui.multiselect(
        piid_labels,
        value=piid_labels,
        label="PIs",
    )
    proj_selector = mo.ui.multiselect(
        project_labels,
        value=project_labels,
        label="Projects",
    )
    mo.vstack([
        mo.md("## Program × PI Matrix"),
        mo.hstack([pi_selector, proj_selector], gap="2rem"),
    ])
    return (pi_selector, proj_selector)


@app.cell
def _(cells, piid_labels, piid_meta, pi_selector, proj_selector, mo):
    _sel_pis   = pi_selector.value
    _sel_projs = proj_selector.value

    if not _sel_pis or not _sel_projs:
        _out = mo.md("_Select at least one PI and one project._")
    else:
        _th     = "padding:6px 10px;text-align:center;background:#0a2447;color:#fff;white-space:nowrap"
        _th_l   = "padding:6px 10px;text-align:left;background:#0a2447;color:#fff"
        _header = "".join(f"<th style='{_th}'>{p}<br><span style='font-weight:400;font-size:11px'>{piid_meta.get(p,{}).get('phase','')}</span></th>" for p in _sel_pis)
        _tbody  = ""

        for _proj in _sel_projs:
            _row_cells = ""
            for _piid in _sel_pis:
                _key  = f"{_proj}|{_piid}"
                _cell = cells.get(_key) or {}
                _stat = _cell.get("status", "—")
                _tot  = _cell.get("total", 0)
                _detail = f"{_cell.get('avg_pct','—')}% done" if _tot else "—"
                _bg = ""
                if "Complete" in _stat:
                    _bg = "background:#dcfce7"
                elif "Incomplete" in _stat:
                    _bg = "background:#fee2e2"
                _row_cells += (
                    f"<td style='padding:5px 10px;text-align:center;{_bg}'>"
                    f"{_stat}<br><span style='font-size:11px;color:#6b7280'>{_detail}</span>"
                    f"</td>"
                )
            _tbody += f"<tr><td style='padding:5px 10px;white-space:nowrap;font-weight:500'>{_proj}</td>{_row_cells}</tr>"

        _out = mo.Html(f"""
        <div style="overflow-x:auto">
        <table style="border-collapse:collapse;font-size:13px">
          <thead><tr>
            <th style="{_th_l}">Project</th>
            {_header}
          </tr></thead>
          <tbody>{_tbody}</tbody>
        </table>
        </div>
        """)
    _out
    return


if __name__ == "__main__":
    app.run()
