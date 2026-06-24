# NCE GitLab SAFe Tooling

Python automation for GitLab groups organised around the **Scaled Agile Framework (SAFe)** hierarchy. Generates realistic lorem test data, manages the Epic → Capability/Feature → Issue tree across multiple groups, and publishes a suite of portfolio-level reports to a GitLab Group Wiki.

---

## SAFe Hierarchy Model

```
Root Group  (Portfolio)
│   Portfolio Epics  🏆
│   Direct Features  🛠️  ← Features parented straight to a Portfolio Epic
│
├── Value Stream 01
│   Capabilities  🧩  ← cross-ART/VS deliverables
│   ├── ART 01
│   │   Capabilities  🧩
│   │   ├── Team 01
│   │   │   Features  🛠️
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

**Requirements:** Python 3.9+, Node.js 18+, Git, a GitLab Personal Access Token with `api` scope.

### 1 — Clone

```bash
git clone https://gitlab.com/saic-study-group/nce-safe-simulator.git
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

Edit `config.json` and set at minimum:

| Field | Description |
|---|---|
| `url` | GitLab instance URL (default `https://gitlab.com`) |
| `private_token` | Personal Access Token with `api` scope |
| `parent_group` | Display name of the SAFe portfolio root group |
| `gitlab_namespace` | URL slug of the namespace that will contain the root group |

All other settings can be edited in-browser via the ⚙ Config button once the server is running.

### 5 — Start the web server

Linux / macOS:
```bash
python3 NceGitLab.py --serve
```

Windows:
```bat
python NceGitLab.py --serve
```

The server starts on `http://localhost:4645`. Open `http://localhost:4645/app/` in your browser.
Run the same command again to stop it.

> **Port override:** the default port is `4645`. To use a different port, pass `--port NNNN` on the command line or set `"port": NNNN` in `config.json`.

---

## Configuration

Copy and edit `config.json`:

```json
{
    "url": "https://gitlab.com",
    "private_token": "glpat-XXXXXXXXXXXXXXXXXXXX",
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
            "direct_feature_ratio": 0.70
        },
        "tools": {
            "close_percent":                30.0,
            "generate_epic_blocks_count":   10,
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
| `defaults.bootstrap` | Default counts and ratios for `--create` (see below) |
| `defaults.tools` | Default parameter values for utility tools (see below) |

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

#### `defaults.tools`

| Key | Default | Description |
|---|---|---|
| `close_percent` | `30.0` | Default % for `close-percent` tool |
| `generate_epic_blocks_count` | `10` | Default block count for `generate-epic-blocks` |
| `simulate_pi_progress_percent` | `50.0` | Default % closure for `simulate-pi-progress` |
| `generate_issues_count` | `5` | Default issues per Feature for `generate-issues` |
| `weight_drift_threshold` | `20.0` | Default drift % for `weight-drift-check` |
| `set_risk_labels_percent` | `15.0` | Default % of open epics to label for `set-risk-labels` |
| `set_wsjf_labels_percent` | `20.0` | Default % of open epics to label for `set-wsjf-labels` |

### Environment Variable Overrides

Any config value can be overridden at runtime without editing the file:

| Variable | Overrides |
|---|---|
| `ACCESS_TOKEN` | `private_token` |
| `GROUP_NAME` | `parent_group` |
| `PROJECT_LABELS` | `project_labels` (comma-separated) |
| `PIID_LABELS` | `piid_labels` (comma-separated) |
| `EPIC_TYPE_LABELS` | `epic_type_labels` (comma-separated) |
| `RISK_LABELS` | `risk_labels` (comma-separated) |
| `WORK_TYPE_LABELS` | `work_type_labels` (comma-separated) |
| `LIFECYCLE_LABELS` | `lifecycle_labels` (comma-separated) |
| `ROAM_LABELS` | `roam_labels` (comma-separated) |
| `FIBONACCI_WEIGHTS` | `fibonacci_weights` (comma-separated integers) |

In a GitLab pipeline, set these as [CI/CD variables](https://docs.gitlab.com/ee/ci/variables/) under **Settings → CI/CD → Variables**. Mark `ACCESS_TOKEN` as **Masked** to keep the token out of job logs. `ACCESS_TOKEN` and `GROUP_NAME` are the minimum required for the `generate-reports` job.

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

`-r` fetches live data from GitLab on every run and saves a timestamped JSON snapshot under `reports/YYYY-MM-DD/HH-MM-SS/data/`. Two flags let you skip the fetch and reuse a previous snapshot:

| Flag | Behaviour |
|------|-----------|
| `--last` | Automatically finds and loads the most recent saved snapshot |
| `--reuse-data DIR` | Loads the snapshot from the directory you specify |

A typical demo cycle:

```bash
# Tear down yesterday's data, rebuild, and publish fresh reports
python3 NceGitLab.py --all
```

### Web UI

A Vue 3 browser interface provides an alternative to the CLI for running utility tools and viewing reports. The backend is a FastAPI server that exposes the same tools over HTTP/WebSocket.

#### Starting the web UI

**Production (recommended for demos):**

```bash
cd frontend && npm run build && cd ..
python3 NceGitLab.py --serve          # serves on http://localhost:4645
```

Navigate to `http://localhost:4645/app/`.

