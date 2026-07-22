# NCE GitLab SAFe Tooling

Python automation for GitLab groups organised around the **Scaled Agile Framework (SAFe)** hierarchy. Generates realistic lorem test data, manages the Epic → Capability/Feature → Issue tree across multiple groups, and publishes a suite of portfolio-level reports to a GitLab Group Wiki.

---

## SAFe Hierarchy Model

```
Root Group  (Portfolio)
│   Portfolio Epics  ⚡
│   Direct Features  🔖  ← Features parented straight to a Portfolio Epic
│
├── Value Stream 01
│   Capabilities  💠  ← cross-ART/VS deliverables
│   ├── ART 01
│   │   Capabilities  💠
│   │   ├── Team 01
│   │   │   Features  🔖
│   │   │   Team Backlog project  (Issues linked to Features)
│   │   └── Team 02  ...
│   └── ART 02  ...
└── Value Stream 02  ...
```

Epic types are distinguished by GitLab labels (`Epic`, `Capability`, `Feature`).

**Capabilities** are cross-ART/VS deliverables — work that spans multiple teams or Value Streams. **Direct Features** are Features parented straight to a Portfolio Epic with no Capability wrapper; they are owned by a single ART and represent the majority of portfolio work items.

Items are further tagged with a **project label** (`project::DO`, `project::RTSO`, …) and a **PIID label** (`PIID::2026Q3`, …) that ties each work item to a Program Increment quarter.

---

## Project Structure

```
NceGitLab.py       # Main class (thin compositor) + CLI entry point
config.json        # Configuration (URL, token, labels, weights, defaults)
requirements.txt

mixins/            # Mixin modules — NceGitLab inherits from all of these
  __init__.py
  utils.py         # GraphQL helpers, PI math, portfolio metrics calculation
  groups.py        # Group CRUD
  projects.py      # Project CRUD
  epics.py         # Epic CRUD operations
  issues.py        # Issue operations
  milestones.py    # Milestone operations
  wiki.py          # Wiki page upload/delete
  labels.py        # Label create/delete
  bootstrap.py     # Lorem data generation, SAFe hierarchy creation, cleanup
  reports.py       # All portfolio report generators
  tools.py         # Interactive utility tool menu and registry
  importexport.py  # Epic and issue import/export (CSV and JSON)
```

---

## Installation

**Requirements:**

