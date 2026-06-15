"""Export all Marimo WASM notebooks with a shared asset directory.

Each notebook is exported normally, then per-notebook asset directories are
consolidated into a single public/interactive/assets/ location and HTML
references are rewritten to point there.  This reduces the public/interactive/
footprint from ~400 MB (11 × 34 MB) to ~40 MB.

Custom brand assets (peo-c4i.css, peo-c4i-head.html) are inlined directly
into each notebook's HTML rather than relying on Marimo's runtime css_file/
html_head_file loading, which does not bundle these files in WASM exports.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

NOTEBOOKS = [
    "health-dashboard",
    "pi-predictability",
    "flow-metrics",
    "art-capacity-balance",
    "piid-project",
    "piid-project-detail",
    "workload",
    "art-feature-status",
    "vs-capability-dashboard",
    "team-backlog",
    "portfolio",
    "diagnostics",
]

OUT = Path("public/interactive")
SHARED_ASSETS = OUT / "assets"
ASSET_URL = "/interactive/assets"
CUSTOM_ASSETS = Path("marimo/assets")


def export_notebook(nb: str) -> None:
    nb_dir = OUT / nb
    result = subprocess.run(
        ["marimo", "export", "html-wasm", f"marimo/{nb}.py", "-o", str(nb_dir), "-f"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)


def promote_assets(nb: str) -> None:
    """Move first notebook's assets to the shared location."""
    per_nb_assets = OUT / nb / "assets"
    if not per_nb_assets.exists():
        return
    if SHARED_ASSETS.exists():
        shutil.rmtree(SHARED_ASSETS)
    shutil.copytree(per_nb_assets, SHARED_ASSETS)


def rewrite_html(nb: str, inline_css: str, inline_head: str) -> None:
    """Remove per-notebook assets dir, rewrite asset references, and inline brand assets."""
    per_nb_assets = OUT / nb / "assets"
    if per_nb_assets.exists():
        shutil.rmtree(per_nb_assets)

    html_file = OUT / nb / "index.html"
    content = html_file.read_text(encoding="utf-8")

    # Rewrite framework asset references to shared location
    content = re.sub(r'="\.\/assets\/', f'="{ASSET_URL}/', content)

    # Null out css_file/html_head_file in the WASM mount config so Marimo's
    # runtime doesn't try to fetch them (paths were removed when we consolidated
    # assets; the CSS and head HTML are already inlined below).
    content = re.sub(r'"css_file"\s*:\s*"[^"]*"', '"css_file": null', content)
    content = re.sub(r'"html_head_file"\s*:\s*"[^"]*"', '"html_head_file": null', content)

    # Inline brand CSS before </head>
    if inline_css:
        content = content.replace("</head>", f"<style>{inline_css}</style>\n</head>", 1)

    # Inline nav/head HTML before </head>
    if inline_head:
        content = content.replace("</head>", f"{inline_head}\n</head>", 1)

    html_file.write_text(content, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    css_file = CUSTOM_ASSETS / "peo-c4i.css"
    head_file = CUSTOM_ASSETS / "peo-c4i-head.html"
    inline_css  = css_file.read_text(encoding="utf-8")  if css_file.exists()  else ""
    inline_head = head_file.read_text(encoding="utf-8") if head_file.exists() else ""

    for i, nb in enumerate(NOTEBOOKS):
        print(f"  {nb}...")
        export_notebook(nb)
        if i == 0:
            promote_assets(nb)
        rewrite_html(nb, inline_css, inline_head)

    size_mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"\nDone. {len(NOTEBOOKS)} notebooks, {size_mb:.0f} MB total.")
    print(f"Shared assets: {SHARED_ASSETS}")


if __name__ == "__main__":
    main()