**Development (hot-reload, edit frontend without rebuilding):**

```bash
python3 NceGitLab.py --serve          # backend on port 4645
cd frontend && npm run dev            # Vite dev server on http://localhost:5173
```

Navigate to `http://localhost:5173/app/`. The dev server proxies `/api` and all non-app paths to the Python backend, so reports and API calls work without a production build.

#### Layout

| Area | Content |
|------|---------|
| Top nav | PMW 120 / NCE Safe Simulator wordmark; running-job count badge; dark ↔ light theme toggle; Status panel toggle |
| Left sidebar | Job picker (collapsible groups) + Run Reports button + footer links: **Quarto ↗**, **Wiki ↗**, **GitLab ↗**, **AMG ↗** (shown only when Grafana URL is configured) |
| Main pane | Job runner — one tab per launched job with streaming log output |
| Right panel | Status sidebar — server polling and session history (toggle via nav bar) |

#### Job picker

Tools are grouped by purpose in collapsible sections, all collapsed by default. A filter input at the top narrows across all groups in real time; × clears it. Each row shows the tool name, a short description, and a status badge (`read-only`, `⚙` for configurable, `● running`).

Clicking a tool with no parameters launches it immediately. Clicking a parameterised tool opens a modal dialog — booleans become toggles (`dry_run` is highlighted amber), integers and floats get number inputs, strings get text inputs, and group-targeting fields pre-fill from the active config. Required fields block Launch until filled. Destructive tools show a confirmation step.

Tools that share a `parallelism_group` cannot run concurrently; the dialog disables Launch and lists the blocking jobs if a conflict exists.

**Run Reports…** — a button pinned at the bottom of the sidebar opens the report picker dialog: choose individual reports or toggle All, select output formats (markdown / plotly / interactive; plotly and interactive require all reports to be selected since site builds are project-wide), and optionally check **Use last available data snapshot** to skip the GitLab API fetch and re-render from the most recent `data/` directory.

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

The sidebar footer contains four links. **Quarto ↗** opens the static Quarto report site (`/quarto/`) in a new tab. **Wiki ↗** opens the GitLab group wiki. **GitLab ↗** opens the root GitLab group. **AMG ↗** opens the Amazon Managed Grafana workspace (only shown when `grafana_url` is set in config). Reports and interactive pages must be built first:

```bash
python3 NceGitLab.py -r all --formats all   # builds markdown + quarto + Marimo outputs
```

---

## What `--create` Builds

`create_all_lorem_objects()` builds a full SAFe group hierarchy under the configured root group:

- Root group with **Portfolio Epics** (🏆)
- *N* Value Stream subgroups, each with **Capabilities** (🧩)
- *N* ART subgroups per Value Stream, each with **Capabilities** (🧩)
- *N* Team subgroups per ART, each with:
  - **Features** (🛠️)
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

All reports are published as GitLab Wiki pages under the root group wiki. Run interactively with `--report` or pass a key directly (e.g. `--report portfolio`). Use `--report all` to run every report non-interactively (required for CI).

### Wiki Structure — Four-Tier Portfolio Home

