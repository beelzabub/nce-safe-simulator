import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from .utils import _fmt_duration


def _gid_to_int(gid_str):
    """Convert 'gid://gitlab/Epic/123' → 123, or return None."""
    try:
        return int(str(gid_str).split("/")[-1])
    except (ValueError, AttributeError):
        return None

# ---------------------------------------------------------------------------
# Report registry — each entry describes one runnable report.
# needs_group: True  → method signature is  method(self, group)
# needs_group: False → method signature is  method(self)
# ---------------------------------------------------------------------------
REPORTS = [
    {
        "key":         "art-capacity-balance",
        "description": "ART Capacity Balance Report — per-team planned vs actual weight per PI with over/under capacity flags",
        "method":      "generate_art_capacity_balance_report",
        "needs_group": False,
    },
    {
        "key":         "art-feature-status",
        "description": "ART Feature Status Report — all Features per ART grouped by Team, with completion, weight, and risk",
        "method":      "generate_art_feature_status_report",
        "needs_group": False,
    },
    {
        "key":         "blocking",
        "description": "Blocking & Cross-ART Risk — blocked epics, ancestor risk propagation, and per-VS cross-ART dependency breakdown",
        "method":      "generate_blocking_report",
        "needs_group": False,
    },
    {
        "key":         "epic-lifecycle",
        "description": "Epic Lifecycle / Portfolio Kanban — epics by SAFe lifecycle state with bottleneck and age analysis",
        "method":      "generate_epic_lifecycle_report",
        "needs_group": False,
    },
    {
        "key":         "flow-metrics",
        "description": "Flow Metrics Report — velocity, load, distribution, and cycle time across the portfolio",
        "method":      "generate_flow_metrics_report",
        "needs_group": False,
    },
    {
        "key":         "health-dashboard",
        "description": "Portfolio Health Dashboard — Tier 1 executive traffic-light view per Value Stream",
        "method":      "generate_portfolio_health_dashboard",
        "needs_group": False,
    },
    {
        "key":         "orphan-epics",
        "description": "Orphaned Epics Report — epics with no parent and no children",
        "method":      "generate_orphan_epics_report",
        "needs_group": False,
    },
    {
        "key":         "orphan-issues",
        "description": "Orphaned Issues Report — issues not linked to any epic, grouped by project",
        "method":      "generate_orphan_issues_report",
        "needs_group": False,
    },
    {
        "key":         "piid-project",
        "description": "Program × PI Report — project label vs PI quarter cross-tab with status and weights",
        "method":      "generate_piid_project_report",
        "needs_group": False,
    },
    {
        "key":         "piid-project-detail",
        "description": "Program PI Detail Report — per-PI section view of program workload and status",
        "method":      "generate_piid_project_detail_report",
        "needs_group": False,
    },
    {
        "key":         "pi-predictability",
        "description": "PI Predictability Scorecard — % of committed Features/Capabilities delivered per PI, trended by ART",
        "method":      "generate_pi_predictability_scorecard",
        "needs_group": False,
    },
    {
        "key":         "portfolio",
        "description": "SAFe Portfolio Report — Epic → Capability → Feature hierarchy with % complete",
        "method":      "generate_portfolio_report",
        "needs_group": False,
    },
    {
        "key":         "risk-register",
        "description": "Risk Register — all risk-flagged epics grouped by level (High → Medium → Low) with PI, ART, and state",
        "method":      "generate_risk_register",
        "needs_group": False,
    },
    {
        "key":         "team-backlog",
        "description": "Team Backlog Report — issues grouped by Feature for every Team, with weight and completion",
        "method":      "generate_team_backlog_report",
        "needs_group": False,
    },
    {
        "key":         "unassigned-pi",
        "description": "Unassigned PI Report — epics with no PIID label, broken down by type",
        "method":      "generate_unassigned_pi_report",
        "needs_group": False,
    },
    {
        "key":         "vs-capability-dashboard",
        "description": "VS Capability Dashboard — Capabilities by PI with per-ART breakdown for each Value Stream",
        "method":      "generate_vs_capability_dashboard_report",
        "needs_group": False,
    },
    {
        "key":         "wiki-index",
        "description": "Portfolio Wiki Home — four-tier navigation index linking all report pages",
        "method":      "generate_wiki_index",
        "needs_group": False,
    },
    {
        "key":         "wsjf",
        "description": "WSJF Priority Board — portfolio backlog epics ranked by Weighted Shortest Job First score",
        "method":      "generate_wsjf_priority_board",
        "needs_group": False,
    },
    {
        "key":         "workload",
        "description": "ART-Team Workload Report — planned vs actual weight per group per PI",
        "method":      "generate_workload_report",
        "needs_group": False,
    },
]

# Wiki tier prefixes are set as instance attributes in _run_reports:
#   self._wiki_t1 = f"{gn} — Portfolio Home/00 Executive Pulse"
#   self._wiki_t2 = f"{gn} — Portfolio Home/01 Program Management"
#   self._wiki_t3 = f"{gn} — Portfolio Home/02 Operational Detail"
#   self._wiki_t4 = f"{gn} — Portfolio Home/03 Data Quality"


def _wiki_slug(page_title: str) -> str:
    """Convert a page title to a GitLab wiki URL slug.

    Rules (applied in order):
      1. Drop non-ASCII characters (e.g. em-dash —, multiplication ×).
      2. Replace any remaining character that isn't alphanumeric, a slash, a
         dash, or a space with a space (e.g. ampersand &).
      3. Collapse runs of whitespace to a single space.
      4. Convert spaces to dashes.
      5. Collapse runs of dashes (produced by steps 1-4) to a single dash.
      6. Strip leading/trailing dashes from each segment.

    Forward slashes are preserved as GitLab wiki path separators.
    """
    import re as _re
    s = _re.sub(r'[^\x00-\x7F]', '', page_title)      # 1. drop non-ASCII
    s = _re.sub(r'[^a-zA-Z0-9/\- ]', ' ', s)           # 2. special ASCII → space
    s = _re.sub(r' +', ' ', s).strip()                  # 3. collapse spaces
    s = s.replace(' ', '-')                              # 4. spaces → dashes
    s = _re.sub(r'-+', '-', s)                           # 5. collapse dashes
    return s.strip('-')


