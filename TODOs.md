# TODOs — SAFe Portfolio Tool Roadmap

_Perspective: DoD program manager overseeing multiple programs modeled as SAFe Portfolio → Value Stream → ART → Team hierarchies._

---

## The Core Problem with Current Reports

The 13 existing reports are organized around **what data we have**, not **what questions a PM needs to answer**. A DoD program manager opens their laptop Monday morning asking four things in order:

1. **What is the health of my portfolio right now?**
2. **Are we going to hit our PI commitments?**
3. **What is blocking us and who owns the fix?**
4. **Do we have the people and capacity to do what we said we'd do?**

None of the current reports directly answers question 1. Questions 2–4 require reading 3–4 reports and mentally assembling the picture. That is the primary gap to close.

---

## Recommended Report Tier Structure

Reorganize all reports — existing and new — into four tiers. This shapes both the wiki index structure and the report generation order.

### Tier 1 — Executive Pulse
_One page. Viewed daily. Read in 90 seconds._

| Report | Status | Notes |
|--------|--------|-------|
| Portfolio Health Dashboard | 🆕 New — highest priority | Single page with traffic-light status (Red/Yellow/Green) per Value Stream across schedule, capacity, risk, and blocking. Rolls up to a portfolio summary row. Top-3 risks and blockers requiring executive action. One line per VS with drill-down links. |

### Tier 2 — Program Management
_Reviewed in weekly ART syncs and PM stand-ups._

| Report | Status | Notes |
|--------|--------|-------|
| Program × PI Matrix | ✅ Keep | Already correct for this level. |
| Program PI Detail | ✅ Keep | Good companion to the matrix. |
| Blocking & Cross-ART Risk | ⚠️ Consolidate | Merge the Blocking Relationships report and VS Cross-ART Risk into a single report. Two separate blocking reports is redundant. Once consolidated, link the **Blocked Epics** metric in the Portfolio Health Dashboard Portfolio Summary directly to this report wiki page. |
| ART Capacity Balance | ✅ Keep | Directly answers "do we have capacity?" |
| PI Predictability Scorecard | 🆕 New — high priority | See details below. |
| Risk Register | 🆕 New | See details below. |
| WSJF Priority Board | 🆕 New | See details below. |

### Tier 3 — Operational Detail
_Drill-down from Tier 2. Available on demand._

| Report | Status | Notes |
|--------|--------|-------|
| ART Feature Status | ✅ Keep | |
| VS Capability Dashboard | ✅ Keep | |
| Team Backlog | ✅ Keep | |
| ART-Team Workload | ⚠️ Review | Largely redundant with Capacity Balance + PI matrix. Consider merging or removing. |
| SAFe Portfolio Hierarchy | ✅ Keep, demote | It is a reference view, not a management tool. Move to Tier 3. |
| Flow Metrics Report | 🆕 New | See details below. |
| Epic Lifecycle / Portfolio Kanban | 🆕 New | See details below. |
| PI Planning Program Board | 🆕 New | See details below. |

### Tier 4 — Data Quality
_Maintenance reports. These indicate labeling/setup problems to fix, not delivery status. Should be grouped under a single "Data Quality" wiki index page with that framing._

| Report | Status | Notes |
|--------|--------|-------|
| Unassigned PI | ✅ Keep, move to Tier 4 | |
| Orphaned Epics | ✅ Keep, move to Tier 4 | |
| Orphaned Issues | ✅ Keep, move to Tier 4 | |

---

## New Reports — Detail Specs

### 1. Portfolio Health Dashboard *(Tier 1)*
The most important missing report. One wiki page per run.

**Content:**
- Portfolio summary row: total epics, % complete, blocked count, at-risk count, unassigned-to-PI count
- One row per Value Stream with traffic-light columns: Schedule (% done vs PI elapsed), Capacity (load %), Risk (open high/medium risks), Blocking (blocked epic count)
- Traffic light logic: 🟢 Green = on track, 🟡 Yellow = within 10% of threshold, 🔴 Red = at risk/exceeded
- "Needs Attention" section: top 3 blockers + top 3 risks with owner and link, formatted as a callout table
- Links to Tier 2 reports for drill-down

**Data sources:** All existing `_rd_*` structures + blocking snapshot. No new API calls needed.

---

### 2. PI Predictability Scorecard *(Tier 2)*
The #1 SAFe metric for program managers. Currently completely absent.

**Concept:** For each ART, % of PI objectives completed as committed. Tracked over the last N PIs to show trend.

**Implementation approach:**
- Each PI objective maps to an epic with a PIID label committed to that ART (group)
- Predictability % = closed epics / total epics for that PI × 100
- Show last 4–6 PIs as columns per ART
- Flag: consistently under 80% = team is struggling; consistently at 100% = likely sandbagging
- Aggregate row at the bottom for portfolio-wide predictability trend