Reports are organized into four tiers by audience and cadence. The wiki home page (`home`) is the entry point; from there, all tier landing pages and individual reports are linked.

```
home  (Portfolio Home index)
├── 00 Executive Pulse        — daily, executives
│   └── Portfolio Health Dashboard
├── 01 Program Management     — weekly, RTEs and PMs
│   ├── Program × PI Matrix
│   ├── Program PI Detail
│   ├── PI Predictability Scorecard
│   ├── Risk Register
│   ├── ART Capacity Balance
│   ├── Blocking & Cross-ART Risk
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

Every report run — whether a single report or all — makes **one pass through the GitLab API**, writes a complete data snapshot to disk, and then generates all wiki pages from that snapshot with no further API reads. This eliminates redundant queries across all reports.

```
reports/
  YYYYMMDD/
    HHMMSS/
      epics.json      # typed epics (full fields + rollups) + all_epics_raw (includes untyped)
      issues.json     # all issues: full fields including assignees, milestone, epic link
      blocking.json   # blocking graph: blocked epics, blockers, at-risk ancestry, id_int mappings
      groups.json     # SAFe group hierarchy: portfolio → VS → ART → Team, each with level tag
      projects.json   # Team Backlog projects with namespace_id, path, and issues_enabled flag
```

The directory is printed to the console at the start of every run:

```
Data snapshot → reports/20260525/143022/
  epics.json    (47 typed + 2 untyped)
  issues.json   (312 issues)
  blocking.json (5 blocked epics)
  groups.json   (15 groups)
  projects.json (8 projects)