class ReportsMixin:

    def generate_summary_report(self, group):
        try:
            group_name = group.name
        except Exception as e:
            return f"Error fetching group '{group}': {e}"

        milestones = []
        issues     = []
        epics      = []

        try:
            milestones = group.milestones.list(all=True)
            epics      = group.epics.list(all=True)
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                full_project       = self.gl.projects.get(project.id)
                project_milestones = full_project.milestones.list(all=True)
                project_issues     = full_project.issues.list(all=True)
                milestones.extend(project_milestones)
                issues.extend(project_issues)
                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")
            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        total_milestones = len(milestones)
        total_epics      = len(epics)
        total_issues     = len(issues)
        print(f"Fetched {total_milestones} milestones")
        print(f"Fetched {total_epics} epics (group-level only)")
        print(f"Fetched {total_issues} issues in total")

        assigned_milestone_ids = {
            issue.milestone['id'] for issue in issues if issue.milestone
        }
        unassigned_issues = [
            issue for issue in issues
            if not issue.milestone or issue.milestone.get('id') not in assigned_milestone_ids
        ]

        markdown_report = []
        markdown_report.append(f"# Workflow Summary Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append("## Workflow Execution Summary")
        markdown_report.append(f"- **Group Name:** `{group_name}`")
        markdown_report.append(f"- **Date:** {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append(f"- **Number of Milestones Created:** {total_milestones}")
        markdown_report.append(f"- **Number of Epics Created:** {total_epics}")
        markdown_report.append(f"- **Number of Issues Created:** {total_issues}")
        markdown_report.append(f"- **Unassigned Issues:** {len(unassigned_issues)}")
        markdown_report.append("")

        if unassigned_issues:
            markdown_report.append("## Unassigned Issues")
            for issue in unassigned_issues:
                markdown_report.append(f"- **[{issue.title}]({issue.web_url})**")
            markdown_report.append("")

        md    = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Summary Report"
        self.upload_to_wiki(self.get_group_by_name(group_name), title, md)

    def generate_detailed_report(self, group):
        group_name = group.name

        milestones                   = []
        epics                        = {}
        project_issues_by_milestone  = defaultdict(list)
        epic_to_issue_map            = defaultdict(list)

        try:
            milestones = group.milestones.list(all=True)
            epics      = {epic.id: epic for epic in group.epics.list(all=True)}
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        print(f"Fetched {len(milestones)} group-level milestones")
        print(f"Fetched {len(epics)} group-level epics")

        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")
                full_project = self.gl.projects.get(project.id)

                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                project_milestones = full_project.milestones.list(all=True)
                project_issues     = full_project.issues.list(all=True)
                milestones.extend(project_milestones)

                for issue in project_issues:
                    if issue.milestone:
                        project_issues_by_milestone[issue.milestone['id']].append(issue)
                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        epic_to_issue_map[issue.epic_issue['epic_id']].append(issue)

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")

            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        markdown_report = []
        markdown_report.append(f"# Detailed Milestones, Issues, and Epics Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Execution Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")

        for milestone in milestones:
            markdown_report.append(f"## Milestone: **{milestone.title}**")
            markdown_report.append(f"- **Start Date:** {milestone.start_date if milestone.start_date else 'Not Set'}")
            markdown_report.append(f"- **Due Date:** {milestone.due_date if milestone.due_date else 'Not Set'}")
            markdown_report.append(f"- **State:** {milestone.state}")
            markdown_report.append("")

            milestone_issues = project_issues_by_milestone.get(milestone.id, [])
            if milestone_issues:
                for issue in milestone_issues:
                    issue_line = f"  - **[{issue.title}]({issue.web_url})** (Status: {issue.state})"

                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        epic_id     = issue.epic_issue['epic_id']
                        epic        = epics.get(epic_id)
                        if epic:
                            linked_issues       = epic_to_issue_map.get(epic_id, [])
                            all_issues_closed   = all(i.state in ["closed", "done"] for i in linked_issues)
                            inferred_epic_state = "closed" if all_issues_closed else epic.state
                            issue_line += f" (_Epic: [{epic.title}]({epic.web_url}) - **State:** {inferred_epic_state}_)"
                        else:
                            issue_line += " (_Epic: Unknown_)"
                    markdown_report.append(issue_line)
            else:
                markdown_report.append("  - No issues linked to this milestone")
            markdown_report.append("")

        all_milestone_ids_with_issues = set(project_issues_by_milestone.keys())
        unlinked_milestones = [m for m in milestones if m.id not in all_milestone_ids_with_issues]

        if unlinked_milestones:
            markdown_report.append("## Milestones Without Linked Issues")
            for milestone in unlinked_milestones:
                markdown_report.append(f"- **{milestone.title}** (No issues linked)")
            markdown_report.append("")

        markdown_report.append("## Epics Overview")
        for epic_id, epic in epics.items():
            linked_issues      = epic_to_issue_map.get(epic_id, [])
            all_issues_closed  = all(issue.state in ["closed", "done"] for issue in linked_issues)
            inferred_epic_state = "closed" if all_issues_closed else epic.state

            markdown_report.append(f"- **Epic: [{epic.title}]({epic.web_url})**")
            markdown_report.append(f"  - **State:** {epic.state}")
            markdown_report.append(f"  - **Linked Issues:** {len(linked_issues)} issue(s)")
            for issue in linked_issues:
                markdown_report.append(f"    - **[{issue.title}]({issue.web_url})** (State: {issue.state})")
            markdown_report.append("")

        md    = "\n".join(markdown_report)
        title = f"{group_name} - Detailed Report"
        self.upload_to_wiki(group, title, md)
        return md

    def generate_issue_progress_report(self, group):
        group_name            = group.name
        project_status_counts = defaultdict(lambda: defaultdict(int))
        project_issues        = defaultdict(list)

        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")
                full_project = self.gl.projects.get(project.id)

                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                issues = full_project.issues.list(all=True)

                for issue in issues:
                    project_status_counts[project.name][issue.state] += 1
                    project_issues[project.name].append(issue)

                print(f"  Found {len(issues)} issues in project '{project.name}'")

            except Exception as e:
                print(f"Failed to process project '{project.name}': {e}")

        markdown_report = []
        markdown_report.append(f"# Issue Progress and Status Overview (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")
        markdown_report.append("## Summary")

        total_open   = sum(counts.get('opened', 0) for counts in project_status_counts.values())
        total_closed = sum(counts.get('closed', 0) for counts in project_status_counts.values())
        total_other  = sum(sum(c.values()) for c in project_status_counts.values()) - total_open - total_closed
        total_issues = total_open + total_closed + total_other

        markdown_report.append(f"- **Total Issues:** {total_issues}")
        markdown_report.append(f"- **Open Issues:** {total_open}")
        markdown_report.append(f"- **Closed Issues:** {total_closed}")
        markdown_report.append(f"- **Other States (e.g., in progress):** {total_other}")
        markdown_report.append("")

        for project_name, issue_list in project_issues.items():
            markdown_report.append("<details>")
            markdown_report.append(f"  <summary><strong>Project: {project_name}</strong></summary>")
            markdown_report.append("")

            project_open   = project_status_counts[project_name].get("opened", 0)
            project_closed = project_status_counts[project_name].get("closed", 0)
            project_other  = sum(project_status_counts[project_name].values()) - project_open - project_closed

            markdown_report.append(f"  **Total Issues:** {len(issue_list)}  ")
            markdown_report.append(f"  **Open Issues:** {project_open}  ")
            markdown_report.append(f"  **Closed Issues:** {project_closed}  ")
            markdown_report.append(f"  **Other States:** {project_other}  ")
            markdown_report.append("")
            markdown_report.append("  | Issue Title | Status | Milestone |")
            markdown_report.append("  |-------------|--------|-----------|")

            for issue in issue_list:
                issue_title    = f"[{issue.title}]({issue.web_url})"
                status         = issue.state.capitalize()
                milestone_title = issue.milestone['title'] if issue.milestone else "None"
                markdown_report.append(f"  | {issue_title} | {status} | {milestone_title} |")

            markdown_report.append("</details>")
            markdown_report.append("")

        md    = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Issue Progress and Status Overview"
        self.upload_to_wiki(group, title, md)
        return md

    def generate_piid_project_report(self):
        """Program × PI cross-tab: rows = project labels, columns = PIID quarters."""
        group   = self._rd_root_obj
        metrics = self._rd_metrics

        # Flatten all types into one list
        all_epics = [e for epics in metrics.values() for e in epics]

        # Index by (project_label, piid) → list of epic metric dicts
        piid_set    = set(self._rd_piid_labels)
        proj_set    = set(self._rd_project_labels)
        cell_data   = defaultdict(list)
        for e in all_epics:
            proj = next((l for l in e["labels"] if l in proj_set), None)
            piid = e.get("piid")
            if proj and piid and piid in piid_set:
                cell_data[(proj, piid)].append(e)

        def _aggregate(epics):
            total    = len(epics)
            open_cnt = sum(1 for e in epics if e["state"].lower() == "opened")
            planned  = sum(e["planned_weight"] for e in epics)
            actual   = sum(e["actual_weight"]  for e in epics)
            blocked  = sum(1 for e in epics if e["blocked_by_count"] > 0)
            if planned > 0:
                avg_pct = round(sum(e["pct_complete"] * (e["planned_weight"] or 1) for e in epics) / planned)
            elif total > 0:
                avg_pct = round(sum(e["pct_complete"] for e in epics) / total)
            else:
                avg_pct = 0
            return total, open_cnt, planned, actual, avg_pct, blocked

        def _status(piid, avg_pct):
            pct_pi = self._pct_through_pi(piid)
            if pct_pi is None:
                return "🔵 Planned", pct_pi
            if pct_pi == 0:
                return "🔵 Planned", pct_pi
            if pct_pi >= 100:
                return ("✅ Complete" if avg_pct >= 100 else "❌ Incomplete"), pct_pi
            return ("✅ On Track" if avg_pct >= pct_pi else "⚠️ At Risk"), pct_pi

        def _board_url(proj, piid):
            return (
                f"{group.web_url}/-/work_items"
                f"?label_name[]={quote(piid, safe='')}"
                f"&label_name[]={quote(proj, safe='')}"
                f"&state=all"
            )

        detail_title = f"{self._wiki_t2}/Program PI Detail"
        detail_url   = f"{self.url}/groups/{group.full_path}/-/wikis/{_wiki_slug(detail_title)}"

        md = []
        md.append(f"# Program × PI Report (Group: {group.name})")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  [→ Per-PI Detail View]({detail_url})")
        md.append("")
        md.append("Each cell shows: **Status · Epics (open/total) · % Done (PI elapsed%) · Planned pt → Actual pt**")
        md.append("")

        # Header row
        header = "| Program |" + "".join(f" {p} |" for p in self._rd_piid_labels)
        sep    = "|---|" + "".join("---|" for _ in self._rd_piid_labels)
        md.append(header)
        md.append(sep)

        for proj in self._rd_project_labels:
            cells = []
            for piid in self._rd_piid_labels:
                epics = cell_data.get((proj, piid), [])
                if not epics:
                    cells.append(" — ")
                    continue

                total, open_cnt, planned, actual, avg_pct, blocked = _aggregate(epics)
                status, pct_pi                                      = _status(piid, avg_pct)
                delta     = actual - planned
                delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")
                pi_str    = f"{pct_pi}%" if pct_pi is not None else "—"
                blocked_str = f" · 🔒{blocked}" if blocked else ""
                board     = _board_url(proj, piid)

                cells.append(
                    f" {status}{blocked_str}<br>"
                    f"{open_cnt}/{total} epics<br>"
                    f"{avg_pct}% done (PI {pi_str})<br>"
                    f"Planned {planned}pt → {actual}pt {delta_str}<br>"
                    f"[View →]({board}) "
                )

            md.append("| **" + proj + "** |" + "|".join(cells) + "|")

        md.extend([
            "",
            "---",
            "## Legend",
            "",
            "### Status",
            "| Icon | Meaning |",
            "|------|---------|",
            "| ✅ On Track | Current PI: % Done ≥ % of PI quarter elapsed |",
            "| ⚠️ At Risk  | Current PI: % Done < % of PI quarter elapsed |",
            "| ✅ Complete | Past PI: all committed work finished (% Done = 100%) |",
            "| ❌ Incomplete | Past PI: PI ended with work remaining |",
            "| 🔵 Planned  | Future PI: not yet started |",
            "| 🔒 N | N epics in this cell are blocked |",
            "",
            "### Metrics",
            "- **% Done** — weighted average completion across all epics in the cell (weighted by planned weight)",
            "- **PI elapsed%** — `(today − PI start) ÷ (PI end − PI start) × 100`",
            "- **Planned pt** — sum of planned weights set on those epics (via GraphQL)",
            "- **Actual pt** — sum of story-point weights on all linked issues",
            "- **Δ** — ▲ actual exceeds planned · ▼ actual below planned · = matched",
            "",
            "## Quick Links",
            "",
            f"- [Work Items]({group.web_url}/-/work_items)",
            f"- [Roadmap]({group.web_url}/-/roadmap)",
            f"- [Epic Boards]({group.web_url}/-/epics)",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/Program × PI Matrix", "\n".join(md))

    def generate_piid_project_detail_report(self):
        """Per-PI section view of program workload — one section per PIID quarter."""
        group   = self._rd_root_obj
        metrics = self._rd_metrics

        all_epics = [e for epics in metrics.values() for e in epics]

        piid_set  = set(self._rd_piid_labels)
        proj_set  = set(self._rd_project_labels)
        cell_data = defaultdict(list)
        for e in all_epics:
            proj = next((l for l in e["labels"] if l in proj_set), None)
            piid = e.get("piid")
            if proj and piid and piid in piid_set:
                cell_data[(proj, piid)].append(e)

        def _aggregate(epics):
            total    = len(epics)
            open_cnt = sum(1 for e in epics if e["state"].lower() == "opened")
            planned  = sum(e["planned_weight"] for e in epics)
            actual   = sum(e["actual_weight"]  for e in epics)
            blocked  = sum(1 for e in epics if e["blocked_by_count"] > 0)
            if planned > 0:
                avg_pct = round(sum(e["pct_complete"] * (e["planned_weight"] or 1) for e in epics) / planned)
            elif total > 0:
                avg_pct = round(sum(e["pct_complete"] for e in epics) / total)
            else:
                avg_pct = 0
            return total, open_cnt, planned, actual, avg_pct, blocked

        def _status_icon(piid, avg_pct, pct_pi):
            if pct_pi is None or pct_pi == 0:
                return "🔵 Planned"
            if pct_pi >= 100:
                return "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
            return "✅ On Track" if avg_pct >= pct_pi else "⚠️ At Risk"

        def _phase_label(pct_pi):
            if pct_pi is None or pct_pi == 0:
                return "Future"
            if pct_pi >= 100:
                return "Past"
            return "Current"

        matrix_title = f"{self._wiki_t2}/Program × PI Matrix"
        matrix_url   = f"{self.url}/groups/{group.full_path}/-/wikis/{_wiki_slug(matrix_title)}"

        md = []
        md.append(f"# Program PI Detail Report (Group: {group.name})")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  [→ Program × PI Matrix View]({matrix_url})")
        md.append("")
        md.append("One section per Program Increment. Each table row is a project/program workstream.")
        md.append("")

        for piid in self._rd_piid_labels:
            pct_pi     = self._pct_through_pi(piid)
            start, end = self._pi_dates_from_label(piid)
            phase      = _phase_label(pct_pi)
            pi_str     = f"{pct_pi}%" if pct_pi is not None else "—"
            date_range = f"{start} → {end}" if start else "unknown dates"

            phase_icon = {"Future": "🔵", "Current": "🟢", "Past": "⬜"}.get(phase, "")
            md.append(f"## {phase_icon} {piid} — {phase}")
            md.append(f"**{date_range}** · PI elapsed: {pi_str}")
            md.append("")
            md.append("| Project | Epics (open/total) | % Done | Status | Planned | Actual | Δ | Blocked |")
            md.append("|---------|-------------------|--------|--------|---------|--------|---|---------|")

            any_row = False
            for proj in self._rd_project_labels:
                epics = cell_data.get((proj, piid), [])
                if not epics:
                    md.append(f"| **{proj}** | — | — | — | — | — | — | — |")
                    continue

                any_row = True
                total, open_cnt, planned, actual, avg_pct, blocked = _aggregate(epics)
                status    = _status_icon(piid, avg_pct, pct_pi)
                delta     = actual - planned
                delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")
                blocked_str = str(blocked) if blocked else "—"
                board_url = (
                    f"{group.web_url}/-/work_items"
                    f"?label_name[]={quote(piid, safe='')}"
                    f"&label_name[]={quote(proj, safe='')}"
                    f"&state=all"
                )
                md.append(
                    f"| **[{proj}]({board_url})** "
                    f"| {open_cnt}/{total} "
                    f"| {avg_pct}% "
                    f"| {status} "
                    f"| {planned} pt "
                    f"| {actual} pt "
                    f"| {delta_str} "
                    f"| {blocked_str} |"
                )

            md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "| Icon | Status | Condition |",
            "|------|--------|-----------|",
            "| ✅ On Track   | Current PI | % Done ≥ % of PI quarter elapsed |",
            "| ⚠️ At Risk    | Current PI | % Done < % of PI quarter elapsed |",
            "| ✅ Complete   | Past PI    | % Done = 100% |",
            "| ❌ Incomplete | Past PI    | % Done < 100% at PI end |",
            "| 🔵 Planned    | Future PI  | PI has not yet started |",
            "",
            "- **% Done** — weighted average completion (weighted by planned weight)",
            "- **Planned** — sum of planned weights set on epics (via GraphQL)",
            "- **Actual** — sum of story-point weights on linked issues",
            "- **Δ** — ▲ actual exceeds planned · ▼ actual below planned · = matched",
            "- **Blocked** — number of epics with at least one active blocker",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/Program PI Detail", "\n".join(md))

    def generate_portfolio_report(self):
        group      = self._rd_root_obj
        group_name = group.name
        print("  Generating SAFe Portfolio Report...")

        try:
            metrics   = self._rd_metrics
            summary   = self.generate_portfolio_summary(metrics, group)

            markdown_report = []
            markdown_report.append(f"# SAFe Portfolio Report (Group: {group_name})")
            markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
            markdown_report.append("")
            markdown_report.append(summary)
            markdown_report.extend(["", "", "", "## Initiative Hierarchy", ""])

            all_epics     = metrics["Epic"] + metrics["Capability"] + metrics["Feature"]
            epic_hierarchy = defaultdict(list)
            for epic in all_epics:
                if epic.get("parent_id") is not None:
                    epic_hierarchy[epic["parent_id"]].append(epic)

            def render_epic_details(epic, indent_level=0):
                nonlocal markdown_report

                epic_type = next((t for t in ["Epic", "Capability", "Feature"] if t in epic.get("labels", [])), "Epic")
                icon      = self.EPIC_TYPE_ICONS.get(epic_type, "🏆")
                children  = epic_hierarchy.get(epic['id'], [])

                blocked    = epic.get('blocked_by_count', 0) > 0
                block_icon = '<span style="font-size:0.62em;">⛔</span> ' if blocked else ""

                pct_done  = epic.get('pct_complete', 0)
                pct_pi    = epic.get('pct_through_pi')
                planned_w = epic.get('planned_weight', 0)
                actual_w  = epic.get('actual_weight', 0)

                pi_str = f" | PI: {pct_pi}%" if pct_pi is not None else ""
                risk   = " ⚠️" if pct_pi is not None and pct_done < pct_pi else ""

                if planned_w and actual_w:
                    drift     = actual_w - planned_w
                    drift_str = f" | Planned: {planned_w}pt  Actual: {actual_w}pt {'▲' if drift > 0 else '▼' if drift < 0 else '='}"
                elif planned_w:
                    drift_str = f" | Planned: {planned_w}pt"
                else:
                    drift_str = ""

                meta  = f"(State: {epic.get('state')} | {pct_done}%{risk}{pi_str}{drift_str})"
                label = f"{block_icon}{icon} **[{epic['title']}]({epic['web_url']})** {meta}"

                if not children:
                    markdown_report.append(label)
                    markdown_report.append("")
                else:
                    markdown_report.append("<details>")
                    markdown_report.append(f"<summary>{label}</summary>")
                    markdown_report.append("")
                    for child_epic in children:
                        render_epic_details(child_epic, indent_level + 1)
                    markdown_report.append("</details>")
                    markdown_report.append("")

            for epic in metrics["Epic"]:
                render_epic_details(epic)

            markdown_report.extend([
                "", "", "",
                "---",
                "## Legend",
                "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
                "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
                "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
                "",
            ])

            md = "\n".join(markdown_report)
            self.upload_to_wiki(group, f"{self._wiki_t3}/SAFe Portfolio Hierarchy", md)

        except Exception as e:
            print(f"Failed to generate epics report for group '{group_name}': {e}")

    def generate_portfolio_summary(self, metrics, group):
        base = f"{group.web_url}/-/epics"

        summary = []
        summary.append("## 📊 Portfolio Summary")
        summary.append("")
        summary.append("| Type | Total | Open | Closed | Blocked By | Blocks | % Done | % Through PI |")
        summary.append("|------|-------|------|--------|------------|--------|--------|--------------|")

        for metric_type, data_list in metrics.items():
            if not data_list:
                continue

            total        = len(data_list)
            open_count   = sum(1 for d in data_list if d["state"] == "Opened")
            closed_count = sum(1 for d in data_list if d["state"] == "Closed")
            total_blocked_by = sum(d["blocked_by_count"] for d in data_list)
            total_blocks     = sum(d["blocks_count"] for d in data_list)

            pcts_done = [d["pct_complete"] for d in data_list]
            avg_done  = round(sum(pcts_done) / len(pcts_done)) if pcts_done else 0

            pcts_pi = [d["pct_through_pi"] for d in data_list if d["pct_through_pi"] is not None]
            avg_pi  = round(sum(pcts_pi) / len(pcts_pi)) if pcts_pi else None

            risk_flag = " ⚠️" if avg_pi is not None and avg_done < avg_pi else ""
            pi_cell   = f"{avg_pi}%{risk_flag}" if avg_pi is not None else "—"

            icon       = self.EPIC_TYPE_ICONS.get(metric_type, "🏆")
            url_all    = f"{base}?label_name[]={metric_type}&state=all"
            url_open   = f"{base}?label_name[]={metric_type}&state=opened"
            url_closed = f"{base}?label_name[]={metric_type}&state=closed"

            summary.append(
                f"| {icon} **{metric_type}** "
                f"| [{total}]({url_all}) "
                f"| [{open_count}]({url_open}) "
                f"| [{closed_count}]({url_closed}) "
                f"| {total_blocked_by} "
                f"| {total_blocks} "
                f"| {avg_done}% "
                f"| {pi_cell} |"
            )

        summary.append("")
        return "\n".join(summary)

    def generate_workload_report(self):
        group = self._rd_root_obj
        print("  Generating ART/Team Workload Report...")

        metrics   = self._rd_metrics
        all_epics = metrics.get("Epic", []) + metrics.get("Capability", []) + metrics.get("Feature", [])
        if not all_epics:
            print("No epics found — skipping workload report.")
            return

        groups_by_id = self._rd_groups_by_id

        pi_group_features = defaultdict(lambda: defaultdict(list))
        for e in all_epics:
            piid = e.get("piid")
            gid  = e.get("group_id")
            if piid and gid:
                pi_group_features[piid][gid].append(e)

        today = date.today()

        def pi_phase(piid):
            start, end = self._pi_dates_from_label(piid)
            if not start:
                return "unknown"
            if today < start:
                return "future"
            if today > end:
                return "past"
            return "current"

        sorted_pis = sorted(
            pi_group_features.keys(),
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        md = []
        md.append(f"# ART/Team Workload Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")

        for piid in sorted_pis:
            phase      = pi_phase(piid)
            pct_pi     = self._pct_through_pi(piid) or 0
            start, end = self._pi_dates_from_label(piid)
            date_range = f"_{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}_" if start else ""

            phase_label = {
                "current": f"🟢 Current PI — {pct_pi}% elapsed",
                "future":  "🔵 Future PI",
                "past":    "⚫ Past PI",
            }.get(phase, "")

            md.append(f"## {piid} — {phase_label}")
            if date_range:
                md.append(date_range)
            md.append("")
            md.append("| Group | Epics | Planned | Actual | Δ | % Done | Status |")
            md.append("|-------|-------|---------|--------|---|--------|--------|")

            group_data = pi_group_features[piid]

            def _avg_pct(fs, total_planned):
                if total_planned:
                    return round(sum(f["planned_weight"] * f["pct_complete"] for f in fs) / total_planned)
                return round(sum(f["pct_complete"] for f in fs) / len(fs)) if fs else 0

            def _risk_sort(gid):
                fs            = group_data[gid]
                total_planned = sum(f["planned_weight"] for f in fs)
                avg_pct       = _avg_pct(fs, total_planned)
                if phase == "past":
                    return (0 if avg_pct < 100 else 2, -len(fs))
                if phase == "current":
                    return (0 if avg_pct < pct_pi else 2, -len(fs))
                return (1, -len(fs))

            for gid in sorted(group_data.keys(), key=_risk_sort):
                fs            = group_data[gid]
                grp           = groups_by_id.get(gid)
                grp_name      = grp["name"]    if grp else f"Group {gid}"
                grp_url       = grp["web_url"] if grp else ""
                total_planned = sum(f["planned_weight"] for f in fs)
                total_actual  = sum(f["actual_weight"]  for f in fs)
                delta         = total_actual - total_planned
                avg_pct       = _avg_pct(fs, total_planned)

                delta_str  = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")

                if phase == "current":
                    status_str = "⚠️ At Risk"  if avg_pct < pct_pi  else "✅ On Track"
                elif phase == "past":
                    status_str = "✅ Complete"  if avg_pct == 100    else "❌ Incomplete"
                else:
                    status_str = "🔵 Planned"

                grp_link   = f'<a href="{grp_url}" target="_blank" rel="noopener noreferrer">{grp_name}</a>' if grp_url else grp_name

                if grp:
                    wi_url = (
                        f"{self.url}/groups/{grp['full_path']}/-/work_items"
                        f"?sort=created_date&state=opened"
                        f"&label_name%5B%5D={quote(piid, safe='')}"
                        f"&first_page_size=100"
                    )
                    epics_cell = f'<a href="{wi_url}" target="_blank" rel="noopener noreferrer">{len(fs)}</a>'
                else:
                    epics_cell = str(len(fs))

                md.append(
                    f"| {grp_link} | {epics_cell} | {total_planned} pt | {total_actual} pt "
                    f"| {delta_str} | {avg_pct}% | {status_str} |"
                )

            md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "### SAFe Hierarchy",
            "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
            "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
            "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
            "",
            "### Column Definitions",
            "- **Epics** — count of Epics, Capabilities, and Features assigned to this group for the PI; links to the filtered work items board",
            "- **Planned** — sum of planned weights set on those epics (the team's committed scope for the PI)",
            "- **Actual** — sum of story-point weights on all linked issues (the team's bottom-up estimate of work)",
            "- **Δ (Delta)** — Actual minus Planned: ▲ more work than planned · ▼ less work than planned · = matched",
            "- **% Done** — weighted average completion across all epics in this group for this PI, calculated as closed issue weight ÷ total issue weight; weighted by planned epic weight so larger epics contribute proportionally",
            "",
            "### Status Definitions",
            "- **🟢 Current PI** — the PI whose date range includes today",
            "- **✅ On Track** — *current PI only*: % Done ≥ % of the PI quarter elapsed; work is progressing at or ahead of the expected pace",
            "- **⚠️ At Risk** — *current PI only*: % Done < % of the PI quarter elapsed; the team is behind the pace needed to complete committed work by PI end",
            "- **✅ Complete** — *past PI*: all committed work finished (% Done = 100%) before or by the end of the PI",
            "- **❌ Incomplete** — *past PI*: the PI ended with work remaining (% Done < 100%); scope was not fully delivered",
            "- **🔵 Planned** — *future PI*: the PI has not yet started; no progress is expected or measured yet",
            "",
            "### PI Elapsed %",
            "- Calculated as: `(today − PI start date) ÷ (PI end date − PI start date) × 100`",
            "- PIID labels follow the pattern `PIID::YYYYQn` and map to calendar quarters: Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t3}/ART-Team Workload", "\n".join(md))

    def list_blocking_epics(self):
        group     = self.get_group_by_name(self.parent_group)
        full_path = group.full_path

        query = """
        query ListAllEpics($fullPath: ID!) {
          group(fullPath: $fullPath) {
            epics {
              nodes {
                title blocked blockingCount webUrl blockedByCount
                labels { nodes { title } }
                blockedByEpics {
                  edges {
                    node {
                      id title webUrl
                      labels { nodes { title } }
                    }
                  }
                }
                state
              }
            }
          }
        }
        """

        def epic_type(node):
            label_titles = {l["title"] for l in node.get("labels", {}).get("nodes", [])}
            for t in ("Epic", "Capability", "Feature"):
                if t in label_titles:
                    return t
            return "Epic"

        data = self.graphql_query(query, variables={"fullPath": full_path})
        if data is None:
            return

        nodes         = data["group"]["epics"]["nodes"]
        blocked_epics = [n for n in nodes if n.get("blockedByCount", 0) > 0]

        if not blocked_epics:
            print("No blocked epics found.")
            return

        print(f"\n{'=' * 70}")
        print(f"  BLOCKED EPICS — {full_path}")
        print(f"{'=' * 70}\n")

        for epic in blocked_epics:
            state          = epic.get("state", "").upper()
            blocked_by_cnt = epic.get("blockedByCount", 0)
            etype          = epic_type(epic)
            icon           = self.EPIC_TYPE_ICONS.get(etype, "🏆")

            print(f"⛔ {epic['title']}  [{icon} {etype}]")
            print(f"   State: {state}  |  Blocked by: {blocked_by_cnt}")
            print(f"   {epic['webUrl']}")

            blockers = epic.get("blockedByEpics", {}).get("edges", [])
            last     = len(blockers) - 1
            for i, edge in enumerate(blockers):
                node      = edge["node"]
                connector = "└─" if i == last else "├─"
                btype     = epic_type(node)
                bicon     = self.EPIC_TYPE_ICONS.get(btype, "🏆")
                print(f"   {connector} 🔒 {node['title']}  [{bicon} {btype}]")
                print(f"        {node['webUrl']}")
            print()

    def generate_blocking_report(self):
        group = self._rd_root_obj
        today = date.today()

        rels  = self._rd_blocking.get("relationships", [])
        summ  = self._rd_blocking.get("summary", {})

        total_relationships = summ.get("total_relationships", 0)

        # Index portfolio-epic ancestors across all relationships
        id_to_ancestor: dict = {}
        epic_to_blocked_descendants: defaultdict = defaultdict(list)
        for rel in rels:
            for anc in rel.get("at_risk_portfolio_epics", []):
                id_to_ancestor[anc["id"]] = anc
                epic_to_blocked_descendants[anc["id"]].append(rel["blocked_epic"])

        # ── Cross-ART dep computation (same logic as generate_vs_cross_art_risk_report) ── #
        epic_int_to_group = {
            e["id"]: e.get("group_id")
            for tier in self._rd_metrics.values()
            for e in tier
        }
        epic_int_to_piid = {
            e["id"]: e.get("piid")
            for tier in self._rd_metrics.values()
            for e in tier
        }
        art_of_group: dict = {}
        vs_of_group: dict  = {}
        for vs_group, art_group in self._iter_art_groups():
            art_of_group[art_group["id"]] = art_group
            vs_of_group[art_group["id"]]  = vs_group
        for vs_group, art_group, team_group in self._iter_team_groups():
            art_of_group[team_group["id"]] = art_group
            vs_of_group[team_group["id"]]  = vs_group

        vs_deps: defaultdict = defaultdict(list)
        for rel in rels:
            blocked = rel["blocked_epic"]
            b_int   = blocked.get("id_int") or _gid_to_int(blocked["id"])
            b_gid   = epic_int_to_group.get(b_int)
            b_art   = art_of_group.get(b_gid)
            b_vs    = vs_of_group.get(b_gid)
            b_piid  = epic_int_to_piid.get(b_int)
            if not b_vs or not b_art:
                continue
            for blocker in rel.get("blocked_by", []):
                bl_int = blocker.get("id_int") or _gid_to_int(blocker["id"])
                bl_gid = epic_int_to_group.get(bl_int)
                bl_art = art_of_group.get(bl_gid)
                bl_vs  = vs_of_group.get(bl_gid)
                if not bl_vs or not bl_art:
                    continue
                if b_vs["id"] != bl_vs["id"]:
                    continue
                if b_art["id"] == bl_art["id"]:
                    continue
                vs_deps[b_vs["id"]].append({
                    "blocked":      blocked,
                    "blocked_art":  b_art,
                    "blocked_piid": b_piid,
                    "blocker":      blocker,
                    "blocker_art":  bl_art,
                })

        cross_art_base = f"{self._wiki_t2}/Blocking & Cross-ART Risk"

        # Generate per-VS detail pages (nested under T2) and collect index entries
        vs_index_entries = []
        for vs_group in self._iter_vs_groups():
            deps  = vs_deps.get(vs_group["id"], [])
            entry = self._generate_vs_cross_art_risk_page(group, vs_group, deps, parent_path=cross_art_base)
            vs_index_entries.append(entry)

        total_cross_art = sum(len(vs_deps.get(vs["id"], [])) for vs in self._iter_vs_groups())

        def link(title, url):
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'

        # ── Build T2 consolidated page ──────────────────────────────────────── #
        md = []
        md.append(f"# Blocking & Cross-ART Risk — {group.name}")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{group.name}]({group.web_url})"
        )
        md.append("")

        # ── Summary bar ────────────────────────────────────────────────────── #
        md.append("## Summary")
        md.append("")
        md.append("| Metric | Count |")
        md.append("|--------|-------|")
        md.append(f"| Directly blocked epics | **{len(rels)}** |")
        md.append(f"| Total blocking relationships | **{total_relationships}** |")
        md.append(f"| Portfolio Epics with blocked descendants | **{len(epic_to_blocked_descendants)}** |")
        md.append(f"| Cross-ART dependencies (within VS) | **{total_cross_art}** |")
        md.append("")

        # ── Portfolio-level risk table ──────────────────────────────────────── #
        if epic_to_blocked_descendants:
            md.append("## Portfolio-Level Risk")
            md.append("")
            md.append("Top-level Epics that contain one or more blocked descendants:")
            md.append("")
            md.append("| Epic | Blocked Descendants |")
            md.append("|------|---------------------|")

            def _short(title):
                return title[:12] + "…" if len(title) > 12 else title

            for epic_id, descendants in sorted(
                epic_to_blocked_descendants.items(),
                key=lambda kv: -len(kv[1])
            ):
                anc_node   = id_to_ancestor[epic_id]
                desc_links = ", ".join(
                    f"{self.EPIC_TYPE_ICONS.get(d.get('type', 'Epic'), '🏆')} {link(_short(d['title']), d['web_url'])}"
                    for d in descendants
                )
                md.append(
                    f"| ⚠️ 🏆 **{link(anc_node['title'], anc_node['web_url'])}** "
                    f"| **{len(descendants)}:** {desc_links} |"
                )
            md.append("")

        # ── Cross-ART Risk section ──────────────────────────────────────────── #
        md.append("## Cross-ART Risk by Value Stream")
        md.append("")
        md.append(
            "Blocking relationships where an epic in one ART is blocked by an epic from a "
            "different ART within the same Value Stream. These require active ART-to-ART "
            "coordination. Click a Value Stream link for the full dependency breakdown."
        )
        md.append("")
        md.append("| Value Stream | Cross-ART Deps | Critical |")
        md.append("|--------------|---------------|----------|")
        for vs_name, vs_wiki_url, total_deps, critical in vs_index_entries:
            crit_str  = f"🔴 {critical}" if critical else "—"
            deps_str  = f"{total_deps}" if total_deps else "✅ None"
            md.append(f"| [🔷 {vs_name}]({vs_wiki_url}) | {deps_str} | {crit_str} |")
        md.append("")

        # ── Blocked items detail ────────────────────────────────────────────── #
        if not rels:
            md.append("## Blocked Items")
            md.append("")
            md.append("_No blocked epics found._")
            md.append("")
        else:
            md.append("## Blocked Items (Detail)")
            md.append("")
            for rel in rels:
                epic           = rel["blocked_epic"]
                etype          = epic.get("type", "Epic")
                icon           = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                state          = epic.get("state", "").capitalize()
                blocked_by_cnt = len(rel.get("blocked_by", []))

                md.append("<details>")
                md.append(
                    f"<summary>⛔ {icon} **{link(epic['title'], epic['web_url'])}**"
                    f" ({etype}) — State: {state}"
                    f" — Blocked by: {blocked_by_cnt}</summary>"
                )
                md.append("")

                for blocker in rel.get("blocked_by", []):
                    btype = blocker.get("type", "Epic")
                    bicon = self.EPIC_TYPE_ICONS.get(btype, "🏆")
                    md.append(f"🔒 {bicon} **{link(blocker['title'], blocker['web_url'])}** ({btype})")
                    md.append("")

                ancestors = rel.get("at_risk_portfolio_epics", [])
                if ancestors:
                    md.append("**Risk propagates up to:**")
                    md.append("")
                    for ancestor in ancestors:
                        atype = ancestor.get("type", "Epic")
                        aicon = self.EPIC_TYPE_ICONS.get(atype, "🏆")
                        md.append(f"⬆️ {aicon} **{link(ancestor['title'], ancestor['web_url'])}** ({atype})")
                        md.append("")

                md.append("</details>")
                md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "### Blocking Status",
            "| Icon | Meaning |",
            "|------|---------|",
            "| ⛔ | **Blocked** — this epic has at least one active blocker preventing progress |",
            "| 🔒 | **Blocker** — this epic is directly blocking one or more other epics |",
            "| ⬆️ | **Risk propagation** — a blocked descendant causes risk to bubble up to this ancestor |",
            "| ⚠️ | **Portfolio risk flag** — a top-level Epic contains one or more blocked descendants |",
            "",
            "### Cross-ART Severity",
            "| Icon | Meaning |",
            "|------|---------|",
            "| 🔴 Critical | Blocked item is in the **current PI** — requires immediate cross-ART coordination |",
            "| 🟡 Watch    | Blocked item is in a **future PI** — dependency to monitor and plan around |",
            "| ⚫ Past     | Blocked item was in a **past PI** — dependency may be stale or resolved |",
            "",
            "### SAFe Hierarchy",
            "| Icon | Type | Description |",
            "|------|------|-------------|",
            "| 🏆 | **Epic** | Portfolio-level initiative; may span multiple PIs and ARTs |",
            "| 🧩 | **Capability** | Large Solution-level deliverable decomposed from an Epic |",
            "| 🛠️ | **Feature** | Service or function delivered by a single ART within one PI |",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/Blocking & Cross-ART Risk", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/Blocking & Cross-ART Risk")

    def generate_orphan_epics_report(self):
        group = self._rd_root_obj
        print(f"Generating orphan report for {group.name}...")

        all_epics = self._rd_epics_all

        epic_hierarchy: defaultdict = defaultdict(list)
        for epic in all_epics:
            pid = epic.get("parent_id")
            if pid is not None:
                epic_hierarchy[pid].append(epic)

        epic_ids_with_children = set(epic_hierarchy.keys())

        orphans = [
            e for e in all_epics
            if e.get("parent_id") is None and e["id"] not in epic_ids_with_children
        ]

        md = []
        md.append(f"# Orphaned Epics Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("An **orphaned epic** has no parent and no children — it is completely disconnected from the portfolio hierarchy.")
        md.append("")

        if not orphans:
            md.append("_No orphaned epics found._")
        else:
            md.append(f"**{len(orphans)} orphaned epic(s) found.**")
            md.append("")
            md.append("| Type | Title | State |")
            md.append("|------|-------|-------|")
            for epic in orphans:
                etype      = next((t for t in ("Epic", "Capability", "Feature") if t in epic["labels"]), "Unknown")
                icon       = self.EPIC_TYPE_ICONS.get(etype, "❓")
                title_link = f"[{epic['title']}]({epic['web_url']})"
                md.append(f"| {icon} {etype} | {title_link} | {epic['state']} |")

        self.upload_to_wiki(group, f"{self._wiki_t4}/Orphaned Epics", "\n".join(md))

    def generate_orphan_issues_report(self):
        group = self._rd_root_obj
        print(f"Generating orphan issues report for {group.name}...")

        orphans_by_project = {}
        all_projects = [p for plist in self._rd_projects_by_nsid.values() for p in plist]
        for project in all_projects:
            if not project.get("issues_enabled", True):
                continue
            issues   = self._rd_issues_by_project.get(project["path_with_namespace"], [])
            orphaned = [i for i in issues if not i.get("epic_id")]
            if orphaned:
                orphans_by_project[project["path_with_namespace"]] = (project, orphaned)

        total = sum(len(v[1]) for v in orphans_by_project.values())

        md = []
        md.append(f"# Orphaned Issues Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("An **orphaned issue** has no epic assigned — it is not tracked within the portfolio hierarchy.")
        md.append("")

        if not orphans_by_project:
            md.append("_No orphaned issues found._")
        else:
            md.append(f"**{total} orphaned issue(s) across {len(orphans_by_project)} project(s).**")
            md.append("")

            for _key, (project, issues) in sorted(orphans_by_project.items()):
                md.append(f"### {project['name_with_namespace']}")
                md.append("")
                md.append("| # | Title | State | Milestone | Assignees |")
                md.append("|---|-------|-------|-----------|-----------|")
                for issue in issues:
                    title_link = f"[{issue['title']}]({issue['web_url']})"
                    state      = issue["state"].capitalize()
                    milestone  = issue["milestone"] or "_None_"
                    assignees  = ", ".join(issue.get("assignees") or []) or "_Unassigned_"
                    md.append(f"| #{issue['iid']} | {title_link} | {state} | {milestone} | {assignees} |")
                md.append("")

        self.upload_to_wiki(group, f"{self._wiki_t4}/Orphaned Issues", "\n".join(md))

    def generate_unassigned_pi_report(self):
        group = self._rd_root_obj
        print("  Generating Unassigned PI Report...")

        all_epics        = self._rd_epics_all
        epic_title_by_id = {e["id"]: e["title"] for e in all_epics}

        unassigned = [e for e in all_epics if not any(l.startswith("PIID::") for l in e["labels"])]

        by_type: dict = {"Epic": [], "Capability": [], "Feature": [], "Unknown": []}
        for e in unassigned:
            etype = next((t for t in ("Epic", "Capability", "Feature") if t in e["labels"]), "Unknown")
            by_type[etype].append(e)

        md = []
        md.append(f"# Unassigned PI Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Items listed here have no `PIID::` label and are not committed to any Program Increment.")
        md.append("")
        md.append(f"**Total unassigned: {len(unassigned)}**")
        md.append("")

        for etype in ("Epic", "Capability", "Feature", "Unknown"):
            items = by_type[etype]
            if not items:
                continue
            icon = self.EPIC_TYPE_ICONS.get(etype, "❓")
            md.append(f"## {icon} {etype} ({len(items)})")
            md.append("")
            md.append("| Title | State | Parent |")
            md.append("|-------|-------|--------|")
            for e in sorted(items, key=lambda x: x["title"]):
                title_link = f"[{e['title']}]({e['web_url']})"
                state      = e["state"]
                parent_id  = e.get("parent_id")
                parent     = f"_{epic_title_by_id[parent_id]}_" if parent_id and parent_id in epic_title_by_id else "—"
                md.append(f"| {title_link} | {state} | {parent} |")
            md.append("")

        md.extend([
            "---",
            "## Legend",
            "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
            "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
            "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
            "- **Parent**: the direct parent epic in the hierarchy, if one exists",
            "- Items with no parent and no children are also captured by the Orphaned Epics report",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t4}/Unassigned PI", "\n".join(md))

    # ------------------------------------------------------------------
    # Hierarchy traversal helpers (shared by team/ART/VS reports)
    # ------------------------------------------------------------------

    def _iter_vs_groups(self, _root=None):
        """Yield vs_group dict for every Value Stream under root."""
        for g in self._rd_groups_by_parent.get(self._rd_root["id"], []):
            yield g

    def _iter_art_groups(self, _root=None):
        """Yield (vs_group, art_group) dicts for every ART in the hierarchy."""
        for vs in self._iter_vs_groups():
            for art in self._rd_groups_by_parent.get(vs["id"], []):
                yield vs, art

    def _iter_team_groups(self, _root=None):
        """Yield (vs_group, art_group, team_group) dicts for every team in the hierarchy."""
        for vs, art in self._iter_art_groups():
            for team in self._rd_groups_by_parent.get(art["id"], []):
                yield vs, art, team

    # ------------------------------------------------------------------
    # Risk Register
    # ------------------------------------------------------------------

    def generate_risk_register(self):
        group = self._rd_root_obj
        today = date.today()
        print(f"  Generating Risk Register for {group.name}...")

        RISK_ORDER = ["risk::high", "risk::medium", "risk::low"]
        RISK_ICONS = {"risk::high": "🔴", "risk::medium": "🟡", "risk::low": "🟢"}

        # Canonical order; append any discovered labels not in the standard set
        active_risk_labels = set(self._rd_risk_labels)
        ordered_levels = [l for l in RISK_ORDER if l in active_risk_labels] + \
                         [l for l in self._rd_risk_labels if l not in set(RISK_ORDER)]

        if not ordered_levels:
            md = [
                f"# Risk Register — {group.name}",
                f"## Report Date: {today.strftime('%Y-%m-%d')}",
                "",
                "_No risk labels found. Apply `risk::high`, `risk::medium`, or `risk::low` to epics and re-run._",
            ]
            self.upload_to_wiki(group, f"{self._wiki_t2}/Risk Register", "\n".join(md))
            return

        # Build relative path from root for each epic's owning group
        root_id = self._rd_root["id"]

        def _group_path(gid):
            parts = []
            cur = self._rd_groups_by_id.get(gid)
            while cur and cur["id"] != root_id:
                parts.append(cur["name"])
                cur = self._rd_groups_by_id.get(cur.get("parent_id"))
            return " / ".join(reversed(parts)) if parts else group.name

        # Assign each epic to its highest risk level (high > medium > low)
        buckets   = {lbl: [] for lbl in ordered_levels}
        seen_ids  = set()
        for lbl in ordered_levels:
            for epic in self._rd_epics_all:
                if epic["id"] in seen_ids:
                    continue
                if lbl in epic.get("labels", []):
                    buckets[lbl].append(epic)
                    seen_ids.add(epic["id"])

        total_risk = len(seen_ids)

        # VS breakdown
        vs_counts = {}
        for vs in self._iter_vs_groups():
            vs_desc_ids = set()
            def _collect(gid):
                vs_desc_ids.add(gid)
                for child in self._rd_groups_by_parent.get(gid, []):
                    _collect(child["id"])
            _collect(vs["id"])
            vs_counts[vs["name"]] = sum(
                1 for e in self._rd_epics_all
                if e.get("group_id") in vs_desc_ids
                and any(l in active_risk_labels for l in e.get("labels", []))
            )

        # ── Render ──────────────────────────────────────────────────────── #
        md = []
        md.append(f"# Risk Register — {group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{group.name}]({group.web_url})"
        )
        md.append("")
        md.append(f"**{total_risk} risk-flagged epic(s).** Each epic is assigned to its highest risk level.")
        md.append("")

        md.append("## Summary")
        md.append("")
        md.append("### By Risk Level")
        md.append("")
        md.append("| Risk Level | Count |")
        md.append("|-----------|-------|")
        for lbl in ordered_levels:
            icon  = RISK_ICONS.get(lbl, "⚪")
            level = lbl.split("::")[-1].capitalize()
            md.append(f"| {icon} {level} | {len(buckets[lbl])} |")
        md.append("")

        if vs_counts:
            md.append("### By Value Stream")
            md.append("")
            md.append("| Value Stream | Risk-Flagged Epics |")
            md.append("|-------------|-------------------|")
            for vs_name, cnt in vs_counts.items():
                md.append(f"| {vs_name} | {cnt} |")
            md.append("")

        # ── Per-level tables ─────────────────────────────────────────────── #
        def _pi_sort_key(e):
            piid = next((l for l in e.get("labels", []) if l.startswith("PIID::")), "PIID::ZZZZ")
            return (piid, e["title"])

        for lbl in ordered_levels:
            epics = buckets[lbl]
            if not epics:
                continue
            icon  = RISK_ICONS.get(lbl, "⚪")
            level = lbl.split("::")[-1].capitalize()
            md.append(f"## {icon} {level} Risk ({len(epics)})")
            md.append("")
            md.append("| Epic | Type | PI | Group / ART | State |")
            md.append("|------|------|----|-------------|-------|")
            for epic in sorted(epics, key=_pi_sort_key):
                etype      = next((t for t in ("Epic", "Capability", "Feature")
                                   if t in epic.get("labels", [])), "Unknown")
                eicon      = self.EPIC_TYPE_ICONS.get(etype, "❓")
                pi         = next((l for l in epic.get("labels", [])
                                   if l.startswith("PIID::")), "—")
                path       = _group_path(epic.get("group_id"))
                title_link = f"[{epic['title']}]({epic['web_url']})"
                state      = epic["state"].capitalize()
                md.append(f"| {title_link} | {eicon} {etype} | {pi} | {path} | {state} |")
            md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "| Icon | Level | Meaning |",
            "|------|-------|---------|",
            "| 🔴 | High   | Immediate attention required — risk to delivery or mission outcome |",
            "| 🟡 | Medium | Monitor closely — risk exists but is being managed |",
            "| 🟢 | Low    | Acknowledged risk — low probability or low impact |",
            "",
            "Risk labels (`risk::high`, `risk::medium`, `risk::low`) are applied directly to epics.  ",
            "Each epic is counted once at its highest assigned risk level.  ",
            "**Group / ART** shows the path from the portfolio root to the owning group.",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/Risk Register", "\n".join(md))

    # ------------------------------------------------------------------
    # PI Predictability Scorecard
    # ------------------------------------------------------------------

    def generate_pi_predictability_scorecard(self):
        """PI Predictability Scorecard — % of committed Features/Capabilities delivered per PI."""
        group = self._rd_root_obj
        today = date.today()
        print(f"  Generating PI Predictability Scorecard for {group.name}...")

        # ART → set of group_ids it contains (ART + its teams)
        art_group_ids: dict = {}
        for vs_group, art_group in self._iter_art_groups():
            ids = {art_group["id"]}
            for team in self._rd_groups_by_parent.get(art_group["id"], []):
                ids.add(team["id"])
            art_group_ids[art_group["id"]] = ids

        # Bucket: art_id → piid → [epic, ...]  (Features + Capabilities as commitment units)
        commitment_epics = (
            self._rd_metrics.get("Feature", []) +
            self._rd_metrics.get("Capability", [])
        )
        art_pi_data: defaultdict = defaultdict(lambda: defaultdict(list))
        for epic in commitment_epics:
            gid  = epic.get("group_id")
            piid = epic.get("piid")
            if not piid:
                continue
            for art_id, gids in art_group_ids.items():
                if gid in gids:
                    art_pi_data[art_id][piid].append(epic)
                    break

        all_pis = sorted(
            {piid for pi_map in art_pi_data.values() for piid in pi_map},
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        if not all_pis:
            md = [
                f"# PI Predictability Scorecard — {group.name}",
                f"**Report Date:** {today.strftime('%Y-%m-%d')}",
                "",
                "_No PI-committed Features or Capabilities found. Ensure epics carry `PIID::` labels._",
            ]
            self.upload_to_wiki(group, f"{self._wiki_t2}/PI Predictability Scorecard", "\n".join(md))
            return

        def _pred(epics):
            total  = len(epics)
            closed = sum(1 for e in epics if e["state"].lower() == "closed")
            pct    = round(closed / total * 100) if total else None
            return closed, total, pct

        def _cell(closed, total, pct, piid):
            if total == 0:
                return " — "
            pct_pi = self._pct_through_pi(piid)
            if pct_pi is None or pct_pi == 0:
                return f" 🔵 {total} planned "
            if pct_pi < 100:
                # Current PI — in-flight, no final score yet
                icon = "✅" if pct >= 80 else ("⚠️" if pct and pct >= 60 else "🟡")
                return f" {icon} {closed}/{total} in progress "
            # Past PI — final predictability
            icon = "✅" if pct >= 80 else ("⚠️" if pct >= 60 else "❌")
            return f" {icon} {pct}% ({closed}/{total}) "

        md = []
        md.append(f"# PI Predictability Scorecard — {group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{group.name}]({group.web_url})"
        )
        md.append("")
        md.append(
            "Percentage of committed Features and Capabilities that were delivered in each PI.  "
            "Target ≥ 80%. Consistently at 100% may indicate sandbagging; below 60% signals a systemic problem."
        )
        md.append("")

        header = "| ART |" + "".join(f" {p} |" for p in all_pis)
        sep    = "|---|" + "".join("---|" for _ in all_pis)
        md.append(header)
        md.append(sep)

        portfolio_by_pi: defaultdict = defaultdict(list)
        any_rows = False

        for vs_group, art_group in self._iter_art_groups():
            art_id  = art_group["id"]
            pi_data = art_pi_data.get(art_id)
            if not pi_data:
                continue
            any_rows = True
            art_link = f"[{art_group['name']}]({art_group['web_url']})"
            cells = []
            for piid in all_pis:
                epics = pi_data.get(piid, [])
                closed, total, pct = _pred(epics)
                portfolio_by_pi[piid].extend(epics)
                cells.append(_cell(closed, total, pct, piid))
            md.append("| **" + art_link + "** |" + "|".join(cells) + "|")

        if not any_rows:
            md.append("_No ART-level commitment data found._")
            md.append("")
        else:
            # Portfolio aggregate row
            cells = []
            for piid in all_pis:
                epics = portfolio_by_pi.get(piid, [])
                closed, total, pct = _pred(epics)
                cells.append(_cell(closed, total, pct, piid))
            md.append("| **Portfolio Total** |" + "|".join(cells) + "|")

        md.extend([
            "",
            "---",
            "## Legend",
            "",
            "**Predictability %** = closed Features + Capabilities ÷ total committed to PI × 100",
            "",
            "| Icon | Range | Meaning |",
            "|------|-------|---------|",
            "| ✅ | ≥ 80% | On target — team reliably delivers commitments |",
            "| ⚠️ | 60–79% | Watch — delivery shortfall, investigate root cause |",
            "| ❌ | < 60%  | At risk — systemic delivery problem, escalate |",
            "| 🟡 | Current PI | In progress — final score not yet determined |",
            "| 🔵 | Future PI  | Not yet started — shows planned commitment count |",
            "",
            "> **Sandbagging signal:** an ART consistently at 100% across multiple past PIs "
            "may be under-committing. Healthy predictability is typically 80–90%.",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/PI Predictability Scorecard", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/PI Predictability Scorecard")

    # ------------------------------------------------------------------
    # Team-level reports
    # ------------------------------------------------------------------

    def generate_team_backlog_report(self):
        """One wiki page per team (on each team's own wiki) plus a root-level index page."""
        root_group = self._rd_root_obj
        print(f"Generating Team Backlog Reports under: {root_group.full_path}")

        index_entries = []  # (vs_name, art_name, team_name, wiki_url, summary_line)

        for vs_group, art_group, team_group in self._iter_team_groups():
            print(f"  Processing {team_group['full_path']}")
            entry = self._generate_team_backlog_page(vs_group, art_group, team_group)
            if entry:
                index_entries.append(entry)

        md = []
        md.append(f"# Team Backlog Index — {root_group.name}")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Links to each team's backlog report hosted in their own wiki.")
        md.append("")

        current_vs  = None
        current_art = None
        for vs_name, art_name, team_name, wiki_url, summary in index_entries:
            if vs_name != current_vs:
                md.append(f"### 🔷 {vs_name}")
                current_vs  = vs_name
                current_art = None
            if art_name != current_art:
                md.append(f"#### {art_name}")
                current_art = art_name
            md.append(f"- [**{team_name} — Team Backlog**]({wiki_url})  {summary}")

        md.append("")
        self.upload_to_wiki(root_group, f"{self._wiki_t3}/Team Backlogs", "\n".join(md))
        print(f"  → Root wiki: {root_group.name} - Team Backlog Index")

    def _generate_team_backlog_page(self, vs_group, art_group, team_group):
        """Upload the team backlog page to the team's own wiki. Returns an index entry tuple."""
        projects       = self._rd_projects_by_nsid.get(team_group["id"], [])
        backlog_project = next((p for p in projects if p["path"].endswith("-backlog")), None)

        breadcrumb = f"{vs_group['name']} / {art_group['name']} / {team_group['name']}"
        wiki_title = "Team Backlog"
        wiki_url   = f"{team_group['web_url']}/-/wikis/team-backlog"

        team_group_live = self.gl.groups.get(team_group["id"])

        if not backlog_project:
            md = [
                f"# Team Backlog — {team_group['name']}",
                f"**{breadcrumb}**  |  **Report Date:** {datetime.today().strftime('%Y-%m-%d')}",
                "",
                "_No Team Backlog project found for this team._",
            ]
            self.upload_to_wiki(team_group_live, wiki_title, "\n".join(md))
            print(f"    → {team_group['full_path']} wiki: {wiki_title}")
            return (vs_group["name"], art_group["name"], team_group["name"], wiki_url, "_(no backlog project)_")

        all_issues = self._rd_issues_by_project.get(backlog_project["path_with_namespace"], [])

        # Group by linked Feature epic
        by_feature: defaultdict = defaultdict(list)
        unlinked = []
        for issue in all_issues:
            eid = issue.get("epic_id")
            if eid:
                by_feature[eid].append(issue)
            else:
                unlinked.append(issue)

        total_w  = sum(i.get("weight") or 0 for i in all_issues)
        closed_w = sum(i.get("weight") or 0 for i in all_issues if i["state"] == "closed")
        open_cnt = sum(1 for i in all_issues if i["state"] == "opened")

        md = []
        md.append(f"# Team Backlog — {team_group['name']}")
        md.append(
            f"**{breadcrumb}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[**View Project**]({backlog_project['web_url']})"
        )
        md.append("")
        md.append("## Summary")
        md.append(f"| | Count | Weight |")
        md.append(f"|---|---|---|")
        md.append(f"| **Total issues** | {len(all_issues)} | {total_w} pt |")
        md.append(f"| Open | {open_cnt} | {total_w - closed_w} pt |")
        md.append(f"| Closed | {len(all_issues) - open_cnt} | {closed_w} pt |")
        pct = round(closed_w / total_w * 100) if total_w else 0
        md.append(f"| **% Done** | | **{pct}%** |")
        md.append("")

        if by_feature:
            md.append("## Issues by Feature")
            md.append("")
            for epic_id, issues in by_feature.items():
                epic_info = self._rd_epics_by_id.get(epic_id, {})
                f_total   = sum(i.get("weight") or 0 for i in issues)
                f_closed  = sum(i.get("weight") or 0 for i in issues if i["state"] == "closed")
                f_pct     = round(f_closed / f_total * 100) if f_total else 0
                f_open    = sum(1 for i in issues if i["state"] == "opened")
                f_state   = epic_info.get("state", "").capitalize() if epic_info else "Unknown"
                epic_url  = epic_info.get("web_url", "#") if epic_info else "#"
                epic_title = epic_info.get("title", f"Epic {epic_id}") if epic_info else f"Epic {epic_id}"

                md.append(
                    f"<details><summary>🛠️ "
                    f"<a href=\"{epic_url}\">{epic_title}</a>"
                    f" — {f_open} open · {f_pct}% done · {f_closed}/{f_total} pt</summary>"
                )
                md.append("")
                md.append(f"**Feature state:** {f_state}")
                md.append("")
                md.append("| Issue | State | Weight | Milestone |")
                md.append("|-------|-------|--------|-----------|")
                for issue in sorted(issues, key=lambda i: i["state"]):
                    ms    = issue.get("milestone") or "—"
                    w     = issue.get("weight") or "—"
                    state = "✅ Closed" if issue["state"] == "closed" else "🔵 Open"
                    md.append(
                        f"| [{issue['title']}]({issue['web_url']}) "
                        f"| {state} | {w} pt | {ms} |"
                    )
                md.append("")
                md.append("</details>")
                md.append("")

        if unlinked:
            md.append("## Unlinked Issues (no Feature)")
            md.append("")
            md.append("| Issue | State | Weight | Milestone |")
            md.append("|-------|-------|--------|-----------|")
            for issue in unlinked:
                ms    = issue.get("milestone") or "—"
                w     = issue.get("weight") or "—"
                state = "✅ Closed" if issue["state"] == "closed" else "🔵 Open"
                md.append(
                    f"| [{issue['title']}]({issue['web_url']}) "
                    f"| {state} | {w} pt | {ms} |"
                )
            md.append("")

        self.upload_to_wiki(team_group_live, wiki_title, "\n".join(md))
        print(f"    → {team_group['full_path']} wiki: {wiki_title}")

        summary = f"· {len(all_issues)} issues · {pct}% done · {total_w} pt total"
        return (vs_group["name"], art_group["name"], team_group["name"], wiki_url, summary)

    # ------------------------------------------------------------------
    # ART-level reports
    # ------------------------------------------------------------------

    def generate_art_feature_status_report(self):
        """One wiki page per ART showing all Features grouped by Team, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating ART Feature Status Reports under: {root_group.full_path}")

        features = self._rd_metrics.get("Feature", [])

        team_hierarchy = {}
        for vs_group, art_group, team_group in self._iter_team_groups():
            team_hierarchy[team_group["id"]] = (vs_group, art_group, team_group)

        art_buckets: defaultdict = defaultdict(lambda: defaultdict(list))
        for f in features:
            gid = f.get("group_id")
            if gid in team_hierarchy:
                _, art_grp, _ = team_hierarchy[gid]
                art_buckets[art_grp["id"]][gid].append(f)

        index_entries = []
        for vs_group, art_group in self._iter_art_groups():
            if art_group["id"] not in art_buckets:
                continue
            entry = self._generate_art_feature_status_page(
                root_group, vs_group, art_group,
                art_buckets[art_group["id"]], team_hierarchy,
            )
            if entry:
                index_entries.append(entry)

        md = []
        md.append(f"# ART Feature Status Index — {root_group.name}")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Links to each ART's feature status report.")
        md.append("")

        current_vs = None
        for vs_name, art_name, wiki_url, total_f, at_risk, blocked in index_entries:
            if vs_name != current_vs:
                md.append(f"### 🔷 {vs_name}")
                current_vs = vs_name
            risk_str    = f" · ⚠️ {at_risk} at risk" if at_risk else ""
            blocked_str = f" · 🔒 {blocked} blocked" if blocked else ""
            md.append(f"- [**{art_name} — Feature Status**]({wiki_url})  · {total_f} features{risk_str}{blocked_str}")

        md.append("")
        # (flat index page removed — navigation is via the nested wiki tree)

        # Group entries by VS for the tier-nested pages
        vs_arts: defaultdict = defaultdict(list)
        for vs_name, art_name, wiki_url, total_f, at_risk, blocked in index_entries:
            vs_arts[vs_name].append((art_name, wiki_url, total_f, at_risk, blocked))

        # VS-level pages
        for vs_name, arts in vs_arts.items():
            wiki_title  = f"{self._wiki_t3}/ART Feature Status/{vs_name}"
            md_vs = []
            md_vs.append(f"# ART Feature Status — {vs_name}")
            md_vs.append(f"**Value Stream:** {vs_name}  |  **Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
            md_vs.append("")
            md_vs.append(f"Feature delivery status for each ART within the **{vs_name}** Value Stream.")
            md_vs.append("")
            md_vs.append("| ART | Features | At Risk | Blocked | Detail |")
            md_vs.append("|-----|----------|---------|---------|--------|")
            for art_name, art_url, total_f, at_risk, blocked in arts:
                risk_str    = str(at_risk) if at_risk else "—"
                blocked_str = str(blocked) if blocked else "—"
                md_vs.append(f"| **{art_name}** | {total_f} | {risk_str} | {blocked_str} | [View →]({art_url}) |")
            md_vs.append("")
            self.upload_to_wiki(root_group, wiki_title, "\n".join(md_vs))
            print(f"    → Wiki: {wiki_title}")

        # Top-level landing page
        top_url  = f"{root_group.web_url}/-/wikis/{_wiki_slug(f'{self._wiki_t3}/ART Feature Status')}"
        md_top   = []
        md_top.append("# ART Feature Status")
        md_top.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md_top.append("")
        md_top.append("All Features per ART, grouped by Team, with completion %, PI progress, and risk flags.")
        md_top.append("Select a Value Stream to browse its ARTs:")
        md_top.append("")
        for vs_name, arts in vs_arts.items():
            vs_url    = f"{root_group.web_url}/-/wikis/{_wiki_slug(f'{self._wiki_t3}/ART Feature Status/{vs_name}')}"
            art_links = "  ·  ".join(f"[{art_name}]({art_url})" for art_name, art_url, *_ in arts)
            md_top.append(f"- 🔷 [**{vs_name}**]({vs_url})  —  {art_links}")
        md_top.append("")
        self.upload_to_wiki(root_group, f"{self._wiki_t3}/ART Feature Status", "\n".join(md_top))
        print(f"    → Wiki: {self._wiki_t3}/ART Feature Status")

    def _generate_art_feature_status_page(self, root_group, vs_group, art_group, team_buckets, team_hierarchy):
        wiki_title = f"{self._wiki_t3}/ART Feature Status/{vs_group['name']}/{art_group['name']}"
        wiki_url   = f"{root_group.web_url}/-/wikis/{_wiki_slug(wiki_title)}"

        md = []
        md.append(f"# ART Feature Status — {art_group['name']}")
        md.append(
            f"**{vs_group['name']} / {art_group['name']}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View ART Group]({art_group['web_url']})"
        )
        md.append("")

        total_f   = 0
        at_risk   = 0
        blocked_c = 0

        for team_id, feature_list in sorted(team_buckets.items(), key=lambda x: team_hierarchy[x[0]][2]["name"]):
            _, _, team_group = team_hierarchy[team_id]
            md.append(f"## {team_group['name']}")
            md.append("")
            md.append("| Feature | PI | State | % Done | PI Elapsed | Weight | Status |")
            md.append("|---------|-----|-------|--------|------------|--------|--------|")

            for f in sorted(feature_list, key=lambda x: x.get("title", "")):
                title      = f["title"]
                url        = f["web_url"]
                piid       = f.get("piid") or "—"
                state      = f["state"].capitalize()
                pct_done   = f["pct_complete"]
                pct_pi     = f.get("pct_through_pi")
                planned    = f.get("planned_weight", 0)
                actual     = f.get("actual_weight", 0)
                blocked_by = f.get("blocked_by_count", 0)

                if blocked_by:
                    status = "🔒 Blocked"
                    blocked_c += 1
                elif pct_pi is None or pct_pi == 0:
                    status = "🔵 Planned"
                elif pct_pi >= 100:
                    status = "✅ Complete" if pct_done >= 100 else "❌ Incomplete"
                elif pct_done >= pct_pi:
                    status = "✅ On Track"
                else:
                    status = "⚠️ At Risk"
                    at_risk += 1

                pi_str     = f"{pct_pi}%" if pct_pi is not None else "—"
                weight_str = f"{planned}pt → {actual}pt"
                md.append(
                    f"| [{title}]({url}) | {piid} | {state} "
                    f"| {pct_done}% | {pi_str} | {weight_str} | {status} |"
                )
                total_f += 1

            md.append("")

        md.extend([
            "---",
            "## Legend",
            "- **% Done** — closed issue weight ÷ total issue weight for all issues linked to this Feature",
            "- **PI Elapsed** — how far through the PI quarter today falls: `(today − PI start) ÷ (PI end − PI start) × 100`",
            "- **Weight** — Planned pt → Actual pt (planned set via GraphQL; actual = sum of linked issue weights)",
            "- **✅ On Track** — % Done ≥ PI Elapsed for the current PI",
            "- **⚠️ At Risk** — % Done < PI Elapsed for the current PI",
            "- **✅ Complete** / **❌ Incomplete** — outcome for a past PI",
            "- **🔵 Planned** — future PI or PI not yet started",
            "- **🔒 Blocked** — Feature has one or more active blocking relationships",
            "",
        ])

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], art_group["name"], wiki_url, total_f, at_risk, blocked_c)

    def generate_art_capacity_balance_report(self):
        """One wiki page per ART showing per-team capacity balance by PI, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating ART Capacity Balance Reports under: {root_group.full_path}")

        features = self._rd_metrics.get("Feature", [])

        team_hierarchy = {}
        for vs_group, art_group, team_group in self._iter_team_groups():
            team_hierarchy[team_group["id"]] = (vs_group, art_group, team_group)

        art_pi_buckets: defaultdict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for f in features:
            gid  = f.get("group_id")
            piid = f.get("piid")
            if gid in team_hierarchy and piid:
                _, art_grp, _ = team_hierarchy[gid]
                art_pi_buckets[art_grp["id"]][piid][gid].append(f)

        index_entries = []
        for vs_group, art_group in self._iter_art_groups():
            if art_group["id"] not in art_pi_buckets:
                continue
            entry = self._generate_art_capacity_balance_page(
                root_group, vs_group, art_group,
                art_pi_buckets[art_group["id"]], team_hierarchy,
            )
            if entry:
                index_entries.append(entry)

        md = []
        md.append(f"# ART Capacity Balance Index — {root_group.name}")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Per-ART view of planned vs actual team capacity by Program Increment.")
        md.append("")

        current_vs = None
        for vs_name, art_name, wiki_url, over_cnt, under_cnt in index_entries:
            if vs_name != current_vs:
                md.append(f"### 🔷 {vs_name}")
                current_vs = vs_name
            flags = []
            if over_cnt:
                flags.append(f"🔴 {over_cnt} over-capacity")
            if under_cnt:
                flags.append(f"🔵 {under_cnt} under-capacity")
            flag_str = "  · " + "  · ".join(flags) if flags else ""
            md.append(f"- [**{art_name} — Capacity Balance**]({wiki_url}){flag_str}")

        md.append("")
        # (flat legacy index removed — top-level landing page is the T2 page below)

        # Intermediate pages — GitLab creates these as blank when nested titles use /
        vs_arts: defaultdict = defaultdict(list)
        for vs_name, art_name, wiki_url, over_cnt, under_cnt in index_entries:
            vs_arts[vs_name].append((art_name, wiki_url, over_cnt, under_cnt))

        # VS-level pages
        for vs_name, arts in vs_arts.items():
            wiki_title = f"{self._wiki_t2}/ART Capacity Balance/{vs_name}"
            md_vs = []
            md_vs.append(f"# ART Capacity Balance — {vs_name}")
            md_vs.append(f"**Value Stream:** {vs_name}  |  **Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
            md_vs.append("")
            md_vs.append(f"Planned vs actual team capacity by Program Increment for each ART in the **{vs_name}** Value Stream.")
            md_vs.append("")
            md_vs.append("| ART | Over-capacity | Under-capacity | Detail |")
            md_vs.append("|-----|--------------|----------------|--------|")
            for art_name, art_url, over_cnt, under_cnt in arts:
                over_str  = f"🔴 {over_cnt}" if over_cnt else "—"
                under_str = f"🔵 {under_cnt}" if under_cnt else "—"
                md_vs.append(f"| **{art_name}** | {over_str} | {under_str} | [View →]({art_url}) |")
            md_vs.append("")
            self.upload_to_wiki(root_group, wiki_title, "\n".join(md_vs))
            print(f"    → Wiki: {wiki_title}")

        # Top-level landing page (Tier 2)
        md_top = []
        md_top.append("# ART Capacity Balance")
        md_top.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md_top.append("")
        md_top.append("Per-ART view of planned vs actual team capacity by Program Increment.")
        md_top.append("Select a Value Stream to browse its ARTs:")
        md_top.append("")
        for vs_name, arts in vs_arts.items():
            vs_url    = f"{root_group.web_url}/-/wikis/{_wiki_slug(f'{self._wiki_t2}/ART Capacity Balance/{vs_name}')}"
            art_links = "  ·  ".join(f"[{art_name}]({art_url})" for art_name, art_url, *_ in arts)
            md_top.append(f"- 🔷 [**{vs_name}**]({vs_url})  —  {art_links}")
        md_top.append("")
        self.upload_to_wiki(root_group, f"{self._wiki_t2}/ART Capacity Balance", "\n".join(md_top))
        print(f"    → Wiki: {self._wiki_t2}/ART Capacity Balance")

    def _generate_art_capacity_balance_page(self, root_group, vs_group, art_group, pi_buckets, team_hierarchy):
        wiki_title = f"{self._wiki_t2}/ART Capacity Balance/{vs_group['name']}/{art_group['name']}"
        wiki_url   = f"{root_group.web_url}/-/wikis/{_wiki_slug(wiki_title)}"

        sorted_pis = sorted(
            pi_buckets.keys(),
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        md = []
        md.append(f"# ART Capacity Balance — {art_group['name']}")
        md.append(
            f"**{vs_group['name']} / {art_group['name']}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View ART Group]({art_group['web_url']})"
        )
        md.append("")

        total_over  = 0
        total_under = 0

        for piid in sorted_pis:
            team_buckets = pi_buckets[piid]
            pct_pi       = self._pct_through_pi(piid)
            start, end   = self._pi_dates_from_label(piid)
            date_range   = f"_{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}_" if start else ""

            md.append(f"## {piid}")
            if date_range:
                md.append(date_range)
            md.append("")
            md.append("| Team | Planned | Actual | Δ | Load% | Status |")
            md.append("|------|---------|--------|---|-------|--------|")

            for team_id, fs in sorted(team_buckets.items(), key=lambda x: team_hierarchy[x[0]][2]["name"]):
                _, _, team_group = team_hierarchy[team_id]
                planned  = sum(f.get("planned_weight", 0) for f in fs)
                actual   = sum(f.get("actual_weight",  0) for f in fs)
                delta    = actual - planned
                delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")

                if planned > 0:
                    load_pct = round(actual / planned * 100)
                else:
                    load_pct = 0

                if load_pct > 120:
                    status = "🔴 Over"
                    total_over += 1
                elif load_pct > 100:
                    status = "🟡 High"
                elif load_pct >= 80:
                    status = "✅ Balanced"
                elif planned > 0:
                    status = "🔵 Under"
                    total_under += 1
                else:
                    status = "—"

                team_link = f'<a href="{team_group["web_url"]}">{team_group["name"]}</a>'
                md.append(
                    f"| {team_link} | {planned} pt | {actual} pt "
                    f"| {delta_str} | {load_pct}% | {status} |"
                )

            md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "### Load%",
            "- **Load%** — `Actual ÷ Planned × 100`: how much work is estimated relative to the team's planned capacity",
            "",
            "### Status thresholds",
            "| Status | Load% range | Meaning |",
            "|--------|-------------|---------|",
            "| 🔴 Over      | > 120% | Actual work significantly exceeds planned capacity — team is over-committed |",
            "| 🟡 High      | 101–120% | Slightly over plan — monitor closely |",
            "| ✅ Balanced  | 80–100% | Actual work aligns with planned capacity |",
            "| 🔵 Under     | < 80%  | Team has more capacity than committed work — potential to take on more |",
            "",
            "### Column definitions",
            "- **Planned** — sum of planned weights on Features assigned to this team for the PI (set via GraphQL)",
            "- **Actual** — sum of story-point weights on all issues linked to those Features",
            "- **Δ** — Actual minus Planned: ▲ more than planned · ▼ less than planned · = matched",
            "",
        ])

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], art_group["name"], wiki_url, total_over, total_under)

    # ------------------------------------------------------------------
    # Value Stream-level reports
    # ------------------------------------------------------------------

    def generate_vs_capability_dashboard_report(self):
        """One wiki page per VS showing Capabilities and Direct Features by PI, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating VS Capability Dashboard Reports under: {root_group.full_path}")

        capabilities = self._rd_metrics.get("Capability", [])
        features     = self._rd_metrics.get("Feature", [])

        art_hierarchy: dict  = {}
        team_hierarchy: dict = {}
        for vs_group, art_group in self._iter_art_groups():
            art_hierarchy[art_group["id"]] = (vs_group, art_group)
        for vs_group, art_group, team_group in self._iter_team_groups():
            team_hierarchy[team_group["id"]] = (vs_group, art_group, team_group)

        def _vs_art_for(gid):
            if gid in art_hierarchy:
                return art_hierarchy[gid]
            if gid in team_hierarchy:
                vs_g, art_g, _ = team_hierarchy[gid]
                return vs_g, art_g
            return None, None

        vs_cap_buckets: defaultdict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for cap in capabilities:
            vs_g, art_g = _vs_art_for(cap.get("group_id"))
            piid = cap.get("piid")
            if vs_g and art_g and piid:
                vs_cap_buckets[vs_g["id"]][piid][art_g["id"]].append(cap)

        # Direct Features: parent is Epic (not Capability) or parentless
        epic_type_by_id = {e["id"]: t for t, tier in self._rd_metrics.items() for e in tier}
        direct_features = [
            f for f in features
            if epic_type_by_id.get(f.get("parent_id")) != "Capability"
        ]

        vs_direct_buckets: defaultdict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for feat in direct_features:
            vs_g, art_g = _vs_art_for(feat.get("group_id"))
            piid = feat.get("piid")
            if vs_g and art_g and piid:
                vs_direct_buckets[vs_g["id"]][piid][art_g["id"]].append(feat)

        index_entries = []
        for vs_group in self._iter_vs_groups():
            if vs_group["id"] not in vs_cap_buckets and vs_group["id"] not in vs_direct_buckets:
                continue
            entry = self._generate_vs_capability_dashboard_page(
                root_group, vs_group,
                vs_cap_buckets.get(vs_group["id"], {}),
                vs_direct_buckets.get(vs_group["id"], {}),
                art_hierarchy, team_hierarchy,
            )
            if entry:
                index_entries.append(entry)

        md = []
        md.append(f"# VS Capability Dashboard Index — {root_group.name}")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Delivery status per Value Stream, broken down by PI and ART.")
        md.append("")
        md.append("- **🧩 Capabilities** — cross-ART/VS deliverables that may span multiple ARTs or Value Streams")
        md.append("- **🛠️ Direct Features** — Features parented directly to an Epic (no Capability wrapper), owned by a single ART")
        md.append("")

        for vs_name, wiki_url, total_caps, total_direct, at_risk, blocked in index_entries:
            parts = []
            if total_caps:
                parts.append(f"{total_caps} capabilities")
            if total_direct:
                parts.append(f"{total_direct} direct features")
            counts      = "  · " + "  · ".join(parts) if parts else ""
            risk_str    = f"  · ⚠️ {at_risk} at risk" if at_risk else ""
            blocked_str = f"  · 🔒 {blocked} blocked" if blocked else ""
            md.append(f"- 🔷 [**{vs_name} — Capability Dashboard**]({wiki_url}){counts}{risk_str}{blocked_str}")

        md.append("")
        # (flat legacy index removed — top-level landing page is the T3 page below)

        # Top-level landing page for the nested wiki section
        md_top = []
        md_top.append("# VS Capability Dashboard")
        md_top.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md_top.append("")
        md_top.append("Delivery status per Value Stream, broken down by PI and ART.")
        md_top.append("")
        md_top.append("- **🧩 Capabilities** — cross-ART/VS deliverables that may span multiple ARTs or Value Streams")
        md_top.append("- **🛠️ Direct Features** — Features parented directly to an Epic (no Capability wrapper), owned by a single ART")
        md_top.append("")
        md_top.append("## Value Streams")
        md_top.append("")
        for vs_name, wiki_url, total_caps, total_direct, at_risk, blocked in index_entries:
            parts = []
            if total_caps:
                parts.append(f"{total_caps} capabilities")
            if total_direct:
                parts.append(f"{total_direct} direct features")
            counts      = "  ·  " + "  ·  ".join(parts) if parts else ""
            risk_str    = f"  ·  ⚠️ {at_risk} at risk" if at_risk else ""
            blocked_str = f"  ·  🔒 {blocked} blocked" if blocked else ""
            md_top.append(f"- 🔷 [**{vs_name} — Capability Dashboard**]({wiki_url}){counts}{risk_str}{blocked_str}")
        md_top.append("")
        self.upload_to_wiki(root_group, f"{self._wiki_t3}/VS Capability Dashboard", "\n".join(md_top))
        print(f"    → Wiki: {self._wiki_t3}/VS Capability Dashboard")

    def _generate_vs_capability_dashboard_page(self, root_group, vs_group, cap_pi_buckets, direct_pi_buckets, art_hierarchy, team_hierarchy):
        wiki_title = f"{self._wiki_t3}/VS Capability Dashboard/{vs_group['name']}"
        wiki_url   = f"{root_group.web_url}/-/wikis/{_wiki_slug(wiki_title)}"

        all_pis = sorted(
            set(cap_pi_buckets) | set(direct_pi_buckets),
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        md = []
        md.append(f"# VS Capability Dashboard — {vs_group['name']}")
        md.append(
            f"**{vs_group['name']}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View VS Group]({vs_group['web_url']})"
        )
        md.append("")

        total_caps   = 0
        total_direct = 0
        at_risk      = 0
        blocked_c    = 0

        def _art_name_url(art_id):
            if art_id in art_hierarchy:
                _, g = art_hierarchy[art_id]
                return g["name"], g["web_url"]
            return f"ART {art_id}", ""

        def _row_status(pct_done, pct_pi, blocked_by):
            nonlocal at_risk, blocked_c
            if blocked_by:
                blocked_c += 1
                return "🔒 Blocked"
            if pct_pi is None or pct_pi == 0:
                return "🔵 Planned"
            if pct_pi >= 100:
                return "✅ Complete" if pct_done >= 100 else "❌ Incomplete"
            if pct_done >= pct_pi:
                return "✅ On Track"
            at_risk += 1
            return "⚠️ At Risk"

        def _detail_rows(items, pct_pi):
            rows = []
            for item in sorted(items, key=lambda x: x.get("title", "")):
                status     = _row_status(item["pct_complete"], pct_pi, item.get("blocked_by_count", 0))
                pi_str     = f"{pct_pi}%" if pct_pi is not None else "—"
                weight_str = f"{item.get('planned_weight', 0)}pt → {item.get('actual_weight', 0)}pt"
                rows.append(
                    f"| [{item['title']}]({item['web_url']}) | {item['state'].capitalize()} "
                    f"| {item['pct_complete']}% | {pi_str} | {weight_str} | {status} |"
                )
            return rows

        for piid in all_pis:
            pct_pi     = self._pct_through_pi(piid)
            start, end = self._pi_dates_from_label(piid)
            date_range = f"_{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}_" if start else ""

            md.append(f"## {piid}")
            if date_range:
                md.append(date_range)
            md.append("")

            # --- Capabilities section ---
            art_cap_buckets = cap_pi_buckets.get(piid, {})
            if art_cap_buckets:
                md.append("### 🧩 Capabilities _(cross-ART/VS deliverables)_")
                md.append("")
                md.append("| ART | Capabilities | Planned | Actual | Δ | % Done | Status |")
                md.append("|-----|-------------|---------|--------|---|--------|--------|")

                art_rows = []
                for art_id, caps in sorted(art_cap_buckets.items(), key=lambda x: _art_name_url(x[0])[0]):
                    art_name, art_url = _art_name_url(art_id)
                    planned   = sum(c.get("planned_weight", 0) for c in caps)
                    actual    = sum(c.get("actual_weight",  0) for c in caps)
                    delta     = actual - planned
                    delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")
                    n_blocked = sum(1 for c in caps if c.get("blocked_by_count", 0) > 0)
                    avg_pct   = round(sum(c["planned_weight"] * c["pct_complete"] for c in caps) / planned) if planned else (round(sum(c["pct_complete"] for c in caps) / len(caps)) if caps else 0)
                    if n_blocked:
                        status = "🔒 Blocked"
                    elif pct_pi is None or pct_pi == 0:
                        status = "🔵 Planned"
                    elif pct_pi >= 100:
                        status = "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
                    elif avg_pct >= pct_pi:
                        status = "✅ On Track"
                    else:
                        status = "⚠️ At Risk"
                    art_link = f'<a href="{art_url}">{art_name}</a>' if art_url else art_name
                    md.append(f"| {art_link} | {len(caps)} | {planned} pt | {actual} pt | {delta_str} | {avg_pct}% | {status} |")
                    art_rows.append((art_name, art_url, caps))
                    total_caps += len(caps)

                md.append("")
                for art_name, art_url, caps in art_rows:
                    md.append(f"<details><summary><strong>{art_name} — Capability Detail</strong></summary>")
                    md.append("")
                    md.append("| Capability | State | % Done | PI Elapsed | Weight | Status |")
                    md.append("|------------|-------|--------|------------|--------|--------|")
                    md.extend(_detail_rows(caps, pct_pi))
                    md.append("")
                    md.append("</details>")
                    md.append("")

            # --- Direct Features section ---
            art_direct_buckets = direct_pi_buckets.get(piid, {})
            if art_direct_buckets:
                md.append("### 🛠️ Direct Features _(parented to Epic, no Capability wrapper)_")
                md.append("")
                md.append("| ART | Features | Planned | Actual | Δ | % Done | Status |")
                md.append("|-----|----------|---------|--------|---|--------|--------|")

                art_direct_rows = []
                for art_id, feats in sorted(art_direct_buckets.items(), key=lambda x: _art_name_url(x[0])[0]):
                    art_name, art_url = _art_name_url(art_id)
                    planned   = sum(f.get("planned_weight", 0) for f in feats)
                    actual    = sum(f.get("actual_weight",  0) for f in feats)
                    delta     = actual - planned
                    delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")
                    n_blocked = sum(1 for f in feats if f.get("blocked_by_count", 0) > 0)
                    avg_pct   = round(sum(f["planned_weight"] * f["pct_complete"] for f in feats) / planned) if planned else (round(sum(f["pct_complete"] for f in feats) / len(feats)) if feats else 0)
                    if n_blocked:
                        status = "🔒 Blocked"
                    elif pct_pi is None or pct_pi == 0:
                        status = "🔵 Planned"
                    elif pct_pi >= 100:
                        status = "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
                    elif avg_pct >= pct_pi:
                        status = "✅ On Track"
                    else:
                        status = "⚠️ At Risk"
                    art_link = f'<a href="{art_url}">{art_name}</a>' if art_url else art_name
                    md.append(f"| {art_link} | {len(feats)} | {planned} pt | {actual} pt | {delta_str} | {avg_pct}% | {status} |")
                    art_direct_rows.append((art_name, art_url, feats))
                    total_direct += len(feats)

                md.append("")
                for art_name, art_url, feats in art_direct_rows:
                    md.append(f"<details><summary><strong>{art_name} — Direct Feature Detail</strong></summary>")
                    md.append("")
                    md.append("| Feature | State | % Done | PI Elapsed | Weight | Status |")
                    md.append("|---------|-------|--------|------------|--------|--------|")
                    md.extend(_detail_rows(feats, pct_pi))
                    md.append("")
                    md.append("</details>")
                    md.append("")

        md.extend([
            "---",
            "## Legend",
            "- **🧩 Capability** — cross-ART/VS deliverable that may span multiple ARTs or Value Streams; decomposed from a Portfolio Epic",
            "- **🛠️ Direct Feature** — Feature parented directly to an Epic (no Capability wrapper); owned and delivered by a single ART",
            "- **% Done** — closed issue weight ÷ total issue weight",
            "- **PI Elapsed** — `(today − PI start) ÷ (PI end − PI start) × 100`",
            "- **Weight** — Planned pt → Actual pt",
            "- **✅ On Track** — % Done ≥ PI Elapsed",
            "- **⚠️ At Risk** — % Done < PI Elapsed",
            "- **✅ Complete** / **❌ Incomplete** — outcome for a past PI",
            "- **🔵 Planned** — future PI or not yet started",
            "- **🔒 Blocked** — has one or more active blocking relationships",
            "",
        ])

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], wiki_url, total_caps, total_direct, at_risk, blocked_c)

    def generate_vs_cross_art_risk_report(self):
        """One wiki page per VS showing blocking relationships that cross ART boundaries, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating VS Cross-ART Risk Reports under: {root_group.full_path}")

        # numeric epic id → group_id / piid from snapshot metrics
        epic_int_to_group = {
            e["id"]: e.get("group_id")
            for tier in self._rd_metrics.values()
            for e in tier
        }
        epic_int_to_piid = {
            e["id"]: e.get("piid")
            for tier in self._rd_metrics.values()
            for e in tier
        }

        # group_id → art_group dict, vs_group dict
        art_of_group: dict = {}
        vs_of_group: dict  = {}
        for vs_group, art_group in self._iter_art_groups():
            art_of_group[art_group["id"]] = art_group
            vs_of_group[art_group["id"]]  = vs_group
        for vs_group, art_group, team_group in self._iter_team_groups():
            art_of_group[team_group["id"]] = art_group
            vs_of_group[team_group["id"]]  = vs_group

        # Build cross-ART deps from blocking snapshot (no extra API call)
        vs_deps: defaultdict = defaultdict(list)
        for rel in self._rd_blocking.get("relationships", []):
            blocked = rel["blocked_epic"]
            b_int   = blocked.get("id_int") or _gid_to_int(blocked["id"])
            b_gid   = epic_int_to_group.get(b_int)
            b_art   = art_of_group.get(b_gid)
            b_vs    = vs_of_group.get(b_gid)
            b_piid  = epic_int_to_piid.get(b_int)
            if not b_vs or not b_art:
                continue

            for blocker in rel.get("blocked_by", []):
                bl_int  = blocker.get("id_int") or _gid_to_int(blocker["id"])
                bl_gid  = epic_int_to_group.get(bl_int)
                bl_art  = art_of_group.get(bl_gid)
                bl_vs   = vs_of_group.get(bl_gid)

                if not bl_vs or not bl_art:
                    continue
                if b_vs["id"] != bl_vs["id"]:
                    continue
                if b_art["id"] == bl_art["id"]:
                    continue

                vs_deps[b_vs["id"]].append({
                    "blocked":      blocked,
                    "blocked_art":  b_art,
                    "blocked_piid": b_piid,
                    "blocker":      blocker,
                    "blocker_art":  bl_art,
                })

        index_entries = []
        for vs_group in self._iter_vs_groups():
            deps = vs_deps.get(vs_group["id"], [])
            entry = self._generate_vs_cross_art_risk_page(root_group, vs_group, deps)
            index_entries.append(entry)

        md = []
        md.append(f"# VS Cross-ART Risk Index — {root_group.name}")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Blocking relationships that cross ART boundaries within each Value Stream.")
        md.append("")

        for vs_name, wiki_url, total_deps, critical in index_entries:
            crit_str = f"  · 🔴 {critical} critical" if critical else ""
            clear_str = "  · ✅ No cross-ART blocks" if total_deps == 0 else f"  · {total_deps} cross-ART dependencies"
            md.append(f"- 🔷 [**{vs_name} — Cross-ART Risk**]({wiki_url}){clear_str}{crit_str}")

        md.append("")
        # (flat legacy index removed — top-level landing page is the T3 page below)

        # Top-level landing page for the nested wiki section
        md_top = []
        md_top.append("# VS Cross-ART Risk")
        md_top.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md_top.append("")
        md_top.append("Blocking relationships that cross ART boundaries within each Value Stream.")
        md_top.append("A cross-ART dependency exists when an epic in one ART is blocked by an epic from a different ART within the same Value Stream — these require active coordination.")
        md_top.append("")
        md_top.append("## Value Streams")
        md_top.append("")
        for vs_name, wiki_url, total_deps, critical in index_entries:
            crit_str  = f"  ·  🔴 {critical} critical" if critical else ""
            clear_str = "  ·  ✅ No cross-ART blocks" if total_deps == 0 else f"  ·  {total_deps} cross-ART dependencies"
            md_top.append(f"- 🔷 [**{vs_name} — Cross-ART Risk**]({wiki_url}){clear_str}{crit_str}")
        md_top.append("")
        self.upload_to_wiki(root_group, f"{self._wiki_t3}/VS Cross-ART Risk", "\n".join(md_top))
        print(f"    → Wiki: {self._wiki_t3}/VS Cross-ART Risk")

    def _generate_vs_cross_art_risk_page(self, root_group, vs_group, deps, parent_path=None):
        if parent_path is None:
            parent_path = self._wiki_t3
        wiki_title = f"{parent_path}/VS Cross-ART Risk/{vs_group['name']}"
        wiki_url   = f"{root_group.web_url}/-/wikis/{_wiki_slug(wiki_title)}"

        today = date.today()

        def pi_phase(piid):
            if not piid:
                return "unknown"
            start, end = self._pi_dates_from_label(piid)
            if not start:
                return "unknown"
            if today < start:
                return "future"
            if today > end:
                return "past"
            return "current"

        def severity(piid):
            phase = pi_phase(piid)
            if phase == "current":
                return "🔴 Critical", 0
            if phase == "future":
                return "🟡 Watch", 1
            if phase == "past":
                return "⚫ Past", 2
            return "⚪ Unknown", 3

        md = []
        md.append(f"# VS Cross-ART Risk — {vs_group['name']}")
        md.append(
            f"**{vs_group['name']}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View VS Group]({vs_group['web_url']})"
        )
        md.append("")

        critical = 0

        if not deps:
            md.append("✅ **No cross-ART blocking relationships found in this Value Stream.**")
            md.append("")
        else:
            md.append(f"**{len(deps)} cross-ART blocking relationship(s) identified.**")
            md.append("")
            md.append("> A cross-ART dependency exists when an epic in one ART is blocked by an epic from a different ART within the same Value Stream. These dependencies require active coordination between ART teams.")
            md.append("")

            # Sort: critical first, then watch, then past
            sorted_deps = sorted(deps, key=lambda d: severity(d["blocked_piid"])[1])

            md.append("| Severity | Blocked | Blocked ART | Blocker | Blocker ART | PI |")
            md.append("|----------|---------|-------------|---------|-------------|-----|")

            for dep in sorted_deps:
                blocked     = dep["blocked"]
                blocker     = dep["blocker"]
                b_art       = dep["blocked_art"]
                bl_art      = dep["blocker_art"]
                piid        = dep["blocked_piid"] or "—"
                sev_label, sev_sort = severity(dep["blocked_piid"])

                b_type  = blocked.get("type", "Epic")
                bl_type = blocker.get("type", "Epic")
                b_icon  = self.EPIC_TYPE_ICONS.get(b_type, "🏆")
                bl_icon = self.EPIC_TYPE_ICONS.get(bl_type, "🏆")

                b_link  = f'[{b_icon} {blocked["title"]}]({blocked["web_url"]})'
                bl_link = f'[{bl_icon} {blocker["title"]}]({blocker["web_url"]})'

                if sev_sort == 0:
                    critical += 1

                md.append(
                    f"| {sev_label} | ⛔ {b_link} | {b_art['name']} "
                    f"| 🔒 {bl_link} | {bl_art['name']} | {piid} |"
                )

            md.append("")

            # Group by ART pair for coordination view
            pair_deps: defaultdict = defaultdict(list)
            for dep in deps:
                key = (dep["blocked_art"]["name"], dep["blocker_art"]["name"])
                pair_deps[key].append(dep)

            if len(pair_deps) > 1 or (len(pair_deps) == 1 and list(pair_deps.values())[0]):
                md.append("## ART Dependency Map")
                md.append("")
                md.append("Summary of which ARTs are blocking which:")
                md.append("")
                md.append("| Blocked ART | ← Blocked by | Blocker ART | Count |")
                md.append("|-------------|--------------|-------------|-------|")
                for (b_art_name, bl_art_name), pair_list in sorted(pair_deps.items(), key=lambda x: -len(x[1])):
                    md.append(f"| {b_art_name} | ⛔←🔒 | {bl_art_name} | {len(pair_list)} |")
                md.append("")

        md.extend([
            "---",
            "## Legend",
            "| Icon | Meaning |",
            "|------|---------|",
            "| 🔴 Critical | Blocked item is in the **current PI** — active risk requiring immediate coordination |",
            "| 🟡 Watch    | Blocked item is in a **future PI** — dependency to monitor and plan around |",
            "| ⚫ Past     | Blocked item was in a **past PI** — dependency may be stale or already resolved |",
            "| ⛔ | The blocked epic (the one that cannot proceed) |",
            "| 🔒 | The blocker epic (the one causing the block) |",
            "",
        ])

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], wiki_url, len(deps), critical)

    def generate_portfolio_health_dashboard(self):
        """Tier 1 executive pulse — single wiki page with per-VS traffic-light status."""
        root_group = self._rd_root_obj
        print(f"Generating Portfolio Health Dashboard for: {root_group.full_path}")

        today = date.today()

        # ── Identify current PI ──────────────────────────────────────────── #
        current_pi = None
        for piid in self._rd_piid_labels:
            pct = self._pct_through_pi(piid)
            if pct is not None and 0 < pct < 100:
                current_pi = piid
                break
        if current_pi is None:
            past_pis = [p for p in self._rd_piid_labels if self._pct_through_pi(p) == 100]
            if past_pis:
                current_pi = max(
                    past_pis,
                    key=lambda p: self._pi_dates_from_label(p)[1] or date.min
                )
        pct_pi             = self._pct_through_pi(current_pi) or 0
        pi_start, pi_end   = self._pi_dates_from_label(current_pi) if current_pi else (None, None)

        # ── Traffic-light helpers ────────────────────────────────────────── #
        def _tl_schedule(pct_done, pct_through):
            if not pct_through:
                return "⬜", "—"
            gap = pct_through - pct_done
            if gap <= 10:
                return "🟢", f"{pct_done}% done, {pct_through}% elapsed"
            if gap <= 20:
                return "🟡", f"{pct_done}% done, {pct_through}% elapsed ({gap}pp behind)"
            return "🔴", f"{pct_done}% done, {pct_through}% elapsed ({gap}pp behind)"

        def _tl_capacity(actual, planned):
            if not planned:
                return "⬜", "—"
            ratio = actual / planned * 100
            if 80 <= ratio <= 110:
                return "🟢", f"{ratio:.0f}% load"
            if 70 <= ratio <= 120:
                return "🟡", f"{ratio:.0f}% load"
            return "🔴", f"{ratio:.0f}% load"

        def _tl_risk(risk_labels_present):
            high   = [l for l in risk_labels_present if "high"   in l.lower()]
            medium = [l for l in risk_labels_present if "medium" in l.lower()]
            if high:
                return "🔴", f"{len(high)} high-risk epic(s)"
            if medium:
                return "🟡", f"{len(medium)} medium-risk epic(s)"
            if risk_labels_present:
                return "🟢", f"{len(risk_labels_present)} low-risk"
            return "🟢", "No risk labels"

        def _tl_blocking(blocked_count):
            if blocked_count == 0:
                return "🟢", "No blocks"
            if blocked_count <= 2:
                return "🟡", f"{blocked_count} blocked"
            return "🔴", f"{blocked_count} blocked"

        def _worst(*lights):
            order = {"🔴": 0, "🟡": 1, "🟢": 2, "⬜": 3}
            return min(lights, key=lambda l: order.get(l, 3))

        # ── Per-VS lookup helpers ────────────────────────────────────────── #
        def _all_descendant_ids(parent_id):
            ids = {parent_id}
            for child in self._rd_groups_by_parent.get(parent_id, []):
                ids |= _all_descendant_ids(child["id"])
            return ids

        blocked_counts: dict = {}
        for rel in self._rd_blocking.get("relationships", []):
            eid = rel["blocked_epic"].get("id_int") or rel["blocked_epic"].get("id")
            if eid:
                blocked_counts[eid] = len(rel.get("blocked_by", []))

        risk_label_set = set(self._rd_risk_labels)

        # ── Per-VS stats ─────────────────────────────────────────────────── #
        vs_rows = []
        portfolio_epics_total   = 0
        portfolio_blocked_total = 0
        portfolio_risk_epics    = 0
        portfolio_unassigned    = 0

        for vs_group in self._iter_vs_groups():
            vs_ids = _all_descendant_ids(vs_group["id"])

            # Typed epics only — used for schedule/capacity (need pct_complete/weights)
            pi_epics = [
                e for tier in self._rd_metrics.values()
                for e in tier
                if e.get("group_id") in vs_ids and e.get("piid") == current_pi
            ]
            all_vs_epics = [
                e for tier in self._rd_metrics.values()
                for e in tier
                if e.get("group_id") in vs_ids
            ]
            # All epics (typed + untyped) — used for risk and unassigned counts
            all_vs_epics_raw = [
                e for e in self._rd_epics_all
                if e.get("group_id") in vs_ids
            ]

            if pi_epics:
                planned_w_vs = sum(e["planned_weight"] for e in pi_epics)
                if planned_w_vs:
                    pct_done_vs = round(
                        sum(e["planned_weight"] * e["pct_complete"] for e in pi_epics) / planned_w_vs
                    )
                else:
                    pct_done_vs = round(sum(e["pct_complete"] for e in pi_epics) / len(pi_epics))
            else:
                pct_done_vs  = 0
                planned_w_vs = 0

            tl_sched, sched_detail = _tl_schedule(pct_done_vs, pct_pi)

            actual_w  = sum(e["actual_weight"]  for e in pi_epics)
            planned_w = sum(e["planned_weight"] for e in pi_epics)
            tl_cap, cap_detail = _tl_capacity(actual_w, planned_w)

            risk_labels_found = [
                lbl for e in all_vs_epics_raw for lbl in e.get("labels", [])
                if lbl in risk_label_set
            ]
            tl_risk, risk_detail = _tl_risk(risk_labels_found)

            vs_epic_ids = {e["id"] for e in (pi_epics if pi_epics else all_vs_epics_raw)}
            vs_blocked  = sum(1 for eid in vs_epic_ids if blocked_counts.get(eid, 0) > 0)
            tl_block, block_detail = _tl_blocking(vs_blocked)

            overall     = _worst(tl_sched, tl_cap, tl_risk, tl_block)
            unassigned_vs = sum(
                1 for e in all_vs_epics_raw
                if not any(l.startswith("PIID::") for l in e.get("labels", []))
            )
            risk_epic_count = len({e["id"] for e in all_vs_epics_raw
                                   for lbl in e.get("labels", []) if lbl in risk_label_set})

            vs_rows.append({
                "vs":          vs_group,
                "overall":     overall,
                "tl_sched":    tl_sched,   "sched_detail":  sched_detail,
                "tl_cap":      tl_cap,     "cap_detail":    cap_detail,
                "tl_risk":     tl_risk,    "risk_detail":   risk_detail,
                "tl_block":    tl_block,   "block_detail":  block_detail,
                "epics_total": len(all_vs_epics),
                "pi_epics":    len(pi_epics),
                "blocked":     vs_blocked,
                "unassigned":  unassigned_vs,
            })

            portfolio_epics_total   += len(all_vs_epics)
            portfolio_blocked_total += vs_blocked
            portfolio_risk_epics    += risk_epic_count
            portfolio_unassigned    += unassigned_vs

        # ── Portfolio-level risk count (all epics, all groups including root) ── #
        portfolio_risk_epics = len({
            e["id"] for e in self._rd_epics_all
            for lbl in e.get("labels", []) if lbl in risk_label_set
        })

        # ── Portfolio-level current PI progress ─────────────────────────── #
        all_pi_epics = [
            e for tier in self._rd_metrics.values()
            for e in tier
            if e.get("piid") == current_pi
        ]
        if all_pi_epics:
            planned_t = sum(e["planned_weight"] for e in all_pi_epics)
            if planned_t:
                port_pct_done = round(
                    sum(e["planned_weight"] * e["pct_complete"] for e in all_pi_epics) / planned_t
                )
            else:
                port_pct_done = round(sum(e["pct_complete"] for e in all_pi_epics) / len(all_pi_epics))
        else:
            port_pct_done = 0
        port_tl_sched, _ = _tl_schedule(port_pct_done, pct_pi)

        # ── Needs Attention ─────────────────────────────────────────────── #
        top_blocked = sorted(
            self._rd_blocking.get("relationships", []),
            key=lambda r: -len(r.get("blocked_by", []))
        )[:5]

        at_risk_epics = sorted(
            [e for e in all_pi_epics if pct_pi - e.get("pct_complete", 0) > 20],
            key=lambda e: -(pct_pi - e.get("pct_complete", 0))
        )[:5]

        # ── Render ───────────────────────────────────────────────────────── #
        pi_label   = current_pi or "—"
        pi_elapsed = f"{pct_pi}% elapsed" if pct_pi else "Not started"
        if pi_start and pi_end:
            pi_range = f"{pi_start.strftime('%d %b %Y')} – {pi_end.strftime('%d %b %Y')}"
        else:
            pi_range = "—"

        md = []
        md.append(f"# Portfolio Health Dashboard — {root_group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{root_group.name}]({root_group.web_url})"
        )
        md.append("")
        md.append(
            f"**Current PI:** {pi_label}  |  "
            f"**PI Period:** {pi_range}  |  "
            f"**PI Elapsed:** {pi_elapsed}"
        )
        md.append("")

        # ── Work Items deep links ─────────────────────────────────────────── #
        from urllib.parse import quote as _pquote

        def _wi(params):
            parts = [f"{_pquote(k, safe='')}={_pquote(v, safe='')}" for k, v in params]
            return f"{root_group.web_url}/-/work_items?{'&'.join(parts)}"

        _wi_all   = _wi([("state", "all"),    ("type[]", "epic")])
        _wi_pi    = (
            _wi([("state", "opened"), ("type[]", "epic"), ("label_name[]", current_pi)])
            if current_pi else _wi_all
        )
        # TODO: link Blocked Epics metric to the consolidated Blocking & Cross-ART Risk
        # report wiki page once the Tier 2 blocking report consolidation is complete.
        _risk_p  = [("state", "opened"), ("type[]", "epic")] + [
            ("or[label_name][]", lbl) for lbl in self._rd_risk_labels
        ]
        _wi_risk  = _wi(_risk_p) if self._rd_risk_labels else _wi_all
        _wi_unasn = _wi([("state", "opened"), ("type[]", "epic")])

        md.append("## Portfolio Summary")
        md.append("")
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Total Epics (all PIs) | [{portfolio_epics_total}]({_wi_all}) |")
        md.append(f"| Epics in Current PI | [{len(all_pi_epics)}]({_wi_pi}) |")
        md.append(
            f"| Current PI Progress | [{port_pct_done}% done]({_wi_pi})  "
            f"({pct_pi}% elapsed) {port_tl_sched} |"
        )
        md.append(f"| Blocked Epics (current PI) | [{portfolio_blocked_total}]({_wi_pi}) |")
        md.append(f"| Risk-Flagged Epics (any level) | [{portfolio_risk_epics}]({_wi_risk}) |")
        md.append(f"| Unassigned to PI | [{portfolio_unassigned}]({_wi_unasn}) |")
        md.append("")

        md.append("## Value Stream Status")
        md.append("")
        md.append(
            "> **Traffic light thresholds:**  "
            "Schedule — 🟢 ≤10pp behind · 🟡 ≤20pp · 🔴 >20pp  |  "
            "Capacity — 🟢 80–110% loaded · 🟡 70–120% · 🔴 outside  |  "
            "Risk — 🟢 none · 🟡 medium/low only · 🔴 any high  |  "
            "Blocking — 🟢 0 · 🟡 1–2 · 🔴 3+"
        )
        md.append("")
        md.append("| Value Stream | Status | Schedule | Capacity | Risk | Blocking | Epics | Unassigned |")
        md.append("|---|---|---|---|---|---|---|---|")

        for row in vs_rows:
            vs      = row["vs"]
            vs_link = f"[{vs['name']}]({vs['web_url']})"
            md.append(
                f"| {vs_link} "
                f"| {row['overall']} "
                f"| {row['tl_sched']} {row['sched_detail']} "
                f"| {row['tl_cap']} {row['cap_detail']} "
                f"| {row['tl_risk']} {row['risk_detail']} "
                f"| {row['tl_block']} {row['block_detail']} "
                f"| {row['pi_epics']} in PI / {row['epics_total']} total "
                f"| {row['unassigned']} |"
            )

        md.append("")
        md.append("## Needs Attention")
        md.append("")

        md.append("### ⛔ Blocked Epics")
        md.append("")
        if top_blocked:
            md.append("| Epic | Type | Blockers | PI |")
            md.append("|------|------|---------|-----|")
            for rel in top_blocked:
                epic   = rel["blocked_epic"]
                etype  = epic.get("type", "—")
                icon   = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                link   = (
                    f'[{icon} {epic["title"]}]({epic["web_url"]})'
                    if epic.get("web_url") else f'{icon} {epic["title"]}'
                )
                n_blk  = len(rel.get("blocked_by", []))
                e_meta = self._rd_epics_by_id.get(
                    epic.get("id_int") or epic.get("id"), {}
                )
                piid   = e_meta.get("piid") or "—"
                md.append(f"| {link} | {etype} | {n_blk} | {piid} |")
        else:
            md.append("✅ No blocked epics found.")
        md.append("")

        md.append("### 🟡 At-Risk Epics (behind schedule)")
        md.append("")
        if at_risk_epics:
            md.append("| Epic | Type | Done | PI Elapsed | Gap | PI |")
            md.append("|------|------|------|-----------|-----|-----|")
            for e in at_risk_epics:
                etype = e.get("type", "—")
                icon  = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                link  = (
                    f'[{icon} {e["title"]}]({e["web_url"]})'
                    if e.get("web_url") else f'{icon} {e["title"]}'
                )
                gap = pct_pi - e.get("pct_complete", 0)
                md.append(
                    f"| {link} | {etype} | {e.get('pct_complete', 0)}% "
                    f"| {pct_pi}% | {gap}pp | {e.get('piid', '—')} |"
                )
        else:
            md.append("✅ No epics significantly behind schedule.")
        md.append("")

        md.extend([
            "---",
            "## Legend",
            "",
            "| Icon | Meaning |",
            "|------|---------|",
            "| 🟢 | On track — within threshold |",
            "| 🟡 | Watch — approaching threshold |",
            "| 🔴 | At risk — threshold exceeded |",
            "| ⬜ | No data |",
            "| ⛔ | Blocked epic |",
            "",
            "**Schedule** — % complete vs % of PI calendar elapsed  ",
            "**Capacity** — actual story-point load vs planned load for current PI  ",
            "**Risk** — presence of `risk::high` / `risk::medium` / `risk::low` labels  ",
            "**Blocking** — count of epics with at least one blocker in current PI  ",
            "",
        ])

        page_title = f"{self._wiki_t1}/Portfolio Health Dashboard"
        self.upload_to_wiki(root_group, page_title, "\n".join(md))
        print(f"  → Wiki: {page_title}")

    # ------------------------------------------------------------------
    # Epic Lifecycle / Portfolio Kanban
    # ------------------------------------------------------------------

    def generate_epic_lifecycle_report(self):
        """Epic Lifecycle / Portfolio Kanban — epics by SAFe lifecycle state."""
        group = self._rd_root_obj
        today = date.today()
        gn    = group.name
        print(f"  Generating Epic Lifecycle / Portfolio Kanban for {gn}...")

        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]

        STATES = [
            ("lifecycle::funnel",       "💡 Funnel",             "Ideas submitted, not yet analyzed"),
            ("lifecycle::analyzing",    "🔍 Analyzing",          "Lean Business Case in development"),
            ("lifecycle::backlog",      "📋 Portfolio Backlog",  "Approved, awaiting capacity"),
            ("lifecycle::implementing", "⚙️ Implementing",       "Active in a Program Increment"),
            ("lifecycle::done",         "✅ Done",               "Delivered"),
        ]
        STATE_KEYS = {s[0] for s in STATES}

        STUCK_THRESHOLDS = {
            "lifecycle::funnel":    90,   # days before flagged
            "lifecycle::analyzing": 30,
            "lifecycle::backlog":   60,
        }

        def _age_days(epic):
            raw = epic.get("created_at")
            if not raw:
                return None
            try:
                c = date.fromisoformat(str(raw)[:10])
                return (today - c).days
            except ValueError:
                return None

        def _group_name(epic):
            gid = epic.get("group_id")
            if gid and hasattr(self, '_rd_groups_by_id'):
                g = self._rd_groups_by_id.get(gid)
                return g["name"] if g else "—"
            return "—"

        def _pi(epic):
            return epic.get("piid") or "—"

        # Partition epics by lifecycle state
        buckets = {key: [] for key, _, _ in STATES}
        buckets["_unlabelled"] = []
        for epic in all_typed:
            labels  = set(epic.get("labels", []))
            matched = labels & STATE_KEYS
            if not matched:
                buckets["_unlabelled"].append(epic)
            else:
                # If multiple lifecycle labels, pick the first in state order
                for key, _, _ in STATES:
                    if key in matched:
                        buckets[key].append(epic)
                        break

        # ── build page ───────────────────────────────────────────────── #
        md = []
        md.append(f"# Epic Lifecycle / Portfolio Kanban — {gn}")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{gn}]({group.web_url})"
        )
        md.append("")
        md.append(
            "> The SAFe Portfolio Kanban tracks where epics are in their approval-to-delivery "
            "lifecycle. Use this report to identify bottlenecks in the funding and approval "
            "pipeline — not just delivery progress. Epics stuck in **Analyzing** or "
            "**Portfolio Backlog** signal decision-making delays that block downstream delivery."
        )
        md.append("")
        md.append("---")

        # ── Summary table ─────────────────────────────────────────────── #
        md.append("## Portfolio Kanban — Current State")
        md.append("")

        def _avg_age(epics):
            ages = [_age_days(e) for e in epics]
            ages = [a for a in ages if a is not None]
            return round(sum(ages) / len(ages)) if ages else None

        def _max_age(epics):
            ages = [_age_days(e) for e in epics]
            ages = [a for a in ages if a is not None]
            return max(ages) if ages else None

        md.append("| State | Count | Avg Age | Oldest | Threshold |")
        md.append("|-------|-------|---------|--------|-----------|")
        for key, label, _ in STATES:
            epics   = buckets[key]
            avg     = _avg_age(epics)
            oldest  = _max_age(epics)
            thresh  = STUCK_THRESHOLDS.get(key)
            t_str   = f"{thresh}d" if thresh else "—"
            avg_str = f"{avg}d" if avg is not None else "—"
            old_str = f"{oldest}d" if oldest is not None else "—"
            warn    = " ⚠️" if (thresh and oldest and oldest > thresh) else ""
            md.append(
                f"| {label} | {len(epics)} | {avg_str} | {old_str}{warn} | {t_str} |"
            )
        unlab = buckets["_unlabelled"]
        avg_u = _avg_age(unlab)
        md.append(
            f"| _(unlabelled)_ | {len(unlab)} | "
            f"{'—' if avg_u is None else str(avg_u)+'d'} | — | — |"
        )
        md.append("")

        no_labels = not self._rd_lifecycle_labels
        if no_labels:
            md.append(
                "> ℹ️ No `lifecycle::` labels found. Apply `lifecycle::funnel`, "
                "`lifecycle::analyzing`, `lifecycle::backlog`, `lifecycle::implementing`, "
                "or `lifecycle::done` labels to epics to enable this view. "
                "Use the `set-lifecycle-labels` utility to assign labels in bulk."
            )
            md.append("")

        md.append("---")

        # ── Stuck items ───────────────────────────────────────────────── #
        stuck_sections = [
            ("lifecycle::analyzing", "🔍 Stuck in Analyzing",
             "Lean Business Case is overdue for a decision. Review and either approve to backlog or cancel."),
            ("lifecycle::backlog",   "📋 Stuck in Portfolio Backlog",
             "Approved work waiting too long for capacity. Consider re-sequencing or rescoping."),
            ("lifecycle::funnel",    "💡 Stale in Funnel",
             "Ideas not yet analyzed beyond the threshold. Either analyze or close."),
        ]

        has_stuck = False
        for key, heading, guidance in stuck_sections:
            thresh = STUCK_THRESHOLDS[key]
            stuck  = [e for e in buckets[key] if (_age_days(e) or 0) > thresh]
            if not stuck:
                continue
            has_stuck = True
            md.append(f"## ⚠️ {heading} (> {thresh} days)")
            md.append("")
            md.append(f"_{guidance}_")
            md.append("")
            md.append("| Epic | Type | Age | PI | Group | Link |")
            md.append("|------|------|-----|----|-------|------|")
            for e in sorted(stuck, key=lambda x: _age_days(x) or 0, reverse=True):
                age = _age_days(e) or 0
                md.append(
                    f"| {e['title'][:50]} | {e.get('type','?')} | **{age}d** "
                    f"| {_pi(e)} | {_group_name(e)} | [→]({e['web_url']}) |"
                )
            md.append("")
            md.append("---")

        if not has_stuck:
            md.append("## ✅ No Stuck Items")
            md.append("")
            md.append("No epics have exceeded their state thresholds. Kanban is flowing.")
            md.append("")
            md.append("---")

        # ── Detail by state ───────────────────────────────────────────── #
        md.append("## Kanban Detail — By State")
        md.append("")

        STATE_ICONS = {
            "lifecycle::funnel":       "💡",
            "lifecycle::analyzing":    "🔍",
            "lifecycle::backlog":      "📋",
            "lifecycle::implementing": "⚙️",
            "lifecycle::done":         "✅",
        }

        for key, label, description in STATES:
            epics = buckets[key]
            md.append(f"### {label}")
            md.append("")
            md.append(f"_{description}_")
            md.append("")
            if not epics:
                md.append("_No epics in this state._")
                md.append("")
                continue
            thresh = STUCK_THRESHOLDS.get(key)
            md.append("| Epic | Type | Age | PI | Group | Link |")
            md.append("|------|------|-----|----|-------|------|")
            for e in sorted(epics, key=lambda x: _age_days(x) or 0, reverse=True):
                age     = _age_days(e)
                age_str = f"**{age}d** ⚠️" if (thresh and age and age > thresh) else (f"{age}d" if age else "—")
                md.append(
                    f"| {e['title'][:50]} | {e.get('type','?')} | {age_str} "
                    f"| {_pi(e)} | {_group_name(e)} | [→]({e['web_url']}) |"
                )
            md.append("")

        if unlab:
            md.append("### _(Unlabelled)_")
            md.append("")
            md.append(
                "_Epics without a `lifecycle::` label. These cannot be placed in the Kanban view. "
                "Apply a lifecycle label or use `set-lifecycle-labels` to assign in bulk._"
            )
            md.append("")
            md.append("| Epic | Type | Age | PI | Group | Link |")
            md.append("|------|------|-----|----|-------|------|")
            for e in sorted(unlab, key=lambda x: _age_days(x) or 0, reverse=True):
                age = _age_days(e)
                md.append(
                    f"| {e['title'][:50]} | {e.get('type','?')} | {age or '—'} "
                    f"| {_pi(e)} | {_group_name(e)} | [→]({e['web_url']}) |"
                )
            md.append("")

        md.append("---")

        # ── About section ─────────────────────────────────────────────── #
        md.append("## ℹ️ SAFe Portfolio Kanban States")
        md.append("")
        md.append("| State | Label | Meaning | Flag if > |")
        md.append("|-------|-------|---------|-----------|")
        for key, label, desc in STATES:
            thresh = STUCK_THRESHOLDS.get(key)
            t_str  = f"{thresh} days" if thresh else "—"
            md.append(f"| {label} | `{key}` | {desc} | {t_str} |")
        md.append("")
        md.append(
            "**Why it matters for DoD programs:** Portfolio Kanban visibility is required "
            "by SAFe 6.0 to manage the flow of Epics from idea to implementation. "
            "For DoD acquisition programs, delays in the Analyzing and Backlog states "
            "often map to contract modification cycles, funding decisions, or requirements "
            "reviews — identifying them early enables proactive stakeholder engagement."
        )
        md.append("")

        page_title = f"{self._wiki_t3}/Epic Lifecycle"
        self.upload_to_wiki(group, page_title, "\n".join(md))
        print(f"  → Wiki: {page_title}")

    # ------------------------------------------------------------------
    # Flow Metrics Report
    # ------------------------------------------------------------------

    def generate_flow_metrics_report(self):
        """Flow Metrics Report — velocity, load, distribution, and cycle time."""
        group = self._rd_root_obj
        today = date.today()
        gn    = group.name
        base  = f"{self.url}/groups/{group.full_path}/-/wikis"
        print(f"  Generating Flow Metrics Report for {gn}...")

        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]
        piids     = self._rd_piid_labels  # chronologically sorted

        # ── helpers ──────────────────────────────────────────────────── #
        def _parse_dt(s):
            if not s:
                return None
            try:
                return date.fromisoformat(str(s)[:10])
            except ValueError:
                return None

        def _age(epic):
            """Days since created_at (open) or approx cycle time (closed)."""
            c = _parse_dt(epic.get("created_at"))
            if not c:
                return None
            if epic.get("state", "").lower() == "closed":
                u = _parse_dt(epic.get("updated_at"))
                return (u - c).days if u else None
            return (today - c).days

        def _avg(vals):
            v = [x for x in vals if x is not None]
            return round(sum(v) / len(v)) if v else None

        def _pct(n, total):
            return f"{round(n / total * 100)}%" if total else "—"

        # ── partition by state ────────────────────────────────────────── #
        open_epics   = [e for e in all_typed if e.get("state", "").lower() != "closed"]
        closed_epics = [e for e in all_typed if e.get("state", "").lower() == "closed"]

        # ── build page ───────────────────────────────────────────────── #
        md = []
        md.append(f"# Flow Metrics — {gn}")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{gn}]({group.web_url})"
        )
        md.append("")
        md.append(
            "> SAFe 6.0 flow metrics measure *how efficiently* work moves through the portfolio, "
            "not just whether it is on schedule. Five of the six metrics are reported here; "
            "Flow Efficiency requires time-tracking data not yet available."
        )
        md.append("")
        md.append("---")

        # ── Section 1: Flow Velocity ──────────────────────────────────── #
        md.append("## 📈 Flow Velocity — Delivered per PI")
        md.append("")
        md.append(
            "Features and Capabilities closed per PI. "
            "Consistent delivery of committed items is the primary ART health signal."
        )
        md.append("")

        feat_types = {"Feature", "Capability"}
        vel_rows = []
        for pi in piids:
            pi_closed = [
                e for e in closed_epics
                if e.get("piid") == pi and e.get("type") in feat_types
            ]
            feat_c = sum(1 for e in pi_closed if e["type"] == "Feature")
            cap_c  = sum(1 for e in pi_closed if e["type"] == "Capability")
            vel_rows.append((pi, feat_c, cap_c, feat_c + cap_c))

        md.append("| PI | Features | Capabilities | Total Delivered |")
        md.append("|----|----------|--------------|-----------------|")
        for pi, f, c, t in vel_rows:
            md.append(f"| `{pi}` | {f} | {c} | **{t}** |")

        total_delivered = sum(r[3] for r in vel_rows)
        if total_delivered == 0:
            md.append("")
            md.append(
                "> ℹ️ No closed epics found — velocity will populate as PIs complete. "
                "Use `simulate-pi-progress` and `close-percent` tools to generate demo data."
            )
        md.append("")
        md.append("---")

        # ── Section 2: Flow Load (WIP) ────────────────────────────────── #
        md.append("## 📦 Flow Load — Work in Progress")
        md.append("")
        md.append(
            "Open epics by PI. High WIP signals overloaded PIs and increases "
            "the risk of context-switching and delayed delivery."
        )
        md.append("")

        md.append("| PI | Features | Capabilities | Epics | Total | Planned Weight |")
        md.append("|----|----------|--------------|-------|-------|----------------|")
        no_pi_open = [e for e in open_epics if not e.get("piid")]
        for pi in piids:
            pi_open = [e for e in open_epics if e.get("piid") == pi]
            f   = sum(1 for e in pi_open if e["type"] == "Feature")
            c   = sum(1 for e in pi_open if e["type"] == "Capability")
            ep  = sum(1 for e in pi_open if e["type"] == "Epic")
            pw  = sum(e.get("planned_weight") or 0 for e in pi_open)
            md.append(f"| `{pi}` | {f} | {c} | {ep} | **{f+c+ep}** | {pw:,} |")
        if no_pi_open:
            f   = sum(1 for e in no_pi_open if e["type"] == "Feature")
            c   = sum(1 for e in no_pi_open if e["type"] == "Capability")
            ep  = sum(1 for e in no_pi_open if e["type"] == "Epic")
            pw  = sum(e.get("planned_weight") or 0 for e in no_pi_open)
            md.append(f"| _(no PI)_ | {f} | {c} | {ep} | **{f+c+ep}** | {pw:,} |")
        md.append("")
        md.append("---")

        # ── Section 3: Flow Distribution ──────────────────────────────── #
        md.append("## 🔀 Flow Distribution — Work Type Mix")
        md.append("")

        # 3a: by SAFe hierarchy level (always available)
        md.append("### By SAFe Hierarchy Level")
        md.append("")
        total_epics = len(all_typed)
        total_pw    = sum(e.get("planned_weight") or 0 for e in all_typed)
        md.append("| Type | Count | % Items | Planned Weight | % Weight |")
        md.append("|------|-------|---------|----------------|----------|")
        for t in ("Feature", "Capability", "Epic"):
            bucket = self._rd_metrics.get(t, [])
            pw     = sum(e.get("planned_weight") or 0 for e in bucket)
            md.append(
                f"| {t} | {len(bucket)} | {_pct(len(bucket), total_epics)} "
                f"| {pw:,} | {_pct(pw, total_pw)} |"
            )
        md.append(f"| **Total** | **{total_epics}** | | **{total_pw:,}** | |")
        md.append("")

        # 3b: by work type label (type::*)
        md.append("### By Work Type Label")
        md.append("")
        work_type_set = set(self._rd_work_type_labels)
        if work_type_set:
            wt_counts = {}
            for lbl in sorted(work_type_set):
                wt_counts[lbl] = [e for e in all_typed if lbl in e.get("labels", [])]

            labeled   = [e for e in all_typed if set(e.get("labels", [])) & work_type_set]
            unlabeled = len(all_typed) - len(labeled)

            md.append("| Work Type | Count | % of Labelled | SAFe Target |")
            md.append("|-----------|-------|---------------|-------------|")
            targets = {
                "type::feature":        "~50%",
                "type::enabler":        "~30%",
                "type::infrastructure": "~20%",
                "type::defect":         "minimize",
            }
            n_lab = len(labeled) or 1
            for lbl, epics in sorted(wt_counts.items()):
                tgt = targets.get(lbl, "—")
                md.append(f"| `{lbl}` | {len(epics)} | {_pct(len(epics), n_lab)} | {tgt} |")
            if unlabeled:
                md.append(f"| _(unlabelled)_ | {unlabeled} | — | — |")
        else:
            md.append(
                "> ℹ️ No `type::` labels found. Apply `type::feature`, `type::enabler`, "
                "`type::infrastructure`, or `type::defect` labels to epics to enable this view. "
                "Use the `set-work-type-labels` utility to assign labels in bulk."
            )
            md.append("")
            md.append("**SAFe 6.0 target distribution:**")
            md.append("")
            md.append("| Work Type | Target | Risk if Skewed |")
            md.append("|-----------|--------|----------------|")
            md.append("| Features (business value) | ~50% | Under-delivery of outcomes |")
            md.append("| Enablers (tech / architecture) | ~30% | Accumulating technical debt |")
            md.append("| Infrastructure / DevSecOps | ~20% | Platform stability erosion |")
            md.append("| Defects | minimize | Quality signal; high % = systemic issues |")
        md.append("")
        md.append("---")

        # ── Section 4: Flow Time (Cycle Time) ────────────────────────── #
        md.append("## ⏱ Flow Time — Cycle Time Analysis")
        md.append("")
        md.append(
            "How long epics spend in-flight. Shorter, more consistent cycle times "
            "indicate a healthy flow system."
        )
        md.append("")

        md.append("### Age of Open Epics (days since created)")
        md.append("")
        md.append("| Type | Count | Avg Age | Min | Max |")
        md.append("|------|-------|---------|-----|-----|")
        has_open_data = False
        for t in ("Feature", "Capability", "Epic"):
            bucket = [e for e in open_epics if e.get("type") == t]
            ages   = [_age(e) for e in bucket]
            ages   = [a for a in ages if a is not None]
            if ages:
                has_open_data = True
                md.append(
                    f"| {t} | {len(bucket)} | {_avg(ages)} days "
                    f"| {min(ages)} | {max(ages)} |"
                )
            elif bucket:
                md.append(f"| {t} | {len(bucket)} | — | — | — |")
        if not has_open_data:
            md.append("| — | — | — | — | — |")
        md.append("")

        if closed_epics:
            md.append(
                "### Cycle Time — Closed Epics "
                "_(updated\\_at used as close\\_date proxy)_"
            )
            md.append("")
            md.append("| Type | Count | Avg Cycle Time | Min | Max |")
            md.append("|------|-------|----------------|-----|-----|")
            for t in ("Feature", "Capability", "Epic"):
                bucket = [e for e in closed_epics if e.get("type") == t]
                times  = [_age(e) for e in bucket]
                times  = [a for a in times if a is not None]
                if times:
                    md.append(
                        f"| {t} | {len(bucket)} | {_avg(times)} days "
                        f"| {min(times)} | {max(times)} |"
                    )
                elif bucket:
                    md.append(f"| {t} | {len(bucket)} | — | — | — |")
            md.append("")
        else:
            md.append(
                "> ℹ️ No closed epics — cycle time will populate as work completes."
            )
            md.append("")

        md.append("---")

        # ── Section 5: Flow Predictability ───────────────────────────── #
        md.append("## 🎯 Flow Predictability")
        md.append("")
        md.append(
            "Percentage of PI objectives met as committed. "
            "SAFe guidance: 80–100% is the healthy range. "
            "Consistently at 100% may indicate sandbagging."
        )
        md.append("")
        scorecard_slug = _wiki_slug(f"{self._wiki_t2}/PI Predictability Scorecard")
        md.append(
            f"Full predictability trend by ART → "
            f"[PI Predictability Scorecard]({base}/{scorecard_slug})"
        )
        md.append("")

        # Summary row from snapshot data
        pi_pred_rows = []
        for pi in piids:
            pi_epics = [
                e for e in all_typed
                if e.get("piid") == pi and e.get("type") in feat_types
            ]
            if not pi_epics:
                continue
            committed = len(pi_epics)
            delivered = sum(1 for e in pi_epics if e.get("state", "").lower() == "closed")
            pct       = round(delivered / committed * 100) if committed else 0
            pi_pred_rows.append((pi, committed, delivered, pct))

        if pi_pred_rows:
            md.append("| PI | Committed | Delivered | Predictability |")
            md.append("|----|-----------|-----------|----------------|")
            for pi, com, dlv, pct in pi_pred_rows:
                icon = "🟢" if pct >= 80 else ("🟡" if pct >= 60 else "🔴")
                md.append(f"| `{pi}` | {com} | {dlv} | {icon} {pct}% |")
            md.append("")

        md.append("---")

        # ── About section ─────────────────────────────────────────────── #
        md.append("## ℹ️ About Flow Metrics")
        md.append("")
        md.append("SAFe 6.0 defines six flow metrics measured at Team, ART, and Portfolio level:")
        md.append("")
        md.append("| Metric | This Report | Status |")
        md.append("|--------|-------------|--------|")
        md.append("| Flow Velocity | Delivered epics per PI | ✅ |")
        md.append("| Flow Load | Open epics per PI (WIP) | ✅ |")
        md.append("| Flow Distribution | Work type mix | ✅ |")
        md.append("| Flow Time | Cycle time (open age + closed proxy) | ✅ |")
        md.append("| Flow Predictability | % PI objectives met | ✅ (link to Scorecard) |")
        md.append("| Flow Efficiency | Value-added vs wait time | ⬜ Requires time tracking |")
        md.append("")

        page_title = f"{self._wiki_t3}/Flow Metrics"
        self.upload_to_wiki(group, page_title, "\n".join(md))
        print(f"  → Wiki: {page_title}")

    # ------------------------------------------------------------------
    # WSJF Priority Board
    # ------------------------------------------------------------------

    def generate_wsjf_priority_board(self):
        """WSJF Priority Board — portfolio backlog epics ranked by Weighted Shortest Job First score."""
        group = self._rd_root_obj
        today = date.today()
        print(f"  Generating WSJF Priority Board for {group.name}...")

        def _label_val(labels, prefix):
            for lbl in labels:
                if lbl.startswith(prefix):
                    try:
                        return int(lbl.split("::")[-1])
                    except ValueError:
                        pass
            return None

        # Scan all typed epics — only these have computed planned_weight
        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]

        candidates = []
        for epic in all_typed:
            if epic.get("state", "").lower() != "opened":
                continue
            labels  = epic.get("labels", [])
            value   = _label_val(labels, "wsjf-value::")
            urgency = _label_val(labels, "wsjf-urgency::")
            risk    = _label_val(labels, "wsjf-risk::")
            if value is None and urgency is None and risk is None:
                continue
            size  = epic.get("planned_weight") or None  # None → partial score
            v, u, r = (value or 0), (urgency or 0), (risk or 0)
            score = round((v + u + r) / size, 2) if size else None
            candidates.append({
                "epic":    epic,
                "type":    epic.get("type", "Unknown"),
                "value":   value,
                "urgency": urgency,
                "risk":    risk,
                "size":    size,
                "score":   score,
                "piid":    epic.get("piid"),
            })

        # Fully scored first (highest → lowest), then partial, then no-size
        candidates.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))

        md = []
        md.append(f"# WSJF Priority Board — {group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{group.name}]({group.web_url})"
        )
        md.append("")
        md.append(
            "Weighted Shortest Job First (WSJF) ranks portfolio backlog items by the ratio of "
            "Cost of Delay to Job Size. Higher score = should be sequenced first."
        )
        md.append("")

        if not candidates:
            md.append(
                "_No WSJF-scored epics found. Apply `wsjf-value::N`, `wsjf-urgency::N`, and "
                "`wsjf-risk::N` labels (Fibonacci scale: 1, 2, 3, 5, 8, 13) to open epics._"
            )
        else:
            scored    = [c for c in candidates if c["score"] is not None]
            partial   = [c for c in candidates if c["score"] is None]
            backlog   = [c for c in candidates if not c["piid"]]
            in_flight = [c for c in candidates if c["piid"]]

            md.append("## Summary")
            md.append("")
            md.append("| | Count |")
            md.append("|---|---|")
            md.append(f"| Fully scored | {len(scored)} |")
            md.append(f"| Partially scored (missing component or job size) | {len(partial)} |")
            md.append(f"| Portfolio Backlog (no PI) | {len(backlog)} |")
            md.append(f"| In-flight (PI assigned) | {len(in_flight)} |")
            md.append("")

            md.append("## Ranked Board")
            md.append("")
            md.append("| Rank | Epic | Type | PI | Value | Urgency | Risk | Size | WSJF |")
            md.append("|------|------|------|----|-------|---------|------|------|------|")

            for rank, c in enumerate(candidates, 1):
                epic   = c["epic"]
                icon   = self.EPIC_TYPE_ICONS.get(c["type"], "🏆")
                link   = f"[{epic['title']}]({epic['web_url']})"
                piid   = c["piid"] or "_backlog_"
                v_str  = str(c["value"])   if c["value"]   is not None else "—"
                u_str  = str(c["urgency"]) if c["urgency"] is not None else "—"
                r_str  = str(c["risk"])    if c["risk"]    is not None else "—"
                s_str  = str(c["size"])    if c["size"]    is not None else "—"
                sc_str = f"**{c['score']}**" if c["score"] is not None else "_partial_"
                md.append(
                    f"| {rank} | {link} | {icon} {c['type']} | {piid} "
                    f"| {v_str} | {u_str} | {r_str} | {s_str} | {sc_str} |"
                )

            md.append("")

        md.extend([
            "---",
            "## How WSJF Works",
            "",
            "**WSJF = (User/Business Value + Time Criticality + Risk Reduction) ÷ Job Size**",
            "",
            "| Component | Label | What it measures |",
            "|-----------|-------|-----------------|",
            "| User/Business Value | `wsjf-value::N` | Economic benefit of delivering this work |",
            "| Time Criticality | `wsjf-urgency::N` | Cost of delay — how fast does value decay? |",
            "| Risk Reduction | `wsjf-risk::N` | Risk reduced or opportunity enabled by this work |",
            "| Job Size | Epic planned weight | Relative effort (set the epic's weight field) |",
            "",
            "**Fibonacci scale:** 1 · 2 · 3 · 5 · 8 · 13  _(higher = more)_",
            "",
            "A score of 8.0 means the item delivers 8× more value per unit of effort than a score-1 item.",
            "",
            "> **Calibration signal:** Scores should spread across the range. If most items cluster "
            "at 13/13/13 the scale has lost meaning — challenge the team to differentiate.",
            "",
            "### Scoring Status",
            "| Status | Condition |",
            "|--------|-----------|",
            "| **N.NN** (bold score) | All three label components present and job size > 0 |",
            "| _partial_ | One or more label components missing, or job size not set |",
            "",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/WSJF Priority Board", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/WSJF Priority Board")

    # ------------------------------------------------------------------
    # Wiki Index
    # ------------------------------------------------------------------

    def generate_wiki_index(self):
        group = self._rd_root_obj
        today = date.today()
        gn    = group.name
        base  = f"{self.url}/groups/{group.full_path}/-/wikis"

        def _wl(page_title, display=None):
            return f"[{display or page_title}]({base}/{_wiki_slug(page_title)})"

        md = []
        md.append(f"# {gn} — Portfolio Home")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** [{gn}]({group.web_url})"
        )
        md.append("")
        md.append("---")
        md.append("")

        # ── Tier 1 ──────────────────────────────────────────────────────── #
        md.append("## 📊 Executive Pulse")
        md.append("")
        md.append("_One page. Viewed daily. Read in 90 seconds._")
        md.append("")
        md.append("| Report | Description |")
        md.append("|--------|-------------|")
        md.append(
            f"| {_wl(f'{self._wiki_t1}/Portfolio Health Dashboard', 'Portfolio Health Dashboard')} "
            f"| Traffic-light status per Value Stream — Schedule, Capacity, Risk, Blocking |"
        )
        md.append("")

        # ── Tier 2 ──────────────────────────────────────────────────────── #
        md.append("## 🗂️ Program Management")
        md.append("")
        md.append("_Reviewed in weekly ART syncs and PM stand-ups._")
        md.append("")
        md.append("| Report | Description |")
        md.append("|--------|-------------|")
        md.append(
            f"| {_wl(f'{self._wiki_t2}/Program × PI Matrix', 'Program × PI Matrix')} "
            f"| Project label vs PI quarter cross-tab with status and weights |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/Program PI Detail', 'Program PI Detail')} "
            f"| Per-PI section view of program workload and status |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/PI Predictability Scorecard', 'PI Predictability Scorecard')} "
            f"| % of committed Features and Capabilities delivered per PI, trended by ART |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/Risk Register', 'Risk Register')} "
            f"| All risk-flagged epics grouped by level (High → Medium → Low) with PI and owning ART |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/ART Capacity Balance', 'ART Capacity Balance')} "
            f"| Per-team planned vs actual weight per PI *(index → VS → ART)* |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/Blocking & Cross-ART Risk', 'Blocking & Cross-ART Risk')} "
            f"| Blocked epics, ancestor risk propagation, and cross-ART dependencies per VS *(index → VS)* |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t2}/WSJF Priority Board', 'WSJF Priority Board')} "
            f"| Portfolio backlog epics ranked by (Value + Urgency + Risk) ÷ Job Size |"
        )
        md.append("")

        # ── Tier 3 ──────────────────────────────────────────────────────── #
        md.append("## 🔍 Operational Detail")
        md.append("")
        md.append("_Drill-down from Tier 2. Available on demand._")
        md.append("")
        md.append("| Report | Description |")
        md.append("|--------|-------------|")
        md.append(
            f"| {_wl(f'{self._wiki_t3}/ART Feature Status', 'ART Feature Status')} "
            f"| Features per ART grouped by Team with completion and risk *(index → VS → ART)* |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/VS Capability Dashboard', 'VS Capability Dashboard')} "
            f"| Capabilities by PI with per-ART breakdown *(index → VS)* |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/Team Backlogs', 'Team Backlogs')} "
            f"| Issues grouped by Feature per Team *(index; detail pages on each team wiki)* |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/SAFe Portfolio Hierarchy', 'SAFe Portfolio Hierarchy')} "
            f"| Collapsible Epic → Capability/Feature hierarchy with % complete and PI progress |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/ART-Team Workload', 'ART-Team Workload')} "
            f"| Per-PI planned vs actual weight per group with on-track / at-risk flags |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/Flow Metrics', 'Flow Metrics')} "
            f"| Velocity, WIP load, work type distribution, and cycle time across the portfolio |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t3}/Epic Lifecycle', 'Epic Lifecycle / Portfolio Kanban')} "
            f"| Epics by SAFe lifecycle state with bottleneck detection and age analysis |"
        )
        md.append("")

        # ── Tier 4 ──────────────────────────────────────────────────────── #
        md.append("## 🔧 Data Quality")
        md.append("")
        md.append("_Maintenance views — labeling and setup problems, not delivery status._")
        md.append("")
        md.append("| Report | Description |")
        md.append("|--------|-------------|")
        md.append(
            f"| {_wl(f'{self._wiki_t4}/Unassigned PI', 'Unassigned PI')} "
            f"| Epics with no `PIID::` label, broken down by type |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t4}/Orphaned Epics', 'Orphaned Epics')} "
            f"| Epics with no parent and no children (disconnected from hierarchy) |"
        )
        md.append(
            f"| {_wl(f'{self._wiki_t4}/Orphaned Issues', 'Orphaned Issues')} "
            f"| Issues not linked to any epic, grouped by project |"
        )
        md.append("")

        self.upload_to_wiki(group, "home", "\n".join(md))
        print(f"  ↳ Wiki home page updated for {gn}")

        home_url  = f"{self.url}/groups/{group.full_path}/-/wikis/home"
        _back     = f"[← Portfolio Home]({home_url})"
        root_name = f"{gn} — Portfolio Home"

        # ── Root folder page (in case GitLab surfaces it as blank) ────────── #
        root_folder_md = [
            f"# {root_name}",
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  **Group:** [{gn}]({group.web_url})",
            "",
            f"This is the SAFe portfolio wiki for **{gn}**. Reports are organized into four tiers "
            f"by audience and cadence — start with the tier that matches your role, then drill down "
            f"as needed. Return to the [Portfolio Home]({home_url}) index at any time.",
            "",
            "## How to navigate",
            "",
            "Each tier is a folder in this wiki. Click a tier link to see the landing page with "
            "a full description of that tier's purpose, audience, and questions answered — "
            "then follow the links to individual reports.",
            "",
            f"| Tier | Audience | Cadence | Purpose |",
            f"|------|----------|---------|---------|",
            f"| [📊 00 Executive Pulse]({base}/{_wiki_slug(self._wiki_t1)}) "
            f"| Executives, Portfolio Managers | Daily | At-a-glance portfolio health |",
            f"| [🗂️ 01 Program Management]({base}/{_wiki_slug(self._wiki_t2)}) "
            f"| Release Train Engineers, PMs | Weekly | Predictability, risk, and prioritisation |",
            f"| [🔍 02 Operational Detail]({base}/{_wiki_slug(self._wiki_t3)}) "
            f"| ART and Team leads | On demand | Root-cause drill-down and hierarchy view |",
            f"| [🔧 03 Data Quality]({base}/{_wiki_slug(self._wiki_t4)}) "
            f"| All — fix labeling gaps | As needed | Find and fix missing labels and broken links |",
            "",
        ]
        self.upload_to_wiki(group, root_name, "\n".join(root_folder_md))

        # ── Tier landing pages (so folder pages are never blank) ─────────── #

        t1_md = [
            f"# 📊 Executive Pulse — {gn}",
            f"**{_back}**  |  **Updated:** {today.strftime('%Y-%m-%d')}",
            "",
            "_One page. Viewed daily. Read in 90 seconds._",
            "",
            "## Purpose",
            "",
            "Executive Pulse gives portfolio leadership an at-a-glance health check across all "
            "Value Streams. The single report in this tier is designed to be consumed in under "
            "two minutes — it surfaces traffic-light status rather than detail, so decision-makers "
            "can quickly spot which Value Streams need attention before drilling into Tier 2.",
            "",
            "## Audience",
            "",
            "Portfolio Managers, Product Management leadership, and programme sponsors who need "
            "a daily situational-awareness view without wading through operational detail.",
            "",
            "## Key questions answered",
            "",
            "- Are any Value Streams behind schedule this PI?",
            "- Which ARTs are at capacity risk or blocked?",
            "- Has any high risk been raised since yesterday's briefing?",
            "",
            "| Report | What it conveys |",
            "|--------|-----------------|",
            f"| {_wl(f'{self._wiki_t1}/Portfolio Health Dashboard', 'Portfolio Health Dashboard')} "
            f"| Traffic-light status per Value Stream — Schedule, Capacity, Risk, Blocking |",
            "",
            "## Metric Reference",
            "",
            "The Portfolio Health Dashboard uses four traffic-light columns per Value Stream:",
            "",
            "| Column | 🟢 Green | 🟡 Yellow | 🔴 Red |",
            "|--------|----------|-----------|--------|",
            "| **Schedule** | % done ≥ % elapsed − 10 pp | 10–20 pp behind PI elapsed | > 20 pp behind PI elapsed |",
            "| **Capacity** | Team load 80–110% of planned weight | Load 70–80% or 110–120% | Load < 70% or > 120% |",
            "| **Risk** | No high-risk epics | 1–2 high-risk epics | 3+ high-risk epics |",
            "| **Blocking** | No blocked epics | 1–2 blocked | 3+ blocked |",
            "",
            "> **% elapsed through PI** is computed from the `PIID::YYYYQn` label mapped to its calendar quarter. "
            "A PI labelled `2026Q3` runs 1 Jul – 30 Sep; on 1 Aug the PI is ~48% elapsed.",
            "",
        ]
        self.upload_to_wiki(group, self._wiki_t1, "\n".join(t1_md))

        t2_md = [
            f"# 🗂️ Program Management — {gn}",
            f"**{_back}**  |  **Updated:** {today.strftime('%Y-%m-%d')}",
            "",
            "_Reviewed in weekly ART syncs and PM stand-ups._",
            "",
            "## Purpose",
            "",
            "Program Management reports give Release Train Engineers, Product Managers, and "
            "Delivery leads the information they need to manage commitments across Program "
            "Increments. Each report answers a distinct programme-level question: are we "
            "predictable, where is risk concentrated, what should we work on next, and do "
            "our ARTs have the capacity to deliver what we have committed?",
            "",
            "## Audience",
            "",
            "Release Train Engineers (RTEs), Product Management, Portfolio Managers, and "
            "ART leadership. Reviewed weekly in ART sync cadences and pre-PI planning.",
            "",
            "## Key questions answered",
            "",
            "- Which programmes are over-committed or under-weight this PI?",
            "- How predictable has each ART been across recent PIs?",
            "- Which epics carry the highest WSJF score and should be prioritised next?",
            "- Where are our blockers and are any crossing ART boundaries?",
            "- Do we have balanced capacity across teams and ARTs?",
            "",
            "## Reports in this tier",
            "",
            "| Report | What it conveys |",
            "|--------|-----------------|",
            f"| {_wl(f'{self._wiki_t2}/Program × PI Matrix', 'Program × PI Matrix')} "
            f"| Project label vs PI quarter cross-tab — see workload and status at a glance |",
            f"| {_wl(f'{self._wiki_t2}/Program PI Detail', 'Program PI Detail')} "
            f"| Per-PI section view — drill into workload and completion for a single PI |",
            f"| {_wl(f'{self._wiki_t2}/PI Predictability Scorecard', 'PI Predictability Scorecard')} "
            f"| % of committed Features/Capabilities delivered — ART predictability trend |",
            f"| {_wl(f'{self._wiki_t2}/Risk Register', 'Risk Register')} "
            f"| All risk-flagged epics grouped by severity with PI and owning ART |",
            f"| {_wl(f'{self._wiki_t2}/ART Capacity Balance', 'ART Capacity Balance')} "
            f"| Per-team planned vs actual weight per PI — spot over/under-capacity early |",
            f"| {_wl(f'{self._wiki_t2}/Blocking & Cross-ART Risk', 'Blocking & Cross-ART Risk')} "
            f"| Blocked epics, ancestor risk propagation, and cross-ART dependencies per VS *(index → VS)* |",
            f"| {_wl(f'{self._wiki_t2}/WSJF Priority Board', 'WSJF Priority Board')} "
            f"| Portfolio backlog ranked by (Value + Urgency + Risk) ÷ Job Size |",
            "",
            "## Metric Reference",
            "",
            "### PI Predictability",
            "Measures ART reliability — the % of committed Features and Capabilities that were "
            "actually delivered by the end of the PI they were assigned to.",
            "",
            "| Range | Interpretation |",
            "|-------|----------------|",
            "| ≥ 80% | Healthy — ART is delivering to its commitments |",
            "| 60–79% | Caution — consistent over-commitment or scope changes mid-PI |",
            "| < 60% | At risk — underlying capacity or planning problem |",
            "| 100% every PI | Investigate — team may be sandbagging (under-committing to guarantee 100%) |",
            "",
            "### WSJF (Weighted Shortest Job First)",
            "Ranks backlog epics by economic priority. Formula: `WSJF = (Value + Urgency + Risk) ÷ Job Size`",
            "",
            "| Component | Label family | Meaning |",
            "|-----------|-------------|---------|",
            "| Business Value | `wsjf-value::N` | Revenue, mission impact, or customer satisfaction |",
            "| Time Criticality | `wsjf-urgency::N` | Cost of delay — how quickly does value decay if deferred? |",
            "| Risk Reduction | `wsjf-risk::N` | Risk or opportunity enabled by doing this item |",
            "| Job Size | `planned_weight` | Relative effort (from epic planned weight) |",
            "",
            "Fibonacci scores 1–13 apply to each label. Higher WSJF = do this first.",
            "",
            "### ART Capacity Balance",
            "Compares **planned weight** (story points assigned to epics) against **actual weight** "
            "(story points on closed issues). A team at 80–110% load is on track; below 70% may "
            "indicate under-commitment or blocked work; above 120% is over-loaded.",
            "",
            "### Risk Register thresholds",
            "Epics carrying `risk::high`, `risk::medium`, or `risk::low` labels are included. "
            "Risk labels are applied manually or via the `set-risk-labels` utility. "
            "High-risk epics in the current PI should be reviewed every ART sync.",
            "",
        ]
        self.upload_to_wiki(group, self._wiki_t2, "\n".join(t2_md))

        t3_md = [
            f"# 🔍 Operational Detail — {gn}",
            f"**{_back}**  |  **Updated:** {today.strftime('%Y-%m-%d')}",
            "",
            "_Drill-down from Tier 2. Available on demand._",
            "",
            "## Purpose",
            "",
            "Operational Detail reports provide the granular view that team leads and RTEs "
            "need when a Tier 2 metric raises a question. These pages are not meant for daily "
            "monitoring — they exist to answer 'why' and 'where exactly' once a problem has "
            "been spotted in the programme-level view.",
            "",
            "## Audience",
            "",
            "ART leads, Team leads, Value Stream Engineers, and anyone conducting a root-cause "
            "investigation. Also useful before PI planning when teams are sizing and scheduling.",
            "",
            "## Key questions answered",
            "",
            "- Which specific Features are behind, and which team owns them?",
            "- How is work distributed across type (feature vs. enabler vs. infrastructure)?",
            "- How long have epics been sitting in each lifecycle stage — are any stuck?",
            "- What does the full Epic → Capability → Feature hierarchy look like right now?",
            "- Which Capabilities are at risk within a Value Stream this PI?",
            "- Are our flow metrics showing a WIP bottleneck or a velocity drop?",
            "",
            "## Reports in this tier",
            "",
            "| Report | What it conveys |",
            "|--------|-----------------|",
            f"| {_wl(f'{self._wiki_t3}/ART Feature Status', 'ART Feature Status')} "
            f"| Features per ART grouped by Team — completion, weight, and risk flags |",
            f"| {_wl(f'{self._wiki_t3}/VS Capability Dashboard', 'VS Capability Dashboard')} "
            f"| Capabilities by PI with per-ART breakdown for each Value Stream |",
            f"| {_wl(f'{self._wiki_t3}/Team Backlogs', 'Team Backlogs')} "
            f"| Issues grouped by Feature per Team — story-point progress and open/closed count |",
            f"| {_wl(f'{self._wiki_t3}/SAFe Portfolio Hierarchy', 'SAFe Portfolio Hierarchy')} "
            f"| Full Epic → Capability → Feature hierarchy with % complete and PI labels |",
            f"| {_wl(f'{self._wiki_t3}/ART-Team Workload', 'ART-Team Workload')} "
            f"| Planned vs actual weight per group per PI — on-track / at-risk flags |",
            f"| {_wl(f'{self._wiki_t3}/Flow Metrics', 'Flow Metrics')} "
            f"| SAFe flow metrics: velocity, WIP load, work type distribution, and cycle time |",
            f"| {_wl(f'{self._wiki_t3}/Epic Lifecycle', 'Epic Lifecycle / Portfolio Kanban')} "
            f"| Epics by SAFe Portfolio Kanban state — bottleneck detection and age analysis |",
            "",
            "## Metric Reference",
            "",
            "### Flow Metrics (SAFe 6.0)",
            "",
            "| Metric | Unit | What to watch |",
            "|--------|------|---------------|",
            "| **Flow Velocity** | Story points / PI | Is throughput stable or growing? A declining trend signals a delivery problem. |",
            "| **Flow Load (WIP)** | Open Features in `implementing` | Rising WIP with flat velocity = bottleneck. SAFe guidance: limit WIP to sustain flow. |",
            "| **Flow Distribution** | % by work type | Target ~50% feature, ~30% enabler, ~20% infra. > 80% feature = technical debt accumulating. |",
            "| **Flow Time** | Days open-to-close | Average days a Feature spends from first `implementing` label to close. Shorter = faster delivery cycle. |",
            "| **Flow Predictability** | Planned vs actual weight % | Ratio of delivered weight to planned weight for closed Features. < 80% = systematic over-commitment. |",
            "",
            "### Epic Lifecycle — Stuck Thresholds",
            "",
            "Epics are flagged ⚠️ when they have remained in a pre-implementing state beyond these thresholds:",
            "",
            "| State | Label | Stuck after |",
            "|-------|-------|-------------|",
            "| 💡 Funnel | `lifecycle::funnel` | 90 days — idea submitted but not yet analyzed |",
            "| 🔍 Analyzing | `lifecycle::analyzing` | 30 days — Lean Business Case taking too long |",
            "| 📋 Portfolio Backlog | `lifecycle::backlog` | 60 days — approved but no PI capacity assigned |",
            "",
            "Use `set-lifecycle-labels` to bulk-seed lifecycle labels and `strip-lifecycle-labels` to reset.",
            "",
        ]
        self.upload_to_wiki(group, self._wiki_t3, "\n".join(t3_md))

        t4_md = [
            f"# 🔧 Data Quality — {gn}",
            f"**{_back}**  |  **Updated:** {today.strftime('%Y-%m-%d')}",
            "",
            "_Maintenance views — labeling and setup problems, not delivery status._",
            "",
            "## Purpose",
            "",
            "Data Quality reports surface the configuration and labeling gaps that would "
            "cause incorrect or misleading results in Tier 1–3 reports. The SAFe portfolio "
            "reporting model depends on every epic having the right type, PI, project, and "
            "lifecycle labels — and on issues being linked to the hierarchy. These reports "
            "make those gaps visible so they can be fixed.",
            "",
            "## Audience",
            "",
            "Anyone responsible for GitLab data stewardship: RTEs, Portfolio Managers, or "
            "Scrum Masters who own the backlog hygiene process. These reports are most useful "
            "after a bootstrap, after a PI boundary, or before generating executive-facing reports.",
            "",
            "## Key questions answered",
            "",
            "- Which epics have never been assigned to a PI — are they sitting in limbo?",
            "- Are there epics with no parent and no children that are invisible to the hierarchy?",
            "- Are there issues sitting in projects with no link to the epic portfolio?",
            "",
            "> **Note:** These reports identify data hygiene issues to fix. They are not delivery "
            "status indicators — a long list here means labeling work to do, not programme problems.",
            "",
            "| Report | What it conveys |",
            "|--------|-----------------|",
            f"| {_wl(f'{self._wiki_t4}/Unassigned PI', 'Unassigned PI')} "
            f"| Epics missing a `PIID::` label — not yet scheduled to any PI |",
            f"| {_wl(f'{self._wiki_t4}/Orphaned Epics', 'Orphaned Epics')} "
            f"| Epics with no parent and no children — disconnected from the hierarchy |",
            f"| {_wl(f'{self._wiki_t4}/Orphaned Issues', 'Orphaned Issues')} "
            f"| Issues in team projects not linked to any epic — invisible to portfolio reporting |",
            "",
        ]
        self.upload_to_wiki(group, self._wiki_t4, "\n".join(t4_md))

    def generate_all_reports(self):
        self._run_reports(REPORTS)

    def run_reports_menu(self, report_key=None):
        """Show the reports selection menu or run a specific report by key."""
        if report_key:
            if report_key == "all":
                self._run_reports(REPORTS)
                return
            report = next((r for r in REPORTS if r["key"] == report_key), None)
            if report is None:
                print(f"Unknown report '{report_key}'. Available: all, " + ", ".join(r['key'] for r in REPORTS))
                sys.exit(1)
            self._run_reports([report])
            return

        print()
        print("Available Reports")
        print("=" * 60)
        for i, report in enumerate(REPORTS, 1):
            print(f"  [{i}] {report['key']:<22} {report['description']}")
        print()
        print("  Enter  — run all reports (default)")
        print("  q      — quit")
        print()

        raw = input(f"Select [1-{len(REPORTS)}, space-separated, or Enter for all]: ").strip()

        if raw.lower() in ("q", "quit"):
            return

        if not raw:
            self._run_reports(REPORTS)
            return

        selected = []
        for token in raw.split():
            try:
                idx = int(token)
                if 1 <= idx <= len(REPORTS):
                    report = REPORTS[idx - 1]
                    if report not in selected:
                        selected.append(report)
                else:
                    print(f"  Ignoring out-of-range selection: {idx}")
            except ValueError:
                print(f"  Ignoring unrecognised input: {token!r}")

        if not selected:
            print("No valid selection — running all reports.")
            selected = REPORTS

        self._run_reports(selected)

    def _fetch_blocking_graph(self, group):
        """Return the raw blocking relationship graph via the REST related_epics API.

        Uses _all_epics_cache (populated by calculate_portfolio_metrics) to avoid
        an extra hierarchy walk, and queries each epic's /related_epics endpoint
        directly — the same API used to create blocking relationships.
        """
        import requests as _requests

        all_epics_raw = getattr(self, '_all_epics_cache', {}).get(self.parent_group, [])
        if not all_epics_raw:
            print("  WARNING: epic cache empty — cannot collect blocking data.")
            return {"relationships": [], "summary": {}}

        session = _requests.Session()
        session.headers.update({"PRIVATE-TOKEN": self.private_token})

        epic_by_id = {e["id"]: e for e in all_epics_raw}
        parent_of  = {e["id"]: e["parent_id"] for e in all_epics_raw if e.get("parent_id")}

        def _etype(labels):
            for t in ("Epic", "Capability", "Feature"):
                if t in labels:
                    return t
            return "Unknown"

        def _portfolio_ancestors(epic_id):
            result, cur, seen = [], epic_id, set()
            while cur in parent_of:
                cur = parent_of[cur]
                if cur in seen:
                    break
                seen.add(cur)
                node = epic_by_id.get(cur)
                if node and _etype(node.get("labels", [])) == "Epic":
                    result.append(node)
            return result

        relationships = []
        total_rels    = 0

        for epic in all_epics_raw:
            grp_id = epic.get("group_id")
            iid    = epic.get("iid")
            eid    = epic.get("id")
            if not (grp_id and iid and eid):
                continue

            url = f"{self.url}/api/v4/groups/{grp_id}/epics/{iid}/related_epics"
            try:
                resp = session.get(url)
            except Exception:
                continue
            if not resp.ok:
                continue

            blockers = []
            for rel in resp.json():
                if rel.get("link_type") != "is_blocked_by":
                    continue
                rel_id   = rel["id"]
                rel_info = epic_by_id.get(rel_id, {})
                blockers.append({
                    "id":      rel_id,
                    "id_int":  rel_id,
                    "title":   rel.get("title", rel_info.get("title", "")),
                    "type":    _etype(rel_info.get("labels", [])),
                    "web_url": rel.get("web_url", rel_info.get("web_url", "")),
                })

            if not blockers:
                continue

            total_rels += len(blockers)
            anc = _portfolio_ancestors(eid)

            relationships.append({
                "blocked_epic": {
                    "id":      eid,
                    "id_int":  eid,
                    "title":   epic.get("title", ""),
                    "type":    _etype(epic.get("labels", [])),
                    "state":   epic.get("state", ""),
                    "web_url": epic.get("web_url", ""),
                },
                "blocked_by":              blockers,
                "at_risk_portfolio_epics": [
                    {
                        "id":      a["id"],
                        "id_int":  a["id"],
                        "title":   a["title"],
                        "type":    _etype(a.get("labels", [])),
                        "web_url": a.get("web_url", ""),
                    }
                    for a in anc
                ],
            })

        at_risk = len({a["id"] for r in relationships for a in r["at_risk_portfolio_epics"]})

        return {
            "summary": {
                "total_blocked":           len(relationships),
                "total_relationships":     total_rels,
                "portfolio_epics_at_risk": at_risk,
            },
            "relationships": relationships,
        }

    def _collect_snapshot_groups_projects(self, root_group):
        """Traverse the SAFe hierarchy once and return (groups_list, projects_list) as plain dicts."""
        all_groups   = []
        all_projects = []

        root_dict = {
            "id": root_group.id, "name": root_group.name,
            "path": root_group.path, "full_path": root_group.full_path,
            "parent_id": None, "web_url": root_group.web_url, "level": "portfolio",
        }
        all_groups.append(root_dict)

        for vs_sg in root_group.subgroups.list(all=True):
            vs = self.gl.groups.get(vs_sg.id)
            vs_dict = {
                "id": vs.id, "name": vs.name, "path": vs.path,
                "full_path": vs.full_path, "parent_id": root_group.id,
                "web_url": vs.web_url, "level": "vs",
            }
            all_groups.append(vs_dict)

            for art_sg in vs.subgroups.list(all=True):
                art = self.gl.groups.get(art_sg.id)
                art_dict = {
                    "id": art.id, "name": art.name, "path": art.path,
                    "full_path": art.full_path, "parent_id": vs.id,
                    "web_url": art.web_url, "level": "art",
                }
                all_groups.append(art_dict)

                for team_sg in art.subgroups.list(all=True):
                    team = self.gl.groups.get(team_sg.id)
                    team_dict = {
                        "id": team.id, "name": team.name, "path": team.path,
                        "full_path": team.full_path, "parent_id": art.id,
                        "web_url": team.web_url, "level": "team",
                    }
                    all_groups.append(team_dict)

                    for proj in team.projects.list(all=True):
                        try:
                            fp = self.gl.projects.get(proj.id)
                            all_projects.append({
                                "id":                   fp.id,
                                "name":                 fp.name,
                                "path":                 fp.path,
                                "path_with_namespace":  fp.path_with_namespace,
                                "name_with_namespace":  fp.name_with_namespace,
                                "namespace_id":         fp.namespace["id"],
                                "web_url":              fp.web_url,
                                "issues_enabled":       fp.issues_enabled,
                            })
                        except Exception as e:
                            print(f"  Failed to fetch project {proj.name}: {e}")

        return all_groups, all_projects

    def _write_report_data(self, data_dir):
        """Write epics.json, issues.json, blocking.json, groups.json, projects.json to data_dir."""
        group = self._rd_root_obj
        ts    = datetime.now().isoformat()

        print("  Collecting data snapshot...")
        metrics = self.calculate_portfolio_metrics(self.parent_group)

        # Epics: typed + untyped
        typed_epics = [e for bucket in metrics.values() for e in bucket]
        all_epics_raw = getattr(self, '_all_epics_cache', {}).get(self.parent_group, typed_epics)
        epics_payload = {
            "generated_at":   ts,
            "group":          self.parent_group,
            "total":          len(typed_epics),
            "total_raw":      len(all_epics_raw),
            "epics":          typed_epics,
            "all_epics_raw":  all_epics_raw,
        }
        (data_dir / "epics.json").write_text(
            json.dumps(epics_payload, indent=2, default=str), encoding="utf-8"
        )

        issues = getattr(self, '_issues_cache', {}).get(self.parent_group, [])
        issues_payload = {
            "generated_at": ts,
            "group":        self.parent_group,
            "total":        len(issues),
            "issues":       issues,
        }
        (data_dir / "issues.json").write_text(
            json.dumps(issues_payload, indent=2, default=str), encoding="utf-8"
        )

        blocking = self._fetch_blocking_graph(group)
        blocking["generated_at"] = ts
        blocking["group"]        = self.parent_group
        (data_dir / "blocking.json").write_text(
            json.dumps(blocking, indent=2, default=str), encoding="utf-8"
        )

        print("  Collecting group/project hierarchy...")
        all_groups, all_projects = self._collect_snapshot_groups_projects(group)
        groups_payload = {
            "generated_at": ts,
            "group":        self.parent_group,
            "total":        len(all_groups),
            "groups":       all_groups,
        }
        (data_dir / "groups.json").write_text(
            json.dumps(groups_payload, indent=2, default=str), encoding="utf-8"
        )
        projects_payload = {
            "generated_at": ts,
            "group":        self.parent_group,
            "total":        len(all_projects),
            "projects":     all_projects,
        }
        (data_dir / "projects.json").write_text(
            json.dumps(projects_payload, indent=2, default=str), encoding="utf-8"
        )

        n_blocked = blocking["summary"].get("total_blocked", 0)
        print(f"\n  Data snapshot → {data_dir}/")
        print(f"    epics.json    ({len(typed_epics)} typed + {len(all_epics_raw) - len(typed_epics)} untyped)")
        print(f"    issues.json   ({len(issues)} issues)")
        print(f"    blocking.json ({n_blocked} blocked epics)")
        print(f"    groups.json   ({len(all_groups)} groups)")
        print(f"    projects.json ({len(all_projects)} projects)\n")

    def _load_report_data(self, data_dir):
        """Load JSON snapshot into self._rd_* lookup structures for use by all report methods."""
        epics_data    = json.loads((data_dir / "epics.json").read_text(encoding="utf-8"))
        issues_data   = json.loads((data_dir / "issues.json").read_text(encoding="utf-8"))
        blocking_data = json.loads((data_dir / "blocking.json").read_text(encoding="utf-8"))
        groups_data   = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        projects_data = json.loads((data_dir / "projects.json").read_text(encoding="utf-8"))

        # Groups
        all_groups = groups_data["groups"]
        self._rd_root = next((g for g in all_groups if g["parent_id"] is None), None)
        self._rd_groups_by_id: dict = {g["id"]: g for g in all_groups}
        self._rd_groups_by_parent: defaultdict = defaultdict(list)
        for g in all_groups:
            if g["parent_id"] is not None:
                self._rd_groups_by_parent[g["parent_id"]].append(g)

        # Projects indexed by namespace (group) id
        self._rd_projects_by_nsid: defaultdict = defaultdict(list)
        for p in projects_data["projects"]:
            self._rd_projects_by_nsid[p["namespace_id"]].append(p)

        # Epics
        self._rd_epics_all: list = epics_data.get("all_epics_raw", epics_data["epics"])
        self._rd_metrics: dict = {
            "Epic":       [e for e in epics_data["epics"] if e.get("type") == "Epic"],
            "Capability": [e for e in epics_data["epics"] if e.get("type") == "Capability"],
            "Feature":    [e for e in epics_data["epics"] if e.get("type") == "Feature"],
        }
        self._rd_epics_by_id: dict = {e["id"]: e for e in epics_data["epics"]}

        # Issues
        self._rd_issues_by_project: defaultdict = defaultdict(list)
        self._rd_issues_by_epic: defaultdict    = defaultdict(list)
        for issue in issues_data["issues"]:
            self._rd_issues_by_project[issue["project_path"]].append(issue)
            if issue.get("epic_id"):
                self._rd_issues_by_epic[issue["epic_id"]].append(issue)

        # Blocking
        self._rd_blocking: dict = blocking_data

        # Derive active label sets from snapshot — not from config
        all_epic_labels = [lbl for e in self._rd_epics_all for lbl in e.get("labels", [])]
        label_set       = set(all_epic_labels)
        self._rd_piid_labels    = sorted(
            {l for l in label_set if l.startswith("PIID::")},
            key=lambda p: (self._pi_dates_from_label(p)[0] or date.min),
        )
        self._rd_project_labels    = sorted({l for l in label_set if l.startswith("project::")})
        self._rd_risk_labels       = sorted({l for l in label_set if l.startswith("risk::")})
        self._rd_work_type_labels  = sorted({l for l in label_set if l.startswith("type::")})
        self._rd_lifecycle_labels  = sorted({l for l in label_set if l.startswith("lifecycle::")})

    def _run_reports(self, reports):
        """Execute a list of report entries from the REPORTS registry."""
        group = self.get_group_by_name(self.parent_group)
        self._rd_root_obj = group
        gn = group.name
        self._wiki_t1 = f"{gn} — Portfolio Home/00 Executive Pulse"
        self._wiki_t2 = f"{gn} — Portfolio Home/01 Program Management"
        self._wiki_t3 = f"{gn} — Portfolio Home/02 Operational Detail"
        self._wiki_t4 = f"{gn} — Portfolio Home/03 Data Quality"
        print(f"\nGenerating reports for group: {group.full_path}\n")

        now      = datetime.now()
        run_dir  = Path("reports") / now.strftime("%Y%m%d") / now.strftime("%H%M%S")
        data_dir = run_dir / "data"
        wiki_dir = run_dir / "wiki"
        data_dir.mkdir(parents=True, exist_ok=True)
        wiki_dir.mkdir(parents=True, exist_ok=True)
        self._report_run_dir = run_dir
        self._wiki_save_dir  = wiki_dir
        self._write_report_data(data_dir)
        self._load_report_data(data_dir)

        total  = len(reports)
        phases = []

        for i, report in enumerate(reports, 1):
            print(f"[{i}/{total}] {report['description']}")
            self._current_op = f"report: {report['key']}"
            start = datetime.now()
            t0    = time.monotonic()
            try:
                method = getattr(self, report["method"])
                method(group) if report["needs_group"] else method()
            except Exception as e:
                print(f"  ERROR running '{report['key']}': {e}")
            elapsed = time.monotonic() - t0
            end     = datetime.now()
            self._current_op = None
            phases.append((report["key"], start, end, elapsed))
            print(f"  ↳ {start.strftime('%H:%M:%S')} → {end.strftime('%H:%M:%S')}  {_fmt_duration(elapsed)}\n")

        self._print_timing_table(phases, f"{total} report(s) completed")

        # expose aggregate for --all phase summary
        if phases:
            wall = (phases[-1][2] - phases[0][1]).total_seconds()
            label = f"reports ({total})" if total > 1 else f"report: {phases[0][0]}"
            self._last_reports_phase = (label, phases[0][1], phases[-1][2], wall)