**Data sources:** `_rd_metrics` filtered by PIID and group_id. No new API calls.

---

### 3. Risk Register *(Tier 2)*
DoD programs are required to maintain risk registers. This bridges Agile delivery to that governance requirement.

**Implementation approach:**
- Drive from a label convention: `risk::high`, `risk::medium`, `risk::low` applied to epics
- Optionally a `mitigation::owner-name` label or a structured description field
- Report shows: Epic title, type, PI, group/ART, risk level, state, link
- Grouped by risk level (High → Medium → Low), sorted by PI
- Summary counts at the top by level and by Value Stream

**Data sources:** `_rd_epics_all` filtered by `risk::*` labels. No new API calls.

**Label convention to add to config:**
```yaml
RISK_LABELS:
  - "risk::high"
  - "risk::medium"
  - "risk::low"
```

---

### 4. WSJF Priority Board *(Tier 2)*
Weighted Shortest Job First — the SAFe-standard method for sequencing portfolio backlog items. Gives leadership a defensible, data-driven prioritization rationale.

**WSJF formula:**
```
WSJF = (User/Business Value + Time Criticality + Risk Reduction) / Job Size
```

**Implementation approach:**
- Drive from labels: `wsjf-value::N`, `wsjf-urgency::N`, `wsjf-risk::N` (N = 1, 2, 3, 5, 8, 13 — Fibonacci-relative scoring)
- Job Size = planned_weight (already stored)
- Report shows open (not-yet-started) epics ranked by computed WSJF score
- Columns: Rank, Epic, Type, PI, Value, Urgency, Risk, Size, WSJF Score, Link
- Filtered to epics in Portfolio Backlog state (no PIID assigned, or `lifecycle::backlog` label)

**Label convention to add to config:**
```yaml
WSJF_LABELS:
  value:   ["wsjf-value::1",  "wsjf-value::2",  "wsjf-value::3",  "wsjf-value::5",  "wsjf-value::8",  "wsjf-value::13"]
  urgency: ["wsjf-urgency::1","wsjf-urgency::2","wsjf-urgency::3","wsjf-urgency::5","wsjf-urgency::8","wsjf-urgency::13"]
  risk:    ["wsjf-risk::1",   "wsjf-risk::2",   "wsjf-risk::3",   "wsjf-risk::5",   "wsjf-risk::8",   "wsjf-risk::13"]
```

---

### 5. Flow Metrics Report *(Tier 2–3)*
Current reports measure % complete against PI elapsed time — a crude progress indicator. Flow metrics tell the richer story SAFe 6.0 is built around.

**Metrics to implement:**

| Metric | Definition | Data source |
|--------|-----------|-------------|
| Flow Velocity | Features/Capabilities completed per PI, trended over last 6 PIs | `closed_at` vs PIID label on `_rd_metrics` |
| Flow Distribution | % of work that is Feature vs Enabler vs Infrastructure vs Defect | `type::enabler` label (new) on epics/issues |
| Flow Load (WIP) | Epics/Features currently open (in-progress), compared to prior PIs | State = opened, by group |
| Flow Time | Average days from epic `created_at` to `closed_at` per type | Existing fields |
| Flow Predictability | % of PI objectives met, trended (overlaps with Predictability Scorecard) | Same source |

**Target distributions (SAFe guidance):**
- Features/Capabilities: ~50%
- Enablers (tech enablers, architecture): ~30%
- Infrastructure / DevSecOps: ~20%
- DoD programs that slide to 80% features accumulate technical debt rapidly

**Label convention to add:**
```yaml
WORK_TYPE_LABELS:
  - "type::feature"
  - "type::enabler"
  - "type::infrastructure"
  - "type::defect"
```

---

### 6. Epic Lifecycle / Portfolio Kanban *(Tier 3)*
Where are portfolio epics in their SAFe lifecycle? Executives want to see whether epics are stuck in analysis or actually moving to delivery.

**SAFe Portfolio Kanban states:**
1. Funnel — idea submitted, not yet analyzed
2. Analyzing — Lean Business Case in development
3. Portfolio Backlog — approved, awaiting capacity
4. Implementing — active, in a PI
5. Done — delivered

**Implementation approach:**
- Drive from labels: `lifecycle::funnel`, `lifecycle::analyzing`, `lifecycle::backlog`, `lifecycle::implementing`, `lifecycle::done`
- Report shows a Kanban-style table: one column per state, one row per epic
- Highlight epics stuck in Analyzing or Backlog for more than N days
- Summary: average age by state (identifies bottlenecks in the approval/funding pipeline)

