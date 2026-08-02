# Status deck tooling

Builds the status `.pptx` from three inputs: the SAIC branding template (fetched
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
- **`aws`** — **not needed for a normal build.** The deck template is committed in the repo (`deck/assets/template.pptx`); `aws` is only required if you re-bootstrap that template from S3 (`--template-s3-path`). See **Template** below.

If Graphviz or the font is missing, `build_deck.py` skips those slides with a warning rather than failing; `glab` is the only hard external-service requirement for the build (for live issue/MR data).

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
python3 deck/capture_test_log.py      # -> deck/screenshots/pytest-run.png
python3 deck/capture_git_workflow.py  # -> deck/screenshots/git-workflow{,-compact,-epic}.png
python3 deck/capture_ci_router.py     # -> deck/screenshots/{ci-recipe-router,security-scan-findings}.png
python3 deck/fetch_metrics.py         # -> deck/metrics.json
python3 deck/build_deck.py            # -> deck/dist/NCE-Safe-Simulator-Status.pptx
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

`capture_test_log.py` runs the Test Coverage Program's unit tests (report / tool /
pipeline — issues #24–#26) via pytest and renders an excerpt of the **real** output as a
terminal-style PNG for the "Test Coverage Program" capability slide. The command shown in
the rendered prompt is the command actually run; if the run doesn't pass cleanly the
script warns and the image shows the failure — fix the tests, don't ship the deck. Same
requirements as `capture_cli_menu.py` (Pillow + DejaVu Sans Mono).

`capture_git_workflow.py` draws the development loop as a git-graph (issue → UI-created
branch → `Refs #NNN` commits → tests on every push → MR review → merge to `develop` →
develop CI publish/deploy) in the deck palette. The wide render gets its own
"Development Workflow" slide; the compact render illustrates "Development Process &
Tools"; the epic render ("Development Workflow — Epics") shows an epic::epic issue's
own integration branch collecting its child-issue branches before merging to develop
once. Keep it in step with the conventions it depicts if they ever change. Same
requirements as `capture_cli_menu.py` (Pillow + DejaVu fonts).

`capture_ci_router.py` renders the CI recipe router (issue #283) as two deck
graphics: the router flow (the unchanged default pipeline vs. `RECIPE=<name>`
selecting a `ci-recipes/` child pipeline) and a findings panel for the security
suite's first verified `security-all` sweep. Both are faithful static renders in
the deck palette — keep its `CATALOG` list in step with `ci-recipes/`, and update
its `SCANNERS` numbers when a newer sweep becomes the one the deck should cite
(the current ones match the wiki's Security-scanning page). Same requirements as
`capture_cli_menu.py` (Pillow + DejaVu fonts).

`build_deck.py` also pulls **every** project issue live via `glab` for the paginated
Issues table, so `glab` must be authenticated when building.

All three are read-only against the target app **except one deliberate exception**:
`live_run_shots` in `shots.yaml` selects a parameterless, explicitly read-only tool
("Diagnose") — selecting it in the UI launches it immediately, so this step performs one
real (but read-only) job execution against the target app on every capture run. No other
step submits any dialog (Launch/Save/Confirm are never clicked).

## Config files

- **`shots.yaml`** — the screenshot shot list: which UI dialogs to open (`ui_shots`),
  the one live-run demo (`live_run_shots`), which Quarto report pages to capture
  (`quarto_shots`), and the `/login` front door (`login_shots`). Add a new tool or
  report page here and re-run `capture_screenshots.py` with `--only <name>` to add just
  that one shot without a full re-capture, or `--section quarto` / `--section login` to
  refresh just those (skips the other sections).

  `login_shots` is captured differently from `ui_shots`: it does **not** seed the auth
  gate (so the real background slideshow shows) but pre-acknowledges the DoD banner so
  the slideshow nav chevrons (issue #187) aren't hidden behind it. One full-bleed image,
  no dark/light toggle — the front door is always the photographic dark theme.

  Report pages are long scrollable documents, so a single full-page screenshot is
  unreadable on a slide. Tall `quarto_shots` are therefore **also** captured as 2–4
  readable, viewport-height crops taken down the page (portrait frame, 2× device
  scale); `build_deck.py` lays those out as a centered row of cards in the Appendix
  (`report_segments_slide`), while short pages keep the single full-bleed image. The
  crop count is automatic from page height; override per shot with `segments: <n>`
  (or `segments: false` to force a single image).
- **`capabilities.yaml`** — the deck's capability-area content: title, issue count, blurb,
  flagship-issue bullets, the full `all_issues` list, and (optionally) which captured
  screenshot to embed. This is a **maintained mapping, not re-derived automatically** —
  clustering issues into capability areas is a judgment call, and re-running that kind of
  semantic pass on every build would be non-deterministic and costly for no real benefit.
  When new issues land, add them here by hand (new bullet, bumped `count`, the new number
  appended to `all_issues`, or a new capability block). `count` must equal the number of
  entries in `all_issues`; the curated `bullets` are a highlighted subset. `build_deck.py`
  renders `all_issues` as a footer on each capability slide ("all N issues in this area:
  #…") so the curated highlights don't read as the complete list.
- **`metrics.json`** — generated by `fetch_metrics.py`, not committed (gitignored). Always
  reflects the current repo/GitLab state at build time: issue/MR counts via
  `glab api projects/:id/...` (no hardcoded project ID — resolved from the current git
  remote), commit velocity via `git log`, and SLOC via a directory walk.

## Deck structure & dating

Beyond the standing sections (overview, architecture, tech stack, metrics, full issues
table, capability areas, appendix), the deck opens with a **Latest Work** section — the
issues merged into `develop` since the previous weekly run, grouped by type
(features / enhancements / bugs / infrastructure), followed by **spotlight detail slides**
for the standout items. It closes with a **"Status Update Complete"** slide. The cover and
closing slides are stamped with the status date.

Both layouts are overflow-safe: the Latest Work list flows down two columns and, in a
heavy week, continues onto additional "continued" slides (a group that splits repeats its
heading as "(cont.)"); bullet lists everywhere step their font down (9 pt floor) when the
authored text would render taller than its box, so content never bleeds past the slide
edge.

**Two repos, one deck** (issue #268): alongside this repo the deck also covers the
**nce-git-ops** platform repo — its issues appear in the Latest Work groups, the issues
table, the KPI counts, and the spotlight-candidate list. References disambiguate the two
trackers: simulator issues stay bare `#N`, platform issues render as `nce-git-ops#N`
everywhere. The covered companions are listed in `COMPANION_PROJECTS` in `build_deck.py`;
a companion that isn't reachable (e.g. an enclave GitLab that only hosts this repo) is
skipped with a warning rather than failing the build. Simulator completions are derived
from merge commits into `develop`; companion completions from issue close dates (those
repos aren't checked out on the build box). Recurring **"Work state sync" housekeeping
issues are excluded** from every deck surface, for both repos. Commit-velocity and SLOC
metrics remain simulator-only (they come from the local git checkout). The platform repo
also has standing coverage: a "Platform GitOps — nce-git-ops" capability area in
`capabilities.yaml` and a "Platform GitOps" appendix section rendered from the committed
screenshots in `deck/assets/spotlight-extras/`.

Which issues get a spotlight is driven by a GitLab **`slides` label**: any issue tagged
`slides` (in either repo) and closed since the previous weekly run is a spotlight candidate. Spotlight *content*
is authored (not derived verbatim) into `deck/latest-work-spotlights.yaml` — a list of
`{title, subtitle, bullets[], images[], caption}` entries, one per slide, with related
issues grouped onto a single slide (e.g. the import/export hardening arc). `build_deck.py`
renders that file (`--spotlights`); with no file present it falls back to one auto-derived
slide per labeled issue. See **Weekly automation** below for how the file is produced each
week.

Dates are all stated in **Pacific** (the machine runs UTC). Two `build_deck.py` flags tune
them; both have sensible defaults so a plain `make deck` needs neither:

- `--since YYYY-MM-DD` — the Latest Work window start. Default: **the previous Friday 15:00
  Pacific** (the prior weekly run), so a Friday build covers the trailing 7 days *including
  the weekend just past* — Saturday/Sunday work is picked up in the following Friday's deck
  rather than skipped. The completed-work set is derived from merge-commit branch names
  (`<type>/<iid>-slug` merged into `develop`), so it needs no extra bookkeeping.
- `--review-date YYYY-MM-DD` — the date on the cover / closing slides. Default: **today
  (Pacific)**.

The output filename **always ends with a `-YYYYMMDD` postfix** (the review date), e.g.
`NCE-Safe-Simulator-Status-20260708.pptx`, so successive builds don't overwrite
each other. `deck/dist/` is gitignored.

## Weekly automation (issue #213)

On the single-box host, a **systemd timer** builds and emails the deck every **Friday
15:00 America/Los_Angeles** (DST-safe; the box is up 08:00–01:00 PT). Units live in
`deck/systemd/`; install with `sudo deck/systemd/install.sh`, then
`systemctl enable --now nce-status-deck.timer`.

The service runs `deck/weekly-status-deck.sh`, which:

1. checks out + pulls the build ref (`develop` by default; `WEEKLY_REF=<branch>` overrides
   for a pre-merge validation run),
2. `make redeploy` — rebuilds the image and hot-swaps the app container so screenshots are
   current — then health-checks the app,
3. captures screenshots and fetches metrics,
4. **authors the spotlights** headless: runs `claude -p` (scoped `--allowedTools`) against
   `deck/weekly-authoring-prompt.md`, which reads the week's `slides`-labeled closed issues
   and writes `deck/dist/latest-work-spotlights.gen.yaml`; if that step fails the build
   falls back to auto-derived spotlights rather than aborting. The same step also **keeps
   the background matter current**: `build_deck.py --print-coverage-gap` lists every closed
   issue (both repos) cited in no capability area, and the authoring step proposes homes
   for them in `deck/dist/capabilities-updates.gen.yaml` (extensions to existing areas
   and/or new areas — schema in the prompt),
5. builds the deck — proposed capability updates are merged in-memory
   (`--capabilities-updates`, default = the gen file) so the Friday deck is current before
   review, and the build warns about any closed issue still in no capability area —
   then uploads the dated `.pptx` to `s3://…/nce-safe-simulator/status/`,
6. **emails** via the SNS topic `nce-status-deck` (us-east-1) — a summary plus a 7-day
   presigned download link, noting when capability updates were proposed (review the gen
   file and fold accepted changes into `deck/capabilities.yaml` on a branch); any failure
   emails a failure notice instead.

Logs land in `deck/dist/weekly-logs/` and the systemd journal
(`journalctl -u nce-status-deck.service`). Prerequisites on the box: `glab`/`aws` auth, the
`claude` CLI, Docker, network to the live app, and `sns:Publish` on the instance role.

## Template

The deck's **template of record is committed in the repo** at `deck/assets/template.pptx`
(~3.3 MB) — the build has **no external template dependency**. It carries only the slide
masters, layouts, and theme (no content slides); `build_deck.py` creates the cover from
the Cover 1 layout, so no seed slides are needed.

Regenerate it from a built deck with `python3 deck/make_template.py` (strips every content
slide out, leaving masters/layouts/theme). It originated from the SAIC branding template,
which is no longer fetched at build time; to re-bootstrap from that original file, fetch it
once with `build_deck.py --template-s3-path s3://…` (or the `DECK_TEMPLATE_S3` env var),
build a deck, then run `make_template.py` on it. `aws` is needed only for that one-off.

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
