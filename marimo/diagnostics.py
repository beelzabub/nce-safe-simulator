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
        Path("data/diagnostics.json"),
        Path("../data/diagnostics.json"),
    ]
    _data_file = next((p for p in _candidates if p.exists()), None)

    if _data_file is not None:
        d = json.loads(_data_file.read_text())
    else:
        import urllib.request
        d = json.loads(urllib.request.urlopen("/data/diagnostics.json").read())

    return (Path, d, json, mo)


@app.cell
def _(d, mo):
    mo.md(f"""
    **Report Date:** {d['report_date']} &nbsp;|&nbsp;
    **Group:** [{d['group']['name']}]({d['group']['url']})

    Environment and API compatibility check — software versions, REST/GraphQL capabilities,
    label validation, and overall report compatibility assessment.
    """)
    return


@app.cell
def _(d, mo):
    mo.md(d["content"])
    return


@app.cell
def _(d, mo):
    mo.md(f"> {d['verdict_md']}")
    return


if __name__ == "__main__":
    app.run()