**Label convention to add:**
```yaml
LIFECYCLE_LABELS:
  - "lifecycle::funnel"
  - "lifecycle::analyzing"
  - "lifecycle::backlog"
  - "lifecycle::implementing"
  - "lifecycle::done"
```

---

### 7. PI Planning Program Board *(Tier 3)*
After PI planning, generate a read-only program board artifact. DoD PMs reference this throughout the PI to track drift from plan.

**Content:**
- Rows = Teams; Columns = Iterations (sprints) within the PI
- Cells = Features committed by that team in that iteration
- Dependency indicators between cells (uses existing blocking data)
- Key milestones (system demos, IP sprint, PI end) shown as column headers
- Status overlay: Planned / In Progress / Complete / At Risk / Blocked

**Implementation note:** This requires knowing which iteration (milestone) each feature is targeted to. Consider a label convention `sprint::N` or milestone assignment on issues.

---

## Wiki Index Restructuring

The current wiki gets pages dropped into it with no navigation hierarchy. The root index page should organize reports into the four tiers. Target structure:

```
{Group} — Portfolio Home
├── 📊 Executive Pulse
│   └── Portfolio Health Dashboard          ← new
│
├── 🗂️ Program Management
│   ├── Program × PI Matrix
│   ├── Program PI Detail
│   ├── PI Predictability Scorecard         ← new
│   ├── Blocking & Cross-ART Risk           ← consolidated
│   ├── ART Capacity Balance
│   ├── Risk Register                       ← new
│   └── WSJF Priority Board                 ← new
│
├── 🔍 Operational Detail
│   ├── Flow Metrics                        ← new
│   ├── Epic Lifecycle / Portfolio Kanban   ← new
│   ├── ART Feature Status/{VS}/{ART}
│   ├── VS Capability Dashboard/{VS}
│   ├── Team Backlogs/{Team}
│   └── SAFe Portfolio Hierarchy
│
└── 🔧 Data Quality
    ├── Unassigned PI
    ├── Orphaned Epics
    └── Orphaned Issues
```

---

## Label Conventions to Standardize

Several new reports depend on richer label data. Add these to `config.yaml` and update the `audit-labels` tool to flag epics missing required labels.

| Label pattern | Purpose | Required on |
|---------------|---------|------------|
| `risk::high` / `risk::medium` / `risk::low` | Risk Register | Epics |
| `wsjf-value::N` / `wsjf-urgency::N` / `wsjf-risk::N` | WSJF Board | Portfolio-backlog epics |
| `type::feature` / `type::enabler` / `type::infrastructure` / `type::defect` | Flow Distribution | Epics and issues |
| `lifecycle::funnel` / `analyzing` / `backlog` / `implementing` / `done` | Portfolio Kanban | Portfolio-level (Epic type) epics |
| `objective::N` | Links features to PI objective number | Features |

---

## Suggested Build Sequence

1. **Portfolio Health Dashboard** — Closes the biggest gap. All data already exists in `_rd_*` structures; no new API calls needed. Build from existing metrics + blocking snapshot.
2. **Restructure wiki index** — Reorganize existing report pages under the four-tier hierarchy. Mostly a reporting/template change.
3. **PI Predictability Scorecard** — High-value, computable from existing data.
4. **Risk Register** — Add `risk::*` label convention + report. Low implementation effort, high governance value for DoD.
5. **Flow Metrics Report** — Add `type::*` label convention; derive velocity, distribution, and load from existing timestamps and weights.
6. **WSJF Priority Board** — Add `wsjf-*` label convention + scoring report.
7. **Epic Lifecycle / Portfolio Kanban** — Add `lifecycle::*` label convention + report.
8. **Consolidate blocking reports** — Merge Blocking Relationships + VS Cross-ART Risk into one Tier 2 report.
9. **PI Planning Program Board** — Requires iteration-level data; most complex. Build last.

---

## Background: SAFe 6.0 Metrics Reference

SAFe 6.0 defines three measurement domains that apply at every level (Team → ART → Portfolio):

| Domain | What it measures |
|--------|----------------|
| **Outcomes** | Business and customer success: KPIs, OKRs, value realized |
| **Flow** | Delivery efficiency: velocity, time, load, efficiency, distribution, predictability |
| **Competency** | Proficiency in SAFe practices (assessed via surveys/maturity models) |

The six flow metrics are the primary operational instrument. Flow Predictability (% PI objectives met) is the single most-watched metric at ART and portfolio level for DoD programs.

For DoD, SAFe metrics complement (not replace) traditional Earned Value Management (EVM). Flow metrics address *what* is being delivered and *how efficiently*; EVM addresses cost and schedule variance against the baseline contract. Both are needed for large acquisition programs.

---

_Last updated: 2026-05-25_