```

**`epics.json` fields:** `id`, `iid`, `type`, `title`, `description`, `state`, `labels`, `parent_id`, `group_id`, `planned_weight`, `actual_weight`, `pct_complete`, `pct_through_pi`, `piid`, `business_value`, `blocked_by_count`, `blocks_count`, `start_date`, `due_date`, `created_at`, `updated_at`, `web_url`, `work_item_id`, `roam_risks`

**`issues.json` fields:** `id`, `iid`, `title`, `description`, `state`, `labels`, `weight`, `due_date`, `assignees`, `epic_id`, `epic_iid`, `project_path`, `web_url`, `created_at`, `updated_at`, `closed_at`

**`blocking.json` structure:** `summary` (total blocked, total relationships, portfolio epics at risk) + `relationships` array where each entry has `blocked_epic` (with `id_int` integer), `blocked_by` list (each with `id_int`), and `at_risk_portfolio_epics` list.

**`groups.json` fields:** `id`, `name`, `path`, `full_path`, `parent_id`, `web_url`, `level` (portfolio / vs / art / team)

**`projects.json` fields:** `id`, `name`, `path`, `path_with_namespace`, `name_with_namespace`, `namespace_id`, `web_url`, `issues_enabled`

#### Output formats

The `--formats` flag controls which output types are produced. Combine multiple:

```bash
python3 NceGitLab.py --report all --formats markdown          # Wiki only (default)
python3 NceGitLab.py --report all --formats plotly            # Quarto HTML only
python3 NceGitLab.py --report all --formats interactive       # Marimo WASM only
python3 NceGitLab.py --report all --formats all               # All formats
```

| Format | Output | Description |
|---|---|---|
| `markdown` | GitLab Wiki | Default; publishes wiki pages to the root group wiki |
| `plotly` | `public/quarto/` | Static HTML reports (Quarto + Plotly); full site in CI |
| `interactive` | `public/interactive/` | Marimo WASM interactive pages (filter/drill-down); see below |

When `--formats` is omitted, `markdown` is assumed. Pass `--no-ssl-verify` to disable TLS certificate verification for corporate proxy environments (also configurable via `SSL_VERIFY=false` env var or `"ssl_verify": false` in `config.json`).

#### Interactive pages

`build_interactive.py` exports a subset of reports as Marimo WASM notebooks — self-contained HTML files that run Python in the browser via WebAssembly. No server required; pages work from GitLab Pages or any static host.

```bash
python3 build_interactive.py    # exports all 12 notebooks → public/interactive/
```

Interactive pages share a single `public/interactive/assets/` directory (~34 MB total vs ~400 MB if each notebook kept its own copy). Notebooks are exported in parallel for speed.

Available interactive reports: health-dashboard, pi-predictability, flow-metrics, art-capacity-balance, piid-project, piid-project-detail, workload, art-feature-status, vs-capability-dashboard, team-backlog, portfolio, diagnostics.

#### CI and GitLab Pages

`.gitlab-ci.yml` has two jobs:

| Job | Stage | Trigger | What it does |
|---|---|---|---|
| `test` | build | every push | `pip install -r requirements.txt && pytest tests/` |
| `pages` | pages | `develop` branch only | Builds the full site → `public/` and publishes to GitLab Pages |

The `pages` job runs `python3 NceGitLab.py --report all --formats all` (Quarto + Marimo) then publishes the resulting `public/` directory. It uses the `ghcr.io/quarto-dev/quarto:latest` image which includes Python, Quarto, and the Marimo CLI.

The deployed site is published at the project's GitLab Pages URL and mirrors the wiki structure as navigable HTML with interactive drill-down on supported reports. Each static report page links to its interactive counterpart via a **📄 Static** toggle button, and vice versa.

### Report Index

> **Label discovery:** Reports derive label sets (`PIID::`, `project::`, `risk::`, `type::`, `lifecycle::`, `wsjf-*`) from the live data snapshot rather than from `config.json`. They reflect whatever labels actually exist in the system, so they work correctly on any live GitLab group.

| Key | Tier | Wiki Page | What it conveys |
|---|---|---|---|
| `wiki-index` | — | `home` | Four-tier navigation index linking all report pages |
| `health-dashboard` | T1 | `00 Executive Pulse/Portfolio Health Dashboard` | Per-VS traffic-light status across Schedule, Capacity, Risk, and Blocking |
| `piid-project` | T2 | `01 Program Management/Program × PI Matrix` | Project label vs PI quarter cross-tab with status and weights |
| `piid-project-detail` | T2 | `01 Program Management/Program PI Detail` | Per-PI section view of program workload and status |
| `pi-predictability` | T2 | `01 Program Management/PI Predictability Scorecard` | % of committed Features/Capabilities delivered per PI, trended by ART |
| `risk-register` | T2 | `01 Program Management/Risk Register` | All risk-flagged epics grouped by level (High → Medium → Low) with PI and owning ART |
| `art-capacity-balance` | T2 | `01 Program Management/ART Capacity Balance` | Per-team planned vs actual weight per PI — spot over/under-capacity *(index → VS → ART)* |
| `blocking` | T2 | `01 Program Management/Blocking & Cross-ART Risk` | Blocked epics, ancestor risk propagation, and per-VS cross-ART dependency breakdown *(index → VS)* |
| `wsjf` | T2 | `01 Program Management/WSJF Priority Board` | Portfolio backlog ranked by `(Value + Urgency + Risk) ÷ Job Size` — shows what to work on next |
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

### Setup

| Key | Description |
|---|---|
| `scaffold` | Create SAFe group/project structure (VS → ART → Team → Team Backlog) with no content |
| `setup-bv-field` | Create or verify the Business Value custom field at the root namespace (Fibonacci 1–21) |

### Seed Data

| Key | Description |
|---|---|
| `generate-issues` | Create issues in team backlog projects linked to Feature epics |
| `generate-epic-blocks` | Randomly create or remove blocking relationships between epics |
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

| Key | Scope | Key fields |
|---|---|---|
| `export-epics` | All epics across the full group hierarchy | `group_path`, `iid`, `id`, `title`, `description`, `state`, `labels`, `start_date`, `due_date`, `parent_id`, `parent_iid`, `planned_weight`, `author`, `web_url`, timestamps |
| `export-issues` | All issues across the full group hierarchy | `project_path`, `iid`, `id`, `title`, `description`, `state`, `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `epic_iid`, `author`, `web_url`, timestamps |
| `import-epics` | Create epics from file with pre-flight validation | Required: `title` — Optional: `group_path`, `labels`, `start_date`, `due_date`, `parent_id`, `planned_weight`, `state` |
| `import-issues` | Create issues from file with pre-flight validation | Required: `title`, `project_path` — Optional: `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `state` |

`planned_weight` on epics is fetched/set via GraphQL (the REST API does not expose it).

Both importers run a full validation pass before creating anything — errors are reported upfront and the import aborts if any are found. Pass `dry_run: yes` to validate and preview without creating. When `parent_id` values from an external system don't match live IDs, the importer asks once how to handle them: `ask` (pick a fallback parent interactively), `label` (create without parent and tag `import::needs-parent`, default), or `skip`.

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

## AWS Deployment

The simulator runs on AWS in two configurations. **EKS (Kubernetes)** is recommended for production — managed node group, EFS persistent storage, CloudFront in front of the ALB. **ECS (Fargate)** is the simpler option for lower-traffic or short-lived deployments. Both share the same CDK project (`cdk/`), ECR image, SSM-stored config, EFS layout, and Grafana workspace.

### Prerequisites

- AWS CLI configured (`aws configure`)
- Docker (for building the container image)
- CDK CLI: `npm install -g aws-cdk`
- `kubectl` (EKS only)
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
| `make eks-destroy` | Tear down all EKS resources |

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

---

### Shared operations

| Command | Description |
|---|---|
| `make seed-config` | Write `config.json` to SSM as a SecureString (re-run to update) |
| `make grafana-setup` | Create/rotate the Grafana Admin API key, store in SSM |
| `make grafana-add-user` | Assign Grafana Admin role to the SSO user defined in `cdk.json` |

### Architecture diagram

The web UI includes an **AWS** button (visible on ECS and EKS deployments) that opens a zoomable, pannable architecture diagram for the active deployment. The diagram is generated at image build time by `diagrams/ecs_architecture.py` and `diagrams/eks_architecture.py` using the Python [`diagrams`](https://diagrams.mingrammer.com/) library.

If the relevant CloudFormation stack is deployed, `make ecr-push` automatically queries live CF outputs (CloudFront domain, EFS ID, EKS cluster name) to label nodes, and conditionally includes the Amazon Managed Grafana node when `GrafanaUrl` is present in the stack outputs. To regenerate diagrams locally without a full push:

```bash
cd cdk
make eks-diagram   # writes public/architecture/eks-architecture.png
make ecs-diagram   # writes public/architecture/ecs-architecture.png
```

### Grafana dashboards

Amazon Managed Grafana is provisioned automatically by the CDK stack. Dashboards read JSON data from `<CloudFrontUrl>/data/<report>.json`, served by the app from the most recent complete report snapshot on EFS. Data refreshes automatically each time reports are run from the web UI.

> **AMG prerequisite:** AWS IAM Identity Center must be enabled in the account (one-time setup, no ongoing cost). Browser login uses SSO; all automation uses an Admin API key stored in SSM at `/nce/grafana-api-key`.

> **Tip:** `make eks-exec` / `make ecs-exec` opens a `/bin/sh` shell inside the running container via SSM — no inbound ports required. Use it to inspect EFS contents, check environment variables, or diagnose startup failures.

---

## Contributing

Bug reports and feature requests are tracked as GitLab issues at [gitlab.com/saic-study-group/nce-safe-simulator/-/issues](https://gitlab.com/saic-study-group/nce-safe-simulator/-/issues). Open an issue describing what you found or what you need — include reproduction steps for bugs, and a use-case description for feature requests.

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

**API session** — All HTTP calls route through a shared `requests.Session` configured by `_make_session()` in `mixins/utils.py`. The session mounts a `_TimeoutAdapter` that enforces `api_timeout` (default 300 s, configurable in `config.json`) on every request and auto-retries 429 responses up to 5 times with exponential backoff (1 → 2 → 4 → 8 → 16 s). This prevents report runs from hanging silently on slow GitLab responses.

**Job timing** — Each phase (clean, create, individual reports, all) logs start/stop times and elapsed duration via `_print_timing_table()` in `mixins/utils.py`. `--all` aggregates all phases into a consolidated summary table.

**Data snapshots** — Every report run writes five files to `reports/YYYYMMDD/HHMMSS/` — `epics.json`, `issues.json`, `blocking.json`, `groups.json`, and `projects.json` — before generating any wiki pages. All report methods read exclusively from this snapshot; no further API calls are made after the snapshot is written. Multiple runs per day each get their own timestamped subdirectory.

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
