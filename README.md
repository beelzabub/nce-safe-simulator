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
  epics.py         # Epic operations, CSV import/export, markdown report
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

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

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
            "weight_drift_threshold":       20.0
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
| `project_labels` | Labels representing programs or workstreams |
| `piid_labels` | `PIID::YYYYQn` labels mapping work to PI quarters |
| `epic_type_labels` | Must include `Epic`, `Capability`, `Feature` |
| `fibonacci_weights` | Valid issue story-point values |
| `epic_type_planned_weights` | Valid planned-weight pools per epic type |
| `defaults.bootstrap` | Default counts and ratios for `--create` (see below) |
| `defaults.tools` | Default parameter values for utility tools (see below) |

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

### Environment Variable Overrides

Any config value can be overridden at runtime without editing the file:

| Variable | Overrides |
|---|---|
| `ACCESS_TOKEN` | `private_token` |
| `GROUP_NAME` | `parent_group` |
| `PROJECT_LABELS` | `project_labels` (comma-separated) |
| `PIID_LABELS` | `piid_labels` (comma-separated) |
| `EPIC_TYPE_LABELS` | `epic_type_labels` (comma-separated) |
| `FIBONACCI_WEIGHTS` | `fibonacci_weights` (comma-separated integers) |

---

## Usage

### Main CLI

```bash
python3 NceGitLab.py --clean              # Delete all data in the root group
python3 NceGitLab.py --create             # Bootstrap a full SAFe lorem data set
python3 NceGitLab.py --scaffold           # Create SAFe group structure only (prompted)
python3 NceGitLab.py --scaffold my/group  # Create SAFe group structure under a specific group
python3 NceGitLab.py --report             # Show the report menu
python3 NceGitLab.py --report all        # Run all reports non-interactively
python3 NceGitLab.py --report portfolio   # Run a single report by key
python3 NceGitLab.py --utilities          # Show the utility tool menu
python3 NceGitLab.py --utilities audit-labels  # Run a single tool by key
python3 NceGitLab.py --all                # clean → create → report in sequence
```

Each phase prints start/stop times and duration. `--all` prints a full run summary table on completion.

A typical demo cycle:

```bash
# Tear down yesterday's data, rebuild, and publish fresh reports
python3 NceGitLab.py --all
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
  - 8–15 Issues per Feature, linked to milestones, with Fibonacci weights

After all objects are created the hierarchy is linked cross-group:  
`VS Capabilities → Portfolio Epics` → `ART Capabilities → VS Capabilities`

Features are then split by `direct_feature_ratio` (default 70%):
- **Direct Features** (majority) — linked straight to Portfolio Epics
- **Capability-chain Features** (remainder) — linked to ART Capabilities

All epics are labelled with a random project label, PIID label, and type label. Planned weights are set via the GraphQL `workItemUpdate` mutation (the REST API silently ignores epic weight).

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

All reports are published as GitLab Wiki pages. Run interactively with `--report` or pass a key directly (e.g. `--report portfolio`). Use `--report all` to run every report non-interactively (required for CI).

### Data Snapshot

Every report run — whether a single report or all — makes **one pass through the GitLab API**, writes a complete data snapshot to disk, and then generates all wiki pages from that snapshot with no further API reads. This eliminates redundant queries across the 13 reports.

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

**`epics.json` fields:** `id`, `iid`, `type`, `title`, `description`, `state`, `labels`, `parent_id`, `group_id`, `planned_weight`, `actual_weight`, `pct_complete`, `pct_through_pi`, `piid`, `blocked_by_count`, `blocks_count`, `start_date`, `due_date`, `created_at`, `updated_at`, `web_url`

**`issues.json` fields:** `id`, `iid`, `title`, `description`, `state`, `labels`, `weight`, `milestone`, `assignees`, `epic_id`, `epic_iid`, `project_path`, `web_url`, `created_at`, `updated_at`, `closed_at`

**`blocking.json` structure:** `summary` (total blocked, total relationships, portfolio epics at risk) + `relationships` array where each entry has `blocked_epic` (with `id_int` integer), `blocked_by` list (each with `id_int`), and `at_risk_portfolio_epics` list.

**`groups.json` fields:** `id`, `name`, `path`, `full_path`, `parent_id`, `web_url`, `level` (portfolio / vs / art / team)

**`projects.json` fields:** `id`, `name`, `path`, `path_with_namespace`, `name_with_namespace`, `namespace_id`, `web_url`, `issues_enabled`

#### CI Artifact

The `generate-reports` job in `.gitlab-ci.yml` runs `--report all` and publishes the `reports/` directory as a downloadable artifact (30-day retention). The job is `when: manual` to avoid unintended API calls. Trigger it from the GitLab pipeline UI after setting `ACCESS_TOKEN` and `GROUP_NAME` as CI/CD variables in the project settings.

Reports fall into two structural types:

**Flat reports** publish a single page to the root group wiki.  
**Hierarchical reports** publish a root-level index page to the root group wiki plus one detail page per group at the relevant hierarchy level. The index page summarises every sub-group and links directly to its detail page, so the root wiki is the single entry point for the full picture.

### Flat Reports

| Key | Wiki Page | Description |
|---|---|---|
| `portfolio` | `<group> - SAFe Portfolio Report` | Collapsible Epic → Capability/Feature hierarchy with % complete, planned vs actual weight, PI progress, and risk flags |
| `workload` | `<group> - ART-Team Workload Report` | Per-PI table of planned vs actual weight per group with on-track / at-risk / incomplete status |
| `blocking` | `<group> - Blocking Relationships Report` | Blocked epics, their blockers, ancestor risk propagation, and portfolio-level risk summary |
| `unassigned-pi` | `<group> - Unassigned PI Report` | Epics with no `PIID::` label, broken down by type |
| `orphan-epics` | `<group> - Orphaned Epics Report` | Epics with no parent and no children (completely disconnected from hierarchy) |
| `orphan-issues` | `<group> - Orphaned Issues Report` | Issues not linked to any epic, grouped by project |
| `piid-project` | `<group> - Program × PI Report` | Project label vs PI quarter cross-tab with status and weights |
| `piid-project-detail` | `<group> - Program PI Detail Report` | Per-PI section view of program workload and status |

### Hierarchical Reports

| Key | Root Index (root group wiki) | Detail Pages | Description |
|---|---|---|---|
| `team-backlog` | `<group> - Team Backlog Report` | One page per Team, published to **each Team's own group wiki** | Issues grouped by Feature per Team with weight and completion |
| `art-feature-status` | `<group> - ART Feature Status Report` | `ART Feature Status/<VS>/<ART>` on root wiki | All Features per ART grouped by Team, with completion, weight, and risk |
| `art-capacity-balance` | `<group> - ART Capacity Balance Report` | `ART Capacity Balance/<VS>/<ART>` on root wiki | Per-team planned vs actual weight per PI with over/under capacity flags |
| `vs-capability-dashboard` | `<group> - VS Capability Dashboard` | `VS Capability Dashboard/<VS>` on root wiki | Capabilities and Direct Features by PI with per-ART breakdown per Value Stream |
| `vs-cross-art-risk` | `<group> - VS Cross-ART Risk Report` | `VS Cross-ART Risk/<VS>` on root wiki | Blocking relationships that cross ART boundaries within a Value Stream |

> **Team Backlog note:** Detail pages are written to each Team group's own wiki (not the root wiki). This keeps team-level work visible in the team's own GitLab group while the root index provides the portfolio roll-up view.

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

Run interactively with `--utilities` or pass a key directly (e.g. `--utilities audit-labels`).

| Key | Description |
|---|---|
| `close-percent` | Randomly close N% of open epics and issues (simulate PI progress) |
| `update-weights` | Assign planned weights to all epics based on SAFe type label |
| `validate-weights` | Validate epic and issue weights against configured pools |
| `generate-epic-blocks` | Randomly create or remove blocking relationships between epics |
| `set-issue-weights` | Assign Fibonacci story-point weights to issues that currently have none |
| `audit-labels` | Report every epic missing a type, PIID, or project label |
| `simulate-pi-progress` | Close X% of open issues linked to epics in a specific PI |
| `set-piid-labels` | Bulk-assign a PIID label to epics that are missing one |
| `set-project-labels` | Bulk-assign a project label to epics that are missing one |
| `generate-issues` | Create issues in team backlog projects linked to Feature epics |
| `set-epic-states` | Open or close all epics matching an optional type and/or PI filter |
| `audit-hierarchy` | Verify Features have valid parents (Capability or Epic) and Capabilities have Epic parents |
| `weight-drift-check` | Flag epics where planned weight vs sum of issue weights drifts beyond a threshold |
| `reset-pi-progress` | Reopen all closed issues linked to epics in a specific PI |
| `strip-labels` | Remove a specific label from all epics (optionally filtered by type) |
| `export-epics` | Export all epics from the group hierarchy to CSV or JSON (full field set, all subgroups) |
| `import-epics` | Import epics from CSV or JSON with pre-flight validation, resilient field handling, dry-run |
| `export-issues` | Export all issues from the group hierarchy to CSV or JSON (full field set, all subgroups) |
| `import-issues` | Import issues from CSV or JSON with pre-flight validation, milestone/assignee lookup, dry-run |
| `scaffold` | Create SAFe group/project structure (VS → ART → Team → Team Backlog) with no content |

---

## Import / Export

Epic and issue import/export is available via the `--utilities` menu (`export-epics`, `import-epics`, `export-issues`, `import-issues`).

### File Formats

Both CSV and JSON are supported. Format is inferred from the file extension (`.json` → JSON, anything else → CSV). Export filenames are auto-named from the group name when no output path is given (e.g. `bmw-120-epics-export.csv`). Relative and `~`-prefixed input paths are resolved to absolute.

### Export

| Tool | Scope | Key fields exported |
|---|---|---|
| `export-epics` | All epics across the full group hierarchy (recursive by default) | `group_path`, `iid`, `id`, `title`, `description`, `state`, `labels`, `start_date`, `due_date`, `parent_id`, `parent_iid`, `planned_weight`, `author`, `web_url`, timestamps |
| `export-issues` | All issues across the full group hierarchy | `project_path`, `iid`, `id`, `title`, `description`, `state`, `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `epic_iid`, `author`, `web_url`, timestamps |