- **Core** — Python 3.9+, Node.js 18+, Git, and a GitLab Personal Access Token with `api` scope.
- **Report & diagram generation** — building reports in the `plotly` / `interactive` / `all` formats shells out to two system binaries that are **not** installed by `pip`/`npm`:
  - **[Quarto CLI](https://quarto.org/docs/get-started/)** — renders the static Quarto site (`mixins/serve.py` runs `quarto render`). The container pins **v1.9.38** (`Dockerfile`) and installs it from this project's package registry, not GitHub (see [Vendored Quarto](#vendored-quarto-quarto)).
  - **[Graphviz](https://graphviz.org/download/)** — the `dot` binary must be on `PATH`; the `diagrams` package uses it to render the architecture views.

  Markdown-only reports (`--formats markdown`, the default) need neither. Quick install — Debian/Ubuntu: `apt-get install graphviz` + Quarto's `.deb`; macOS: `brew install graphviz quarto`.

### 1 — Clone

```bash
git clone https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator.git
cd nce-safe-simulator
```

### 2 — Python virtual environment

Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (Command Prompt):
```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3 — Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

This compiles the Vue app into `public/app/`.

### 4 — Configure

Copy the template, then edit your local copy (which stays out of git):

```bash
cp config.example.json config.json
```

Set at minimum:

| Field | Description |
|---|---|
| `url` | GitLab instance URL (default `https://gitlab.com`) |
| `parent_group` | Display name of the SAFe portfolio root group |
| `gitlab_namespace` | URL slug of the namespace that will contain the root group |

**The GitLab token is supplied via the `GITLAB_TOKEN` environment variable, not the config file** — `config.json` is git-ignored and ships with a blank `private_token` so the secret never lands in the repo. Export a Personal Access Token with `api` scope:

```bash
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx   # add to ~/.bashrc to persist
```

Token resolution precedence: `GITLAB_TOKEN` env → `config.json` `private_token` → `ACCESS_TOKEN` (deprecated). All other settings can be edited in-browser via the ⚙ Config button once the server is running.

### 5 — Start the web server

Linux / macOS:
```bash
python3 NceGitLab.py --serve
```

Windows:
```bat
python NceGitLab.py --serve
```

The server starts on `http://localhost` (port **80**). Open `http://localhost/app/` in your browser.
Run the same command again to stop it.

> **Port override:** the default port is `80`. To use a different port, set `defaults.serve.port` in `config.json`. The Docker image publishes the container's port 80 as host port 4645 (`-p 4645:80`), so a containerized run is reached at `http://localhost:4645/app/`.

---

## Configuration

Start from the template (`cp config.example.json config.json`) and edit your local copy. Leave `private_token` blank and supply the token via the `GITLAB_TOKEN` environment variable (see [Configure](#4--configure)):

```json
{
    "url": "https://gitlab.com",
    "private_token": "",
    "parent_group": "my-portfolio-group",
    "gitlab_namespace": "my-top-level-namespace",
    "project_labels": ["project::DO", "project::RTSO", "project::DCGS"],
    "piid_labels": ["PIID::2026Q3", "PIID::2026Q4", "PIID::2027Q1"],
    "epic_type_labels": ["Epic", "Capability", "Feature"],
    "risk_labels": ["risk::high", "risk::medium", "risk::low"],
    "work_type_labels": ["type::feature", "type::enabler", "type::infrastructure", "type::defect"],
    "lifecycle_labels": ["lifecycle::funnel", "lifecycle::analyzing", "lifecycle::backlog", "lifecycle::implementing", "lifecycle::done"],
    "wsjf_labels": {
        "urgency": ["wsjf-urgency::1", "wsjf-urgency::2", "wsjf-urgency::3", "wsjf-urgency::5", "wsjf-urgency::8", "wsjf-urgency::13"],
        "risk":    ["wsjf-risk::1", "wsjf-risk::2", "wsjf-risk::3", "wsjf-risk::5", "wsjf-risk::8", "wsjf-risk::13"]
    },
    "fibonacci_weights": [1, 2, 3, 5, 8, 13],
    "epic_type_planned_weights": {
        "Feature":    [3, 5, 8, 13],
        "Capability": [21, 34, 55, 89],
        "Epic":       [89, 144, 233, 377]
    },
    "defaults": {
        "bootstrap": {
            "num_value_streams":    {"min": 1, "max": 4, "desired": 2},
            "num_arts":             {"min": 1, "max": 3, "desired": 2},
            "num_teams":            {"min": 1, "max": 4, "desired": 2},
            "portfolio_epics":      {"min": 3, "max": 8, "desired": 5},
            "vs_caps_per_vs":       {"min": 2, "max": 5, "desired": 3},
            "art_caps_per_art":     {"min": 2, "max": 6, "desired": 4},
            "features_per_team":    {"min": 3, "max": 6, "desired": 4},
            "direct_feature_ratio": 0.70,
            "seed_blocks":          true,
            "epic_block_percent":   12,
            "issue_block_percent":  8
        },
        "tools": {
            "close_percent":                30.0,
            "generate_epic_blocks_count":   10,
            "generate_issue_blocks_count":  10,
            "simulate_pi_progress_percent": 50.0,
            "generate_issues_count":        5,
            "weight_drift_threshold":       20.0,
            "set_risk_labels_percent":      15.0,
            "set_wsjf_labels_percent":      20.0
        }
    }
}
```

| Field | Description |
|---|---|
| `url` | GitLab instance URL |
| `private_token` | Personal access token with `api` scope |
| `parent_group` | Name of the root group to create/manage |
| `gitlab_namespace` | Parent namespace for root group creation |
| `project_labels` | Labels representing programs or workstreams (`project::*`) |
| `piid_labels` | `PIID::YYYYQn` labels mapping work to PI quarters |
| `epic_type_labels` | SAFe hierarchy tier labels — scoped (`epic::epic`, `epic::capability`, `epic::feature`) or plain (`Epic`, `Capability`, `Feature`). Display names are derived by stripping the scope prefix and capitalizing. All mixins, reports, and Marimo pages resolve tier names from this list; changing it reconfigures the entire application. |
| `risk_labels` | `risk::*` labels used by the Risk Register report and `set-risk-labels` tool |
| `work_type_labels` | `type::*` labels classifying epics by SAFe work type (feature, enabler, infrastructure, defect) |
| `lifecycle_labels` | `lifecycle::*` labels representing SAFe Portfolio Kanban states (funnel → done) |
| `wsjf_labels` | Fibonacci label sets for WSJF Time Criticality and Risk Reduction — `wsjf-urgency::N`, `wsjf-risk::N` (N from 1–13); Business Value uses the native custom field |
| `fibonacci_weights` | Valid issue story-point values |
| `epic_type_planned_weights` | Valid planned-weight pools per epic type |
| `stuck_thresholds` | Per-lifecycle-state age limits (days) the Epic Lifecycle report uses to flag "stuck" epics (see below) |
| `defaults.bootstrap` | Default counts and ratios for `--create` (see below) |
| `defaults.tools` | Default parameter values for utility tools (see below) |
| `auth` | Login-page / front-door settings (see below); future AAA options land here |

### Authentication (`auth` section)

Settings for the web UI login page (epic #135). All keys are optional — the server applies these defaults when the section (or the whole `config.json`) is absent:

```json
"auth": {
    "method": "none",
    "dod_banner_enabled": true,
    "background": {
        "rotation_seconds": 15,
        "max_images": 12,
        "source": "repo",
        "staging_s3": {
            "bucket": "nce-safe-sim-assets",
            "prefix": "login-backgrounds/",
            "presign_ttl_seconds": 3600
        }
    }
}
```

| Field | Description |
|---|---|
| `method` | Authentication enforcement: `none` (default — no server enforcement, cosmetic front door) or `basic` (dev-only hardcoded credential `asdf`/`asdf`; every request must authenticate). AAA methods (CAC/PKI, OIDC, SAML, LDAP, local) plug in here as they land |
| `dod_banner_enabled` | Show the standard DoD Notice and Consent banner on the login page (surfaced to the client via `GET /api/config`) |
| `background.rotation_seconds` | Background slideshow rotation interval |
| `background.max_images` | Maximum images returned to the client per page load |
| `background.source` | `repo` (default) serves the committed images; `s3-test` presigns the staging bucket for live curation preview |
| `background.staging_s3` | Staging bucket/prefix and presigned-URL TTL — used only by `s3-test` mode and the curation tooling |

The images themselves are committed to the repo under `media/login-backgrounds/` with a `credits.json` credit-line manifest (see the README in that directory). The server exposes them via:

- `GET /api/auth/backgrounds` — server-shuffled list: `images[0]` is the random initial background, the rest are the client's lazy-loaded rotation pool. Degrades to `{"fallback": true, "images": []}` (HTTP 200) when no images are available, so the login page always renders.
- `GET /api/auth/backgrounds/{name}` — serves a single committed image with long-lived cache headers.

With `method: "basic"` the server enforces authentication on **everything** — all other `/api/*` endpoints (including the durable job surface report/tool runs use), `/reports`, `/logs`, `/quarto`, and `/data` return 401 (`WWW-Authenticate: Basic`) unless the request carries the session cookie from `POST /api/auth/login` or an `Authorization: Basic` header (`curl -u asdf:asdf ...`). The login surface itself (SPA shell and assets, login/session/logout endpoints, background imagery, curated `GET /api/config`) stays open so the front door can render. The dev credential is hardcoded and dev-only; it never appears in config.

### Label Conventions

All label families are defined in `config.json` and created in GitLab at bootstrap time. Reports discover labels dynamically from the live snapshot rather than from config, so they work on any group.

| Family | Prefix | Purpose |
|---|---|---|
| **Project** | `project::` | Maps epics to programmes/workstreams (e.g. `project::DO`, `project::RTSO`) |
| **PIID** | `PIID::` | Maps work to Program Increment quarters (`PIID::2026Q3`) |
| **Epic type** | _(bare label)_ | `Epic`, `Capability`, `Feature` — defines hierarchy level |
| **Risk** | `risk::` | `risk::high`, `risk::medium`, `risk::low` — feeds the Risk Register |
| **Work type** | `type::` | `type::feature`, `type::enabler`, `type::infrastructure`, `type::defect` — SAFe work classification for Flow Distribution metric |
| **Lifecycle** | `lifecycle::` | `lifecycle::funnel` → `lifecycle::analyzing` → `lifecycle::backlog` → `lifecycle::implementing` → `lifecycle::done` — SAFe Portfolio Kanban states for Epic Lifecycle report |
| **WSJF** | `wsjf-urgency::`, `wsjf-risk::` | Fibonacci 1–13 scores for Time Criticality and Risk Reduction; Business Value comes from the native custom field; job size comes from planned weight |

#### `defaults.bootstrap`

Each count key accepts either a plain integer **or** a range object:

```json
"num_value_streams": 2                           // fixed
"num_value_streams": {"desired": 2}              // always 2
"num_value_streams": {"min": 1, "max": 4}        // random between 1 and 4
"num_value_streams": {"min": 1, "max": 4, "desired": 2}  // always 2 (desired takes precedence)
```

At run time `--create` and `--scaffold` resolve each range to a single integer and print a structure summary before creating anything.

| Key | Default | Description |
|---|---|---|
| `num_value_streams` | `{"min":1,"max":4,"desired":2}` | Value Stream subgroups |
| `num_arts` | `{"min":1,"max":3,"desired":2}` | ART subgroups per Value Stream |
| `num_teams` | `{"min":1,"max":4,"desired":2}` | Team subgroups per ART |
| `portfolio_epics` | `{"min":3,"max":8,"desired":5}` | Portfolio Epics at the root group |
| `vs_caps_per_vs` | `{"min":2,"max":5,"desired":3}` | Capabilities per Value Stream |
| `art_caps_per_art` | `{"min":2,"max":6,"desired":4}` | Capabilities per ART |
| `features_per_team` | `{"min":3,"max":6,"desired":4}` | Features per Team |
| `direct_feature_ratio` | `0.70` | Fraction of Features linked directly to Portfolio Epics; remainder link via Capability chain |
| `seed_blocks` | `true` | Seed epic→epic and issue→issue blocking during `--create` so the blocking and WSJF _at risk_ reports have data out of the box |
| `epic_block_percent` | `12` | Percent of epics to block when `seed_blocks` is on (a normal-portfolio level, not block-heavy) |
| `issue_block_percent` | `8` | Percent of open issues to block when `seed_blocks` is on |

#### `defaults.tools`

| Key | Default | Description |
|---|---|---|
| `close_percent` | `30.0` | Default % for `close-percent` tool |
| `generate_epic_blocks_count` | `10` | Default block count for `generate-epic-blocks` |
| `generate_issue_blocks_count` | `10` | Default block count for `generate-issue-blocks` |
| `simulate_pi_progress_percent` | `50.0` | Default % closure for `simulate-pi-progress` |
| `generate_issues_count` | `5` | Default issues per Feature for `generate-issues` |
| `weight_drift_threshold` | `20.0` | Default drift % for `weight-drift-check` |
| `set_risk_labels_percent` | `15.0` | Default % of open epics to label for `set-risk-labels` |
| `set_wsjf_labels_percent` | `20.0` | Default % of open epics to label for `set-wsjf-labels` |

#### Stuck Item Thresholds

The Epic Lifecycle / Portfolio Kanban report flags epics that have sat too long in an early lifecycle state. An epic is "stuck" when its age (from `created_at`) **exceeds** the threshold for its `lifecycle::` state. Only the three pre-delivery states are flagged; `implementing` and `done` have no threshold. Edit these in the web UI under **Config → Reports**.

| Key | Default | Description |
|---|---|---|
| `lifecycle::funnel` | `90` | Days before a funnel epic is flagged as stale |
| `lifecycle::analyzing` | `30` | Days before an analyzing epic is flagged as stuck (Lean Business Case overdue) |
| `lifecycle::backlog` | `60` | Days before a backlog epic is flagged as stuck (awaiting capacity too long) |

Omitting `stuck_thresholds`, or any individual key, falls back to these defaults.

### Environment Variable Overrides

Any config value can be overridden at runtime without editing the file:

| Variable | Overrides |
|---|---|
| `GITLAB_TOKEN` | `private_token` (preferred — keeps the secret out of `config.json`) |
| `ACCESS_TOKEN` | `private_token` (**deprecated** — use `GITLAB_TOKEN`) |
| `GROUP_NAME` | `parent_group` |
| `PROJECT_LABELS` | `project_labels` (comma-separated) |
| `PIID_LABELS` | `piid_labels` (comma-separated) |
| `EPIC_TYPE_LABELS` | `epic_type_labels` (comma-separated) |
| `RISK_LABELS` | `risk_labels` (comma-separated) |
| `WORK_TYPE_LABELS` | `work_type_labels` (comma-separated) |
| `LIFECYCLE_LABELS` | `lifecycle_labels` (comma-separated) |
| `ROAM_LABELS` | `roam_labels` (comma-separated) |
| `FIBONACCI_WEIGHTS` | `fibonacci_weights` (comma-separated integers) |

In a GitLab pipeline, set these as [CI/CD variables](https://docs.gitlab.com/ee/ci/variables/) under **Settings → CI/CD → Variables**. Mark `GITLAB_TOKEN` as **Masked** (and **Protected**) to keep the token out of job logs. `GITLAB_TOKEN` and `GROUP_NAME` are the minimum required for the report jobs.

---

## Usage

### Main CLI

Running with no arguments launches the **interactive main menu** — a numbered prompt covering Reports, Utilities, Scaffold, Create, and Clean. All options are also available as flags for non-interactive / scripted use.

```bash
python3 NceGitLab.py                      # Interactive main menu (default)

# Core operations
python3 NceGitLab.py -c  / --clean        # Delete all group data
python3 NceGitLab.py -C  / --create       # Bootstrap a full SAFe lorem data set
python3 NceGitLab.py -a  / --all          # clean → create → report in sequence

# Reports
python3 NceGitLab.py -r                   # Interactive report menu
python3 NceGitLab.py -r all               # Run all reports
python3 NceGitLab.py -r portfolio         # Run a single report by key
python3 NceGitLab.py -r --last            # Reuse most recent data snapshot (no API fetch)
python3 NceGitLab.py -r --reuse-data DIR  # Load snapshot from a specific directory

# Utility tools
python3 NceGitLab.py -ut                  # Interactive utility tool menu
python3 NceGitLab.py -ut audit-labels     # Run a single tool by key
python3 NceGitLab.py -ut set-wsjf-labels --open_only  # Pass tool params as flags

# Diagnostics
python3 NceGitLab.py -D  / --diagnose     # Print environment, API, and label diagnostics to stdout

# Scaffold
python3 NceGitLab.py -s                   # Create SAFe group/project structure (prompted)
python3 NceGitLab.py -s my/group          # Create structure under a specific group
```

Each phase logs start/stop times and elapsed duration. `--all` prints a consolidated timing table on completion. Ctrl-C prints a clean interrupt message showing which phase was running.

#### Data snapshots

`-r` fetches live data from GitLab on every run and saves a timestamped JSON snapshot under `reports/YYYY-MM-DD/HH-MM-SS/data/`. These flags control fetching and reuse:

| Flag | Behaviour |
|------|-----------|
| `--last` | Automatically finds and loads the most recent **complete** snapshot |
| `--reuse-data DIR` | Loads the snapshot from the directory you specify |
| `--full-fetch` | Force every fetch phase even for a partial report selection (#183) |

**Selective fetch (#183).** A report run fetches only the snapshot phases the selected reports actually read, derived automatically from the registry — no picker. The four phases are **A** portfolio metrics (`epics.json` + `issues.json`, always run), **B** epic blocking graph (`blocking_graph.json`), **C** issue blocking graph (`issue_blocking.json`), and **D** group/project walk (`groups.json` + `projects.json`). So `-r portfolio` skips B, C, and D — roughly half the API calls of a full run — while `-r blocking orphan-issues` runs A + B + D and skips C. Running **all** reports (or `--full-fetch`) fetches everything.

A run that skips a phase writes a **partial** snapshot: it records a `snapshot.manifest.json` listing the files fetched but is *not* marked `snapshot.complete`, so `--last`, the server, and the Portfolio Explorer only ever pick up **complete** snapshots — a partial testing snapshot can never silently feed them. `--reuse-data DIR` will reuse a partial snapshot but warns loudly if it doesn't cover the reports you selected.

A typical demo cycle:

```bash
# Tear down yesterday's data, rebuild, and publish fresh reports
python3 NceGitLab.py --all
```

### Login background curation

The web UI login page rotates through U.S. Navy imagery committed under `media/login-backgrounds/` (with photographer credit lines in `credits.json`). `scripts/sync_login_backgrounds.py` manages the pipeline that gets images there — an S3 staging bucket (`nce-safe-sim-assets` by default, configurable via `auth.background.staging_s3` in `config.json`) holds candidates so they can be previewed live before being committed:

```bash
# Optimize (1920px JPEG, EXIF stripped) and upload candidates for preview.
# Credit lines come from an optional credits.json next to the source images.
python3 scripts/sync_login_backgrounds.py stage ~/navy-candidates/

python3 scripts/sync_login_backgrounds.py list        # see what's staged
# Preview staged candidates on the login page: set auth.background.source
# to "s3-test" in config.json, then reload /login.

# Pull the keepers into media/login-backgrounds/ + merge credits, then commit
python3 scripts/sync_login_backgrounds.py promote     # or: promote name.jpg ...
```

Images are curated public-domain U.S. Government works (DVIDS / navy.mil / Wikimedia Commons); every image keeps its credit line, and appearance of DoD visual information does not imply endorsement. The current set spans classic PMW-120 fleet themes plus NAVCENT-released imagery from Operation Epic Fury (Tomahawk launches, Arabian Gulf strike-group formations, night flight-deck operations). The server never reads the staging bucket in production (`auth.background.source: "repo"`).

### Web UI

A Vue 3 browser interface provides an alternative to the CLI for running utility tools and viewing reports. The backend is a FastAPI server that exposes the same tools over HTTP.

#### Starting the web UI

**Production (recommended for demos):**

```bash
cd frontend && npm run build && cd ..
python3 NceGitLab.py --serve          # serves on http://localhost (port 80)
```

Navigate to `http://localhost/app/`.

**Development (hot-reload, edit frontend without rebuilding):**

```bash
python3 NceGitLab.py --serve          # backend on port 80
cd frontend && npm run dev            # Vite dev server on http://localhost:5173
```

Navigate to `http://localhost:5173/app/`. The dev server proxies `/api` and all non-app paths to the Python backend, so reports and API calls work without a production build.

#### Login page

`/app/login` is the UI's front door: a full-viewport slideshow of the committed U.S. Navy imagery (crossfading every `auth.background.rotation_seconds`, with a slow Ken Burns drift and the photographer's credit in the corner) with the sign-in form fully dissolved at rest — only a faint "Sign in" affordance remains. A faint NCE mark floats top-center (the NavBar's white emblem, ~40% opacity, dimming further once the card is summoned) so the resting page still identifies the site. Any intent signal (hovering or focusing the affordance, clicking the page, Tab, or typing) materializes the card with the username field focused; Escape or ~25 s of inactivity with untouched fields dissolves it back, while typed content keeps it up. The server picks the first image at random and the client lazily preloads the rest; with no images configured the page falls back to the bundled hero image. Once more than one background has loaded, subtle left/right chevrons (and the ← / → arrow keys while the card is dissolved) step through the imagery manually, each move resetting the rotation clock so the chosen slide gets its full dwell. The backend serves the app shell for hard loads of client-side routes (SPA history fallback), so deep links like `/app/login` work in production.

Before the sign-in card becomes interactive, the standard DoD Notice and Consent banner (DTM 08-060) fronts the page and requires explicit acknowledgment **per logon attempt**: it reappears after an explicit sign-out and after any other end of access — the 12-hour session TTL lapsing or a server restart wiping the session store (#163) — while a mid-form reload before ever signing in does not re-nag. Toggle it with `auth.dod_banner_enabled` in `config.json`.

Unauthenticated navigation anywhere in the app redirects to `/login`. Behavior depends on `auth.method`: with `none` the gate is cosmetic (any non-empty credentials accepted, client-side session flag, no security); with `basic` the sign-in card round-trips to `POST /api/auth/login`, wrong credentials are rejected inline, and the server enforces authentication on every endpoint (see the Authentication section above). The NavBar's **Sign out** control ends the session and returns to `/login` without closing the browser; sign-out (like any end of access) clears the DoD banner acknowledgment so the next logon attempt re-presents consent. Gate logic lives in `frontend/src/composables/useAuthGate.js`, where the AAA methods will plug in. Login-page settings, including the auth method, are editable in the Config dialog's **Auth** tab.

#### Layout

| Area | Content |
|------|---------|
| Top nav | PMW 120 / NCE Safe Simulator wordmark; running-job count badge; dark ↔ light theme toggle; Status panel toggle |
| Left sidebar | Multi-function side panel with **Tools / Reports / Analysis** tabs (active tab persists across reloads; epic #165). **Tools** hosts the job picker (collapsible groups) + Run Reports button. **Reports** browses snapshot runs and opens wiki pages in the in-app markdown viewer, with its own Run Reports… button. **Analysis** hosts portfolio analysis tools computed from snapshots — first up, the **Portfolio Explorer** |
| Main pane | Owned by the active side-panel tab: **Tools** shows the job runner (one card per launched job with streaming log output, plus the docked CLI command bar — a single truncated line by default, with a toggle to expand long commands so they never distort the layout), **Reports** the markdown viewer, **Analysis** the Portfolio Explorer. Launching a job pulls the runner forward from any tab |
| Right panel | Status sidebar — server polling and session history (toggle via nav bar) |

#### Durable background jobs

Long-running work runs as a **durable job** that outlives the browser connection. A durable job is a `subprocess.Popen` child **owned by the server**, in its own session/process group, with its stdout+stderr tee'd to `logs/jobs/<id>.log` and a JSON manifest (`logs/jobs/<id>.json`) recording its lifecycle (`id`, `kind`, `params`, `argv`, `pid`, `state`, `started`, `finished`, `exit_code`). Because the process and its state live outside the request, a job survives page refreshes, re-logins, extra tabs, and even a server restart (the OS process keeps running; the manifest is reconciled on startup). This is the foundation for the Deploy Options epic (#134) — deploy/destroy jobs mutate real cloud resources and must never be killed by a stray refresh.

**Report and tool runs are durable jobs (#219).** Launching a report or utility tool from the UI is a `POST /api/jobs` — the run becomes a subprocess with an id, manifest, and log file, exactly like a deploy job. The old `/ws/run` WebSocket, whose in-process thread streamed over a socket and was **cancelled when that socket closed**, has been retired along with its disconnect-kills-job behavior. So you can start a report, close the laptop or refresh the page, and the run keeps going; when you come back the UI reattaches to its live log. A multi-report selection runs as one subprocess (`-r key1,key2`) sharing a single data snapshot. Cancelling is now only the explicit **Stop** button (`POST /api/jobs/{id}/cancel`) — never a side effect of a disconnect.

| Endpoint | Purpose |
|----------|---------|
| `POST /api/jobs` | Launch a job. Body is the report/tool run shape (`{"tool": key, "params": {…}}`, `{"report": key, "formats": […], "reuse_data": "last"}`, or `{"reports": [key, …], …}`); the server maps it to a whitelisted command line (no arbitrary commands accepted) and echoes that command as the first log line. A write tool that conflicts with a running job is rejected with `409` and the blocking job list; reports are read-only and never conflict. Returns the manifest. |
| `GET /api/jobs` | All jobs (live + recent), newest first. |
| `GET /api/jobs/{id}?offset=N` | Manifest plus the log tail from byte `N`; the returned `offset` is where to resume on the next poll — this is how a fresh page load reattaches to a running job's live output. |
| `POST /api/jobs/{id}/cancel` | Explicitly cancel a running job (SIGTERM → the process group, escalating to SIGKILL). Cancellation is only ever this call — never a side effect of a disconnect. |
| `GET /api/running` | Currently-running jobs (key + elapsed), derived from the live manifests — feeds the Server-status tab. |

On startup the server reconciles any manifest left `running` by a previous process: a job whose pid is dead becomes `unknown` (its outcome was never recorded), while one still alive is re-adopted so its terminal state is captured when it exits. On page load the UI reattaches by reconciling `GET /api/jobs` (live + recent runs, resuming the live tail of anything still running) alongside the on-disk history reconstruction from `GET /api/history` (`useJobs.loadDiskHistory`), so both in-flight and finished runs repopulate. The client-side engine primitives live in `frontend/src/composables/useDurableJobs.js`; the report/tool run UI (launch, tail, reattach, cancel, session history) lives in `frontend/src/composables/useJobs.js`.

#### Version badge

The bottom-right corner shows the running build's version (hidden at phone widths; it shifts left of the AWS button on ECS/EKS). Resolution order, computed once per server process and served via `GET /api/config`:

1. `NCE_VERSION` env var — explicit deploy-time override
2. `version.json` — baked at image build (`docker build` receives `VCS_REF` / `NCE_VERSION` args from the Makefile and deploy scripts; a tagged release shows the tag, a branch build shows `nce-<commit>`)
3. Live git (local checkouts): exact tag on HEAD → the tag; otherwise `nce-<short-hash>`
4. The committed `VERSION` file (source-tarball fallback)

#### Mobile support

The UI is responsive and touch-ready — usable on iPhones, iPads, and Android phones. At phone widths (≤ 768 px):

- The job picker becomes a **slide-in drawer**, toggled with the ☰ button in the nav bar. It starts open so the job list is the first thing you see, and closes automatically when a job launches so the runner output takes the screen.
- The status panel opens as a **full-width overlay**; all dialogs (tool parameters, report picker, config editor, help, architecture) go **full-screen**.
- The docked CLI command bar is hidden — it is a hover affordance, and the server still echoes the exact command into every run's output.
- Touch details: tap targets meet a 40–44 px floor, text fields render at ≥ 16 px so iOS Safari doesn't zoom on focus, log panes and status sections resize via touch drag (pointer events), and the viewport uses dynamic-height units so mobile URL bars don't clip the layout.

**Mobile test suite** — Playwright drives the real UI on emulated device profiles (iPhone SE, iPhone 14 portrait + landscape, iPad, Pixel 7, Galaxy S9+) and asserts the flows above work by touch: no horizontal overflow, DoD banner + login usable, drawer/overlay behavior, dialog fit, tap-target sizes. All `/api` traffic is mocked, so no Python backend or GitLab is needed:

```bash
cd frontend
npx playwright install chromium       # once per machine
npm run test:mobile                   # full device matrix (Chromium emulation)

# Optional true-Safari (WebKit) pass — needs system libraries:
#   sudo npx playwright install-deps webkit && npx playwright install webkit
npm run test:mobile:webkit
```

#### Job picker

Tools are grouped by purpose in collapsible sections, all collapsed by default. A filter input at the top narrows across all groups in real time; × clears it. Each row shows the tool name, a short description, and a status badge (`read-only`, `⚙` for configurable, `● running`).

Clicking a tool with no parameters launches it immediately. Clicking a parameterised tool opens a modal dialog — booleans become toggles, integers and floats get number inputs, strings get text inputs, and group-targeting fields pre-fill from the active config. Required fields block Launch until filled. Mutating tools (including epic/issue imports) show a confirmation step that warns objects will be created in GitLab. The `dry_run` preview toggle is CLI-only and is not shown in the web UI.

Tools that share a `parallelism_group` cannot run concurrently; the dialog disables Launch and lists the blocking jobs if a conflict exists.

**Run Reports…** — a button pinned at the bottom of the sidebar opens the report picker dialog: choose individual reports or toggle All, select output formats (markdown / plotly / interactive; plotly and interactive require all reports to be selected since site builds are project-wide), and optionally check **Use last available data snapshot** to skip the GitLab API fetch and re-render from the most recent `data/` directory.

#### Deployments

A dedicated **Deployments** dialog — opened from the **Deployments…** button beside **Run Reports…** in the sidebar footer — stands the app itself up on AWS from the browser. It lists four targets — **S3**, **ECR**, **ECS**, and **EKS** — one per row, each showing its **live deployment status** as a **red/green/amber indicator dot with the state spelled out in text**: `not deployed`, `deploying…`, `deployed` (with a link to the public URL), `destroying…`, or `error` (plus ECR's `repo created — no image`, and `status unavailable` when the server's AWS identity cannot read the state — a permissions gap renders as unreadable, never as a false `not deployed`; the deployed instances' pod/task IAM roles carry scoped read-only grants for exactly these probes, issue #235). Status is served by `GET /api/deploy/status`, which reads CloudFormation (`describe_stacks` on `NceStack` for ECS and `NceEksStack` for EKS), ECR (`describe-repositories`/`describe-images` — image count and last push shown inline), and, for S3, discovers the live deployment from **CloudFront** (issue #225 — see below). The result is cached for a few seconds server-side and the dialog polls it on the shared 3s cadence, but only while it's open.

- Each row carries **one state-driven action button**: **Deploy** when not deployed, a disabled **Deploying…/Destroying…** while a job is in flight, and **Destroy** once deployed (alongside the public URL). There are no checkboxes or batch actions — deploy and destroy are per-target.
- **The S3 row includes a bucket selector** (issue #225): a dropdown of the account's existing buckets (from `GET /api/deploy/s3/buckets`) plus a **Create new…** option that previews a globally-unique `${base}-${accountId}` name. S3 bucket names are globally unique across all AWS accounts, so a fixed name is fragile; the account-id suffix guarantees uniqueness and is deterministic (idempotent re-runs).
- **Clicking Deploy or Destroy** opens a **pre-flight dialog**. For ECS/EKS it embeds the architecture diagram (the same `diagrams/` PNGs and zoom/pan viewer as the AWS Architecture button), itemizes every resource about to be created (VPC, Fargate/EKS cluster, ALB, EFS, CloudFront, ECR, Grafana…), warns that it's a long-running, billable operation, and requires an explicit acknowledgement before launching. S3 gets a lighter confirm.
- **Deploy and destroy run as [durable jobs](#durable-background-jobs)** through the same runner as report runs: launching one drops you onto the **live streaming job card** in the main pane, and the job survives a page refresh (a running deploy is re-adopted on reload). ECS/EKS deploys run their `make`/`cdk` subprocess under a **pseudo-tty** so cdk/node output streams line-by-line rather than arriving in one burst at the end.

Cloud execution is real for all four targets — **S3** (#216), **ECR** (#234), **ECS** (#217), and **EKS** (#218): each delegates to a whitelisted CLI (`--deploy-s3` / `--deploy-ecr` / `--deploy-ecs` / `--deploy-eks`) that runs the real publish/destroy path as a durable subprocess. The `POST /api/deploy/{target}/{action}` route maps the UI's `deploy` action to the CLI's `publish` and passes `destroy` straight through; for an S3 publish it also accepts an optional `{ "bucket": … }` body naming the target.

**The ECR repository is shared infrastructure with its own row** (issue #234). ECS and EKS both pull the app image from the single `nce-safe-simulator` repository — and it used to be a resource *inside* `NceStack`, so an ECS destroy deleted the repo (and its images) out from under a live EKS deployment. The repo is now owned by the **ECR target**: its Deploy creates the repository when absent and builds+pushes `:latest` (`make -C cdk ecr-push`, requires Docker on the server), its Destroy deletes the repo and images behind an explicit consequence-labelled confirm, and `NceStack` merely references the repo by name. The ECS/EKS pre-flights gate on it and fail fast — EKS blocks when the repo is absent **or** empty; ECS blocks when it is absent — pointing at the ECR row instead of dying 30 minutes later as an `ImagePullBackOff` 503. The manual paths (`make -C cdk ecr-push`, `ecs-deploy`'s first-image branch) create the repo if missing, so operator workflows stay self-sufficient.

**CloudFront is the source of truth for the S3 deployment** (issue #225). Rather than remembering the bucket name in config, S3 **status** and **destroy** find the app's distribution by its fixed origin id and recover the bucket (and region) from the origin domain (`<bucket>.s3.<region>.amazonaws.com`). So a deployed site is always discoverable — even with no `deploy.s3.bucket` in config — and destroy always tears down what's actually live. The bucket picker's dropdown needs `s3:ListAllMyBuckets` on the deploying role; without it (or without credentials) the endpoint degrades gracefully and **Create new** still works.

The ECS deploy (#217) runs the same CDK path an operator drives by hand — `make -C cdk ecs-deploy` / `ecs-destroy` → `cdk deploy/destroy NceStack` — as a refresh-survivable job, streaming CDK output to the job log. Per **decision A3** it **reuses the existing ECR image tag** (the deploy only builds+pushes a new image when the repository is empty and a Docker daemon is present; there is **no CodeBuild**). A preflight verifies the toolchain (`make`, `jq`, `cdk`, `node`, `aws` — EKS additionally `kubectl`, `helm`) and fails fast with a clear message when a first image is needed but Docker is unavailable — so the job log explains the failure instead of dying deep inside make/cdk. Because it drives the local CDK toolchain, the ECS/EKS deploys need that toolchain **where the server runs**: a source checkout on an operator box, or the **ops image variant** (below). The slim container fails the preflight with a clear message.

**Image variants (issue #231).** The `Dockerfile` produces two images from the same build:

- **Slim (default)** — what every existing call site builds (`docker build .`, `make -C cdk ecr-push`, the redeploy script) and the only image pushed to ECR. Serves the app, runs reports, performs S3 deploys (pure boto3), and shows live status for all three targets; ECS/EKS deploy attempts fail fast at preflight.
- **Ops** (`docker build --target ops -t nce-safe-simulator:ops .`) — the slim runtime plus the CDK deploy toolchain (`make`, `jq`, Node 22 + `aws-cdk`, AWS CLI v2, `kubectl`, `helm`, a client-only `docker` CLI, and `cdk/requirements.txt`). Run this variant on an operator box (with host AWS credentials mounted, see **AWS credentials** below) when the in-app **ECS/EKS Deploy/Destroy buttons** should work from inside a container. It is intentionally never pushed to ECR — a trailing default stage in the `Dockerfile` keeps plain builds slim. **`make redeploy-ops`** runs the usual rebuild-and-swap (`scripts/redeploy.sh --ops`) with the ops image — same version guard, mounts, and container name, Caddy untouched — while plain `make redeploy` keeps deploying slim. `scripts/docker-sim-run.sh --ops` does the same for the lightweight local runner (plain runs keep the slim image; add `--build` to rebuild it first).

  **First-time ECS deploy (empty/absent ECR repo)** works fully in-app from the ops container: the stack creates the ECR repository itself, the make target deploys the infra with the service scaled to 0, builds and pushes the initial image, then scales up. The image build runs against the **host's Docker daemon** — both `--ops` run scripts mount `/var/run/docker.sock` into the container when present (the slim image never gets the socket; it has no docker CLI). Note the ECS stack builds for `linux/arm64`: on an amd64 operator box the host daemon needs multi-arch emulation (Docker Desktop ships it; on bare dockerd run `docker run --privileged --rm tonistiigi/binfmt --install arm64` once).

#### Equivalent CLI command

The UI shows the **equivalent command line** for the operation, so a run you set up in the browser can be scripted, scheduled, or reproduced on another machine. The CLI accepts operations non-interactively — after `-ut <tool>` (tools) or `-r <report>` (reports), `--param value` / `--flag` tokens are applied as prefills without prompting — so the displayed command is a runnable one-liner, not a template. Two surfaces cover every operation:

- A **docked command bar** along the bottom of the window shows the command for whatever you are currently looking at — a hovered job row, or a tool dialog / report picker rebuilding **live** as you edit parameters — with a **Copy** button. Because a modal dialog covers the docked bar, the **tool dialog and report picker carry the same live command strip inline**, pinned to the bottom of the dialog, so the command stays visible and copyable while you configure it. The docked bar also **keeps the last command after a dialog closes**, so a command you just built stays reachable. Only set values contribute: a checked boolean becomes `--flag`, text/number values become `--name "value"` (shell-quoted when needed), and blank optionals are omitted so the CLI falls back to its own defaults. Values that begin with `-` (e.g. a negative count) use the `--name=value` form, and a default-on boolean turned off is stated explicitly (`--flag=false`), so the command always reproduces the exact operation.
- When a job **launches**, the server echoes the exact command it runs as the first line of that run's output (`$ python3 NceGitLab.py …`). Because the job log is recallable from the session/status window, every run — instant-launch utilities like `diagnose` included — carries the command that reproduces it, permanently.

The generated flags are contract-tested against the real CLI parser both from the browser builder (`tests/test_cli_command_preview.py`, via Node) and the server builder (`tests/test_cli_command_server.py`), so a command shown in the UI parses back to exactly the parameters it was launched with.

#### Job runner

Each launched job appears as a card in the main pane, stacked vertically. The card header shows a status indicator (spinning while running, ✓ / ✕ / ◼ when done), the job name, and a Stop or × button. Click the header to collapse or expand the log pane.

When a job finishes, a **countdown bar** drains across the bottom of the header — when it empties the tab closes automatically. Hover over the header to pause the countdown; click the bar to pin it (freezes until clicked again).

The log pane is resizable after a job completes: drag the bottom-right corner triangle to set the height.

#### Status panel

Accessible via the toggle in the nav bar; slides in from the right and is itself resizable by dragging its left edge. Two tabs:

**Server** — polls `/api/running` every 3 seconds and shows each active job with elapsed time and a Stop button. Jobs that started before the current browser session are shown as informational only (no Stop button).

**Session** — two sections separated by a draggable divider:
- *Jobs This Session* — in-memory history of every job run since the page loaded, with status dot, duration, line count, a Log ↗ link (for tool runs), and a View button to re-open the tab.
- *Report Runs* — on-disk run directories from `reports/YYYYMMDD/HHMMSS/`, each with Log ↗ and Data ↗ links. Both sections have a Clear button with an inline confirmation.

#### Config editor

The **⚙** button in the nav bar opens a dialog for editing `config.json` directly from the browser. Changes are written to disk immediately and the running server reloads its config without a restart. The dialog is organised into four tabs:

| Tab | Fields |
|-----|--------|
| Connection | GitLab URL, private token (masked by default), parent group, namespace, SSL verify, API timeout, delete workers |
| Labels | All label arrays (project, PIID, epic type, risk, ROAM, work type, lifecycle, WSJF urgency/risk) — one value per line |
| Weights | Fibonacci weights, epic type planned weights, business value field options |
| Defaults | `defaults.bootstrap` and `defaults.tools` as editable JSON |

#### Theme

Dark palette is default (GitLab shell colours + SAFe blue + GitLab orange accents). Click the toggle in the nav bar to switch to light. Preference is saved to `localStorage` and survives page reload.

#### Reports

The side panel's **Reports** tab is the in-app reading surface: it lists report snapshot runs (newest first, switchable), mirrors each run's **GitLab wiki hierarchy** exactly (page paths persisted per run in `wiki/pages.json`; legacy runs fall back to flat tier grouping), offers a filter box like the Tools tab's, carries its own **Run Reports…** button (pinned at the bottom, same as the Tools tab), and opens any page in a themed in-app markdown viewer in the main pane (server-rendered via `GET /api/runs/{date}/{time}/wiki/index.json` and `.../{slug}.json` — same python-markdown renderer as the standalone `/api/runs/.../wiki/{slug}` pages, so there is exactly one renderer). The side panel footer (visible on every tab) carries the external links: **Quarto ↗** opens the static Quarto report site (`/quarto/`; each report page there toggles to its Marimo interactive counterpart), **GitLab ↗** the group wiki, **Grafana ↗** the Amazon Managed Grafana workspace (only when `grafana_url` is set), **Raw ↗** the latest run's raw wiki index. Reports and interactive pages must be built first:

```bash
python3 NceGitLab.py -r all --formats all   # builds markdown + quarto + Marimo outputs
```

#### Analysis API

`GET /api/analysis/portfolio` (epic #165) computes a **portfolio-level view** from the newest complete report snapshot on disk — no GitLab calls, so it responds instantly and works offline. Every portfolio epic (the `epic::epic` tier) is listed with attention flags: **blocked** (a blocked descendant anywhere in its chain, with the full hierarchy path Epic → Capability → Feature → blocked item, the blockers, and a rollup of `blocked_count` plus **three-tier weight/BV metrics**, #178) and **behind_schedule** (open epic whose `pct_complete` trails `pct_through_pi` — the standard At Risk rule). Each of weight and BV comes in three tiers answering different questions: **direct** (`blocked_weight` / `blocked_business_value` — on the blocked items themselves: "the work that can't move"), **downstream** (`*_downstream` — blocked items plus their *open* descendants: "value that can't be delivered until this clears"; closed items are excluded because delivered value can't be held hostage, so the number shrinks as teams deliver around the block), and **subtree** (`*_subtree` — the whole subtree, closed included: sizing/exposure of the threatened branch, not risk). Blocked weight is the **recursive effective weight** (#179): an epic's own `planned_weight` when set — zero counts as unset, since snapshots never emit null — else the sum of its children's effective weights, bottoming out at the `actual_weight` issue roll-up on leaves. A set weight is authoritative for its whole subtree (descendants are covered by it, not added on top), and each weight tier sums at the top-most blocked nodes, so overlapping branches never double-count — which also means the direct and subtree weight tiers coincide by construction; in the downstream tier closed epics contribute 0 and a non-leaf never falls back to its `actual_weight` roll-up, because that roll-up cannot exclude already-delivered work. A blocked item counts toward every portfolio epic it threatens, while the grand `totals` dedupe blocked items — and overlapping blocked subtrees sum over the union of nodes — so portfolio-wide numbers aren't inflated. A *closed* epic still carrying `is_blocked_by` links stays in the chain (a data-cleanup signal) but contributes 0 to downstream at-risk figures. Chains traverse **untyped epics** (no `epic_type_labels` tier label — common when child epics are created by hand, since GitLab doesn't inherit labels) rather than dropping them: untyped nodes render with an `untyped` badge, their weight/BV still counts, and a data-quality hint totals them — a labeling slip degrades the display instead of hiding risk. Epics needing attention sort first (by downstream BV at risk, then downstream blocked weight); returns 404 with a hint when no snapshot exists yet.

The **Portfolio Explorer** (Analysis tab) renders this: a totals strip (portfolio epics · need attention · weight at risk · BV at risk — the headline numbers are the **downstream** figures, with direct and subtree on a sub-line, and ⓘ help icons opening a definitions panel so the metrics are self-explaining), then one GitLab-style card per portfolio epic — state, linked title, PIID/project chips, and a progress bar with a **PI-clock notch** (fill short of the notch = visibly behind schedule). Attention cards carry a red edge and issue badges (⛔ blocked count, ⚓ weight and ★ BV badges each showing `direct · dn downstream` with all three tiers in the tooltip, ⏱ behind schedule); healthy epics read "on track" at a glance. A closed-but-still-blocked node renders a muted struck-through `blocked · closed` flag with a "consider clearing links" tooltip. Blocked cards expand to the hierarchy chains — rendered in the UI with Jira-style tier badges (purple bolt Epic, teal layered-diamond Capability, blue bookmark Feature; `TierIcon.vue`), while text surfaces use the matching emoji (⚡ Epic → 💠 Capability → 🔖 Feature) — with the blocked node flagged, its blockers linked, and per-node weight/BV figures; the top blocked card starts expanded. Empty states cover no-snapshot (with a call-to-action to run reports) and a portfolio with no `epic::epic` items.

---

## What `--create` Builds

`create_all_lorem_objects()` builds a full SAFe group hierarchy under the configured root group:

- Root group with **Portfolio Epics** (⚡)
- *N* Value Stream subgroups, each with **Capabilities** (💠)
- *N* ART subgroups per Value Stream, each with **Capabilities** (💠)
- *N* Team subgroups per ART, each with:
  - **Features** (🔖)
  - A `Team Backlog` GitLab project
  - 8–15 Issues per Feature, with Fibonacci weights

After all objects are created the hierarchy is linked cross-group:  
`VS Capabilities → Portfolio Epics` → `ART Capabilities → VS Capabilities`

Features are then split by `direct_feature_ratio` (default 70%):
- **Direct Features** (majority) — linked straight to Portfolio Epics
- **Capability-chain Features** (remainder) — linked to ART Capabilities

All epics are labelled with a random project label, PIID label, and type label. Planned weights are set via the GraphQL `workItemUpdate` mutation (the REST API silently ignores epic weight).

### PI distribution and history simulation

PIID labels are drawn from a weighted distribution: **65% past PIs / 20% current PI / 15% future PIs**, so the bootstrapped portfolio naturally looks like one with history rather than a uniform spread across all quarters.

After all epics and issues are created, `_simulate_history()` runs a second pass:

1. Each ART is assigned a **stable base reliability** drawn from `history_close_rate_min`–`history_close_rate_max` (default 70–95%).
2. For each past PI, that ART's epics are closed at `base ± 10%` (floor 50%, ceiling 100%).
3. Child issues of closed epics are closed in the same pass.
4. For the current PI, `current_pi_issue_close_pct` (default 50%) of issues are closed but **epics are left open** — this drives health-dashboard at-risk flags.

After the close pass, `lifecycle::` labels are applied deterministically to every epic:

| Condition | Label |
|-----------|-------|
| Closed epic | `lifecycle::done` |
| Open epic, past or current PI | `lifecycle::implementing` |
| Open epic, future PI | `lifecycle::backlog` |
| Open epic, no PI label | `lifecycle::funnel` |

This means the Epic Lifecycle / Portfolio Kanban report shows meaningful data immediately after `--create` without needing to run `set-lifecycle-labels` separately.

### Block seeding

Finally, when `defaults.bootstrap.seed_blocks` is `true` (the default), `--create` seeds a realistic amount of dependency data so the blocking and WSJF _at risk_ reports are populated out of the box:

- **Epic→epic** blocks on `epic_block_percent` (default 12%) of epics, and
- **Issue→issue** `is_blocked_by` links on `issue_block_percent` (default 8%) of open issues.

Percentages mimic a normal portfolio mid-PI rather than a block-heavy one. Set `seed_blocks` to `false` to skip this pass, or use the `generate-epic-blocks` / `generate-issue-blocks` tools to add or remove blocks afterward.

---

## What `--scaffold` Builds

`--scaffold` creates only the **SAFe group and project structure** — no epics, issues, milestones, or labels. Use it when you want a clean hierarchy to populate manually or via import.

```bash
python3 NceGitLab.py --scaffold           # prompted for target group (default from config)
python3 NceGitLab.py --scaffold my/group  # scaffold directly under an existing group path
```

Structure created under the target group:

```
<target group>
└── Value Stream 01
    └── ART 01
        └── Team 01
            └── Team 01 — Team Backlog  (project)
        └── Team 02
            └── Team 02 — Team Backlog  (project)
    └── ART 02
        ...
└── Value Stream 02
    ...
```

Group counts are resolved from `defaults.bootstrap` using `num_value_streams`, `num_arts`, and `num_teams`. Scalar, `desired`, and `min`/`max` range formats are all supported (see [defaults.bootstrap](#defaultsbootstrap)).

If the target group does not exist and the path matches `parent_group` from config, it will be created. Otherwise the target group must already exist.

---

## Reports

Reports render in three output formats — GitLab **Wiki** pages, static **Quarto HTML**, and **interactive Marimo WASM** pages (see [Output formats](#output-formats) below). Both the web UI's report picker and the CLI (`--formats` omitted) default to **all three**; pass `--formats markdown` for a Wiki-only run. Wiki pages publish under the root group wiki (structure below). Run interactively with `--report` or pass a key directly (e.g. `--report portfolio`); use `--report all` to run every report non-interactively (required for CI).

### Wiki Structure — Four-Tier Portfolio Home

Reports are organized into four tiers by audience and cadence. The wiki home page (`home`) is the entry point; from there, all tier landing pages and individual reports are linked.

```
home  (Portfolio Home index)
├── 00 Executive Pulse        — daily, executives
│   ├── Portfolio Health Dashboard
│   └── Portfolio Explorer
├── 01 Program Management     — weekly, RTEs and PMs
│   ├── Program × PI Matrix
│   ├── Program PI Detail
│   ├── PI Predictability Scorecard
│   ├── Risk Register
│   ├── ART Capacity Balance
│   ├── Blocking & Cross-ART Risk
│   ├── Issue Blocking
│   └── WSJF Priority Board
├── 02 Operational Detail      — on demand, team leads
│   ├── ART Feature Status
│   ├── VS Capability Dashboard
│   ├── Team Backlogs
│   ├── SAFe Portfolio Hierarchy
│   ├── ART-Team Workload
│   ├── Flow Metrics
│   └── Epic Lifecycle / Portfolio Kanban
└── 03 Data Quality            — as needed, data stewards
    ├── Unassigned PI
    ├── Orphaned Epics
    └── Orphaned Issues
```

### Data Snapshot

Every report run makes **one pass through the GitLab API**, writes a data snapshot to disk, and then generates all wiki pages from that snapshot with no further API reads. This eliminates redundant queries across all reports. Since #183 the pass fetches only the phases the selected reports read (see **Data snapshots** above); a full run (all reports, or `--full-fetch`) writes the complete six-file snapshot below and marks it `snapshot.complete`, while a selective run writes a partial snapshot plus a `snapshot.manifest.json` and is deliberately left un-marked so it can't feed `--last`, the server, or the Portfolio Explorer.

```
reports/
  YYYYMMDD/
    HHMMSS/
      epics.json      # typed epics (full fields + rollups) + all_epics_raw (includes untyped)
      issues.json     # all issues: full fields including assignees, milestone, epic link
      blocking_graph.json # blocking graph: blocked epics, blockers, at-risk ancestry, id_int mappings
                      # (named to avoid the Quarto data layer's blocking.json, written to the same dir — Refs #172)
      issue_blocking.json # issue→issue blocking graph: blocked issues, blockers, parent epic
      groups.json     # SAFe group hierarchy: portfolio → VS → ART → Team, each with level tag
      projects.json   # Team Backlog projects with namespace_id, path, and issues_enabled flag
```

The directory is printed to the console at the start of every run:

```
Data snapshot → reports/20260525/143022/
  epics.json    (47 typed + 2 untyped)
  issues.json   (312 issues)
  blocking_graph.json (5 blocked epics)
  issue_blocking.json (3 blocked issues)
  groups.json   (15 groups)
  projects.json (8 projects)
```

**`epics.json` fields:** `id`, `iid`, `type`, `title`, `description`, `state`, `labels`, `parent_id`, `group_id`, `planned_weight`, `actual_weight`, `pct_complete`, `pct_through_pi`, `piid`, `business_value`, `blocked_by_count`, `blocks_count`, `start_date`, `due_date`, `created_at`, `updated_at`, `web_url`, `work_item_id`, `roam_risks`, `inherited_roam_risks` (active ROAM risks bubbled up from descendant epics — Refs #95)

**`issues.json` fields:** `id`, `iid`, `title`, `description`, `state`, `labels`, `weight`, `due_date`, `assignees`, `epic_id`, `epic_iid`, `project_path`, `web_url`, `created_at`, `updated_at`, `closed_at`

**`blocking_graph.json` structure:** `summary` (total blocked, total relationships, portfolio epics at risk) + `relationships` array where each entry has `blocked_epic` (with `id_int` integer), `blocked_by` list (each with `id_int` and an `item_type` of `Epic` or `Issue` — epic blockers come from the REST `related_epics` graph, while **issue-type blockers** are collected from the work-items linked-items widget via GraphQL, since GitLab's cross-type blocking links appear in neither the epic→epic nor the issue→issue APIs, #177), and `at_risk_portfolio_epics` list.

> **`blocked_by_count` is reconciled against this graph (Refs #107).** Once the blocking relationships are built, each epic's `blocked_by_count` is recomputed from `blocking_graph.json` — so the summary tables and the blocking detail can never disagree (they previously came from the legacy GraphQL `blockedByCount` and the REST `/related_epics` view independently). If an epic's blocking fetch fails, its prior value is kept rather than reset to `0`, and a warning is printed, so a transient API error can't silently mark a blocked epic as unblocked.

**`issue_blocking.json` structure:** `summary` (total blocked, total relationships) + `relationships` array where each entry has `blocked_issue` (`id`, `iid`, `title`, `web_url`, `project_path`, `state`, `epic_iid`, `epic_title`) and a `blocked_by` list (each `id`, `iid`, `title`, `web_url`, `project_path`). Blocked issues are flagged via a bulk GraphQL `Issue.blocked` query; only flagged issues are then REST-fetched (`GET /projects/:id/issues/:iid/links`, keeping `is_blocked_by` links).

**`groups.json` fields:** `id`, `name`, `path`, `full_path`, `parent_id`, `web_url`, `level` (portfolio / vs / art / team)

**`projects.json` fields:** `id`, `name`, `path`, `path_with_namespace`, `name_with_namespace`, `namespace_id`, `web_url`, `issues_enabled`

#### Output formats

The `--formats` flag controls which output types are produced. Combine multiple:

```bash
python3 NceGitLab.py --report all                            # All formats (--formats omitted)
python3 NceGitLab.py --report all --formats markdown          # Wiki only
python3 NceGitLab.py --report all --formats plotly            # Quarto HTML only
python3 NceGitLab.py --report all --formats interactive       # Marimo WASM only
python3 NceGitLab.py --report all --formats all               # All formats (explicit)
```

| Format | Output | Description |
|---|---|---|
| `markdown` | GitLab Wiki | Publishes wiki pages to the root group wiki |
| `plotly` | `public/quarto/` | Static HTML reports (Quarto + Plotly); full site in CI |
| `interactive` | `public/interactive/` | Marimo WASM interactive pages (filter/drill-down); see below |

When `--formats` is omitted, **all three** formats are produced (equivalent to `--formats all`) — so an unqualified run needs quarto and marimo; pass an explicit `--formats markdown` for a Wiki-only run. Pass `--no-ssl-verify` to disable TLS certificate verification for corporate proxy environments (also configurable via `SSL_VERIFY=false` env var or `"ssl_verify": false` in `config.json`).

#### Interactive pages

`build_interactive.py` exports a subset of reports as Marimo WASM notebooks — self-contained HTML files that run Python in the browser via WebAssembly. No server required; pages work from GitLab Pages or any static host.

```bash
python3 build_interactive.py    # exports all 12 notebooks → public/interactive/
```

Interactive pages share a single `public/interactive/assets/` directory (~34 MB total vs ~400 MB if each notebook kept its own copy). Notebooks are exported in parallel for speed.

Available interactive reports: health-dashboard, pi-predictability, flow-metrics, art-capacity-balance, piid-project, piid-project-detail, workload, art-feature-status, vs-capability-dashboard, team-backlog, portfolio, diagnostics.

#### CI and the Container Registry

`.gitlab-ci.yml` has two jobs:

| Job | Stage | Trigger | What it does |
|---|---|---|---|
| `test` | build | every push | Installs WeasyPrint's system packages from the project package registry (below), then `pip install -r requirements.txt && pytest tests/` |
| `containerize` | containerize | default branch only (`$CI_DEFAULT_BRANCH` — `develop` here, `main` on a lifted repo) | Builds and pushes the runtime and dev images to the GitLab Container Registry (`:latest` + `:<sha>`) via Kaniko |

`containerize` gates on `test` (`needs: [test]`), so an image is never published from a failing suite. It uses the built-in `$CI_JOB_TOKEN` to authenticate to the registry — no secret to configure. See [Container-Based Development & Registry](#container-based-development--registry) for how developers consume the published images.

> The report site was previously published to GitLab Pages by a `pages` job; that job was retired once the site was no longer consumed. Reports are still generated on demand with `python3 NceGitLab.py --report all` and served by the running app.

##### CI system packages (`weasyprint-apt-debs`)

The `test` job needs Pango and a font at the system level (WeasyPrint renders a real PDF in the suite; pip can't supply these). Rather than `apt-get install` from `deb.debian.org` on every run, the exact `.deb` files live in this project's **generic package registry** as package `weasyprint-apt-debs`, and the job fetches them with the built-in `$CI_JOB_TOKEN` and installs via `dpkg -i` — no external mirror dependency, no apt index download (issue #261).

Current version **`2026.07.21`** holds `libpango-1.0-0_1.56.3-1_amd64.deb`, `libpangoft2-1.0-0_1.56.3-1_amd64.deb`, and `fonts-dejavu-core_2.37-8_all.deb`, captured from the amd64 `python:3.11` image (Debian trixie — the job's image, on gitlab.com's amd64 shared runners).

To refresh (e.g. after the `python:3.11` tag moves to a new Debian release):

```bash
# 1. Capture the current debs from the CI image (on arm64 hosts add: docker run --privileged --rm tonistiigi/binfmt --install amd64)
docker run --platform linux/amd64 --rm -v "$PWD/debs:/out" python:3.11 \
  bash -c 'apt-get update -q && cd /out && apt-get download libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core'
# 2. Upload under a new date version
for f in debs/*.deb; do glab api --method PUT --input "$f" \
  "projects/<project-id>/packages/generic/weasyprint-apt-debs/$(date +%Y.%m.%d)/$(basename "$f")"; done
# 3. Update the version folder and filenames in .gitlab-ci.yml's test job
```

##### Vendored Quarto (`quarto`)

The Quarto CLI is the one build dependency that upstream ships only via GitHub releases — there is no apt repo to mirror. So the pinned `.deb`s are vendored in the same generic package registry as package **`quarto`**, version **`1.9.38`** (matching `QUARTO_VERSION` in the Dockerfile), for **both architectures**: `quarto-1.9.38-linux-amd64.deb` (CI image builds) and `quarto-1.9.38-linux-arm64.deb` (Graviton `ecr-push` builds), plus the upstream `quarto-1.9.38-checksums.txt` for re-verification (issue #262).

The Dockerfile downloads from the registry, not GitHub. The project URL comes from the `QUARTO_PKG_PROJECT` build-arg, which **deliberately has no default** — a hardcoded host would silently point at the wrong network after an enclave lift. Instead:

- The `containerize` CI job passes `${CI_API_V4_URL}/projects/${CI_PROJECT_ID}` — the pipeline pulls from **whatever GitLab instance it runs on**.
- Every local build path (`make dev-shell`, `make registry-push`, `make -C cdk ecr-push`/`ecs-deploy`, the redeploy scripts) derives it from the clone's own `git remote origin` via [`scripts/quarto-pkg-url.sh`](scripts/quarto-pkg-url.sh) — so a clone from an enclave GitLab automatically resolves to that instance's registry, zero configuration.
- A bare `docker build .` without the arg **fails immediately with a clear error** instead of quietly reaching for the wrong network. To build by hand:

```bash
docker build --build-arg QUARTO_PKG_PROJECT="$(scripts/quarto-pkg-url.sh)" .
# or explicitly: --build-arg QUARTO_PKG_PROJECT=https://<gitlab-host>/api/v4/projects/<id-or-url-encoded-path>
```

The download is anonymous: the project sets **`package_registry_access_level=public`**, which lets anyone pull from the *package registry only* while the project itself stays private — so no token is ever passed as a build-arg (build-args are recorded in image history). Uploads still require authentication.

To bump Quarto: download the new release's `linux-amd64.deb` + `linux-arm64.deb` + checksums from [quarto-cli releases](https://github.com/quarto-dev/quarto-cli/releases), verify (`sha256sum -c`), upload the three files under `packages/generic/quarto/<new-version>/`, and update `QUARTO_VERSION` in the Dockerfile.

### Report Index

> **Label discovery:** Reports derive label sets (`PIID::`, `project::`, `risk::`, `type::`, `lifecycle::`, `wsjf-*`) from the live data snapshot rather than from `config.json`. They reflect whatever labels actually exist in the system, so they work correctly on any live GitLab group.

| Key | Tier | Wiki Page | What it conveys |
|---|---|---|---|
| `wiki-index` | — | `home` | Four-tier navigation index linking all report pages |
| `health-dashboard` | T1 | `00 Executive Pulse/Portfolio Health Dashboard` | Per-VS traffic-light status across Schedule, Capacity, Risk, and Blocking |
| `portfolio-explorer` | T1 | `00 Executive Pulse/Portfolio Explorer` | Every portfolio epic, attention first — blocking chains (Portfolio Epic → … → blocked item, blockers linked, closed-blocked cleanup flags, untyped warnings) and three-tier BV/weight-at-risk rollups (direct / downstream / subtree, #178). Publishes exactly what the app's Portfolio Explorer shows — both surfaces are computed by `server/analysis.py:build_portfolio_view` from the same snapshot. Also available as a Quarto page (Executive menu) |
| `piid-project` | T2 | `01 Program Management/Program × PI Matrix` | Project label vs PI quarter cross-tab with status and weights |
| `piid-project-detail` | T2 | `01 Program Management/Program PI Detail` | Per-PI section view of program workload and status |
| `pi-predictability` | T2 | `01 Program Management/PI Predictability Scorecard` | % of committed Features/Capabilities delivered per PI, trended by ART. The "committed" population is every typed Feature/Capability carrying the `PIID::` label; items owned by a group outside the ART tree are collected in an **Unassigned / Portfolio** row so the Portfolio Total agrees with Flow Metrics (#188) |
| `risk-register` | T2 | `01 Program Management/Risk Register` | All risk-flagged epics grouped by level (High → Medium → Low) with PI and owning ART. ROAM risks linked to a Feature also bubble up the hierarchy: each ancestor Capability/Epic is listed as threatened, tagged _(via child)_, and flagged **⚠️ Child at risk** |
| `art-capacity-balance` | T2 | `01 Program Management/ART Capacity Balance` | Per-team planned vs actual weight per PI — spot over/under-capacity *(index → VS → ART)* |
| `blocking` | T2 | `01 Program Management/Blocking & Cross-ART Risk` | Blocked epics, ancestor risk propagation, and per-VS cross-ART dependency breakdown *(index → VS)* |
| `issue-blocking` | T2 | `01 Program Management/Issue Blocking` | Issue-to-issue `is_blocked_by` relationships, with owning project and parent epic |
| `wsjf` | T2 | `01 Program Management/WSJF Priority Board` | Portfolio backlog ranked by `(Value + Urgency + Risk) ÷ Job Size` — shows what to work on next. The **Blocking Detail** keeps _Epic at Risk_ (the at-risk Portfolio Epic) distinct from the _Blocked Item_ (the blocked Capability/Feature); a blocked item with no Portfolio Epic ancestor keeps its row but leaves _Epic at Risk_ blank and is excluded from the Business-Value-at-risk total (Refs #108) |
| `art-feature-status` | T3 | `02 Operational Detail/ART Feature Status` | Features per ART grouped by Team with completion and risk *(index → VS → ART)* |
| `vs-capability-dashboard` | T3 | `02 Operational Detail/VS Capability Dashboard` | Capabilities by PI with per-ART breakdown per VS *(index → VS)* |
| `team-backlog` | T3 | `02 Operational Detail/Team Backlogs` | Issues grouped by Feature per Team *(index; detail pages on each team wiki)* |
| `portfolio` | T3 | `02 Operational Detail/SAFe Portfolio Hierarchy` | Collapsible Epic → Capability/Feature hierarchy with % complete, PI progress, and risk flags |
| `workload` | T3 | `02 Operational Detail/ART-Team Workload` | Per-PI planned vs actual weight per group with on-track / at-risk flags |
| `flow-metrics` | T3 | `02 Operational Detail/Flow Metrics` | SAFe flow metrics: velocity, WIP load, work type distribution, and cycle time |
| `epic-lifecycle` | T3 | `02 Operational Detail/Epic Lifecycle` | Epics by SAFe Portfolio Kanban state with bottleneck detection and age analysis |
| `unassigned-pi` | T4 | `03 Data Quality/Unassigned PI` | Epics with no `PIID::` label, broken down by type |
| `orphan-epics` | T4 | `03 Data Quality/Orphaned Epics` | Epics with no parent and no children (disconnected from hierarchy) |
| `orphan-issues` | T4 | `03 Data Quality/Orphaned Issues` | Issues not linked to any epic, grouped by project |

### PI Progress Calculation

PIID labels follow the pattern `PIID::YYYYQn` (e.g. `PIID::2026Q3`).  
The tooling maps these to calendar quarters and computes `% elapsed through PI` as of today.  
Reports flag items as **At Risk** (⚠️) when `% done < % elapsed through PI`.

### % Complete Rollup

- **Feature** % = closed issue weight ÷ total issue weight
- **Capability** % = average of its Features' %
- **Epic** % = average of its Capabilities' %; if the Epic has Direct Features (no Capability wrapper), those Features are included directly in the average

---

## Utility Tools

Run interactively with `-ut` (category → tool menu) or pass a key directly (e.g. `-ut audit-labels`). Tool params can be passed as flags (e.g. `-ut set-wsjf-labels --open_only`).

### Diagnose

| Key | Description |
|---|---|
| `diagnose` | Print software versions, REST and GraphQL API capability probes, label validation, and a per-report compatibility assessment to stdout |

The `diagnose` tool is also available as a top-level CLI flag (`-D` / `--diagnose`) for quick checks without entering the interactive menu:

```bash
python3 NceGitLab.py --diagnose
```

The same diagnostic output is automatically appended as a collapsible **🔧 Environment & API Diagnostics** section at the bottom of the Portfolio Home wiki page (`/wikis/home`) every time reports are published. It covers:

| Section | What it checks |
|---|---|
| **Software Versions** | Python, python-gitlab, requests, pandas, plotly, marimo, jupyter, nbformat, GitLab server version, and GitLab tier (Free / Premium / Ultimate) |
| **Configuration** | Active label sets from `config.json` — Epic Type, PIID, Project, Risk, Lifecycle |
| **REST API Capabilities** | Live probes of Group Epics, Group Wiki, Labels, Milestones, and Epic Issues endpoints with HTTP error detail on failure |
| **GraphQL API Capabilities** | Functional probes (not schema introspection) for Epic blocking fields, `Epic.blockedByEpics`, `WorkItemWidgetWeight`, `Namespace.customFields`, `Issue.linkedWorkItems`, and `Group.workItemTypes` |
| **Label Validation** | Checks every configured Epic Type, PIID, Project, and Risk label against what exists in the target group — missing labels are the most common cause of empty report cells |
| **Compatibility Assessment** | Traffic-light (✅ / ❌ / ⚠️) verdict per report area with an overall summary sentence |

`diagnose` and the **preflight gate** (below) share one dependency manifest (`mixins/preflight.py`), so the litmus you run by hand and the gate that runs automatically check the exact same things. `--diagnose` renders the *whole* manifest; the gate renders only the slice the current job needs.

### Preflight dependency gate

The repo is lifted into air-gapped enclaves via `git clone` → `cp -R` into an empty repo → push, then run there — where apt mirrors and PyPI may be unreachable, so system and pip package availability differs per enclave. To keep a missing dependency from surfacing as a raw Python traceback mid-run, **every job runs a preflight gate first** that checks only the dependencies that job actually needs and, on a gap, prints a clean report and stops **before any work starts**.

```
⛔  Preflight -- cannot start "reports (report-plotly)"
Missing 1 required dependency(ies) for this job:
  ❌  quarto -- static HTML report site
        needs:     --formats plotly
        fix:       install Quarto (see README)
        air-gap: provision from your internal apt/PyPI mirror
        removable: drop --formats plotly to skip
```

- **Job-scoped** — a `--formats markdown` run never demands WeasyPrint or quarto. The profile is derived from the invocation:

  | Job | Checked (required) |
  |---|---|
  | `--report … --formats markdown` | python-gitlab, requests, pandas, python-dateutil, markdown |
  | `--formats plotly` | + quarto (graphviz `dot` optional) |
  | `--formats interactive` | + marimo |
  | `--formats all` | + quarto + marimo |
  | `-ut epic-cards` (PDF) | core + **WeasyPrint render** (Pango + fonts) |
  | `--create` / `--scaffold` / `--clean` | core |

- **Clean output, no stack traces.** Each missing dependency is shown with a `fix:` hint, an air-gap note (provision from your internal mirror), and a `removable:` note saying how the requirement can be avoided (drop a format, or flag it for a code rework that removes the dependency). Optional items (graphviz, the deploy toolchain) warn but never block. The gate exits with code **2** (distinct from a crash's 1).
- **Iterative by design.** The gap list is also written to **`logs/preflight-gaps.json`** — resolve a few dependencies at a time and re-run the same command, or hand that file to the enclave's platform team / send it back for a code rework. Each run re-checks and shows only what is still missing.
- **Skip** (three-tier precedence): `--skip-preflight` flag > `PREFLIGHT_SKIP=1` env var > `defaults.preflight.skip` in `config.json`.
- **Unexpected failures too.** Any error that is *not* a known dependency gap is caught by a top-level guard that prints a framed message naming the phase and saves the full traceback to `logs/<date>/<time>_crash.log` — so an operator gets a next-step ("run `--diagnose`") and a log to share, never a wall of traceback.

### Setup

| Key | Description |
|---|---|
| `scaffold` | Create SAFe group/project structure (VS → ART → Team → Team Backlog) with no content |
| `setup-bv-field` | Create or verify the Business Value custom field at the root namespace (Fibonacci 1–21) |

### Seed Data

| Key | Description |
|---|---|
| `generate-issues` | Create issues in team backlog projects linked to Feature epics |
| `generate-epic-blocks` | Create or remove blocking relationships between epics. The blocked side is restricted to Capabilities/Features that roll up to a Portfolio Epic (link direction `is_blocked_by`), so the WSJF _Epic at Risk_ column resolves to a distinct ancestor rather than collapsing onto the blocked item (Refs #108) |
| `generate-issue-blocks` | Create or remove `is_blocked_by` blocking relationships between issues (positive count creates, negative removes). Feeds the Issue Blocking report (Refs #113) |
| `generate-roam-risks` | Create ROAM risk issues, each related to a random number of epics |
| `generate-risk-reasons` | Create Behind Schedule / Past Due / Child Overdue / Blocked conditions on a random % of open epics |
| `close-percent` | Randomly close N% of open epics and issues (simulate PI progress) |
| `simulate-pi-progress` | Close X% of open issues linked to epics in a specific PI |
| `set-epic-states` | Open or close all epics matching an optional type and/or PI filter |
| `orphan-epics` | Remove parent links from N or X% of epics (simulate orphaned data) |
| `orphan-issues` | Remove epic links from N or X% of issues (simulate orphaned data) |

### Labels

| Key | Description |
|---|---|
| `set-lifecycle-labels` | Randomly assign `lifecycle::*` labels to epics |
| `strip-lifecycle-labels` | Remove all `lifecycle::*` labels from every epic |
| `set-piid-labels` | Bulk-assign a PIID label to epics that are missing one |
| `set-project-labels` | Bulk-assign a project label to epics that are missing one |
| `set-risk-labels` | Randomly assign `risk::high/medium/low` labels to open epics that have none |
| `set-work-type-labels` | Randomly assign `type::*` labels to open epics |
| `strip-work-type-labels` | Remove all `type::*` labels from every epic |
| `set-business-value` | Randomly assign Business Value custom field (Fibonacci 1–21) to open epics |
| `strip-business-value` | Clear the Business Value custom field from every epic |
| `set-wsjf-labels` | Randomly assign `wsjf-urgency::N` and `wsjf-risk::N` Fibonacci labels to open epics |
| `strip-wsjf-labels` | Remove all `wsjf-*` labels from every epic |
| `strip-labels` | Remove a specific label from all epics (optionally filtered by type) |

### Weights

| Key | Description |
|---|---|
| `set-issue-weights` | Assign Fibonacci story-point weights to issues (skip already-weighted unless `reassign=True`) |
| `strip-issue-weights` | Zero out all issue weights across every team project |
| `update-weights` | Assign planned weights to all epics based on SAFe type label |
| `validate-weights` | Validate epic and issue weights against configured pools |
| `weight-drift-check` | Flag epics where planned weight vs sum of issue weights drifts beyond a threshold |

### Reset / Clean

| Key | Description |
|---|---|
| `reset-pi-progress` | Reopen all closed issues linked to epics in a specific PI |
| `clean-roam-risks` | Delete all ROAM risk issues and their epic links across the group |
| `clean-epic-blocks` | Remove all blocking relationships between epics across the group |
| `clean-wikis` | Delete all wiki pages from a specified scope (portfolio / teams / all / group-path) |
| `clean-reports` | Delete local report run directories older than N days |
| `clean-logs` | Delete local log directories older than N days |

### Audit

| Key | Description |
|---|---|
| `audit-hierarchy` | Verify Features have valid parents (Capability or Epic) and Capabilities have Epic parents |
| `audit-labels` | Report every epic missing a type, PIID, or project label |
| `list-wikis` | List all wiki pages for a specified scope (portfolio / teams / all / group-path) |

> `diagnose` is listed under the **Diagnose** category (first entry in the utilities menu) and via `-D` / `--diagnose` — see [Diagnose](#diagnose) above.

### Import / Export

Both CSV and JSON are supported. Format is inferred from the file extension (`.json` → JSON, anything else → CSV). Export filenames are auto-named from the group name when no output path is given. Relative and `~`-prefixed paths are resolved to absolute.

The Tools menu lists these as export/import pairs, bundle first: Bundle, Epics, Issues, Links.

| Key | Scope | Key fields |
|---|---|---|
| `export-bundle` | Epics, issues, and links exports plus a merged group-names sidecar and a manifest, packaged as **one zip** (#206) | `epics.csv`, `issues.csv`, `links.csv`, `group-names.json`, `manifest.json` |
| `import-bundle` | Import a bundle zip in **one run**: containers, epics, issues, blocking links | Validates the manifest, threads the epic id map between phases automatically |
| `export-epics` | All epics across the full group hierarchy | `group_path`, `source_root`, `iid`, `id`, `title`, `description`, `state`, `labels`, `start_date`, `due_date`, `parent_id`, `parent_iid`, `planned_weight`, `business_value`, `author`, `web_url`, timestamps |
| `import-epics` | Create epics from file with pre-flight validation | Required: `title` — Optional: `group_path`, `source_root`, `labels`, `start_date`, `due_date`, `parent_id`, `planned_weight`, `business_value`, `state` |
| `export-issues` | All issues across the full group hierarchy | `project_path`, `source_root`, `iid`, `id`, `title`, `description`, `state`, `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `epic_iid`, `epic_title`, `author`, `web_url`, timestamps |
| `import-issues` | Create issues from file with pre-flight validation | Required: `title`, `project_path` — Optional: `source_root`, `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `epic_title`, `state` |
| `export-links` | Every `is_blocked_by` relationship under the hierarchy (epic←epic, issue←issue, and the cross-type epic←Issue links from the work-items model, #177) | `link_type`, `source_type`/`target_type` (`Epic`/`Issue`), ids, iids, titles, container full paths, `source_root` |
| `import-links` | Recreate exported `is_blocked_by` links on this system — run **after** importing epics/issues | Resolves endpoints via the epic id-map / titles; never raw source ids |

`planned_weight` on epics is fetched/set via GraphQL (the REST API does not expose it). `business_value` round-trips the Business Value custom field the same way: exports carry each epic's value, and the importer sets it on created/updated epics by matching the value against the target field's select options — a value that isn't an option WARNs per row. A target *without* the field — the normal case on a first cross-instance transfer — is decided by the epic importer's `on_missing_bv_field` policy (#204): **`create`** (default) creates the field from the configured `business_value_field` definition at the target root's **top-level group** (custom fields live there and apply only within that tree; creating one requires GitLab Ultimate and Owner — when creation fails, the import continues and degrades to `ignore` with a WARN), **`ignore`** imports everything and drops the values, or **`fail`** aborts during pre-flight before any row is touched. Dropped values are **counted in the run summary** whichever way they drop; an existing field is never modified. Dry runs preview `bv=N` and announce `would create …` without mutating anything. The BV mutation retries twice on transient GraphQL failures (a just-created epic can be briefly invisible to GraphQL), and any value that still can't be set WARNs per row **and is counted in the run summary** (#202). Misses and drops can be backfilled afterwards by re-importing the affected rows with `on_existing: update` (note update rewrites the other imported fields of those rows too; `skip` re-runs deliberately never touch BV).

Both importers run a full validation pass before creating anything — errors are reported upfront and the import aborts if any are found. Pass `dry_run: yes` to validate and preview without creating. When `parent_id` values from an external system don't match live IDs, the epic importer's `unresolved_parent` action decides how to handle them: `label` (create without parent and tag `import::needs-parent`, default), `skip` (skip the affected rows), or `ask` (pick one fallback parent interactively). In the web dialog this is a dropdown (offering `label`/`skip`) with a `?` help tooltip describing each option; `ask` is CLI-only because it prompts on the live hierarchy, and a non-interactive run that requests `ask` degrades to `label` with a note rather than blocking.

#### Active group + per-run override

All four import/export tools show the **active GitLab group** they act on — the **source** group for exports (what you export *from*) and the **target** group for imports (what you import *into*). The indicator is pre-filled from `config.json` (`gitlab_namespace` / `parent_group`); in the web UI it appears as a read-only field with an **Edit** button.

Each tool also accepts an optional **group override** that retargets that one run only — `config.json` is never modified. The accepted format is `namespace/group` or just `group` (the configured namespace is kept). The group part may be a **display name**, a **URL path slug**, or a full **URL path** — all three resolve, so you can paste a group's address straight from GitLab (#256); the namespace part may be a display name (`TWA-122 - PlatformEngineering/JamieGroup`) or a full URL-slug path (`a/b/c/JamieGroup`) — create-if-missing resolves the namespace by display name first and falls back to the path (#202). Leave it blank to use the configured group, so CLI/automation behaviour is unchanged.

In the web UI the override field is a **populated dropdown** (a datalist-backed combobox): clicking **Edit** unlocks it and offers the groups discovered under the configured namespace (served read-only by `GET /api/groups`), with the active group pre-selected. It stays a free-text field, so you can still type a not-yet-existing group path to use with create-if-missing, and it falls back to a plain editable text box if the group list can't be fetched. The interactive CLI is unchanged — it still accepts a typed group path at the prompt.

Imports add a **create-if-missing** checkbox: when the (overridden) target group doesn't exist, ticking it creates the group under the configured namespace before importing; leaving it unticked produces a clear, actionable error. It creates the target **root group only** — per-row subgroups (epics) and projects (issues) are never created by this option; rows pointing at missing containers follow the placement precedence below. Exports have no such option — you can't export from a group that doesn't exist.

#### Import destination picker

On top of the active-group indicator above, each importer takes an explicit **destination** that controls where the created objects land, so placement is consistent between the two importers:

- **`import-epics`** — a `dest_group` parameter (web UI: a subgroup dropdown, a datalist-backed combobox populated from `GET /api/groups`; CLI: an optional free-text group path prompt). It is the **fallback** for rows whose own `group_path` can't be resolved under the target root — those rows are created in `dest_group` instead of being dumped at the root. Rows whose `group_path` *does* resolve still go there, so any structure the file carried is preserved.
- **`import-issues`** — the existing `target_project_path` parameter (web UI: a project dropdown, a datalist-backed combobox populated from `GET /api/projects`; CLI: the same optional free-text project-path prompt as before). Same fallback semantics: rows whose own `project_path` resolves go there; rows that don't resolve are created in `target_project_path` instead of being skipped.

Both dropdowns allow free text (so you can type a not-yet-cached path) and fall back to a plain editable text box if the list can't be fetched. Both destination parameters are optional strings, so the interactive CLI and automation are unchanged.

**Placement precedence** (both importers): (1) the row's own path is used when it resolves directly under the target root; (2) otherwise the path is **reconciled across roots** (see below) — the source root is stripped and the structural remainder re-resolved under the target root; (2b, epics only) with **`create_missing_groups`** enabled, a reconciled path whose groups don't exist yet is **created** — the missing subgroup chain is built mkdir-p-style under the target root and the epic placed in it, so an incomplete mirror gets completed instead of flattened. Creation only triggers from a **trusted** source root (the export's stamp or an explicit `source_root` override — never the guessed common prefix, so a bad guess can't mint a wrong tree); created containers are named from the **group-names sidecar** when one is supplied (see below) and fall back to the path segment otherwise, a dry run lists the groups that would be created (with their names), and the run summary counts them; (2c, issues) with **`create_missing_projects`** enabled, the missing subgroup chain **and project** are created along the reconciled path (same trusted-root guardrail, dry-run preview, summary count) — like the epics-side 2b, creation preempts the fallback below; (3) otherwise the chosen destination is used; (4) otherwise epics fall back to the root group and issues are skipped. A destination that is set but doesn't resolve is a **hard error** — the import aborts before anything is created, rather than silently root-dumping (epics) or skipping every row (issues).

The one remaining structural difference only applies when **no destination is chosen** and a row's path can't be resolved (or reconciled): **epics** land at the target root group (the root is a valid epic container, so nothing is silently lost — and you can now direct them explicitly with `dest_group`), while **issues** are **skipped** (the root group is not a project, so there's nowhere valid to place them).

#### Cross-enclave placement (relative-path reconciliation)

Files exported from a **different** group hierarchy — the airgapped enclave-to-enclave case, where the target mirrors the source structure under a different root — carry paths rooted at the *source*, so they never resolve directly under the target root. Rather than root-dump or skip these rows, the importer **reconciles them by structure**: it strips the source root and re-resolves the relative remainder under the target root.

```
exported group_path : ns-a/portfolio / vs-01/art-02/team-03
strip source root   (ns-a/portfolio)  ->  vs-01/art-02/team-03
resolve under target (ns-b/portfolio)  ->  ns-b/portfolio/vs-01/art-02/team-03   ✓ lands here
```

Matching is on the **whole relative path**, not a bare leaf name (group/project names are only unique within their parent), so a path resolves to exactly one target container or none — an ambiguous leaf name can never cause a silent misplacement. Epics reconcile against the target's subgroups; issues against its projects.

The source root to strip is determined in this order:

1. an explicit **`source_root`** import parameter (web UI: an optional text field with a `?` help tooltip; CLI: an optional prompt) — trusted verbatim, for un-stamped files;
2. the **`source_root` stamp** that exports now record automatically (the exporting root's full path) — deterministic, so the round-trip needs no source connection;
3. the **longest common path-prefix** of the file's rows — a best-effort fallback for older, un-stamped files. Because this is a guess that can over-strip when every row shares a deeper subtree, it is used only to reconcile rows with a non-trivial relative remainder and never to silently land a row at the bare target root.

This runs entirely on the target side against the target's live GitLab, so it works across an airgap with only the codebase and the exported CSVs carried across. Same-root imports are unaffected (a row's own path resolves directly and wins).

#### Cross-system hierarchy (within-file parent remapping)

Source-system ids don't exist on the target, so `parent_id` values from an export can't be used verbatim. The epic importer instead treats the file as **self-describing**: each row's own `id` column plus its `parent_id` define the exported tree, parents are imported first (topological order, stable within the file), and every child links through a `source_id → new_id` map recorded as rows materialize — including parents that were *skipped or updated as already-existing* (`on_existing`), which map to the existing epic's id. The hierarchy is rebuilt on any target regardless of what ids exist there.

Resolution precedence per row: (1) a parent that is **another row in the file** → the id map; (2) a live target epic id — distrusted only when the file **positively** comes from a disjoint root: a *trusted* source root (explicit override or export stamp) that neither equals, contains, nor sits under the target root (an equal id on a different system is coincidence — attaching to it would silently corrupt the tree; the distrust is reported). An LCP-*guessed* root never triggers distrust, so legacy same-system subtree exports keep resolving their live parent ids; (3) the `unresolved_parent` action (`label`/`skip`/`ask`). An in-file parent that never materializes (failed create, cycle) degrades the child to `import::needs-parent` at runtime rather than mis-linking. A `parent_id` cycle in the file data is broken at its first row (labeled) while the remaining members keep their links; duplicate `id` values WARN and first-occurrence wins. Dry-run previews in-file parentage symbolically (`parent=(epic from row N)`). Title-based `on_existing` matching WARNs when several same-titled items exist in one container (first match wins).

**Issue → epic links** resolve the same way (#197): exports carry `epic_title` alongside the source `epic_id`, and a completed epics import writes an **epic id map** (`source id → new id`, saved to `public/exports` and printed with a download link). The issues importer resolves each row's epic reference by precedence: (1) the id-map file passed via the optional `epic_id_map` parameter — the **paired import** flow (import epics first, feed its map to the issues import); (2) exact `epic_title` match among the target's epics (ambiguity WARNs, first match wins); (3) the raw `epic_id` — same-root imports only, under the same trusted-disjoint-root rule as epics, since an equal id on a different system would attach the issue to an unrelated epic. An unresolvable reference WARNs and the link is dropped; the issue itself still imports.

#### Transfer bundle (`export-bundle` / `import-bundle`)

The recommended cross-enclave transfer path (#206): one artifact, one action in each direction. `export-bundle` runs the three exports against the (overridable) source group and packages a single zip — `epics.csv`, `issues.csv`, `links.csv`, `group-names.json` (the two sidecars merged; it covers groups *and* projects so both importers consume it unchanged), and `manifest.json` (format version, `source_root` stamp, per-file counts, and how many links have external endpoints that a cross-system import will drop).

`import-bundle` takes that zip on the isolated system, validates the manifest (not-a-bundle, missing files, and newer-format-version all fail before anything is touched), and runs the proven sequence internally: **epics → issues → blocking links**, with the epic id map captured in-memory from the epics phase and threaded into the other two — no hand-carried map file. Defaults are transfer-tuned and differ from the standalone importers: the target root group is created if missing (`create_missing` **on**), subgroups and projects are always created along reconciled paths (gated on the bundle's trusted `source_root` stamp, and named from the bundled names file), and `on_existing: skip` makes re-running the same bundle a safe no-op — which is also the recovery story for a partially-failed import: just run it again. The epics phase honors `on_missing_bv_field` (#204, default `create` — a target instance that lacks the Business Value field gets it created at the top-level group before values are set; see the import-epics docs above for `ignore`/`fail` and the degradation rules). `dry_run` (CLI) threads through all three phases and previews containers, rows, and link resolution without creating anything; under dry run no id map exists yet, so epic references preview by title — and because a dry run never creates the target root group, previewing requires the root to already exist (against a missing root the preview stops after the epics phase with a pointer, since the real import would create it). Epics-only and issues-only hierarchies bundle fine: the missing file is simply absent from the manifest and its phase is skipped on import. In the web UI the bundle export downloads the zip and the bundle import accepts an uploaded zip like any other import file.

The individual tools below remain for piecemeal use; the bundle is orchestration over exactly the same building blocks, so everything documented about them (validation, placement precedence, id-map resolution, BV round-trip, external-link drops) applies unchanged.

#### Blocking-link round-trip (`export-links` / `import-links`)

`export-links` captures every `is_blocked_by` relationship under the hierarchy in one file: **epic←epic** (REST `related_epics`), **issue←issue** (bulk GraphQL blocked-flag pass, then REST `links` for flagged issues only), and the **cross-type epic←Issue** links that exist only in the work-items model (#177). Each row records both endpoints' type, id, iid, title, and container full path, plus the `source_root` stamp. Links whose *other* endpoint lives **outside the exported tree** (e.g. a stale link into another hierarchy or a deletion-scheduled group) are flagged with a WARN at export time, listing each affected pair — they still export, but a cross-system import has no counterpart to attach and will drop them, so the drop is predictable up front (#202).

`import-links` recreates them on the target — run it **after** the epics/issues imports so the endpoints exist. Endpoints resolve exactly like the other cross-system references: epics via the paired-import **epic id map** then exact title (ambiguity WARNs, first wins); issues via the **reconciled project path + exact title**. Raw source ids are never used to address target objects. Epic←epic and issue←issue links are created over REST; the cross-type epic←Issue link uses the `workItemAddLinkedItems` GraphQL mutation. Existing links are skipped (409/422 → "already existed"), unresolvable endpoints WARN and drop the link (never mis-link), and dry run resolves + previews without creating anything. The full air-gap sequence is: `export-epics` + `export-issues` + `export-links` on the source → carry files across (including the group-names sidecars) → `import-epics` (grab the printed id-map) → `import-issues --epic_id_map …` → `import-links --epic_id_map …`.

#### Group/project display names (`group-names` sidecar)

Exports carry container paths as URL **slugs** (`vs-01/art-02`), so containers recreated by `create_missing_groups` / `create_missing_projects` would otherwise be named after their path segments instead of the source's display names ("Value Stream 01"). Both `export-epics` and `export-issues` therefore write a **`<export>-group-names.json` sidecar** — `{"groups": {relative path: display name}, "projects": {…}}` — next to the export, printed with a download link. Pass it to either importer via the optional **Group names file** parameter (`--group_names`) and every created subgroup/project is named like the source; without it (or for paths missing from the file) the slug fallback applies, and a corrupt file WARNs and degrades rather than aborting. Names never affect paths or placement — reconciliation still matches on slugs. Dry runs preview the display name that would be used.

#### Re-import behaviour (`on_existing`)

Re-running the same file could otherwise create duplicates. The `on_existing` parameter (web UI: a dropdown; CLI: a prompt accepting `create` / `skip` / `update`) controls this, matching an existing item by **exact title** within the target project (issues) or group (epics) — the group's **own** epics only, so same-titled epics in different subgroups never collide (#199):

- **`skip`** (default) — if a same-title item exists, leave it untouched and report `SKIP — already exists (#iid)`; create it otherwise. Safe to re-run.
- **`update`** — apply the row's fields to the existing item (merge — omitted fields are left as-is; the matched title is not rewritten); create it if there's no match.
- **`create`** — always create, never match; the original create-only behaviour (may duplicate on re-import).

Existence checks are **batched per container** (#201): each target group/project's items are listed once per run and looked up locally, instead of one search call per row — large re-imports no longer hammer the API into rate limiting. Items created during the run join the cache, so intra-run duplicates (the same title twice in one container in one file) are still caught. SKIP lines name the matched container (`already exists (#4 in …/team-07)`) since iids are only unique per group. When GitLab does rate-limit a run (HTTP 429), the retry backoff is now announced in the job log (`GitLab rate limit hit (429) — retrying after 45s...`) instead of sleeping silently.

The run summary reports counts as `N created | N updated | N skipped | N failed`. Title matching is intentionally simple (no stable-id round-trip), so distinct items sharing a title are treated as the same — keep titles unique if you rely on `skip`/`update`.

### Printable Epic Cards (PDF)

The `epic-cards` tool renders filtered epics as a **print-ready PDF** for hard-copy PI planning (#249). Two modes: the default **cut-apart cards** — Letter-size (**portrait by default, or landscape** — #254) with dashed cut borders, **1, 2, or 4 cards per page** — or a **large-format tiled "wall"** (#241) sized for a plotter (see [Large-format plotter wall](#large-format-plotter-wall-241) below). Output is written to `public/exports` and returned as a browser download (`/api/download/<file>.pdf`), same as the CSV/JSON exports. Rendering uses WeasyPrint (HTML/CSS → PDF); no headless browser required.

| Param | Purpose |
|---|---|
| `group` | Source group (defaults to the configured root; all subgroups included) |
| `per_page` | Cards per sheet — `1` (default), `2`, or `4` (ignored when `grid` is set) |
| `orientation` | Page orientation — `portrait` (default, 8.5×11) or `landscape` (11×8.5) |
| `page_size` | Sheet size for large-format output (#241) — a preset (`letter`, `tabloid`, `arch-c`/`d`/`e`, `ansi-c`/`d`/`e`) or exact `WxH` inches (e.g. `36x48`); blank = Letter |
| `grid` | `COLSxROWS` (e.g. `6x8`) to tile many cards per sheet as a printable "wall" (#241), overriding `per_page`; extra cards flow onto further sheets |
| `card_spec` | Path to a card-spec JSON (**filter + taxonomy**); blank uses the shipped `epic-cards-spec.json` — see below |
| `label_filter` | Comma-separated labels; an epic must carry **all** of them. A trailing `*` is a scope wildcard — `mission-thread::*` matches any `mission-thread::…` label. **Overrides the spec's `filter`** (the taxonomy always comes from the spec). |

**Card spec** — a card set is defined by one JSON file at the repo root, `epic-cards-spec.json`, that ships with the tool and is meant to be **edited by the operator to match their target system's labels**:

```json
{
  "filter":   ["epic::capability", "mission-thread::*"],
  "taxonomy": {
    "bucket":  ["ALL", "bucket1", "…", "bucket20"],
    "project": ["DCGS", "DO", "RTSO"]
  }
}
```

`filter` is the label set every epic must carry to appear on a card; `taxonomy` classifies each epic's unscoped labels — `bucket` names become the chip row, `project` names become the related-systems list.

> **Both `bucket` and `project` are explicit whitelists.** Only the unscoped labels you enumerate are classified — every other unscoped label an epic carries (lifecycle tags, workflow states, ad-hoc labels) is ignored and never rendered. There is no wildcard for these lists: the operator must enumerate the real bucket and system/group names, because the unscoped namespace is shared with unrelated labels and a wildcard would sweep them in as bogus systems. (The primary system still comes from the scoped `project::` label; its unscoped twin is de-duplicated out of the related-systems list.)

With the shipped spec in place the tool is self-contained:

```bash
# Uses epic-cards-spec.json for both the filter and the taxonomy (1 card/page).
python3 NceGitLab.py -ut epic-cards

# Point at an alternate spec, or override the filter for a one-off:
python3 NceGitLab.py -ut epic-cards --card_spec specs/mission.json
python3 NceGitLab.py -ut epic-cards --label_filter "epic::capability,mission-thread::*"

# Landscape sheet (11x8.5) instead of the default portrait (8.5x11):
python3 NceGitLab.py -ut epic-cards --orientation landscape

# Large-format wall: tile all filtered cards 6-across x 8-down on a 36x48in sheet:
python3 NceGitLab.py -ut epic-cards --page_size arch-e --grid 6x8
```

#### Large-format plotter wall (#241)

For a wall-format PI-planning artifact, set an explicit **`page_size`** and a **`grid`** and the whole filtered set tiles onto one large sheet (overflow flows to further sheets) at a shared, readable card size — using the same card design as the cut-apart deck. Print it on a plotter and pin the sheet up; no cutting.

- **`page_size`** — a preset (`letter` 8.5×11, `tabloid` 11×17, `arch-c` 18×24, `arch-d` 24×36, `arch-e` 36×48, `ansi-c` 17×22, `ansi-d` 22×34, `ansi-e` 34×44) or exact `WxH` inches (e.g. `36x48`). Presets swap with `orientation`; an explicit `WxH` is taken verbatim.
- **`grid`** — `COLSxROWS`, e.g. `6x8` = 48 cards per sheet.

Because WeasyPrint sets the PDF's `@page` size in **real-world inches**, the media box equals the requested physical dimensions (a `36x48` request yields a 2592×3456 pt / 36×48 in page), so a plotter prints it **1:1 with no fit-to-page scaling** — the "right size" failure mode #222 flagged. Bad `page_size`/`grid` values warn and fall back to the Letter / cards-per-page path.

When run from a non-interactive shell (no TTY — e.g. a CI job), the tool never prompts: any option you don't pass takes its default, so `python3 NceGitLab.py -ut epic-cards --output_path deck.pdf` runs unattended (group from `config.json`, filter + taxonomy from the spec). See `ci-recipes/` for a ready-to-copy GitLab CI job that publishes the deck as a pipeline artifact.

Each card shows **mission thread and weight (header), title, description, buckets, project / related systems, and due date**. Scoped labels resolve directly (`mission-thread::` → thread, `project::` → main system); the unscoped **bucket** and **related-system** labels are classified against the spec's `taxonomy`. With no taxonomy the scoped fields still render and the unscoped ones are left empty. Program accent colors are placeholders pending Program's palette (#222).

Content that would overflow a card is **truncated in Python (not clipped by CSS)** so the cut is always visible and WeasyPrint never hits its O(n²) overflow-relayout path: the **description** is trimmed to a per-layout character budget and ends in ` …` when cut, and **buckets** past the ~two-line budget collapse into a trailing `…` chip. The special bucket value **`ALL`** (buckets only) means "all buckets" and renders as a single `ALL` chip regardless of any other bucket labels on the epic.

Bucket chips **honor each label's live GitLab color** — the exporter reads the group's label colors and fills each chip with its color, picking a readable ink (dark or white) by the same YIQ rule GitLab uses. Change a label's color in GitLab and the next render reflects it; labels with no color fall back to the default chip styling.

### Test Data Seeding Pattern

The `set-*` and `strip-*` pairs are designed for rapid test-data cycling:

```bash
# Seed WSJF data, run the board, strip and repeat
python3 NceGitLab.py -ut set-business-value
python3 NceGitLab.py -ut set-wsjf-labels
python3 NceGitLab.py -r wsjf
python3 NceGitLab.py -ut strip-business-value
python3 NceGitLab.py -ut strip-wsjf-labels

# Same pattern works for lifecycle, work-type, and risk labels
```

---

## Running in a CI/CD pipeline

The CLI is built to run unattended in a pipeline — every job the tool exposes (reports, the epic-cards deck, create/scaffold) runs the same way in CI as on a workstation. Three things make that safe; this section ties them together. (For how the **repository's own** pipeline builds and publishes its container images, see [CI and the Container Registry](#ci-and-the-container-registry) instead — that is a different concern.)

### Copy-and-own recipes

The [`ci-recipes/`](ci-recipes/) directory holds self-contained GitLab CI job snippets — **examples you copy into your project's top-level `.gitlab-ci.yml`**, not files GitLab includes automatically. To use one: open the recipe, read its header (it lists the prerequisites — committed files, CI/CD variables, access tokens), copy the job block into your `.gitlab-ci.yml`, and adjust the marked spots (`stage`, `image`, `rules`). Secrets go in masked CI/CD variables, never in the file. Full instructions and the recipe list live in [`ci-recipes/README.md`](ci-recipes/README.md). Two examples ship today: [`epic-cards-deck.yml`](ci-recipes/epic-cards-deck.yml) renders the Capability Card PDF as a downloadable pipeline artifact, and [`all-reports.yml`](ci-recipes/all-reports.yml) runs the full report suite (`--report all`) inside the project's own runtime image — Quarto, Pango, and every pip dependency baked in, no external downloads at job time — publishing the rendered `public/` site as the artifact (scheduled + manual by default, since a full run rewrites the wiki report pages).

### Non-interactive by default

When stdin isn't a TTY (every CI runner), tools never prompt: each option you don't pass on the command line takes its default, so `python3 NceGitLab.py -ut epic-cards --output_path deck.pdf` runs to completion unattended (group from `config.json`, filter + taxonomy from the spec). A genuinely required value with no default fails the job loudly by name instead of hanging on a prompt.

### The preflight gate is the fail-fast

Because the repo is lifted across air-gapped enclaves where package availability differs, every job runs the [preflight dependency gate](#preflight-dependency-gate) first — **before** the GitLab client is even built, so a missing dependency (or a not-yet-configured token) produces a clean gap report rather than an auth or import failure that buries it. On a gap the gate prints the ✅/❌ list with `fix:` and air-gap notes, writes **`logs/preflight-gaps.json`** (publish it as a job artifact to hand to the enclave's platform team, or send it back for a code rework that drops the dependency), and **exits 2** before any work runs. Resolve a few deps at a time and re-run the same command until it passes. To bypass it — e.g. a job you know needs only a subset — set `--skip-preflight`, `PREFLIGHT_SKIP=1`, or `defaults.preflight.skip` in `config.json`.

### No raw tracebacks

Any *unexpected* failure — one that is **not** a known dependency gap — is caught by a top-level guard that prints a framed message naming the phase and saves the full traceback to **`logs/<date>/<time>_crash.log`**, then exits 1. A job log therefore always carries a next step ("run `--diagnose`") and a shareable log, never a wall of traceback.

---

## Container-Based Development & Registry

The [Installation](#installation) steps above install the toolchain (Python, Node,
Quarto, Graphviz) directly on your host. As an alternative, the project ships a
**dev/build container** that already carries the entire toolchain — clone the
repo, mount it into the container, and develop with nothing installed locally.
This is the container-based SDLC the project uses to demonstrate moving teams off
per-developer VMs (issues #243 / #244).

Two images are built from the multi-stage `Dockerfile`:

| Image | Target | Purpose |
|---|---|---|
| `…/nce-safe-simulator` | `runtime` | The slim served app (uvicorn/FastAPI). Same image deployed to ECS/EKS. |
| `…/nce-safe-simulator/dev` | `dev` | Full build toolchain (Python + deps, Node 20, Quarto, Graphviz, make, git). Source is **not** baked in — you mount your working tree. |

### Develop inside the container

```bash
git clone https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator.git
cd nce-safe-simulator
make dev-shell          # builds the dev image, then opens a shell with $PWD mounted at /app
```

Inside that shell the whole pipeline runs with no host setup:

```bash
pytest tests/                       # run the test suite
cd frontend && npm ci && npm run build && cd ..   # build the Vue app
make build                          # fetch data, export notebooks, render the site
python3 NceGitLab.py --serve        # http://localhost:4645 (port published by make dev-shell)
```

> **Tip:** run `make` (or `make help`) in the repo root for a grouped, self-documenting list of all targets (the `cdk/Makefile` behaves the same way).

Because only the working tree is mounted, edits in your local IDE are visible
immediately inside the container, and rebuilding the image is only needed when the
toolchain itself changes (dependency bumps, tool versions). Your IDE stays on the
host; the container is just the build/run environment.

To pull the published dev image instead of building it locally:

```bash
docker login registry.gitlab.com
docker run --rm -it -v "$PWD":/app -w /app -p 4645:80 \
  registry.gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/dev:latest
```

### Registry & CI

On every merge to the default branch (`$CI_DEFAULT_BRANCH` — `develop` here, `main` on a lifted repo), the `containerize` CI job (`.gitlab-ci.yml`) builds
both images with [Kaniko](https://github.com/GoogleContainerTools/kaniko) and
pushes them to this project's GitLab Container Registry, tagged `:latest` and
`:<short-sha>`:

```
registry.gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator        # runtime
registry.gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/dev    # dev toolchain
```

To build and push the same images by hand (the local mirror of the CI job):

```bash
docker login registry.gitlab.com     # username + a PAT/deploy token with write_registry scope
make registry-push
```

> **Architecture note.** gitlab.com shared runners are amd64, so the registry
> images are amd64 — ideal for developer laptops pulling the `dev` image. The
> arm64 (Graviton) production images used by the AWS deploys are unchanged; they
> still build via `make -C cdk ecr-push`.

---

## Enclave Transfer (Air-Gapped GitLab)

This project is built to be lifted — **repo included** — into a network with **no GitHub egress**. Everything that would otherwise come from GitHub is vendored in this project's GitLab registries: the generic **package registry** carries the system `.deb`s ([`weasyprint-apt-debs`](#ci-system-packages-weasyprint-apt-debs) and [`quarto`](#vendored-quarto-quarto)), and the **container registry** carries the built runtime/dev images. The CI yaml composes every registry URL from `${CI_API_V4_URL}` / `${CI_PROJECT_ID}` and triggers on `$CI_DEFAULT_BRANCH`, so the same pipeline runs unmodified against the enclave's own GitLab instance — whatever its host or default branch — once the artifacts are imported.

Two scripts do the whole lift (issue #263); both need only bash, git, curl, and python3 (plus docker for the image phases). **Windows boxes are covered too**: PowerShell ports ([`enclave-export.ps1`](scripts/enclave-export.ps1) / [`enclave-import.ps1`](scripts/enclave-import.ps1), issue #264) mirror the bash pair phase-for-phase and need only PowerShell 5.1+, git, curl, and tar (`curl.exe` and `tar` are built into Windows 10+/Server 2019+) — `Invoke-RestMethod` and `Get-FileHash` replace the python3 and sha256sum dependencies, while package file bodies stream through real curl, since Windows PowerShell 5.1's web cmdlets reliably drop long TLS transfers. Package downloads and uploads retry with backoff on all four scripts, so one transient network reset doesn't abort a transfer. The two families are cross-compatible: checksums are written in `sha256sum -c` format either way, and every artifact carries **both** importers, so a Windows export imports on Linux and vice versa.

| Script | Runs on | What it does |
|---|---|---|
| [`scripts/enclave-export.sh`](scripts/enclave-export.sh) | a connected box, from any directory inside a clone of this repo | Produces **one file**: `<repo-name>-<YYYY-MM-DD>.txt` — a gzipped tar (the `.txt` extension is the transfer-media naming convention) containing a git bundle of **every branch + tag**, the **project wiki** (if any), **every generic package** (enumerated live from the API, so new versions are picked up automatically), the **runtime + dev container images**, and a `SHA256SUMS` manifest over all of it. The outer file's sha256 is printed for verification on the far side |
| [`scripts/enclave-import.sh`](scripts/enclave-import.sh) | an enclave box that can reach the target GitLab | Verifies checksums, **creates the project if absent**, pushes all branches/tags + wiki, sets the default branch, uploads all packages, enables anonymous package-registry pull, and loads/retags/pushes the images. Idempotent — rerun safely after a partial failure |

> **Stated assumption:** Debian apt, PyPI, and npm are served by enclave mirrors/proxies (standard practice). Quarto is the piece that has no mirrorable package repo — hence the registry vendoring. If the enclave has no apt mirror, the Docker *builds* (which `apt-get install` graphviz, node, etc.) won't run there — import the prebuilt images instead and skip `containerize`.

**Validating the scripts** (`tests/test_enclave_scripts.py`): the suite pins the bash↔PowerShell contract — phases, flags, artifact layout, checksum format, shipped importers — and syntax-checks with the real interpreters. `bash -n` always runs; the PowerShell AST-parse tests need a PowerShell on PATH and **skip otherwise** (CI has none — run them locally before review). On Windows the built-in `powershell` (5.1, exactly the declared floor) is picked up automatically; on Linux install the portable `pwsh` tarball (no package manager needed; pick `linux-x64` or `linux-arm64`):

```bash
mkdir -p ~/.local/pwsh && curl -fsSL \
  https://github.com/PowerShell/PowerShell/releases/download/v7.4.6/powershell-7.4.6-linux-x64.tar.gz \
  | tar -xz -C ~/.local/pwsh && chmod +x ~/.local/pwsh/pwsh
PATH=~/.local/pwsh:$PATH python -m pytest tests/test_enclave_scripts.py   # parse tests included; live e2e stays opt-in
```

### 1 — Export (on a connected box)

```bash
export GITLAB_TOKEN=<read_api token>        # needed to ENUMERATE packages; downloads are anonymous
scripts/enclave-export.sh -o /media/transfer
# → /media/transfer/nce-safe-simulator-2026-07-21.txt  (single artifact; sha256 printed)
# no docker on the box?          add --no-images
# enclave has no image proxy?    add --with-base-images  (python:3.11, python:3.11-slim,
#                                node:20-slim, kaniko — what CI jobs and builds pull)
```

Windows equivalent (`-OutDir`, `-NoImages`, `-WithBaseImages`):

```powershell
$env:GITLAB_TOKEN = '<read_api token>'
scripts/enclave-export.ps1 -OutDir D:\transfer
```

Everything inside is checksummed into `SHA256SUMS` (verified again by the importer), and the Quarto debs additionally carry the upstream release manifest for independent re-verification. Note the printed outer sha256, then move the single `.txt` file across on approved media per the enclave's transfer process.

For a **browser-only export** of the packages: the source project's **Deploy → Package registry** UI has per-file download links (anonymous pull is enabled), so the .debs can be fetched by hand. The git repo and container images have no UI download — those need the script (or `git bundle` / `docker save` directly).

### 2 — Import (on the enclave side)

The enclave box starts with **only the `.txt` file** — the repo (and with it the importers' canonical copies) is still locked inside the bundle. The artifact therefore carries copies of both importers at its top level; extract just the one for your shell first:

```bash
tar -xf nce-safe-simulator-2026-07-21.txt ./enclave-import.sh   # bootstrap: pull the importer out of the artifact
export GITLAB_TOKEN=<api-scope token on the TARGET instance>
./enclave-import.sh -d nce-safe-simulator-2026-07-21.txt \
  -u https://<enclave-gitlab> -p <group>/nce-safe-simulator
# -d takes the .txt artifact (extracted next to itself) or an already-extracted directory
# --default-branch main is the default; --skip-repo/--skip-packages/--skip-images for partial runs
```

**If the target enforces the "committer restriction" push rule** — every branch bounces off the pre-receive hook with `You cannot push commits for '<source email>'. You can only push commits if the committer email is one of your own verified emails` — add `--rewrite-committer 'Full Name <email@domain>'` (PowerShell: `-RewriteCommitter`) with the importing account's verified identity. It rewrites author + committer on every commit of the repo **and wiki** before pushing (via `git filter-branch`, which ships inside git — nothing to install). Trade-offs: every commit hash changes (deterministically, so reruns stay idempotent) and in-repo attribution moves to the importing user. If an admin can instead drop that push rule for the target group, prefer that — it keeps the history untouched.

On a **Windows** box, same flow in PowerShell (switches: `-DefaultBranch`, `-RewriteCommitter`, `-SkipRepo`, `-SkipPackages`, `-SkipImages`):

```powershell
tar -xf nce-safe-simulator-2026-07-21.txt ./enclave-import.ps1
$env:GITLAB_TOKEN = '<api-scope token on the TARGET instance>'
./enclave-import.ps1 -TransferPath nce-safe-simulator-2026-07-21.txt `
  -GitLabUrl https://<enclave-gitlab> -Project <group>/nce-safe-simulator
```

The script prints a post-import checklist (runners, the `GITLAB_API_TOKEN` CI variable for the report recipes, `config.json` from the template, branch protection). Notes:

- **There is no UI upload for packages.** GitLab's package-registry UI can browse, download, and delete, but generic-package *upload* exists only as the API `PUT` the script performs — don't hunt for an upload button.
- **GitLab's project export/import tarball carries neither registry.** It does carry issues/MRs/labels, which the scripts deliberately don't (they lift the *functional* project); if that metadata matters, run a project export/import as a complement — but the packages and images still arrive only via these scripts.
- The raw API calls, for doing any single step by hand, are exactly what the scripts run — they're short and commented; read them as the reference.

### 3 — Verify

- Pipeline: run a branch pipeline — the `test` job must fetch the three Pango debs from the *enclave* registry (the job log shows the `$CI_API_V4_URL` host) and go green.
- Image build: a merge to the enclave's default branch (`main`) runs `containerize` — the trigger is `$CI_DEFAULT_BRANCH`, not a hardcoded branch name; the kaniko log's Quarto `curl` must hit the enclave host. (Or verify offline: `docker run --rm <enclave-registry>/<group>/nce-safe-simulator:latest quarto --version` → `1.9.38`.)
- Reports: the [`all-reports.yml`](ci-recipes/all-reports.yml) recipe runs entirely from the imported runtime image — no external downloads at job time — and is the end-to-end proof that report generation works inside the enclave.

There is **no gitlab.com reference anywhere in the build chain**: CI composes the registry URL from its own instance variables, and local builds derive it from `git remote origin` ([`scripts/quarto-pkg-url.sh`](scripts/quarto-pkg-url.sh)) — an enclave clone resolves to the enclave instance automatically. A bare `docker build .` without the build-arg fails loudly by design.

---

## Single-Box Deployment (nce-safe-sim.com)

The lightest deployment runs the simulator on a single EC2 instance and serves it
straight from the public domain. It is the cheapest option and doubles as the
development box.

```
nce-safe-sim.com / www  ──Route 53 A──▶  Elastic IP
        │
        ▼
   EC2 instance ── host :80/:443 ──▶  caddy container
                                          │  reverse_proxy over the nce-net network
                                          ▼
                                     nce-safe-sim container :80 (uvicorn / FastAPI)
```

[Caddy](https://caddyserver.com/) terminates TLS, automatically provisioning and
renewing a real **Let's Encrypt** certificate (90-day, auto-renewed) for the apex
and `www`. The app container is internal-only — it is never published on a host
port; all traffic reaches it through Caddy. Both containers run with
`--restart unless-stopped`, so they return after a reboot.

> **Cost control.** The instance is governed by an EventBridge start/stop schedule.
> While it is running the domain serves the simulator; while it is stopped the site
> is simply unavailable — there is no always-on standby, by design.

**Persistent data.** The served, generated directories are bind-mounted from the
project root so they survive container recreation (`make redeploy`), mirroring the
cloud EFS layout: `reports/`, `public/interactive/` (Marimo WASM pages),
`quarto-site/` (rendered Quarto site), and the UI import/export temp dirs
`uploads/` (browser-uploaded import files) and `public/exports/` (generated
export downloads) — mounting the latter two keeps generated exports from being
lost on every redeploy. `logs/` is mounted too (box-only — the cloud ships logs
to CloudWatch). The image-baked `public/app` frontend and `public/architecture`
diagrams are left in the image; only individual `public/` subdirectories are
mounted, so they stay intact.

**Temp-file retention.** `uploads/` and `public/exports/` are pruned by age so
they don't grow unbounded on disk/EFS: the server sweeps them on startup and
opportunistically on each upload/download, deleting files older than
`TEMP_FILE_RETENTION_HOURS` (default `24`; set to `0` to disable). Only these two
UI temp dirs are touched — explicit CLI export/import paths live elsewhere and
are never affected.

**AWS credentials (in-app deploys).** The app-driven deploys (S3/CloudFront #216,
ECS #217, EKS #218) call AWS from inside the app container, so it needs
credentials. `redeploy.sh`/`docker-sim-run.sh` **bind-mount the host's `~/.aws`
read-only** into the container (`-v "$HOME/.aws:/root/.aws:ro"` — the container
runs as root, so boto3 reads `/root/.aws`). Credentials are deliberately **not
baked into the image**: that would leave IAM keys in image layers (including
anything pushed to ECR) and force a rebuild on rotation. The mount is skipped
when the host has no `~/.aws`, so the site still comes up for non-deploy use —
only the in-app deploy buttons need it. The mounted identity must carry the
deploy permissions (`s3:ListAllMyBuckets` + the S3/CloudFront/OAC actions for the
S3 path; CDK/CloudFormation for ECS/EKS).

### Prerequisites

- DNS: Route 53 A records for `nce-safe-sim.com` and `www` pointing at the instance's Elastic IP.
- Security group: inbound `80` and `443` open (80 is required for Let's Encrypt's HTTP-01 challenge).
- `config.json` present in the project root (carries `private_token`), or `GITLAB_TOKEN` exported.

### First-time bring-up

```bash
make deploy-local        # builds the image, starts app + Caddy, issues certs
```

### Iterative development workflow

Edit code, then push the change to the live site with a single command:

```bash
make redeploy            # rebuild image + swap the app container in place
```

`redeploy.sh` rebuilds the image (Docker layer cache keeps backend-only changes
fast) and recreates **only** the app container — Caddy, the issued certificates,
and the domain binding are left untouched, so the site at
`https://nce-safe-sim.com` reflects the new code within about a minute with no
TLS churn. Use `make deploy-local` only for a full bring-up or after changing the
Caddy config (`deploy/Caddyfile`).

---

## AWS Deployment

The simulator runs on AWS in two configurations. **EKS (Kubernetes)** is recommended for production — managed node group, EFS persistent storage, CloudFront in front of the ALB. **ECS (Fargate)** is the simpler option for lower-traffic or short-lived deployments. Both share the same CDK project (`cdk/`), ECR image, SSM-stored config, EFS layout, and Grafana workspace.

### Prerequisites

- AWS CLI configured (`aws configure`)
- Docker (for building the container image)
- CDK CLI: `npm install -g aws-cdk`
- `jq` — the `cdk/Makefile` deploy/audit targets parse and write `cdk-*.json` state with it
- `kubectl` and `helm` (EKS only)
- SSM Session Manager plugin (for exec into the running container):
  ```bash
  sudo dnf install -y https://s3.amazonaws.com/session-manager-downloads/plugin/latest/linux_arm64/session-manager-plugin.rpm
  ```

### Option 1 — EKS (Kubernetes)

The app runs on an ARM64 managed node group behind an ALB provisioned by the AWS Load Balancer Controller. CloudFront sits in front of the ALB providing HTTPS and restricting inbound traffic to CloudFront edge IPs only. Amazon Managed Grafana is provisioned by the CDK stack.

```
Browser → CloudFront (HTTPS) → ALB (HTTP, CloudFront-only SG) → EKS pod
                                                                    ↓
                                                    EFS (config / reports / interactive / quarto-site)
```

#### Deploy (fresh stack)

```bash
cd cdk
make eks-install        # create LB Controller IAM policy (once per AWS account)
make bootstrap          # bootstrap CDK (once per account+region)
make ecr-push           # build and push :latest to ECR
make eks-full-deploy    # end-to-end: CDK + kubeconfig + LB controller + Helm + Grafana (~30-40 min)
make seed-config        # store config.json in SSM (re-run any time config changes)
```

After `eks-full-deploy` finishes, navigate to the CloudFront URL (printed in CDK outputs) and use **Run Reports…** from the sidebar to generate the initial report set. This populates the Quarto static site, Marimo interactive pages, and Grafana dashboards on EFS.

#### Day-to-day operations

| Command | Description |
|---|---|
| `make ecr-push` | Build and push a new `:latest` image to ECR |
| `make eks-redeploy` | Restart the pod to pick up a freshly pushed image |
| `make eks-logs` | Tail live pod logs |
| `make eks-exec` | Open a shell in the running pod (SSM tunnel, no inbound ports) |
| `make eks-deploy` | Apply CDK stack changes |
| `make eks-grafana-deploy` | Re-push dashboard changes to the Grafana workspace |
| `make grafana-setup` | Rotate the Grafana Admin API key in SSM (valid 30 days) |
| `make eks-full-redeploy` | Full teardown + rebuild from scratch — runs `eks-destroy` then `eks-full-deploy`; reuses the current ECR tag, so run `ecr-push` first for fresh code. Safe to run unattended: `nohup make eks-full-redeploy > redeploy-eks.log 2>&1 &` |
| `make eks-destroy` | Tear down all EKS resources |

#### From the web UI / app (issue #218)

Deploy and destroy EKS from the browser's **[Deployments](#deployments)** dialog — both run as [durable background jobs](#durable-background-jobs), so a refresh can never kill a cloud mutation.

| Endpoint | Description |
|---|---|
| `POST /api/deploy/eks` | Deploy (or update) the EKS stack `NceEksStack` + Helm release. Returns a job manifest. |
| `POST /api/deploy/eks/destroy` | Tear down `NceEksStack` (the Helm release is uninstalled first). Returns a job manifest. |

These delegate to the whitelisted CLI below (this is also the exact argv the durable job runs):

```bash
python NceGitLab.py --deploy-eks publish    # make eks-full-deploy (CDK + Helm, reuses the existing ECR image tag)
python NceGitLab.py --deploy-eks status     # prints status JSON (state, url, stack_status)
python NceGitLab.py --deploy-eks destroy    # make eks-destroy
```

`publish`/`destroy` shell to the same path as `make -C cdk eks-full-deploy` / `eks-destroy`. Per **decision A3** the deploy **reuses the existing ECR image tag** — unlike ECS, `eks-full-deploy` never builds an image (the Helm chart pulls the current tag), so publish fails fast in preflight if the repository is empty; push an image first with `make -C cdk ecr-push` (there is **no CodeBuild**). A preflight verifies the toolchain (`make`, `cdk`, `node`, `aws`, `kubectl`, `helm`). Because it drives the local CDK/Helm toolchain, launch these from the **operator's** server (the box running `--serve`), not from inside the deployed container. `status` reports `not_deployed`, `deploying`, `deployed` (with the public URL, falling back to the `eks_cf_url` in `cdk-eks.json`), `destroying`, or `error`, read from the `NceEksStack` CloudFormation stack.

---

### Option 2 — ECS (Fargate)

The app runs as a single Fargate task on ARM64 behind an ALB with CloudFront in front. Simpler than EKS — no Kubernetes tooling required.

#### Deploy (fresh stack)

```bash
cd cdk
make bootstrap          # bootstrap CDK (once per account+region)
make ecr-push           # build and push :latest to ECR
make ecs-full-deploy    # CDK deploy + Grafana setup end-to-end
make seed-config        # store config.json in SSM
```

#### Day-to-day operations

| Command | Description |
|---|---|
| `make ecr-push` | Build and push a new `:latest` image to ECR |
| `make ecs-redeploy` | Force a new ECS deployment to pick up a freshly pushed image |
| `make ecs-logs` | Tail live container logs |
| `make ecs-exec` | Open a shell in the running Fargate task (SSM tunnel) |
| `make ecs-deploy` | Apply CDK stack changes |
| `make ecs-grafana-deploy` | Re-push dashboard changes to the Grafana workspace |
| `make grafana-setup` | Rotate the Grafana Admin API key in SSM (valid 30 days) |
| `make ecs-destroy` | Tear down ECS resources (EFS and CloudWatch logs are retained) |

#### From the web UI / app (issue #217)

Deploy and destroy ECS from the browser's **[Deployments](#deployments)** dialog — both run as [durable background jobs](#durable-background-jobs), so a refresh can never kill a cloud mutation.

| Endpoint | Description |
|---|---|
| `POST /api/deploy/ecs` | Deploy (or update) the ECS/Fargate stack `NceStack`. Returns a job manifest. |
| `POST /api/deploy/ecs/destroy` | Tear down `NceStack` (EFS and CloudWatch logs are retained). Returns a job manifest. |

These delegate to the whitelisted CLI below (this is also the exact argv the durable job runs):

```bash
python NceGitLab.py --deploy-ecs publish    # cdk deploy NceStack (reuses the existing ECR image tag)
python NceGitLab.py --deploy-ecs status     # prints status JSON (state, url, stack_status)
python NceGitLab.py --deploy-ecs destroy    # cdk destroy NceStack
```

`publish`/`destroy` shell to the same CDK path as `make -C cdk ecs-deploy` / `ecs-destroy`. Per **decision A3** the deploy **reuses the existing ECR image tag** — it only builds+pushes a new image when the repository is empty *and* a Docker daemon is present (there is **no CodeBuild**). A preflight verifies the toolchain (`make`, `cdk`, `node`, `aws`) and, when a first image is needed but Docker is absent, fails fast with a clear message. Because it drives the local CDK toolchain, launch these from the **operator's** server (the box running `--serve`), not from inside the deployed container. `status` reports `not_deployed`, `deploying`, `deployed` (with the public URL), `destroying`, or `error`, read from the `NceStack` CloudFormation stack.

---

### Option 3 — S3 static site (CloudFront + OAC)

Publish the **rendered static site** (Quarto pages + Marimo WASM notebooks + the JSON data layer) to a **private S3 bucket fronted by CloudFront** — no running container. The bucket blocks all public access; CloudFront reads it through an **Origin Access Control (OAC)**, with the bucket policy scoped to the distribution ARN (`aws:SourceArn`). The site is served over HTTPS, never from the raw S3 website endpoint.

**Choosing the bucket** — from the web UI the S3 row offers a **bucket selector** (issue #225): pick one of the account's existing buckets, or **Create new…**, which appends the AWS account id to a base name (`nce-safe-sim-site` → `nce-safe-sim-site-123456789012`) so the name is globally unique (an S3 requirement) and deterministic. Alternatively set a base in `config.json` under `deploy.s3` (used as the "create new" default and the pre-distribution fallback):

```json
"deploy": {
  "s3": {
    "bucket": "nce-safe-sim-site",
    "region": "us-east-1",
    "prefix": "",
    "distribution_comment": "NCE SAFe Simulator static site"
  }
}
```

Build the site first (`python NceGitLab.py --serve` → **Site** → *build all*, which produces `quarto-site/`, `public/interactive/`, and `public/data/`), then publish.

**From the web UI / API** — publish and destroy run as [durable background jobs](#durable-background-jobs) (a browser refresh can never kill a cloud mutation):

| Endpoint | Description |
|---|---|
| `GET /api/deploy/s3/buckets` | List the account's buckets + account id + suggested base name for the selector. Needs `s3:ListAllMyBuckets`; resilient (empty on failure). |
| `POST /api/deploy/s3` | Ensure the bucket, sync the built site (correct content-types + stale-object deletion), put it behind CloudFront/OAC, and report the HTTPS URL. Optional `{ "bucket": … }` body names the target. Returns a job manifest. |
| `POST /api/deploy/s3/destroy` | Disable + delete the distribution, empty the bucket (discovered from CloudFront), and delete it. Returns a job manifest. |

Publish is idempotent — the bucket, OAC, and distribution are reused on re-runs; each sync uploads changed files and deletes any object no longer part of the built site. **Status and destroy read the live bucket from CloudFront** (the app's distribution names its own bucket via the origin domain), so they work with no `deploy.s3.bucket` configured and always act on what's actually deployed.

**From the CLI** (this is also the exact argv the durable job runs):

```bash
python NceGitLab.py --deploy-s3 publish                       # publish to the configured bucket
python NceGitLab.py --deploy-s3 publish --deploy-s3-bucket X  # publish to a chosen/created bucket
python NceGitLab.py --deploy-s3 status                        # status JSON (state, url, object_count, last_sync, bucket)
python NceGitLab.py --deploy-s3 destroy                       # tear down the live deployment (bucket found via CloudFront)
```

Status reports one of `not_deployed`, `deploying` (bucket present, distribution not yet created), `deployed` (distribution live, with the HTTPS URL and the resolved bucket), or `error`.

**Infrastructure-as-code alternative** — the identical private-bucket + CloudFront/OAC topology is also available as a CDK stack for operators who prefer declarative IaC (object sync still happens via the publish job):

```bash
cd cdk
make s3-deploy     # deploy private bucket + CloudFront/OAC distribution
make s3-destroy    # tear it down (empties the bucket, deletes the distribution)
```

---

### Shared operations

| Command | Description |
|---|---|
| `make seed-config` | Write `config.json` to SSM as a SecureString (re-run to update) |
| `make grafana-setup` | Create/rotate the Grafana Admin API key, store in SSM |
| `make grafana-add-user` | Assign Grafana Admin role to the SSO user defined in `cdk-ecs.json` |
| `make audit` | Audit AWS resources for both ECS and EKS stacks — shows what is deployed, missing, or orphaned |

> **CDK config** — ECS and EKS each read their own config file (`cdk-ecs.json` / `cdk-eks.json`), loaded directly by `ecs_app.py` / `eks_app.py`. Values can be overridden per-command with `--context key=value`. The two stacks share no state and can be deployed, diffed, or destroyed simultaneously.

### Deploy/validate loop

`cdk/scripts/deploy-validate-loop.sh` exercises both stacks end-to-end — teardown → deploy ECS → validate ECS → deploy EKS → validate EKS → destroy — repeated `MAX_ITERATIONS` times (default 3). Each iteration checks CloudFormation status, ECS service / EKS pod health, and ALB HTTP response, failing fast on any error. Useful for confirming a clean deploy/destroy cycle after infrastructure changes.

```bash
cd cdk
MAX_ITERATIONS=1 nohup bash scripts/deploy-validate-loop.sh > deploy-validate-loop.log 2>&1 &
```

### Architecture diagram

The web UI includes an **AWS** button (visible on ECS and EKS deployments) that opens a zoomable, pannable architecture diagram for the active deployment. The diagram is generated at image build time by `diagrams/ecs_architecture.py` and `diagrams/eks_architecture.py` using the Python [`diagrams`](https://diagrams.mingrammer.com/) library.

If the relevant CloudFormation stack is deployed, `make ecr-push` automatically queries live CF outputs (CloudFront domain, EFS ID, EKS cluster name) to label nodes, and conditionally includes the Amazon Managed Grafana node when `GrafanaUrl` is present in the stack outputs. To regenerate diagrams locally without a full push:

```bash
cd cdk
make eks-diagram   # writes public/architecture/eks-architecture.png
make ecs-diagram   # writes public/architecture/ecs-architecture.png
```

### DoD architecture view set

Beyond the two deployment summaries, `diagrams/` carries a standard set of DoD-style architecture views organized along DoDAF viewpoints — suitable for program reviews and as the skeleton of an assessment package:

| View | DoDAF viewpoint | Script |
|---|---|---|
| Operational concept (stakeholders → system → GitLab → reporting) | OV-1 | `ov1_operational_concept.py` |
| System interfaces (components + every external interface w/ protocol & port) | SV-1 | `sv1_system_interfaces.py` |
| Deployment topology (EKS trust zones, security groups, ports) | SV-2 | `sv2_deployment_eks.py` |
| Deployment topology (ECS Fargate trust zones, security groups, ports) | SV-2 | `sv2_deployment_ecs.py` |
| Data flow (sources → snapshot pipeline → EFS stores → egress) | SV-4 | `dataflow_architecture.py` |
| DevSecOps pipeline (CI + operator deploy paths) | — | `devsecops_pipeline.py` |

[`diagrams/DOD_ARCHITECTURE.md`](diagrams/DOD_ARCHITECTURE.md) is the master document: an AV-1 overview, the view index, a PPSM ports/protocols/services table, the OV-6c logon & consent sequence (Mermaid, renders in GitLab), a security posture summary, and a known-gaps register. The PNGs are generated at container build time (Dockerfile stage 2) and appear as extra tabs in the web UI's **AWS** architecture dialog; regenerate locally with `make dod-diagrams` in `cdk/`.

### Grafana dashboards

Amazon Managed Grafana is **optional and off by default** (~$9/editor/month regardless of usage). Enable it at deploy time:

```bash
cdk deploy -c enable_grafana=true   # ECS
cdk deploy -c enable_grafana=true --app "python eks_app.py"   # EKS
```

Dashboards read JSON data from `<CloudFrontUrl>/data/<report>.json`, served by the app from the most recent complete report snapshot on EFS. Data refreshes automatically each time reports are run from the web UI.

> **AMG prerequisite:** AWS IAM Identity Center must be enabled in the account (one-time setup, no ongoing cost). Browser login uses SSO; all automation uses an Admin API key stored in SSM at `/nce/grafana-api-key`.

> **Tip:** `make eks-exec` / `make ecs-exec` opens a `/bin/sh` shell inside the running container via SSM — no inbound ports required. Use it to inspect EFS contents, check environment variables, or diagnose startup failures.

---

## Contributing

Bug reports and feature requests are tracked as GitLab issues at [gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/issues](https://gitlab.com/gl-demo-ultimate-lmwilliams/nce-safe-simulator/-/issues). Open an issue describing what you found or what you need — include reproduction steps for bugs, and a use-case description for feature requests.

---

## What `--clean` Removes

`cleanup_group()` performs a full teardown in safe dependency order:

1. Wiki pages (root group)
2. Epics (children before parents, recursively)
3. Issues (all projects, parallel)
4. Labels (root group + subgroups + projects)
5. Projects
6. Subgroups (deepest first)
7. Root group

---

## Design Notes

**Mixin architecture** — `NceGitLab` inherits from twelve single-responsibility mixin classes in `mixins/`. The main file contains only `__init__` (config loading and GitLab auth) and the CLI `main()`. Adding new capabilities means adding a new mixin or extending an existing one without touching the core class.

**GraphQL for epic weights** — GitLab's REST API does not expose planned weight on epics; it must be read and written via the GraphQL `workItemUpdate` mutation and `WorkItemWidgetWeight` widget. All weight operations route through `_set_epic_weight()` and `_fetch_epic_weights()` in `mixins/utils.py`.

**Metrics caching** — `calculate_portfolio_metrics()` caches results per group name in `_metrics_cache` so that multiple reports generated in the same session share a single fetch pass.

**Config-driven defaults** — All numeric defaults for bootstrap counts and tool parameters live in `config.json` under `defaults.bootstrap` and `defaults.tools`. Function signatures use `None` sentinels and resolve from `self.default_*` at runtime, so callers can still override individual values programmatically. Structure count keys (`num_value_streams`, `num_arts`, `num_teams`, etc.) accept a plain integer, `{"desired": N}`, or `{"min": M, "max": N}` range object. `_resolve_range()` in `mixins/bootstrap.py` handles all three forms; `_range_label()` produces a human-readable annotation for the run summary.

**API session** — All HTTP calls route through a shared `requests.Session` configured by `_make_session()` in `mixins/utils.py`. The session mounts a `_TimeoutAdapter` that enforces `api_timeout` (default 300 s, configurable in `config.json`) on every request and auto-retries 429 and transient 5xx (500/502/503/504) responses up to 5 times with exponential backoff (1 → 2 → 4 → 8 → 16 s) — idempotent methods only, so mutations keep fail-fast semantics. The python-gitlab client mounts the same adapter and is constructed with `retry_transient_errors=False`: python-gitlab's own retry re-sends *all* methods, so a create whose response was lost to a gateway blip would be re-POSTed and silently duplicated on the target (#207). Under this policy a mutation that hits a transient error fails fast and is counted in the run summary, and re-running the import/bundle with `on_existing=skip` recovers it; reads still survive passing gateway errors, so report runs don't die minutes into a snapshot (#176). Each scheduled retry is announced in the job log (#201).

**Job timing** — Each phase (clean, create, individual reports, all) logs start/stop times and elapsed duration via `_print_timing_table()` in `mixins/utils.py`. `--all` aggregates all phases into a consolidated summary table.

**Data snapshots** — Every report run writes six files to `reports/YYYYMMDD/HHMMSS/` — `epics.json`, `issues.json`, `blocking_graph.json`, `issue_blocking.json`, `groups.json`, and `projects.json` — before generating any wiki pages. All report methods read exclusively from this snapshot; no further API calls are made after the snapshot is written. Multiple runs per day each get their own timestamped subdirectory.

---

## SAFe 6.0 Reference

SAFe 6.0 defines three measurement domains applied at every level (Team → ART → Portfolio):

| Domain | What it measures |
|--------|-----------------|
| **Outcomes** | Business and customer success: KPIs, OKRs, value realized |
| **Flow** | Delivery efficiency: velocity, time, load, efficiency, distribution, predictability |
| **Competency** | Proficiency in SAFe practices (assessed via surveys/maturity models) |

### Six Flow Metrics

| Metric | Definition | This tool |
|--------|-----------|-----------|
| Flow Velocity | Features/Capabilities completed per PI | ✅ Flow Metrics report |
| Flow Load | Open epics/features (WIP) vs prior PIs | ✅ Flow Metrics report |
| Flow Distribution | % Feature vs Enabler vs Infrastructure vs Defect | ✅ Flow Metrics report (`type::` labels) |
| Flow Time | Average days from epic created to closed | ✅ Flow Metrics report (proxy via `updated_at`) |
| Flow Predictability | % of PI objectives met, trended | ✅ PI Predictability Scorecard |
| Flow Efficiency | Value-added time vs total wait time | ⬜ Requires time-in-state tracking not available via GitLab epics API |

Flow Predictability (% PI objectives met) is the single most-watched metric at ART and portfolio level for DoD programs.

### Relationship to Earned Value Management (EVM)

For DoD acquisition programs, SAFe flow metrics complement rather than replace traditional EVM. Flow metrics address *what* is being delivered and *how efficiently*; EVM addresses cost and schedule variance against the baseline contract. Both are needed for large acquisition programs.
