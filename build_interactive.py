"""Export all Marimo WASM notebooks with a shared asset directory.

Each notebook is exported normally, then per-notebook asset directories are
consolidated into a single public/interactive/assets/ location and HTML
references are rewritten to point there.  This reduces the public/interactive/
footprint from ~400 MB (11 × 34 MB) to ~40 MB.
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
]

OUT = Path("public/interactive")
SHARED_ASSETS = OUT / "assets"
ASSET_URL = "/interactive/assets"


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


def rewrite_html(nb: str) -> None:
    """Remove per-notebook assets dir and rewrite asset references."""
    per_nb_assets = OUT / nb / "assets"
    if per_nb_assets.exists():
        shutil.rmtree(per_nb_assets)

    html_file = OUT / nb / "index.html"
    content = html_file.read_text(encoding="utf-8")
    content = re.sub(r'="\.\/assets\/', f'="{ASSET_URL}/', content)
    # appConfig JSON values reference css_file/html_head_file as bare "assets/..."
    content = re.sub(r'(?<=": ")assets/', f'{ASSET_URL}/', content)
    html_file.write_text(content, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for i, nb in enumerate(NOTEBOOKS):
        print(f"  {nb}...")
        export_notebook(nb)
        if i == 0:
            promote_assets(nb)
        rewrite_html(nb)

    size_mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"\nDone. {len(NOTEBOOKS)} notebooks, {size_mb:.0f} MB total.")
    print(f"Shared assets: {SHARED_ASSETS}")


if __name__ == "__main__":
    main()
