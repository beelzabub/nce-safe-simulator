# Sprint-review deck tooling

Builds the sprint-review `.pptx` from three inputs: the SAIC branding template (fetched
from S3), live project metrics (GitLab issues/MRs + git history + SLOC), and screenshots
of the live web UI and Quarto reports captured with Playwright.

## Setup

```bash
python3 -m venv .venv-deck
source .venv-deck/bin/activate
pip install -r deck/requirements-deck.txt   # playwright, python-pptx, Pillow, PyYAML, segno
playwright install chromium
```

**System prerequisites** (not pip-installable — the pipeline shells out to these):

- **Graphviz** — the `dot` binary on `PATH`, for the architecture diagrams (`capture_diagrams.py`). Debian/Ubuntu `apt-get install graphviz`, macOS `brew install graphviz`.
- **DejaVu Sans Mono** font — for the CLI-menu render (`capture_cli_menu.py`). Present by default on most Linux (`fonts-dejavu`); macOS `brew install font-dejavu`. The script locates it across distros/macOS (known dirs → recursive scan → fontconfig `fc-match`), so no fixed path is assumed.
- **`glab`**, authenticated (`glab auth status`) — `build_deck.py` / `fetch_metrics.py` pull live issues & MRs.
- **`aws`**, authenticated — `build_deck.py` fetches the SAIC template from S3.

If Graphviz or the font is missing, `build_deck.py` skips those slides with a warning rather than failing; `glab`/`aws` are hard requirements for the build.

## Pipeline

```bash
make deck-screenshots   # Playwright: capture UI dialogs + Quarto reports (~10-15 min)
make deck               # fetch live metrics, then build the .pptx
```

Or run the steps directly:

```bash
python3 deck/capture_screenshots.py   # -> deck/screenshots/
python3 deck/capture_diagrams.py      # -> deck/screenshots/architecture/ (DoD/DoDAF diagrams)
python3 deck/capture_cli_menu.py      # -> deck/screenshots/cli-interactive-menu.png
python3 deck/fetch_metrics.py         # -> deck/metrics.json
python3 deck/build_deck.py            # -> deck/dist/NCE-Safe-Simulator-Sprint-Review.pptx
```

`capture_diagrams.py` renders the architecture view set (`diagrams/*.py` — the same
OV-1 / SV-1 / SV-2 / data-flow / DevSecOps views the container builds at image time)
into `deck/screenshots/architecture/`, where `build_deck.py` drops them onto the DoD
architecture slides. It needs the `diagrams` package (in `requirements.txt`) and the
Graphviz `dot` binary on PATH. If those images are absent, `build_deck.py` simply skips
the diagram slides (with a warning) — the rest of the deck still builds.

`capture_cli_menu.py` renders the CLI interactive main menu (`NceGitLab.py`'s
`_run_main_menu`) as a terminal-style PNG for the "CLI vs. UI" slide. The live menu is
interactive and prints runtime GitLab/server state, so this is a faithful static render
(menu rows mirror `_run_main_menu`; the status block uses sample values) — keep its `MENU`
list in sync if that menu changes. Needs only Pillow and the DejaVu Sans Mono system font;
if the image is absent, `build_deck.py` skips it and the slide keeps the UI half.

`build_deck.py` also pulls **every** project issue live via `glab` for the paginated
Issues table, so `glab` must be authenticated when building.

All three are read-only against the target app **except one deliberate exception**:
`live_run_shots` in `shots.yaml` selects a parameterless, explicitly read-only tool
("Diagnose") — selecting it in the UI launches it immediately, so this step performs one
real (but read-only) job execution against the target app on every capture run. No other
step submits any dialog (Launch/Save/Confirm are never clicked).

## Config files

- **`shots.yaml`** — the screenshot shot list: which UI dialogs to open (`ui_shots`),
  the one live-run demo (`live_run_shots`), and which Quarto report pages to capture
  (`quarto_shots`). Add a new tool or report page here and re-run `capture_screenshots.py`
  with `--only <name>` to add just that one shot without a full re-capture, or
  `--section quarto` to refresh just the report pages (skips the UI/live shots).

  Report pages are long scrollable documents, so a single full-page screenshot is
  unreadable on a slide. Tall `quarto_shots` are therefore **also** captured as 2–4
  readable, viewport-height crops taken down the page (portrait frame, 2× device
  scale); `build_deck.py` lays those out as a centered row of cards in the Appendix
  (`report_segments_slide`), while short pages keep the single full-bleed image. The
  crop count is automatic from page height; override per shot with `segments: <n>`
  (or `segments: false` to force a single image).
- **`capabilities.yaml`** — the deck's capability-area content: title, issue count, blurb,
  flagship-issue bullets, and (optionally) which captured screenshot to embed. This is a
  **maintained mapping, not re-derived automatically** — clustering issues into capability
  areas is a judgment call, and re-running that kind of semantic pass on every build would
  be non-deterministic and costly for no real benefit. When new issues land, add them here
  by hand (new bullet, bumped count, or a new capability block).
- **`metrics.json`** — generated by `fetch_metrics.py`, not committed (gitignored). Always
  reflects the current repo/GitLab state at build time: issue/MR counts via
  `glab api projects/:id/...` (no hardcoded project ID — resolved from the current git
  remote), commit velocity via `git log`, and SLOC via a directory walk.

## Template

The SAIC branding template lives in S3, not in this repo (`build_deck.py` fetches and
caches it under `deck/.template-cache/`, gitignored) — keeps a corporate branding file and
its embedded stock media out of git history. Override the source with
`--template-s3-path` or the `DECK_TEMPLATE_S3` env var if it ever moves.

Theme colors (blue/teal/green/yellow accents) are read from the template's own theme XML
at build time, not hardcoded — swapping the template file changes the deck's palette
automatically instead of silently mismatching it.

## Adding a new capability area or screenshot

1. Add the tool/report to `shots.yaml`, run `capture_screenshots.py --only <name>`.
2. Add or update the relevant block in `capabilities.yaml`, pointing `image:` at the new
   screenshot filename (relative to `deck/screenshots/`).
3. Re-run `make deck`.

Every screenshot captured also gets its own full-bleed slide in the Appendix
automatically (driven directly by `shots.yaml` + whatever files exist in
`deck/screenshots/`) — no separate list to keep in sync there.
