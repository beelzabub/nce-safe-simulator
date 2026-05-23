# NCE GitLab SAFe Tooling

Python automation for GitLab groups organised around the **Scaled Agile Framework (SAFe)** hierarchy. Generates realistic lorem test data, manages the Epic → Capability → Feature → Issue tree across multiple groups, and publishes a suite of portfolio-level reports to a GitLab Group Wiki.

---

## SAFe Hierarchy Model

```
Root Group  (Portfolio)
│   Epics  🏆
│
├── Value Stream 01
│   Capabilities  🧩
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
Items are further tagged with a **project label** (`project::DO`, `project::RTSO`, …) and a **PIID label** (`PIID::2026Q3`, …) that ties each work item to a Program Increment quarter.

---

## Project Structure

```
NceGitLab.py              # Main class (thin compositor) + CLI entry point
config.json    # Configuration (URL, token, labels, weights)
requirements.txt

mixins/                   # Mixin modules — NceGitLab inherits from all of these
  __init__.py
  utils.py                # GraphQL helpers, PI math, portfolio metrics calculation
  groups.py               # Group CRUD
  projects.py             # Project CRUD
  epics.py                # Epic operations, CSV import/export, markdown report
  issues.py               # Issue operations
  milestones.py           # Milestone operations
  wiki.py                 # Wiki page upload/delete
  labels.py               # Label create/delete
  bootstrap.py            # Lorem data generation, SAFe hierarchy creation, cleanup
  reports.py              # All portfolio report generators

utilities/                # Standalone helper scripts
  _shared.py              # Shared: load_config(), connect(), get_group()
  close_percent.py        # Randomly close N% of open epics/issues (simulate PI progress)
  update_epic_weights.py  # Set epic planned weights via GraphQL
  validate_weights.py     # Validate epic and issue weights against configured pools
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
    }
}
```

| Field | Description |
|---|---|
| `url` | GitLab instance URL |
| `private_token` | Personal access token with `api` scope |
| `parent_group` | Name of the root group to create/manage |
| `gitlab_namespace` | Parent namespace for root group creation |
| `project_labels` | Labels representing programmes or workstreams |
| `piid_labels` | `PIID::YYYYQn` labels mapping work to PI quarters |
| `epic_type_labels` | Must include `Epic`, `Capability`, `Feature` |
| `fibonacci_weights` | Valid issue story-point values |
| `epic_type_planned_weights` | Valid planned-weight pools per epic type |

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
python3 NceGitLab.py --clean     # Delete all data in the root group
python3 NceGitLab.py --create    # Bootstrap a full SAFe lorem data set
python3 NceGitLab.py --report    # Generate all reports and publish to wiki
python3 NceGitLab.py --all       # clean → create → report in sequence
```

A typical demo cycle:

```bash
# Tear down yesterday's data, rebuild, and publish fresh reports
python3 NceGitLab.py --all
```

### Utility Scripts

Run from the `utilities/` directory. Each script accepts `--config` to point at a non-default config file.