`planned_weight` on epics is fetched via GraphQL (the REST API does not expose it).

### Import — Pre-flight Validation

Both importers run a full validation pass before creating anything. All errors are reported upfront; if any are found the import aborts without touching the instance.

Checks performed:
- Required column(s) present (`title` for both; `project_path` for issues unless a target project is provided at the prompt)
- Unknown columns noted as warnings and silently ignored
- Blank required fields flagged per row
- Date fields validated as `YYYY-MM-DD`
- Numeric fields (`weight`, `parent_id`, `epic_id`, `planned_weight`) validated as integers
- `state` values validated (`opened` / `closed`)
- All `parent_id` values checked against live epic IDs in the target hierarchy (see below)

**Minimum required columns:**

| Import | Required | Commonly useful optional |
|---|---|---|
| `import-epics` | `title` | `group_path`, `labels`, `start_date`, `due_date`, `parent_id`, `planned_weight`, `state` |
| `import-issues` | `title`, `project_path` | `labels`, `weight`, `due_date`, `milestone`, `assignees`, `epic_id`, `state` |

**Post-create steps applied automatically:**
- `planned_weight` set via GraphQL after epic creation
- `milestone` resolved by title lookup in the target project
- `assignees` resolved by GitLab username lookup (cached per run; unknown usernames warned and skipped)
- `epic_id` assigned to issues via a post-create save
- Epics or issues with `state: closed` are closed after creation

Pass `dry_run: yes` to validate and preview every row without creating anything.

### Unresolvable `parent_id` Values

When importing epics from an external system, `parent_id` values will not match IDs in the target GitLab instance. The pre-flight pass identifies all affected rows, reports them as a table, and asks once how to handle them before any creation starts:

| Mode | Behaviour |
|---|---|
| `ask` | Displays the live epic hierarchy grouped by containing group; user picks a single fallback parent for all affected rows. Choosing `0` falls back to the `label` approach. |
| `label` | Creates the epic without a parent and adds the label `import::needs-parent` *(default)* |
| `skip` | Skips the affected rows entirely |

An **orphan summary table** is printed at the end of any run that produces epics without their intended parent (row number, original `parent_id`, group, title). Filter by label `import::needs-parent` in GitLab to find and re-parent these epics.

---

## Known Issues / TODO

- **Direct Features in ART-level reports:** `ART Feature Status` and `ART Capacity Balance` still assume the full three-tier chain (Epic → Capability → Feature) and do not surface Features parented directly to a Portfolio Epic. Both reports need hierarchy traversal updates to handle the two-tier (Epic → Feature) case.

---

## What `--clean` Removes

`cleanup_group()` performs a full teardown in safe dependency order:

1. Wiki pages (root group)
2. Epics (children before parents, recursively)
3. Milestones (root group + all subgroups)
4. Issues (all projects, synchronously)
5. Labels (root group + subgroups + projects)
6. Projects
7. Subgroups (deepest first)
8. Root group

---

## Design Notes

**Mixin architecture** — `NceGitLab` inherits from twelve single-responsibility mixin classes in `mixins/`. The main file contains only `__init__` (config loading and GitLab auth) and the CLI `main()`. Adding new capabilities means adding a new mixin or extending an existing one without touching the core class.

**GraphQL for epic weights** — GitLab's REST API does not expose planned weight on epics; it must be read and written via the GraphQL `workItemUpdate` mutation and `WorkItemWidgetWeight` widget. All weight operations route through `_set_epic_weight()` and `_fetch_epic_weights()` in `mixins/utils.py`.

**Metrics caching** — `calculate_portfolio_metrics()` caches results per group name in `_metrics_cache` so that multiple reports generated in the same session share a single fetch pass.

**Config-driven defaults** — All numeric defaults for bootstrap counts and tool parameters live in `config.json` under `defaults.bootstrap` and `defaults.tools`. Function signatures use `None` sentinels and resolve from `self.default_*` at runtime, so callers can still override individual values programmatically. Structure count keys (`num_value_streams`, `num_arts`, `num_teams`, etc.) accept a plain integer, `{"desired": N}`, or `{"min": M, "max": N}` range object. `_resolve_range()` in `mixins/bootstrap.py` handles all three forms; `_range_label()` produces a human-readable annotation for the run summary.

**Job timing** — Each phase (`--clean`, `--create`, individual reports, `--all`) prints start/stop times and duration. `--all` aggregates all phases into a single summary table.

**Data snapshots** — Every report run writes `epics.json`, `issues.json`, and `blocking.json` to `reports/YYYYMMDD/HHMMSS/` before any wiki pages are generated. The data comes from `calculate_portfolio_metrics()` (which already fetches and caches all epics and issues) plus a dedicated GraphQL call for the full blocking graph. Multiple runs per day each get their own timestamped subdirectory. The `.gitlab-ci.yml` `generate-reports` job exposes this directory as a downloadable CI artifact.