```bash
cd utilities

# Simulate PI progress — close 40% of open epics and issues at random
python3 close_percent.py --percent 40

# Preview what would be closed without making changes
python3 close_percent.py --percent 40 --dry-run --seed 42

# Assign random planned weights to all epics (uses GraphQL — REST ignores epic weight)
python3 update_epic_weights.py

# Dry-run weight assignment
python3 update_epic_weights.py --dry-run

# Validate that every epic and issue has a weight from the correct pool
python3 validate_weights.py
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
  - 8–15 Issues per Feature, linked to milestones, with fibonacci weights

After all objects are created the hierarchy is linked cross-group:  
`VS Capabilities → Portfolio Epics` → `ART Capabilities → VS Capabilities` → `Features → ART Capabilities`

All epics are labelled with a random project label, PIID label, and type label. Planned weights are set via the GraphQL `workItemUpdate` mutation (the REST API silently ignores epic weight).

---

## Reports

All reports are published as GitLab Wiki pages on the root group. They are generated by `--report` or `generate_all_reports()`.

| Report | Wiki Page | Description |
|---|---|---|
| SAFe Portfolio Report | `<group> - SAFe Portfolio Report` | Collapsible Epic → Capability → Feature hierarchy with % complete, planned vs actual weight, PI progress, and risk flags |
| ART/Team Workload Report | `<group> - ART/Team Workload Report` | Per-PI table of planned vs actual weight per group, with on-track / at-risk / incomplete status |
| Blocking Relationships Report | `<group> - Blocking Relationships Report` | Blocked epics, their blockers, ancestor risk propagation, and portfolio-level risk summary |
| Unassigned PI Report | `<group> - Unassigned PI Report` | Epics with no `PIID::` label, broken down by type |
| Orphaned Epics Report | `<group> - Orphaned Epics Report` | Epics with no parent and no children (completely disconnected from hierarchy) |
| Orphaned Issues Report | `<group> - Orphaned Issues Report` | Issues not linked to any epic, grouped by project |

### PI Progress Calculation

PIID labels follow the pattern `PIID::YYYYQn` (e.g. `PIID::2026Q3`).  
The tooling maps these to calendar quarters and computes `% elapsed through PI` as of today.  
Reports flag items as **At Risk** (⚠️) when `% done < % elapsed through PI`.

### % Complete Rollup

- **Feature** % = closed issue weight ÷ total issue weight
- **Capability** % = average of its Features' %
- **Epic** % = average of its Capabilities' %

---

## Utilities Roadmap

Planned utilities for seeding test data, simulating PI progress, validating model completeness, and resetting state. All will follow the existing `utilities/` pattern with `--config` and `--dry-run` flags.

### Priority 1 — Model Validity

| Utility | Description | Status |
|---------|-------------|--------|
| `set-issue-weights` | Assign random story-point weights to issues that have none. Without issue weights, `% done` columns across all reports show 0%. Options: `--fibonacci`, `--min`, `--max`, `--dry-run` | ✅ Done |
| `audit-labels` | Report every epic missing a required label (type, PIID, or project label). Surfaces gaps that cause blank cells or misleading zeros before running reports. | ✅ Done |
| `simulate-pi-progress` | Given a PIID label, close X% of issues on epics in that PI. More targeted than the global `close-percent` tool. Options: `--piid`, `--percent`, `--dry-run` | ✅ Done |

### Priority 2 — Data Seeding

| Utility | Description | Status |
|---------|-------------|--------|
| `set-piid-labels` | Bulk-assign a PIID label to epics that are missing one. Feeds the workload, capacity, and PI matrix reports. Options: `--piid`, `--type` filter, `--dry-run` | ✅ Done |
| `set-project-labels` | Bulk-assign a project label to epics missing one. Feeds the Program × PI cross-tab report. Options: `--label`, `--type` filter, `--dry-run` | ✅ Done |
| `generate-issues` | Create N issues in each team backlog project linked to Feature epics. Useful when backlogs are sparse and reports need realistic data. Options: `--count` (default 5 per feature), `--dry-run` | ✅ Done |

### Priority 3 — State Simulation

| Utility | Description | Status |
|---------|-------------|--------|
| `set-epic-states` | Open or close all epics matching a type and/or PI filter. Lets you model past PIs as complete so historical reports render correctly. Options: `--state` (open/close), `--piid`, `--type`, `--dry-run` | ✅ Done |

### Priority 4 — Validation

| Utility | Description | Status |
|---------|-------------|--------|
| `audit-hierarchy` | Verify that Features have Capability parents and Capabilities have Epic parents. Flags orphaned or misplaced epics that would skew hierarchy reports. | ✅ Done |
| `weight-drift-check` | Compare planned weight (GraphQL) vs sum of issue weights (REST) per epic. Flag epics where drift exceeds a configurable threshold. Options: `--threshold` (default 20%), `--type` filter | ✅ Done |

> **Note — Features under Epics:**  
> In some SAFe configurations a Feature may be parented directly to an Epic (skipping the Capability level). The current `audit-hierarchy` logic treats this as a violation. Several reports (`ART Feature Status`, `ART Capacity Balance`, `VS Capability Dashboard`) also assume the full three-tier chain.  
> **TODO:** Review and update hierarchy traversal and audit logic across utilities and reports to accommodate the two-tier (Epic → Feature) case where no Capability is present.

### Priority 5 — Reset / Cleanup

| Utility | Description | Status |
|---------|-------------|--------|
| `reset-pi-progress` | Reopen all issues in a given PI. Lets you re-run a simulation from scratch without recreating data. Options: `--piid`, `--dry-run` | ✅ Done |
| `strip-labels` | Remove a specific label from all epics matching a filter. Useful for reassigning PI allocations or clearing test labels. Options: `--label`, `--type` filter, `--dry-run` | ✅ Done |

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

**Mixin architecture** — `NceGitLab` inherits from ten single-responsibility mixin classes in `mixins/`. The main file contains only `__init__` (config loading and GitLab auth) and the CLI `main()`. Adding new capabilities means adding a new mixin or extending an existing one without touching the core class.

**GraphQL for epic weights** — GitLab's REST API does not expose planned weight on epics; it must be read and written via the GraphQL `workItemUpdate` mutation and `WorkItemWidgetWeight` widget. All weight operations route through `_set_epic_weight()` and `_fetch_epic_weights()` in `mixins/utils.py`.

**Metrics caching** — `calculate_portfolio_metrics()` caches results per group name in `_metrics_cache` so that multiple reports generated in the same session (portfolio, workload, blocking) share a single fetch pass.

**Utilities share a common foundation** — `utilities/_shared.py` provides `load_config()`, `connect()`, and `get_group()` so standalone scripts don't duplicate auth and group-lookup boilerplate.
