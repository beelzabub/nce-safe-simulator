import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from .utils import _clear, _fmt_duration, _tee_to_log



def _gid_to_int(gid_str):
    """Convert 'gid://gitlab/Epic/123' → 123, or return None."""
    try:
        return int(str(gid_str).split("/")[-1])
    except (ValueError, AttributeError):
        return None

def _mlink(title, url):
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'

def _tip(icon, label):
    return f'<span title="{label}">{icon}</span>'

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
        "key":         "issue-blocking",
        "description": "Issue Blocking — issue-to-issue is_blocked_by relationships, with project and parent epic",
        "method":      "generate_issue_blocking_report",
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
        "key":         "premature-closures",
        "description": "Premature Closures — closed Epics/Capabilities with open child epics or open linked issues",
        "method":      "generate_premature_closures_report",
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
        "description": "Program Workload by Group — planned vs actual weight per group per PI",
        "method":      "generate_workload_report",
        "needs_group": False,
    },
    {
        "key":         "diagnostics",
        "description": "Environment & API Diagnostics — software versions, REST/GraphQL compatibility, and label validation",
        "method":      "generate_diagnostics_report",
        "needs_group": False,
    },
]

ALL_FORMATS = frozenset({"markdown", "plotly", "interactive"})

# Wiki tier prefixes are set as instance attributes in _run_reports:
#   self._wiki_t1 = f"{gn} — Portfolio Home/00 Executive Pulse"
#   self._wiki_t2 = f"{gn} — Portfolio Home/01 Program Management"
#   self._wiki_t3 = f"{gn} — Portfolio Home/02 Operational Detail"
#   self._wiki_t4 = f"{gn} — Portfolio Home/03 Data Quality"


def _wiki_slug(page_title: str) -> str:
    """Convert a page title to a GitLab wiki URL slug.

    Matches GitLab's own slug generation, confirmed from live API error output:
      - Non-ASCII characters (e.g. em-dash —) are kept as-is; GitLab preserves them.
      - ASCII characters that are not alphanumeric, slash, dash, or space → space.
      - Runs of whitespace collapsed to a single space.
      - Spaces → dashes.
      - Consecutive dashes collapsed to one.
      - Leading/trailing dashes stripped.

    Forward slashes are preserved as GitLab wiki path separators.
    """
    import re as _re
    s = _re.sub(r'[^-􏿿a-zA-Z0-9/\-& ]', ' ', page_title)
    s = _re.sub(r' +', ' ', s).strip()                                # collapse spaces
    s = s.replace(' ', '-')                                            # spaces → dashes
    s = _re.sub(r'-+', '-', s)                                        # collapse dashes
    return s.strip('-')


_ROAM_ICONS = {
    "roam::owned":    "⚠️ O",
    "roam::accepted": "⚠️ A",
    "roam::mitigated":"⚠️ M",
    "roam::resolved": "⚠️ R",
}

_ACTIVE_ROAM = {"roam::owned", "roam::accepted", "roam::mitigated"}

_TYPE_ICON_LEGEND = [
    "",
    "### Epic Type Icons",
    "",
    "| Icon | Type |",
    "|------|------|",
    "| 🏆 | Epic |",
    "| 🧩 | Capability |",
    "| 🛠️ | Feature |",
    "",
]

_LEGEND_OPEN  = ["---", "<details>", "<summary>Legend</summary>", ""]
_LEGEND_CLOSE = ["", "</details>"]


def _side_by_side(*panels):
    """Return one HTML string placing (title, [(left, right), ...]) panels side by side."""
    def _panel(title, rows):
        trs = "".join(f"<tr><td>{l}</td><td>{r}</td></tr>" for l, r in rows)
        return (
            f"<td valign='top'><strong>{title}</strong>"
            f"<table><tr><th align='left'>Icon</th><th align='left'>Meaning</th></tr>"
            f"{trs}</table></td>"
        )
    spacer = '<td width="40"></td>'
    return f"<table><tr valign='top'>{spacer.join(_panel(t, r) for t, r in panels)}</tr></table>"


def _item_risk_reasons(item, today=None):
    """Return a compact at-risk reason string for an epic/feature dict.

    Checks four distinct causes (Refs #8, #10):
      🔒 Blocked         — has one or more active blocking relationships
      ⏱️ Behind Schedule — active PI, % done < % PI elapsed
      📅 Past Due        — due_date in the past, not Closed
      ⚠️ N risk(s)       — has linked active ROAM risk issues (Refs #10)
      ⚠️ Child at risk   — a descendant epic has an active ROAM risk (Refs #95)
    Returns "—" when no risk applies, or when work and PI are both 100% complete.
    """
    if today is None:
        today = date.today()
    state    = (item.get("state") or "").lower()
    pct_done = item.get("pct_complete", 0)
    pct_pi   = item.get("pct_through_pi")
    due_date = item.get("due_date")
    blocked  = (item.get("blocked_by_count") or 0) > 0

    if pct_done >= 100 and pct_pi is not None and pct_pi >= 100:
        return "—"

    reasons = []
    if blocked:
        reasons.append("🔒 Blocked")
    if pct_pi is not None and 0 < pct_pi < 100 and state != "closed" and pct_done < pct_pi:
        reasons.append("⏱️ Behind Schedule")
    if due_date and state != "closed":
        try:
            dd = date.fromisoformat(str(due_date)[:10])
            if dd < today:
                reasons.append("📅 Past Due")
        except (ValueError, TypeError):
            pass

    active_roam = [r for r in (item.get("roam_risks") or [])
                   if (r.get("roam_status") or "roam::owned") in _ACTIVE_ROAM]
    if active_roam:
        reasons.append(f"⚠️ {len(active_roam)} risk(s)")

    inherited_roam = [r for r in (item.get("inherited_roam_risks") or [])
                      if (r.get("roam_status") or "roam::owned") in _ACTIVE_ROAM]
    if inherited_roam:
        reasons.append(f"⚠️ Child at risk ({len(inherited_roam)})")

    return " · ".join(reasons) if reasons else "—"


class ReportsMixin:

    def _relative_project_name(self, project):
        """Return project name_with_namespace starting from parent_group."""
        name = project.get("name_with_namespace", project.get("path_with_namespace", ""))
        pg   = getattr(self, "parent_group", "")
        if pg:
            parts = name.split(" / ")
            try:
                idx = next(i for i, p in enumerate(parts) if p.lower() == pg.lower())
                return " / ".join(parts[idx:])
            except StopIteration:
                pass
        return name

    def _relative_project_breadcrumb(self, project):
        """Return [{name, url}, ...] for each path segment from parent_group down.

        Zips name_with_namespace display names with path_with_namespace slugs so
        each segment links to its GitLab group or project page.
        """
        name_parts = project.get("name_with_namespace", "").split(" / ")
        path_parts = project.get("path_with_namespace", "").split("/")
        base_url   = (getattr(self, "url", None) or "https://gitlab.com").rstrip("/")
        pg         = getattr(self, "parent_group", "")
        try:
            start = next(i for i, p in enumerate(name_parts) if p.lower() == pg.lower())
        except StopIteration:
            start = 0
        result = []
        for i in range(start, len(name_parts)):
            url = base_url + "/" + "/".join(path_parts[:i + 1]) if i < len(path_parts) else ""
            result.append({"name": name_parts[i], "url": url})
        return result

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
                markdown_report.append(f"- **{_mlink(issue.title, issue.web_url)}**")
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
                    issue_line = f"  - **{_mlink(issue.title, issue.web_url)}** (Status: {issue.state})"

                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        epic_id     = issue.epic_issue['epic_id']
                        epic        = epics.get(epic_id)
                        if epic:
                            linked_issues       = epic_to_issue_map.get(epic_id, [])
                            all_issues_closed   = all(i.state in ["closed", "done"] for i in linked_issues)
                            inferred_epic_state = "closed" if all_issues_closed else epic.state
                            issue_line += f" (_Epic: {_mlink(epic.title, epic.web_url)} - **State:** {inferred_epic_state}_)"
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

            markdown_report.append(f"- **Epic: {_mlink(epic.title, epic.web_url)}**")
            markdown_report.append(f"  - **State:** {epic.state}")
            markdown_report.append(f"  - **Linked Issues:** {len(linked_issues)} issue(s)")
            for issue in linked_issues:
                markdown_report.append(f"    - **{_mlink(issue.title, issue.web_url)}** (State: {issue.state})")
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
                issue_title    = _mlink(issue.title, issue.web_url)
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
                f"{group.web_url}/-/epics"
                f"?label_name[]={quote(piid, safe='')}"
                f"&label_name[]={quote(proj, safe='')}"
                f"&state=all"
            )

        detail_title = f"{self._wiki_t2}/Program PI Detail"
        detail_url   = f"{self.url}/groups/{group.full_path}/-/wikis/{_wiki_slug(detail_title)}"

        md = []
        md.append(f"# Program × PI Report (Group: {group.name})")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  {_mlink('→ Per-PI Detail View', detail_url)}")
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
                    f"{_mlink('View →', board)} "
                )

            md.append("| **" + proj + "** |" + "|".join(cells) + "|")

        md.extend([
            "",
            "---",
            "<details>",
            "<summary>Legend</summary>",
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
            "</details>",
            "",
            "## Quick Links",
            "",
            f"- {_mlink('Work Items', f'{group.web_url}/-/work_items')}",
            f"- {_mlink('Epic Boards', f'{group.web_url}/-/epics')}",
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
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  {_mlink('→ Program × PI Matrix View', matrix_url)}")
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
                    f"{group.web_url}/-/epics"
                    f"?label_name[]={quote(piid, safe='')}"
                    f"&label_name[]={quote(proj, safe='')}"
                    f"&state=all"
                )
                md.append(
                    f"| **{_mlink(proj, board_url)}** "
                    f"| {open_cnt}/{total} "
                    f"| {avg_pct}% "
                    f"| {status} "
                    f"| {planned} pt "
                    f"| {actual} pt "
                    f"| {delta_str} "
                    f"| {blocked_str} |"
                )

            md.append("")

        md.extend(_LEGEND_OPEN + [
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
        ] + _LEGEND_CLOSE)

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

            all_epics     = [e for t in self.EPIC_TYPE_DISPLAY_NAMES for e in metrics.get(t, [])]
            epic_hierarchy = defaultdict(list)
            for epic in all_epics:
                if epic.get("parent_id") is not None:
                    epic_hierarchy[epic["parent_id"]].append(epic)

            def render_epic_details(epic, indent_level=0):
                nonlocal markdown_report

                epic_type = self._epic_type_display(epic.get("labels", []))
                icon      = _tip(self.EPIC_TYPE_ICONS.get(epic_type, "🏆"), epic_type)
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
                label = f"{block_icon}{icon} **{_mlink(epic['title'], epic['web_url'])}** {meta}"

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

            for epic in metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[0], []):
                render_epic_details(epic)

            markdown_report.extend(["", "", ""] + _LEGEND_OPEN + [
                "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
                "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
                "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
            ] + _LEGEND_CLOSE)

            md = "\n".join(markdown_report)
            self.upload_to_wiki(group, f"{self._wiki_t3}/SAFe Portfolio Hierarchy", md)

        except Exception as e:
            print(f"Failed to generate epics report for group '{group_name}': {e}")

    def generate_portfolio_summary(self, metrics, group):
        base = f"{group.web_url}/-/epics"
        label_by_type = {dn: lbl for lbl, dn in zip(self.EPIC_TYPE_LABELS, self.EPIC_TYPE_DISPLAY_NAMES)}

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

            icon       = _tip(self.EPIC_TYPE_ICONS.get(metric_type, "🏆"), metric_type)
            lbl        = label_by_type.get(metric_type, metric_type)
            url_all    = f"{base}?label_name[]={lbl}&state=all"
            url_open   = f"{base}?label_name[]={lbl}&state=opened"
            url_closed = f"{base}?label_name[]={lbl}&state=closed"

            summary.append(
                f"| {icon} **{metric_type}** "
                f"| {_mlink(str(total), url_all)} "
                f"| {_mlink(str(open_count), url_open)} "
                f"| {_mlink(str(closed_count), url_closed)} "
                f"| {total_blocked_by} "
                f"| {total_blocks} "
                f"| {avg_done}% "
                f"| {pi_cell} |"
            )

        summary.append("")
        return "\n".join(summary)

    def generate_workload_report(self):
        group = self._rd_root_obj
        print("  Generating Program Workload by Group Report...")

        metrics   = self._rd_metrics
        all_epics = [e for t in self.EPIC_TYPE_DISPLAY_NAMES for e in metrics.get(t, [])]
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
        md.append(f"# Program Workload by Group (Group: {group.name})")
        md.append(
            "> **Note:** The Epics count reflects work items directly owned by each group. "
            "The linked Work Items page includes items from sub-groups, so the count and the link may differ."
        )
        md.append("")
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
                        f"?type[]=8&label_name[]={quote(piid, safe='')}"
                    )
                    epics_cell = f'<a href="{wi_url}" target="_blank" rel="noopener noreferrer">{len(fs)}</a>'
                else:
                    epics_cell = str(len(fs))

                md.append(
                    f"| {grp_link} | {epics_cell} | {total_planned} pt | {total_actual} pt "
                    f"| {delta_str} | {avg_pct}% | {status_str} |"
                )

            md.append("")

        md.extend(_LEGEND_OPEN + [
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
        ] + _LEGEND_CLOSE)

        self.upload_to_wiki(group, f"{self._wiki_t3}/Program Workload by Group", "\n".join(md))

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
            return self._epic_type_display(list(label_titles))

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
            f"**Group:** {link(group.name, group.web_url)}"
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
            md.append(f"| {link(f'🔷 {vs_name}', vs_wiki_url)} | {deps_str} | {crit_str} |")
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
                etype          = epic.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
                icon           = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                state          = epic.get("state", "").capitalize()
                blocked_by_cnt = len(rel.get("blocked_by", []))

                md.append("<details>")
                md.append(
                    f"<summary>⛔ {icon} **{link(epic['title'], epic['web_url'])}**"
                    f" — State: {state}"
                    f" — Blocked by: {blocked_by_cnt}</summary>"
                )
                md.append("")

                for blocker in rel.get("blocked_by", []):
                    btype = blocker.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
                    bicon = self.EPIC_TYPE_ICONS.get(btype, "🏆")
                    md.append(f"🔒 {bicon} **{link(blocker['title'], blocker['web_url'])}**")
                    md.append("")

                ancestors = rel.get("at_risk_portfolio_epics", [])
                if ancestors:
                    md.append("**Risk propagates up to:**")
                    md.append("")
                    for ancestor in ancestors:
                        atype = ancestor.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
                        aicon = self.EPIC_TYPE_ICONS.get(atype, "🏆")
                        md.append(f"⬆️ {aicon} **{link(ancestor['title'], ancestor['web_url'])}**")
                        md.append("")

                md.append("</details>")
                md.append("")

        md.extend(_LEGEND_OPEN + [
            _side_by_side(
                ("Epic Type Icons",  [(self.EPIC_TYPE_ICONS.get(t, "?"), t) for t in self.EPIC_TYPE_DISPLAY_NAMES]),
                ("Blocking Status",  [("⛔", "Blocked — has at least one active blocker"),
                                      ("🔒", "Blocker — directly blocking one or more epics"),
                                      ("⬆️", "Risk propagation — blocked descendant risk bubbles up"),
                                      ("⚠️", "Portfolio risk flag — top-level Epic has blocked descendants")]),
                ("Cross-ART Severity", [("🔴 Critical", "Blocked item is in the current PI"),
                                        ("🟡 Watch",    "Blocked item is in a future PI"),
                                        ("⚫ Past",     "Blocked item was in a past PI")]),
            ),
        ] + _LEGEND_CLOSE)

        self.upload_to_wiki(group, f"{self._wiki_t2}/Blocking & Cross-ART Risk", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/Blocking & Cross-ART Risk")

    def generate_issue_blocking_report(self):
        """Issue Blocking — issue→issue ``is_blocked_by`` relationships.

        Sibling of the epic-level *Blocking & Cross-ART Risk* report.  Surfaces
        the issue-to-issue blocking links the tool generates but never reported,
        as a flat table of Blocked Issue | Project | Epic | Blocked By.
        """
        group = self._rd_root_obj
        today = date.today()

        rels = self._rd_issue_blocking.get("relationships", [])
        summ = self._rd_issue_blocking.get("summary", {})
        total_relationships = summ.get("total_relationships", 0)

        def link(title, url):
            if not url:
                return title
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'

        md = []
        md.append(f"# Issue Blocking — {group.name}")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** {link(group.name, group.web_url)}"
        )
        md.append("")

        # ── Summary bar ────────────────────────────────────────────────────── #
        md.append("## Summary")
        md.append("")
        md.append("| Metric | Count |")
        md.append("|--------|-------|")
        md.append(f"| Blocked issues | **{len(rels)}** |")
        md.append(f"| Total blocking relationships | **{total_relationships}** |")
        md.append("")

        # ── Blocked issues table ───────────────────────────────────────────── #
        if not rels:
            md.append("## Blocked Issues")
            md.append("")
            md.append("_No blocked issues found._")
            md.append("")
        else:
            md.append("## Blocked Issues")
            md.append("")
            md.append("Issues with one or more active `is_blocked_by` links:")
            md.append("")
            md.append("| Blocked Issue | Project | Epic | Blocked By |")
            md.append("|---------------|---------|------|------------|")
            for rel in rels:
                issue   = rel["blocked_issue"]
                proj    = issue.get("project_path", "") or "—"
                etitle  = issue.get("epic_title")
                epic_md = etitle if etitle else "—"
                blockers = rel.get("blocked_by", [])
                blocked_by_md = "<br>".join(
                    f"🔒 {link(b.get('title', ''), b.get('web_url', ''))}"
                    for b in blockers
                ) or "—"
                md.append(
                    f"| ⛔ {link(issue.get('title', ''), issue.get('web_url', ''))} "
                    f"| {proj} | {epic_md} | {blocked_by_md} |"
                )
            md.append("")

        md.extend(_LEGEND_OPEN + [
            _side_by_side(
                ("Blocking Status", [("⛔", "Blocked — has at least one active blocker"),
                                     ("🔒", "Blocker — directly blocking this issue")]),
            ),
        ] + _LEGEND_CLOSE)

        self.upload_to_wiki(group, f"{self._wiki_t2}/Issue Blocking", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/Issue Blocking")

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
            md.append("| Title | State |")
            md.append("|-------|-------|")
            for epic in orphans:
                etype      = self._epic_type_display(epic["labels"])
                icon       = self.EPIC_TYPE_ICONS.get(etype, "❓")
                title_link = _mlink(epic['title'], epic['web_url'])
                md.append(f"| {icon} {title_link} | {epic['state']} |")

        md.extend(_LEGEND_OPEN + _TYPE_ICON_LEGEND + _LEGEND_CLOSE)
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
            orphaned = [i for i in issues
                        if not i.get("epic_id")
                        and i.get("state", "").lower() == "opened"
                        and not any(l.startswith("roam::") for l in (i.get("labels") or []))]
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
                name    = project.get("path", project.get("path_with_namespace", ""))
                web_url = project.get("web_url", "")
                heading = f'<a href="{web_url}" target="_blank">{name}</a>' if web_url else name
                md.append(f"### {heading}")
                md.append("")
                md.append("| # | Title | State | Assignees |")
                md.append("|---|-------|-------|-----------|")
                for issue in issues:
                    url        = issue['web_url']
                    title      = issue['title']
                    title_link = f'<a href="{url}" target="_blank">{title}</a>'
                    state      = issue["state"].capitalize()
                    assignees  = ", ".join(issue.get("assignees") or []) or "_Unassigned_"
                    md.append(f"| #{issue['iid']} | {title_link} | {state} | {assignees} |")
                md.append("")

        self.upload_to_wiki(group, f"{self._wiki_t4}/Orphaned Issues", "\n".join(md))

    def generate_premature_closures_report(self):
        group = self._rd_root_obj
        today = date.today()
        print("  Generating Premature Closures report...")

        # Build parent → direct children map
        children_by_parent: defaultdict = defaultdict(list)
        for e in self._rd_epics_all:
            pid = e.get("parent_id")
            if pid is not None:
                children_by_parent[pid].append(e)

        # Find closed Epics and Capabilities with open direct children or open linked issues
        findings = []   # list of dicts
        for etype in self.EPIC_TYPE_DISPLAY_NAMES[:2]:
            for epic in self._rd_epics_all:
                if epic.get("type") != etype:
                    continue
                if (epic.get("state") or "").lower() != "closed":
                    continue

                open_children = [
                    c for c in children_by_parent.get(epic["id"], [])
                    if (c.get("state") or "").lower() != "closed"
                ]
                open_issues = [
                    i for i in self._rd_issues_by_epic.get(epic["id"], [])
                    if i.get("state", "").lower() != "closed"
                ]

                if open_children or open_issues:
                    findings.append({
                        "epic":          epic,
                        "etype":         etype,
                        "open_children": open_children,
                        "open_issues":   open_issues,
                    })

        by_type = {t: [f for f in findings if f["etype"] == t] for t in self.EPIC_TYPE_DISPLAY_NAMES[:2]}
        total = len(findings)

        md = []
        md.append(f"# Premature Closures — {group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** {_mlink(group.name, group.web_url)}"
        )
        md.append("")
        md.append(
            "A **premature closure** is a closed Epic or Capability that still has open "
            "child epics or open linked issues. Either reopen the parent to reflect "
            "in-flight work, or close and reassign the remaining items."
        )
        md.append("")

        if not findings:
            md.append("✅ _No premature closures found — all closed epics have fully closed descendants._")
            self.upload_to_wiki(group, f"{self._wiki_t4}/Premature Closures", "\n".join(md))
            return

        md.append(f"**{total} closed epic(s) with open work remaining.**")
        md.append("")

        for etype in self.EPIC_TYPE_DISPLAY_NAMES[:2]:
            rows = by_type.get(etype, [])
            if not rows:
                continue
            icon = self.EPIC_TYPE_ICONS.get(etype, "?")
            md.append("---")
            md.append(f"## {icon} Closed {etype}s with Open Work ({len(rows)})")
            md.append("")

            for f in sorted(rows, key=lambda x: x["epic"]["title"]):
                epic         = f["epic"]
                open_children = f["open_children"]
                open_issues   = f["open_issues"]
                title_link   = _mlink(epic['title'], epic['web_url'])
                child_note   = f"⚠️ {len(open_children)} open child epic(s)" if open_children else ""
                issue_note   = f"⚠️ {len(open_issues)} open issue(s)" if open_issues else ""
                notes        = " · ".join(x for x in (child_note, issue_note) if x)

                md.append(f"### {title_link}  — {notes}")
                md.append("")

                if open_children:
                    md.append("**Open child epics:**")
                    md.append("")
                    md.append("| Title | PI |")
                    md.append("|-------|----|")
                    for child in sorted(open_children, key=lambda c: c["title"]):
                        ctype = self._epic_type_display(child.get("labels", []))
                        cicon     = self.EPIC_TYPE_ICONS.get(ctype, "❓")
                        clink     = _mlink(child['title'], child['web_url'])
                        piid      = next((l for l in child.get("labels", []) if l.startswith("PIID::")), "—")
                        md.append(f"| {cicon} {clink} | {piid} |")
                    md.append("")

                if open_issues:
                    md.append("**Open linked issues:**")
                    md.append("")
                    md.append("| # | Issue | Assignee |")
                    md.append("|---|-------|----------|")
                    for issue in sorted(open_issues, key=lambda i: i.get("iid", 0)):
                        ilink     = _mlink(issue['title'], issue['web_url'])
                        assignees = ", ".join(issue.get("assignees") or []) or "_Unassigned_"
                        md.append(f"| #{issue['iid']} | {ilink} | {assignees} |")
                    md.append("")

        md.extend(_LEGEND_OPEN + _TYPE_ICON_LEGEND + _LEGEND_CLOSE)
        self.upload_to_wiki(group, f"{self._wiki_t4}/Premature Closures", "\n".join(md))

    def generate_unassigned_pi_report(self):
        group = self._rd_root_obj
        print("  Generating Unassigned PI Report...")

        all_epics        = self._rd_epics_all
        epic_title_by_id = {e["id"]: e["title"] for e in all_epics}

        unassigned = [e for e in all_epics if not any(l.startswith("PIID::") for l in e["labels"])]

        by_type: dict = {t: [] for t in [*self.EPIC_TYPE_DISPLAY_NAMES, "Unknown"]}
        for e in unassigned:
            etype = self._epic_type_display(e["labels"])
            by_type[etype].append(e)

        md = []
        md.append(f"# Unassigned PI Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Items listed here have no `PIID::` label and are not committed to any Program Increment.")
        md.append("")
        md.append(f"**Total unassigned: {len(unassigned)}**")
        md.append("")

        for etype in [*self.EPIC_TYPE_DISPLAY_NAMES, "Unknown"]:
            items = by_type[etype]
            if not items:
                continue
            icon = self.EPIC_TYPE_ICONS.get(etype, "❓")
            md.append(f"## {icon} {etype} ({len(items)})")
            md.append("")
            md.append("| Title | State | Parent |")
            md.append("|-------|-------|--------|")
            for e in sorted(items, key=lambda x: x["title"]):
                title_link = _mlink(e['title'], e['web_url'])
                state      = e["state"]
                parent_id  = e.get("parent_id")
                parent     = f"_{epic_title_by_id[parent_id]}_" if parent_id and parent_id in epic_title_by_id else "—"
                md.append(f"| {title_link} | {state} | {parent} |")
            md.append("")

        md.extend(_LEGEND_OPEN + [
            "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
            "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
            "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
            "- **Parent**: the direct parent epic in the hierarchy, if one exists",
            "- Items with no parent and no children are also captured by the Orphaned Epics report",
        ] + _LEGEND_CLOSE)

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

        ROAM_ORDER = ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"]
        ROAM_ICONS = {
            "roam::owned":    "⚠️ Owned",
            "roam::accepted": "✋ Accepted",
            "roam::mitigated":"🛡️ Mitigated",
            "roam::resolved": "✅ Resolved",
        }

        # Build relative path from root for each epic's owning group
        root_id = self._rd_root["id"]

        def _group_path(gid):
            parts = []
            cur = self._rd_groups_by_id.get(gid)
            while cur and cur["id"] != root_id:
                parts.append(cur["name"])
                cur = self._rd_groups_by_id.get(cur.get("parent_id"))
            return " / ".join(reversed(parts)) if parts else group.name

        # ── ROAM risk issues (primary) ────────────────────────────────── #
        # Build {risk_key: (risk_dict, [epic_dict, ...])} — one entry per unique risk issue.
        # A risk may relate to multiple epics; we collect all of them.
        # Key on web_url (globally unique), NOT iid — issue iids are only unique per
        # project, so two risks in different backlog projects can share an iid and
        # would otherwise be merged into one row (Refs #101).
        def _risk_key(risk):
            return risk.get("web_url") or risk["iid"]

        risk_map: dict = {}        # key → (risk_dict, [epic_dicts])
        inherited_by_risk: dict = {}   # key → [epic_dicts impacted via a child] (Refs #95)
        roam_epics_seen: set = set()
        for epic in self._rd_epics_all:
            for risk in epic.get("roam_risks") or []:
                key = _risk_key(risk)
                if key not in risk_map:
                    risk_map[key] = (risk, [])
                risk_map[key][1].append(epic)
                roam_epics_seen.add(epic["id"])
            # Parents (e.g. a Capability) impacted by a descendant Feature's risk
            for risk in epic.get("inherited_roam_risks") or []:
                key = _risk_key(risk)
                if key not in risk_map:
                    risk_map[key] = (risk, [])
                inherited_by_risk.setdefault(key, []).append(epic)
                roam_epics_seen.add(epic["id"])

        # Bucket by ROAM status — one entry per unique risk issue
        roam_buckets: dict = {lbl: [] for lbl in ROAM_ORDER}
        for key, (risk, epics) in risk_map.items():
            status = risk.get("roam_status") or "roam::owned"
            roam_buckets.setdefault(status, []).append((risk, epics))

        # ── Condition buckets — independent, an epic may appear in multiple ─ #
        # Build parent→children map for child-overdue detection
        children_by_parent: defaultdict = defaultdict(list)
        for e in self._rd_epics_all:
            pid = e.get("parent_id")
            if pid is not None:
                children_by_parent[pid].append(e)

        def _has_overdue_child_feature(epic_id):
            for child in children_by_parent.get(epic_id, []):
                if (child.get("state") or "").lower() == "closed":
                    continue
                dd = child.get("due_date")
                if dd:
                    try:
                        if date.fromisoformat(str(dd)[:10]) < today:
                            return True
                    except (ValueError, TypeError):
                        pass
                if _has_overdue_child_feature(child["id"]):
                    return True
            for issue in self._rd_issues_by_epic.get(epic_id, []):
                if (issue.get("state") or "").lower() == "closed":
                    continue
                dd = issue.get("due_date")
                if dd:
                    try:
                        if date.fromisoformat(str(dd)[:10]) < today:
                            return True
                    except (ValueError, TypeError):
                        pass
            return False

        def _is_past_due(dd_str):
            try:
                return date.fromisoformat(str(dd_str)[:10]) < today
            except (ValueError, TypeError):
                return False

        open_epics_caps = [
            e for e in self._rd_epics_all
            if e.get("type") in self.EPIC_TYPE_DISPLAY_NAMES
            and (e.get("state") or "").lower() != "closed"
        ]

        blocked_bucket = [
            e for e in open_epics_caps
            if (e.get("blocked_by_count") or 0) > 0
        ]
        child_overdue_bucket = [
            e for e in open_epics_caps
            if _has_overdue_child_feature(e["id"])
        ]
        past_due_bucket = [
            e for e in open_epics_caps
            if e.get("type") in self.EPIC_TYPE_DISPLAY_NAMES[:2]
            and _is_past_due(e.get("due_date"))
        ]
        behind_schedule_bucket = [
            e for e in open_epics_caps
            if e.get("pct_through_pi") is not None
            and 0 < e["pct_through_pi"] < 100
            and e.get("pct_complete", 0) < e["pct_through_pi"]
        ]

        total_roam_risks   = len(risk_map)
        total_blocked      = len(blocked_bucket)
        total_child_over   = len(child_overdue_bucket)
        total_past_due     = len(past_due_bucket)
        total_behind_sched = len(behind_schedule_bucket)

        # ── VS breakdown ─────────────────────────────────────────────── #
        vs_counts = {}
        for vs in self._iter_vs_groups():
            vs_desc_ids: set = set()
            def _collect(gid):
                vs_desc_ids.add(gid)
                for child in self._rd_groups_by_parent.get(gid, []):
                    _collect(child["id"])
            _collect(vs["id"])
            roam_cnt = sum(1 for e in self._rd_epics_all
                           if e.get("group_id") in vs_desc_ids and e["id"] in roam_epics_seen)
            vs_counts[vs["name"]] = roam_cnt

        # ── Render ──────────────────────────────────────────────────── #
        md = []
        md.append(f"# Risk Register — {group.name}")
        md.append(
            f"**Report Date:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** {_mlink(group.name, group.web_url)}"
        )
        md.append("")

        # ── Summary: side-by-side panels ─────────────────────────────── #
        def _panel(title, col1, col2, rows):
            thead = f"<tr><th align='left'>{col1}</th><th align='left'>{col2}</th></tr>"
            tbody = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in rows)
            return (
                f"<td valign='top'><strong>{title}</strong>"
                f"<table>{thead}{tbody}</table></td>"
            )

        panels = []

        # Count all issues per ROAM label from the snapshot (regardless of epic linkage)
        all_roam_counts: dict = {lbl: 0 for lbl in ROAM_ORDER}
        for issues in self._rd_issues_by_project.values():
            for issue in issues:
                for lbl in (issue.get("labels") or []):
                    if lbl in all_roam_counts:
                        all_roam_counts[lbl] += 1

        def _roam_all_cell(lbl, n):
            url = f"{group.web_url}/-/issues?label_name[]={lbl}&state=all"
            return f"<a href='{url}' target='_blank'>{n}</a>" if n else "0"

        total_all_roam = sum(all_roam_counts.values())
        roam_rows = [(ROAM_ICONS.get(lbl, lbl),
                      _roam_all_cell(lbl, all_roam_counts.get(lbl, 0)),
                      len(roam_buckets.get(lbl, [])))
                     for lbl in ROAM_ORDER]
        roam_rows.append(("<strong>Total</strong>",
                          f"<strong>{total_all_roam}</strong>",
                          f"<strong>{total_roam_risks}</strong>"))
        _roam_thead = "<tr><th align='left'>Status</th><th align='left'>All</th><th align='left'>Linked</th></tr>"
        _roam_tbody = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td></tr>" for r in roam_rows)
        panels.append(
            f"<td valign='top'><strong>ROAM Risk Issues</strong>"
            f"<table>{_roam_thead}{_roam_tbody}</table></td>"
        )

        alert_rows = []
        if total_blocked:
            alert_rows.append(("🔒 Blocked", total_blocked))
        if total_child_over:
            alert_rows.append(("📅 Child Overdue", total_child_over))
        if total_past_due:
            alert_rows.append(("📅 Past Due", total_past_due))
        if total_behind_sched:
            alert_rows.append(("⏱️ Behind Schedule", total_behind_sched))
        if alert_rows:
            panels.append(_panel("Condition Alerts", "Condition", "Items", alert_rows))

        if vs_counts:
            panels.append(_panel("By Value Stream", "Value Stream", "ROAM Risks",
                                 list(vs_counts.items())))

        spacer = '<td width="40"></td>'
        md.append("## Summary")
        md.append("")
        md.append(f"<table><tr valign='top'>{spacer.join(panels)}</tr></table>")
        md.append("")
        md.append(
            "_An epic may appear in more than one condition section below — "
            "conditions are independent and cumulative._"
        )
        md.append("")

        # ── Section 1: ROAM risk issues ──────────────────────────────── #
        def _pi_sort_key(e):
            piid = next((l for l in e.get("labels", []) if l.startswith("PIID::")), "PIID::ZZZZ")
            return (piid, e["title"])

        def _epic_meta(epic):
            etype = self._epic_type_display(epic.get("labels", []))
            eicon = self.EPIC_TYPE_ICONS.get(etype, "❓")
            pi    = next((l for l in epic.get("labels", []) if l.startswith("PIID::")), "—")
            path  = _group_path(epic.get("group_id"))
            state = epic["state"].capitalize()
            return etype, eicon, pi, path, state

        if total_roam_risks:
            md.append("---")
            md.append("## ⚠️ ROAM Risk Issues")
            md.append("")
            md.append(
                "Each row is one risk issue.  "
                "A risk may threaten more than one epic — all are listed in the last column.  "
                "Remove the issue (or mark it closed) when the risk is no longer relevant."
            )
            md.append("")

            for lbl in ROAM_ORDER:
                rows = roam_buckets.get(lbl, [])
                if not rows:
                    continue
                icon = ROAM_ICONS.get(lbl, lbl)
                md.append(f"### {icon} ({len(rows)})")
                md.append("")
                md.append("| Risk Issue | Assignee | Epics Threatened |")
                md.append("|------------|----------|-----------------|")
                for risk, epics in sorted(rows, key=lambda x: x[0].get("title", "")):
                    risk_link  = _mlink(risk['title'], risk['web_url'])
                    assignee   = risk.get("assignee") or "—"
                    threatened = [_mlink(e['title'], e['web_url']) for e in epics]
                    threatened += [
                        f"{_mlink(e['title'], e['web_url'])} _(via child)_"
                        for e in inherited_by_risk.get(_risk_key(risk), [])
                    ]
                    epic_links = ", ".join(threatened)
                    md.append(f"| {risk_link} | {assignee} | {epic_links} |")
                md.append("")
        else:
            md.append("---")
            md.append("## ⚠️ ROAM Risk Issues")
            md.append("")
            md.append(
                "_No ROAM risk issues found.  "
                "Create issues with `roam::owned`, `roam::accepted`, `roam::mitigated`, or "
                "`roam::resolved` labels and link them to the threatened epic via **\"relates to\"**._"
            )
            md.append("")

        def _render_epic_table(epics, prepend=None):
            md.append("| Epic | PI | Group / ART | State | At Risk Reasons |")
            md.append("|------|----|-------------|-------|-----------------|")
            for epic in sorted(epics, key=_pi_sort_key):
                etype, eicon, pi, path, state = _epic_meta(epic)
                title_link = _mlink(epic['title'], epic['web_url'])
                reasons    = _item_risk_reasons(epic, today)
                if prepend and prepend not in reasons:
                    reasons = (f"{prepend} · " + reasons) if reasons != "—" else prepend
                md.append(f"| {eicon} {title_link} | {pi} | {path} | {state} | {reasons} |")
            md.append("")

        # ── Section 2: Blocked ───────────────────────────────────────────── #
        if blocked_bucket:
            md.append("---")
            md.append(f"## 🔒 Blocked ({total_blocked})")
            md.append("")
            md.append("_Has one or more active blocking relationships._")
            md.append("")
            _render_epic_table(blocked_bucket, prepend="🔒 Blocked")

        # ── Section 3: Child Overdue ──────────────────────────────────── #
        if child_overdue_bucket:
            md.append("---")
            md.append(f"## 📅 Child Overdue ({total_child_over})")
            md.append("")
            md.append("_A child Feature has passed its due date and is not Closed._")
            md.append("")
            _render_epic_table(child_overdue_bucket, prepend="📅 Child Overdue")

        # ── Section 4: Past Due ───────────────────────────────────────── #
        if past_due_bucket:
            md.append("---")
            md.append(f"## 📅 Past Due ({total_past_due})")
            md.append("")
            md.append("_The epic's own due date has passed and it is not Closed._")
            md.append("")
            _render_epic_table(past_due_bucket, prepend="📅 Past Due")

        # ── Section 5: Behind Schedule ────────────────────────────────── #
        if behind_schedule_bucket:
            md.append("---")
            md.append(f"## ⏱️ Behind Schedule ({total_behind_sched})")
            md.append("")
            md.append("_Open in an active PI with % complete below % of PI elapsed._")
            md.append("")
            _render_epic_table(behind_schedule_bucket, prepend="⏱️ Behind Schedule")

        md.extend(_LEGEND_OPEN + [
            _side_by_side(
                ("Epic Type Icons",   [(self.EPIC_TYPE_ICONS.get(t, "?"), t) for t in self.EPIC_TYPE_DISPLAY_NAMES]),
                ("ROAM Dispositions", [("⚠️ Owned",    "Someone owns this risk and is actively managing it"),
                                       ("✋ Accepted",  "Risk acknowledged; no action planned"),
                                       ("🛡️ Mitigated", "Steps taken to reduce probability or impact"),
                                       ("✅ Resolved",  "Risk eliminated — close or remove the issue")]),
            ),
            "",
            "### At Risk Reason Indicators",
            "",
            "| Indicator | Meaning |",
            "|-----------|---------|",
            "| ⚠️ N risk(s)       | Item has N linked ROAM risk issues |",
            "| ⚠️ Child at risk   | A descendant epic (e.g. a Feature) has an active ROAM risk |",
            "| ⏱️ Behind Schedule | Active PI: % Done is less than % of PI elapsed |",
            "| 📅 Past Due        | Item's due date has passed and it is not Closed |",
            "| 📅 Child Overdue   | A child Feature has passed its due date and is not Closed |",
            "| 🔒 Blocked         | Item has one or more active blocking relationships |",
        ] + _LEGEND_CLOSE)

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
        commitment_epics = [
            e for t in self.EPIC_TYPE_DISPLAY_NAMES[1:]
            for e in self._rd_metrics.get(t, [])
        ]
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
            f"**Group:** {_mlink(group.name, group.web_url)}"
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
            art_link = _mlink(art_group['name'], art_group['web_url'])
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

        md.extend([""] + _LEGEND_OPEN + [
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
        ] + _LEGEND_CLOSE)

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
        for vs_name, vs_url, art_name, art_url, team_name, wiki_url, issue_cnt, pct, total_w in index_entries:
            if vs_name != current_vs:
                vs_link = f'<a href="{vs_url}" target="_blank" rel="noopener noreferrer">🔷 {vs_name}</a>' if vs_url else f"🔷 {vs_name}"
                md.append(f"### {vs_link}")
                md.append("")
                current_vs  = vs_name
                current_art = None
            if art_name != current_art:
                art_link = f'<a href="{art_url}" target="_blank" rel="noopener noreferrer">{art_name}</a>' if art_url else art_name
                md.append(f"#### {art_link}")
                md.append("")
                md.append("| Team | Issues | % Done | Weight |")
                md.append("|------|--------|--------|--------|")
                current_art = art_name
            team_link = f'<a href="{wiki_url}" target="_blank" rel="noopener noreferrer">{team_name}</a>'
            if issue_cnt is None:
                md.append(f"| {team_link} | _(no backlog project)_ | — | — |")
            else:
                md.append(f"| {team_link} | {issue_cnt} | {pct}% | {total_w} pt |")
        if index_entries:
            md.append("")

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
            return (vs_group["name"], vs_group.get("web_url", ""), art_group["name"], art_group.get("web_url", ""), team_group["name"], wiki_url, None, None, None)

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
            f'<a href="{backlog_project["web_url"]}" target="_blank" rel="noopener noreferrer"><strong>View Project</strong></a>'
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
                    f"<details open><summary>🛠️ "
                    f'<a href="{epic_url}" target="_blank" rel="noopener noreferrer">{epic_title}</a>'
                    f" — {f_open} open · {f_pct}% done · {f_closed}/{f_total} pt</summary>"
                )
                md.append("")
                md.append(f"**Feature state:** {f_state}")
                md.append("")
                md.append("| Issue | State | Weight |")
                md.append("|-------|-------|--------|")
                for issue in sorted(issues, key=lambda i: i["state"]):
                    w     = issue.get("weight") or "—"
                    state = "✅ Closed" if issue["state"] == "closed" else "🔵 Open"
                    md.append(
                        f"| {_mlink(issue['title'], issue['web_url'])} "
                        f"| {state} | {w} pt |"
                    )
                md.append("")
                md.append("</details>")
                md.append("")

        if unlinked:
            md.append(f"<details open><summary>📋 Unlinked Issues (no Feature) — {len(unlinked)} issue(s)</summary>")
            md.append("")
            md.append("| Issue | State | Weight |")
            md.append("|-------|-------|--------|")
            for issue in unlinked:
                w     = issue.get("weight") or "—"
                state = "✅ Closed" if issue["state"] == "closed" else "🔵 Open"
                md.append(
                    f"| {_mlink(issue['title'], issue['web_url'])} "
                    f"| {state} | {w} pt |"
                )
            md.append("")
            md.append("</details>")
            md.append("")

        self.upload_to_wiki(team_group_live, wiki_title, "\n".join(md))
        print(f"    → {team_group['full_path']} wiki: {wiki_title}")

        return (vs_group["name"], vs_group.get("web_url", ""), art_group["name"], art_group.get("web_url", ""), team_group["name"], wiki_url, len(all_issues), pct, total_w)

    # ------------------------------------------------------------------
    # ART-level reports
    # ------------------------------------------------------------------

    def generate_art_feature_status_report(self):
        """One wiki page per ART showing all Features grouped by Team, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating ART Feature Status Reports under: {root_group.full_path}")

        features = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

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
            md.append(f'- <a href="{wiki_url}" target="_blank" rel="noopener noreferrer"><strong>{art_name} — Feature Status</strong></a>  · {total_f} features{risk_str}{blocked_str}')

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
                art_link    = _mlink(f"**{art_name}**", art_url)
                feat_str    = _mlink(str(total_f), art_url)
                risk_str    = _mlink(str(at_risk), art_url) if at_risk else "—"
                blocked_str = _mlink(str(blocked), art_url) if blocked else "—"
                md_vs.append(f"| {art_link} | {feat_str} | {risk_str} | {blocked_str} | {_mlink('View →', art_url)} |")
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
            art_links = "  ·  ".join(_mlink(art_name, art_url) for art_name, art_url, *_ in arts)
            md_top.append(f'- 🔷 <a href="{vs_url}" target="_blank" rel="noopener noreferrer"><strong>{vs_name}</strong></a>  —  {art_links}')
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
            f"{_mlink('View ART Group', art_group['web_url'])}"
        )
        md.append("")

        total_f   = 0
        at_risk   = 0
        blocked_c = 0

        for team_id, feature_list in sorted(team_buckets.items(), key=lambda x: team_hierarchy[x[0]][2]["name"]):
            _, _, team_group = team_hierarchy[team_id]
            md.append(f"## {team_group['name']}")
            md.append("")
            md.append("| Feature | PI | State | % Done | PI Elapsed | Weight | Status | At Risk Reason |")
            md.append("|---------|-----|-------|--------|------------|--------|--------|----------------|")

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
                reason     = _item_risk_reasons(f)
                md.append(
                    f"| {_mlink(title, url)} | {piid} | {state} "
                    f"| {pct_done}% | {pi_str} | {weight_str} | {status} | {reason} |"
                )
                total_f += 1

            md.append("")

        md.extend(_LEGEND_OPEN + [
            "- **% Done** — closed issue weight ÷ total issue weight for all issues linked to this Feature",
            "- **PI Elapsed** — how far through the PI quarter today falls: `(today − PI start) ÷ (PI end − PI start) × 100`",
            "- **Weight** — Planned pt → Actual pt (planned set via GraphQL; actual = sum of linked issue weights)",
            "- **✅ On Track** — % Done ≥ PI Elapsed for the current PI",
            "- **⚠️ At Risk** — % Done < PI Elapsed for the current PI",
            "- **✅ Complete** / **❌ Incomplete** — outcome for a past PI",
            "- **🔵 Planned** — future PI or PI not yet started",
            "- **🔒 Blocked** — Feature has one or more active blocking relationships",
        ] + _LEGEND_CLOSE)

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], art_group["name"], wiki_url, total_f, at_risk, blocked_c)

    def generate_art_capacity_balance_report(self):
        """One wiki page per ART showing per-team capacity balance by PI, plus a root index."""
        root_group = self._rd_root_obj
        print(f"Generating ART Capacity Balance Reports under: {root_group.full_path}")

        features = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

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
        vs_web_urls: dict = {}
        for vs_group, art_group in self._iter_art_groups():
            if art_group["id"] not in art_pi_buckets:
                continue
            vs_web_urls[vs_group["name"]] = vs_group.get("web_url", "")
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
            md.append(f'- <a href="{wiki_url}" target="_blank" rel="noopener noreferrer"><strong>{art_name} — Capacity Balance</strong></a>{flag_str}')

        md.append("")
        # (flat legacy index removed — top-level landing page is the T2 page below)

        # Intermediate pages — GitLab creates these as blank when nested titles use /
        vs_arts: defaultdict = defaultdict(list)
        for vs_name, art_name, wiki_url, over_cnt, under_cnt in index_entries:
            vs_arts[vs_name].append((art_name, wiki_url, over_cnt, under_cnt))

        # VS-level pages
        for vs_name, arts in vs_arts.items():
            wiki_title = f"{self._wiki_t2}/ART Capacity Balance/{vs_name}"
            vs_url     = vs_web_urls.get(vs_name, "")
            vs_link    = _mlink(vs_name, vs_url) if vs_url else vs_name
            md_vs = []
            md_vs.append(f"# ART Capacity Balance — {vs_name}")
            md_vs.append(f"**Value Stream:** {vs_link}  |  **Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
            md_vs.append("")
            md_vs.append(f"Planned vs actual team capacity by Program Increment for each ART in the **{vs_name}** Value Stream.")
            md_vs.append("")
            md_vs.append("| ART | Over-capacity | Under-capacity | Detail |")
            md_vs.append("|-----|--------------|----------------|--------|")
            for art_name, art_url, over_cnt, under_cnt in arts:
                art_link  = _mlink(f"**{art_name}**", art_url)
                over_str  = _mlink(f"🔴 {over_cnt}", art_url) if over_cnt else "—"
                under_str = _mlink(f"🔵 {under_cnt}", art_url) if under_cnt else "—"
                md_vs.append(f"| {art_link} | {over_str} | {under_str} | {_mlink('View →', art_url)} |")
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
            art_links = "  ·  ".join(_mlink(art_name, art_url) for art_name, art_url, *_ in arts)
            md_top.append(f'- 🔷 <a href="{vs_url}" target="_blank" rel="noopener noreferrer"><strong>{vs_name}</strong></a>  —  {art_links}')
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

        feature_status_title = f"{self._wiki_t3}/ART Feature Status/{vs_group['name']}/{art_group['name']}"
        feature_status_url   = f"{root_group.web_url}/-/wikis/{_wiki_slug(feature_status_title)}"

        md = []
        md.append(f"# ART Capacity Balance — {art_group['name']}")
        md.append(
            f"**{vs_group['name']} / {art_group['name']}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"{_mlink('View ART Group', art_group['web_url'])}  |  "
            f"{_mlink('Feature Status →', feature_status_url)}"
        )
        md.append("")

        total_over  = 0
        total_under = 0

        for piid in sorted_pis:
            team_buckets  = pi_buckets[piid]
            pct_pi        = self._pct_through_pi(piid)
            start, end    = self._pi_dates_from_label(piid)
            date_range    = f"_{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}_" if start else ""
            pi_board_url  = (
                f"{art_group['web_url']}/-/epics"
                f"?label_name[]={quote(piid, safe='')}&state=all"
            )

            md.append(f"## {piid}")
            meta_parts = [date_range] if date_range else []
            meta_parts.append(_mlink("View Features →", pi_board_url))
            md.append("  |  ".join(meta_parts))
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

                team_link = f'<a href="{team_group["web_url"]}" target="_blank" rel="noopener noreferrer">{team_group["name"]}</a>'
                md.append(
                    f"| {team_link} | {planned} pt | {actual} pt "
                    f"| {delta_str} | {load_pct}% | {status} |"
                )

            md.append("")

        md.extend(_LEGEND_OPEN + [
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
        ] + _LEGEND_CLOSE)

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

        capabilities = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[1], [])
        features     = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

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
            if epic_type_by_id.get(f.get("parent_id")) != self.EPIC_TYPE_DISPLAY_NAMES[1]
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
            md.append(f'- 🔷 <a href="{wiki_url}" target="_blank" rel="noopener noreferrer"><strong>{vs_name} — Capability Dashboard</strong></a>{counts}{risk_str}{blocked_str}')

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
            md_top.append(f'- 🔷 <a href="{wiki_url}" target="_blank" rel="noopener noreferrer"><strong>{vs_name} — Capability Dashboard</strong></a>{counts}{risk_str}{blocked_str}')
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
            f"{_mlink('View VS Group', vs_group['web_url'])}"
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
                reason     = _item_risk_reasons(item)
                rows.append(
                    f"| {_mlink(item['title'], item['web_url'])} | {item['state'].capitalize()} "
                    f"| {item['pct_complete']}% | {pi_str} | {weight_str} | {status} | {reason} |"
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
                    art_link = f'<a href="{art_url}" target="_blank" rel="noopener noreferrer">{art_name}</a>' if art_url else art_name
                    md.append(f"| {art_link} | {len(caps)} | {planned} pt | {actual} pt | {delta_str} | {avg_pct}% | {status} |")
                    art_rows.append((art_name, art_url, caps))
                    total_caps += len(caps)

                md.append("")
                for art_name, art_url, caps in art_rows:
                    md.append(f"<details><summary><strong>{art_name} — Capability Detail</strong></summary>")
                    md.append("")
                    md.append("| Capability | State | % Done | PI Elapsed | Weight | Status | At Risk Reason |")
                    md.append("|------------|-------|--------|------------|--------|--------|----------------|")
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
                    art_link = f'<a href="{art_url}" target="_blank" rel="noopener noreferrer">{art_name}</a>' if art_url else art_name
                    md.append(f"| {art_link} | {len(feats)} | {planned} pt | {actual} pt | {delta_str} | {avg_pct}% | {status} |")
                    art_direct_rows.append((art_name, art_url, feats))
                    total_direct += len(feats)

                md.append("")
                for art_name, art_url, feats in art_direct_rows:
                    md.append(f"<details><summary><strong>{art_name} — Direct Feature Detail</strong></summary>")
                    md.append("")
                    md.append("| Feature | State | % Done | PI Elapsed | Weight | Status | At Risk Reason |")
                    md.append("|---------|-------|--------|------------|--------|--------|----------------|")
                    md.extend(_detail_rows(feats, pct_pi))
                    md.append("")
                    md.append("</details>")
                    md.append("")

        md.extend(_LEGEND_OPEN + [
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
        ] + _LEGEND_CLOSE)

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
            md.append(f'- 🔷 <a href="{wiki_url}" target="_blank" rel="noopener noreferrer"><strong>{vs_name} — Cross-ART Risk</strong></a>{clear_str}{crit_str}')

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
            f"{_mlink('View VS Group', vs_group['web_url'])}"
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

                b_type  = blocked.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
                bl_type = blocker.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
                b_icon  = self.EPIC_TYPE_ICONS.get(b_type, "🏆")
                bl_icon = self.EPIC_TYPE_ICONS.get(bl_type, "🏆")

                b_link  = _mlink(f'{b_icon} {blocked["title"]}', blocked["web_url"])
                bl_link = _mlink(f'{bl_icon} {blocker["title"]}', blocker["web_url"])

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

        md.extend(_LEGEND_OPEN + [
            "| Icon | Meaning |",
            "|------|---------|",
            "| 🔴 Critical | Blocked item is in the **current PI** — active risk requiring immediate coordination |",
            "| 🟡 Watch    | Blocked item is in a **future PI** — dependency to monitor and plan around |",
            "| ⚫ Past     | Blocked item was in a **past PI** — dependency may be stale or already resolved |",
            "| ⛔ | The blocked epic (the one that cannot proceed) |",
            "| 🔒 | The blocker epic (the one causing the block) |",
        ] + _LEGEND_CLOSE)

        self.upload_to_wiki(root_group, wiki_title, "\n".join(md))
        print(f"    → Wiki: {wiki_title}")

        return (vs_group["name"], wiki_url, len(deps), critical)

    def _data_portfolio_health(self) -> dict:
        """Compute portfolio health snapshot → JSON-serializable dict.

        Returns a structured dict consumed by both generate_portfolio_health_dashboard
        (markdown renderer) and write_report_json (Quarto data layer).
        """
        root_group = self._rd_root_obj
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
        pct_pi           = self._pct_through_pi(current_pi) or 0
        pi_start, pi_end = self._pi_dates_from_label(current_pi) if current_pi else (None, None)

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

        def _tl_capacity(epics):
            has_issues = [e for e in epics if e.get("actual_weight", 0) > 0]
            scope_only = [e for e in epics if e.get("actual_weight", 0) == 0
                          and e.get("planned_weight", 0) > 0]

            issue_pts  = sum(e["actual_weight"]         for e in has_issues)
            scope_pts  = sum(e["planned_weight"]         for e in scope_only)
            total_plan = sum(e.get("planned_weight", 0) for e in epics)

            if not issue_pts and not total_plan:
                return "⬜", "—"

            if has_issues and scope_only:
                return "⬜", (
                    f"{issue_pts}pt estimated + {scope_pts}pt scoped"
                    f" / {total_plan}pt planned"
                )

            if not has_issues:
                return "⬜", f"{total_plan}pt planned (no issues)"

            if not total_plan:
                return "⬜", f"{issue_pts}pt (no epic weight set)"

            ratio = issue_pts / total_plan * 100
            if 80 <= ratio <= 110:
                return "🟢", f"{issue_pts}pt/{total_plan}pt ({ratio:.0f}%)"
            if 70 <= ratio <= 120:
                return "🟡", f"{issue_pts}pt/{total_plan}pt ({ratio:.0f}%)"
            return "🔴", f"{issue_pts}pt/{total_plan}pt ({ratio:.0f}%)"

        def _tl_risk(active_roam_count):
            if active_roam_count >= 3:
                return "🔴", f"{active_roam_count} active risk(s)"
            if active_roam_count > 0:
                return "🟡", f"{active_roam_count} active risk(s)"
            return "🟢", "No active risks"

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

        _active_roam = {"roam::owned", "roam::accepted", "roam::mitigated"}

        # ── Per-VS stats ─────────────────────────────────────────────────── #
        vs_rows = []
        portfolio_blocked_total = 0
        portfolio_unassigned    = 0

        for vs_group in self._iter_vs_groups():
            vs_ids = _all_descendant_ids(vs_group["id"])

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
                pct_done_vs = 0

            tl_sched, sched_detail = _tl_schedule(pct_done_vs, pct_pi)
            tl_cap,   cap_detail   = _tl_capacity(pi_epics)

            vs_roam_count = sum(
                1 for e in all_vs_epics_raw
                if any(r.get("roam_status") in _active_roam
                       for r in (e.get("roam_risks") or []))
                or any(r.get("roam_status") in _active_roam
                       for r in (e.get("inherited_roam_risks") or []))
            )
            tl_risk,  risk_detail  = _tl_risk(vs_roam_count)

            vs_epic_ids = {e["id"] for e in (pi_epics if pi_epics else all_vs_epics_raw)}
            vs_blocked  = sum(1 for eid in vs_epic_ids if blocked_counts.get(eid, 0) > 0)
            tl_block, block_detail = _tl_blocking(vs_blocked)

            overall       = _worst(tl_sched, tl_cap, tl_risk, tl_block)
            unassigned_vs = sum(
                1 for e in all_vs_epics_raw
                if not any(l.startswith("PIID::") for l in e.get("labels", []))
            )

            vs_rows.append({
                "vs":          {"name": vs_group["name"], "web_url": vs_group["web_url"]},
                "overall":     overall,
                "tl_sched":    tl_sched,  "sched_detail": sched_detail,
                "tl_cap":      tl_cap,    "cap_detail":   cap_detail,
                "tl_risk":     tl_risk,   "risk_detail":  risk_detail,
                "tl_block":    tl_block,  "block_detail": block_detail,
                "epics_total": len(all_vs_epics),
                "pi_epics":    len(pi_epics),
                "blocked":     vs_blocked,
                "unassigned":  unassigned_vs,
            })

            portfolio_blocked_total += vs_blocked
            portfolio_unassigned    += unassigned_vs

        # ── Portfolio-level totals ────────────────────────────────────────── #
        portfolio_epics_total = sum(1 for e in self._rd_epics_all if not e.get("is_cross_group"))
        portfolio_risk_epics  = sum(
            1 for e in self._rd_epics_all
            if not e.get("is_cross_group")
            and any(r.get("roam_status") in _active_roam
                    for r in (e.get("roam_risks") or []))
        )

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
                port_pct_done = round(
                    sum(e["pct_complete"] for e in all_pi_epics) / len(all_pi_epics)
                )
        else:
            port_pct_done = 0
        port_tl_sched, _ = _tl_schedule(port_pct_done, pct_pi)
        _, port_wt_str    = _tl_capacity(all_pi_epics)

        # ── Needs Attention ─────────────────────────────────────────────── #
        top_blocked_rels = sorted(
            self._rd_blocking.get("relationships", []),
            key=lambda r: -len(r.get("blocked_by", []))
        )[:5]
        top_blocked = []
        for rel in top_blocked_rels:
            epic   = rel["blocked_epic"]
            e_meta = self._rd_epics_by_id.get(
                epic.get("id_int") or epic.get("id"), {}
            )
            _etype = epic.get("type", "—")
            top_blocked.append({
                "title":     epic.get("title", "—"),
                "url":       epic.get("web_url"),
                "type":      _etype,
                "icon":      self.EPIC_TYPE_ICONS.get(_etype, "❓"),
                "n_blockers": len(rel.get("blocked_by", [])),
                "piid":      e_meta.get("piid") or "—",
            })

        at_risk_raw = sorted(
            [e for e in all_pi_epics if pct_pi - e.get("pct_complete", 0) > 20],
            key=lambda e: -(pct_pi - e.get("pct_complete", 0))
        )[:5]
        at_risk_epics = []
        for e in at_risk_raw:
            pw = e.get("planned_weight", 0)
            aw = e.get("actual_weight",  0)
            if pw and aw:
                wt_str = f"{aw}pt/{pw}pt"
            elif pw:
                wt_str = f"{pw}pt (epic)"
            elif aw:
                wt_str = f"{aw}pt (issues)"
            else:
                wt_str = "—"
            _etype = e.get("type", "—")
            at_risk_epics.append({
                "title":      e.get("title", "—"),
                "url":        e.get("web_url"),
                "type":       _etype,
                "icon":       self.EPIC_TYPE_ICONS.get(_etype, "❓"),
                "pct_done":   e.get("pct_complete", 0),
                "pct_elapsed": pct_pi,
                "gap":        pct_pi - e.get("pct_complete", 0),
                "weight_str": wt_str,
                "piid":       e.get("piid", "—"),
            })

        return {
            "generated_at": today.isoformat(),
            "report_date":  today.isoformat(),
            "group": {
                "name":    root_group.name,
                "url":     root_group.web_url,
                "wiki_t2": self._wiki_t2,
            },
            "pi": {
                "current":     current_pi,
                "pct_elapsed": pct_pi,
                "start":       pi_start.isoformat() if pi_start else None,
                "end":         pi_end.isoformat()   if pi_end   else None,
            },
            "portfolio": {
                "epics_total":    portfolio_epics_total,
                "pi_epics_count": len(all_pi_epics),
                "pct_done":       port_pct_done,
                "tl_schedule":    port_tl_sched,
                "blocked_total":  portfolio_blocked_total,
                "risk_epics":     portfolio_risk_epics,
                "unassigned":     portfolio_unassigned,
                "capacity_str":   port_wt_str,
            },
            "vs_rows":       vs_rows,
            "top_blocked":   top_blocked,
            "at_risk_epics": at_risk_epics,
        }

    # ------------------------------------------------------------------
    # Quarto data extraction — one _data_* per report key
    # ------------------------------------------------------------------

    def _data_orphan_epics(self) -> dict:
        group = self._rd_root_obj
        epic_ids_with_children = {
            e["parent_id"] for e in self._rd_epics_all if e.get("parent_id") is not None
        }
        orphans = [
            e for e in self._rd_epics_all
            if e.get("parent_id") is None and e["id"] not in epic_ids_with_children
        ]
        rows = []
        for e in orphans:
            etype = self._epic_type_display(e.get("labels", []))
            rows.append({
                "title": e["title"],
                "url":   e.get("web_url", ""),
                "state": e["state"],
                "type":  etype,
                "icon":  self.EPIC_TYPE_ICONS.get(etype, "❓"),
            })
        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "orphans":     rows,
        }

    def _data_orphan_issues(self) -> dict:
        group = self._rd_root_obj
        all_projects = sorted(
            [p for plist in self._rd_projects_by_nsid.values() for p in plist],
            key=lambda p: p.get("path_with_namespace", ""),
        )
        project_rows = []
        total = 0
        for project in all_projects:
            if not project.get("issues_enabled", True):
                continue
            issues  = self._rd_issues_by_project.get(project["path_with_namespace"], [])
            orphans = [
                i for i in issues
                if not i.get("epic_id")
                and not any(l.startswith("roam::") for l in (i.get("labels") or []))
            ]
            if orphans:
                total += len(orphans)
                project_rows.append({
                    "name":       self._relative_project_name(project),
                    "url":        project.get("web_url", ""),
                    "breadcrumb": self._relative_project_breadcrumb(project),
                    "issues": [
                        {
                            "iid":       i["iid"],
                            "title":     i["title"],
                            "url":       i.get("web_url", ""),
                            "state":     i["state"].capitalize(),
                            "assignees": i.get("assignees") or [],
                        }
                        for i in orphans
                    ],
                })
        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "total":       total,
            "projects":    project_rows,
        }

    def _data_premature_closures(self) -> dict:
        group = self._rd_root_obj
        children_by_parent: defaultdict = defaultdict(list)
        for e in self._rd_epics_all:
            pid = e.get("parent_id")
            if pid is not None:
                children_by_parent[pid].append(e)

        findings = []
        for etype in self.EPIC_TYPE_DISPLAY_NAMES[:2]:
            for epic in self._rd_epics_all:
                if epic.get("type") != etype:
                    continue
                if (epic.get("state") or "").lower() != "closed":
                    continue
                open_children = [
                    c for c in children_by_parent.get(epic["id"], [])
                    if (c.get("state") or "").lower() != "closed"
                ]
                open_issues = [
                    i for i in self._rd_issues_by_epic.get(epic["id"], [])
                    if i.get("state", "").lower() != "closed"
                ]
                if not open_children and not open_issues:
                    continue
                findings.append({
                    "type":  etype,
                    "icon":  self.EPIC_TYPE_ICONS.get(etype, "❓"),
                    "title": epic["title"],
                    "url":   epic.get("web_url", ""),
                    "open_children": [
                        {
                            "title": c["title"],
                            "url":   c.get("web_url", ""),
                            "type":  self._epic_type_display(c.get("labels", [])),
                            "icon":  self.EPIC_TYPE_ICONS.get(
                                self._epic_type_display(c.get("labels", [])),
                                "❓",
                            ),
                            "piid": next(
                                (l for l in c.get("labels", []) if l.startswith("PIID::")), "—"
                            ),
                        }
                        for c in sorted(open_children, key=lambda c: c["title"])
                    ],
                    "open_issues": [
                        {
                            "iid":       i["iid"],
                            "title":     i["title"],
                            "url":       i.get("web_url", ""),
                            "assignees": i.get("assignees") or [],
                        }
                        for i in sorted(open_issues, key=lambda i: i.get("iid", 0))
                    ],
                })
        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "total":       len(findings),
            "findings":    findings,
        }

    def _data_unassigned_pi(self) -> dict:
        group = self._rd_root_obj
        all_epics = self._rd_epics_all
        epic_title_by_id = {e["id"]: e["title"] for e in all_epics}
        unassigned = [
            e for e in all_epics
            if not any(l.startswith("PIID::") for l in e.get("labels", []))
        ]
        by_type: dict = {t: [] for t in [*self.EPIC_TYPE_DISPLAY_NAMES, "Unknown"]}
        for e in unassigned:
            etype = self._epic_type_display(e.get("labels", []))
            parent_id = e.get("parent_id")
            by_type[etype].append({
                "title":  e["title"],
                "url":    e.get("web_url", ""),
                "state":  e["state"],
                "parent": epic_title_by_id.get(parent_id) if parent_id else None,
            })
        for rows in by_type.values():
            rows.sort(key=lambda x: x["title"])
        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "total":       len(unassigned),
            "by_type":     by_type,
        }

    def _data_risk_register(self) -> dict:
        group = self._rd_root_obj
        today = date.today()

        ROAM_ORDER = ["roam::owned", "roam::accepted", "roam::mitigated", "roam::resolved"]
        ROAM_LABELS = {
            "roam::owned":     "Owned",
            "roam::accepted":  "Accepted",
            "roam::mitigated": "Mitigated",
            "roam::resolved":  "Resolved",
        }
        ROAM_ICONS = {
            "roam::owned":     "⚠️",
            "roam::accepted":  "✋",
            "roam::mitigated": "🛡️",
            "roam::resolved":  "✅",
        }
        root_id = self._rd_root["id"]

        def _group_path(gid):
            parts = []
            cur = self._rd_groups_by_id.get(gid)
            while cur and cur["id"] != root_id:
                parts.append(cur["name"])
                cur = self._rd_groups_by_id.get(cur.get("parent_id"))
            return " / ".join(reversed(parts)) if parts else group.name

        risk_map: dict = {}
        roam_epics_seen: set = set()
        for epic in self._rd_epics_all:
            for risk in epic.get("roam_risks") or []:
                iid = risk["iid"]
                if iid not in risk_map:
                    risk_map[iid] = (risk, [])
                risk_map[iid][1].append(epic)
                roam_epics_seen.add(epic["id"])

        roam_buckets: dict = {lbl: [] for lbl in ROAM_ORDER}
        for iid, (risk, epics) in risk_map.items():
            status = risk.get("roam_status") or "roam::owned"
            roam_buckets.setdefault(status, []).append((risk, epics))

        all_roam_counts: dict = {lbl: 0 for lbl in ROAM_ORDER}
        for issues in self._rd_issues_by_project.values():
            for issue in issues:
                for lbl in (issue.get("labels") or []):
                    if lbl in all_roam_counts:
                        all_roam_counts[lbl] += 1

        roam_summary = [
            {
                "label":  lbl,
                "icon":   ROAM_ICONS[lbl],
                "status": ROAM_LABELS[lbl],
                "all":    all_roam_counts.get(lbl, 0),
                "linked": len(roam_buckets.get(lbl, [])),
                "url":    f"{group.web_url}/-/issues?label_name[]={lbl}&state=all",
            }
            for lbl in ROAM_ORDER
        ]

        children_by_parent: defaultdict = defaultdict(list)
        for e in self._rd_epics_all:
            pid = e.get("parent_id")
            if pid is not None:
                children_by_parent[pid].append(e)

        def _has_overdue_child(epic_id):
            for child in children_by_parent.get(epic_id, []):
                if (child.get("state") or "").lower() == "closed":
                    continue
                dd = child.get("due_date")
                if dd:
                    try:
                        if date.fromisoformat(str(dd)[:10]) < today:
                            return True
                    except (ValueError, TypeError):
                        pass
                if _has_overdue_child(child["id"]):
                    return True
            for issue in self._rd_issues_by_epic.get(epic_id, []):
                if (issue.get("state") or "").lower() == "closed":
                    continue
                dd = issue.get("due_date")
                if dd:
                    try:
                        if date.fromisoformat(str(dd)[:10]) < today:
                            return True
                    except (ValueError, TypeError):
                        pass
            return False

        def _is_past_due(dd_str):
            try:
                return date.fromisoformat(str(dd_str)[:10]) < today
            except (ValueError, TypeError):
                return False

        open_all = [
            e for e in self._rd_epics_all
            if e.get("type") in self.EPIC_TYPE_DISPLAY_NAMES
            and (e.get("state") or "").lower() != "closed"
        ]

        def _pi_sort(e):
            piid = next(
                (l for l in e.get("labels", []) if l.startswith("PIID::")), "PIID::ZZZZ"
            )
            return (piid, e["title"])

        def _epic_row(epic):
            etype = self._epic_type_display(epic.get("labels", []))
            return {
                "title":   epic["title"],
                "url":     epic.get("web_url", ""),
                "type":    etype,
                "icon":    self.EPIC_TYPE_ICONS.get(etype, "❓"),
                "piid":    next(
                    (l for l in epic.get("labels", []) if l.startswith("PIID::")), "—"
                ),
                "path":    _group_path(epic.get("group_id")),
                "state":   epic["state"].capitalize(),
                "reasons": _item_risk_reasons(epic, today),
            }

        blocked_list   = sorted(
            [e for e in open_all if (e.get("blocked_by_count") or 0) > 0], key=_pi_sort
        )
        child_over_list = sorted(
            [e for e in open_all if _has_overdue_child(e["id"])], key=_pi_sort
        )
        past_due_list  = sorted(
            [e for e in open_all
             if e.get("type") in self.EPIC_TYPE_DISPLAY_NAMES[:2] and _is_past_due(e.get("due_date"))],
            key=_pi_sort,
        )
        behind_list    = sorted(
            [e for e in open_all
             if e.get("pct_through_pi") is not None
             and 0 < e["pct_through_pi"] < 100
             and e.get("pct_complete", 0) < e["pct_through_pi"]],
            key=_pi_sort,
        )

        vs_counts = []
        for vs in self._iter_vs_groups():
            vs_desc: set = set()
            def _collect(gid, _vs_desc=vs_desc):
                _vs_desc.add(gid)
                for child in self._rd_groups_by_parent.get(gid, []):
                    _collect(child["id"], _vs_desc)
            _collect(vs["id"])
            vs_counts.append({
                "name":  vs["name"],
                "count": sum(
                    1 for e in self._rd_epics_all
                    if e.get("group_id") in vs_desc and e["id"] in roam_epics_seen
                ),
            })

        roam_rows = {
            lbl: [
                {
                    "title":    risk["title"],
                    "url":      risk.get("web_url", ""),
                    "assignee": risk.get("assignee") or "—",
                    "epics": [
                        {"title": e["title"], "url": e.get("web_url", "")} for e in epics
                    ],
                }
                for risk, epics in sorted(
                    roam_buckets.get(lbl, []), key=lambda x: x[0].get("title", "")
                )
            ]
            for lbl in ROAM_ORDER
        }

        return {
            "report_date": today.isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "summary": {
                "roam":           roam_summary,
                "total_all_roam": sum(r["all"] for r in roam_summary),
                "total_linked":   len(risk_map),
                "alerts": {
                    "blocked":         len(blocked_list),
                    "child_overdue":   len(child_over_list),
                    "past_due":        len(past_due_list),
                    "behind_schedule": len(behind_list),
                },
                "vs_counts": vs_counts,
            },
            "roam_rows":       roam_rows,
            "blocked":         [_epic_row(e) for e in blocked_list],
            "child_overdue":   [_epic_row(e) for e in child_over_list],
            "past_due":        [_epic_row(e) for e in past_due_list],
            "behind_schedule": [_epic_row(e) for e in behind_list],
        }

    def _data_wsjf(self) -> dict:
        group = self._rd_root_obj

        def _label_val(labels, prefix):
            for lbl in labels:
                if lbl.startswith(prefix):
                    try:
                        return int(lbl.split("::")[-1])
                    except ValueError:
                        pass
            return None

        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]
        candidates = []
        for epic in all_typed:
            if epic.get("state", "").lower() != "opened":
                continue
            labels  = epic.get("labels", [])
            value   = epic.get("business_value")
            urgency = _label_val(labels, "wsjf-urgency::")
            risk    = _label_val(labels, "wsjf-risk::")
            if value is None and urgency is None and risk is None:
                continue
            size  = epic.get("planned_weight") or None
            v, u, r = (value or 0), (urgency or 0), (risk or 0)
            score = round((v + u + r) / size, 2) if size else None
            etype = self._epic_type_display(epic.get("labels", []))
            candidates.append({
                "title":   epic["title"],
                "url":     epic.get("web_url", ""),
                "type":    etype,
                "icon":    self.EPIC_TYPE_ICONS.get(etype, "🏆"),
                "piid":    epic.get("piid"),
                "value":   value,
                "urgency": urgency,
                "risk":    risk,
                "size":    size,
                "score":   score,
            })
        candidates.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        scored    = sum(1 for c in candidates if c["score"] is not None)
        partial   = sum(1 for c in candidates if c["score"] is None)
        backlog   = sum(1 for c in candidates if not c["piid"])
        in_flight = sum(1 for c in candidates if c["piid"])

        bv_by_id = {
            e["id"]: e.get("business_value")
            for bucket in self._rd_metrics.values()
            for e in bucket
        }
        epic_url_by_id = {
            e["id"]: e.get("web_url", "")
            for bucket in self._rd_metrics.values()
            for e in bucket
        }

        detail_rows = []
        seen_pe_bv: dict  = {}
        seen_pe: dict     = {}
        pe_blocked_ct: dict = {}

        for rel in self._rd_blocking.get("relationships", []):
            blocked  = rel["blocked_epic"]
            blockers = rel.get("blocked_by", [])
            ancs     = rel.get("at_risk_portfolio_epics", [])
            # A non-Portfolio-Epic blocked item with no Portfolio Epic ancestor
            # (orphaned data) keeps its row but leaves "Epic at Risk" blank and is
            # excluded from the BV rollup, rather than collapsing the column onto the
            # blocked item (Refs #108). See the WSJF markdown renderer for the mirror.
            pe_candidates = (
                ([blocked] + ancs) if blocked.get("type") == self.EPIC_TYPE_DISPLAY_NAMES[0] else ancs
            )
            b_type = blocked.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
            blocker_list = [
                {"title": b["title"], "url": b.get("web_url", "")} for b in blockers
            ]

            if not pe_candidates:
                detail_rows.append({
                    "pe_title":      "",
                    "pe_url":        "",
                    "pe_bv":         None,
                    "blocked_title": blocked["title"],
                    "blocked_url":   blocked.get("web_url", ""),
                    "blocked_type":  b_type,
                    "blocked_icon":  self.EPIC_TYPE_ICONS.get(b_type, "🏆"),
                    "blockers":      blocker_list,
                })
                continue

            for pe in pe_candidates:
                pe_id  = pe.get("id") or pe.get("id_int")
                pe_bv  = bv_by_id.get(pe_id)
                pe_url = pe.get("web_url") or epic_url_by_id.get(pe_id, "")
                detail_rows.append({
                    "pe_title":      pe["title"],
                    "pe_url":        pe_url,
                    "pe_bv":         pe_bv,
                    "blocked_title": blocked["title"],
                    "blocked_url":   blocked.get("web_url", ""),
                    "blocked_type":  b_type,
                    "blocked_icon":  self.EPIC_TYPE_ICONS.get(b_type, "🏆"),
                    "blockers":      blocker_list,
                })
                if pe_id not in seen_pe_bv:
                    seen_pe_bv[pe_id] = pe_bv
                    seen_pe[pe_id]    = {"title": pe["title"], "url": pe_url, "bv": pe_bv}
                pe_blocked_ct[pe_id] = pe_blocked_ct.get(pe_id, 0) + 1

        detail_rows.sort(key=lambda x: (x["pe_bv"] is None, -(x["pe_bv"] or 0)))
        total_bv   = sum(v for v in seen_pe_bv.values() if v is not None)
        pe_summary = sorted(
            [
                {
                    "title":     v["title"],
                    "url":       v["url"],
                    "bv":        v["bv"],
                    "n_blocked": pe_blocked_ct[pid],
                }
                for pid, v in seen_pe.items()
            ],
            key=lambda x: (x["bv"] is None, -(x["bv"] or 0)),
        )

        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "summary": {
                "scored": scored, "partial": partial,
                "backlog": backlog, "in_flight": in_flight,
            },
            "candidates":  candidates,
            "blocked_bv":  {
                "total_bv":        total_bv,
                "portfolio_epics": pe_summary,
                "detail_rows":     detail_rows,
            } if detail_rows else None,
        }

    def _data_blocking(self) -> dict:
        group = self._rd_root_obj
        today = date.today()
        rels  = self._rd_blocking.get("relationships", [])
        summ  = self._rd_blocking.get("summary", {})

        id_to_ancestor: dict = {}
        epic_to_blocked_descendants: defaultdict = defaultdict(list)
        for rel in rels:
            for anc in rel.get("at_risk_portfolio_epics", []):
                id_to_ancestor[anc["id"]] = anc
                epic_to_blocked_descendants[anc["id"]].append(rel["blocked_epic"])

        epic_int_to_group = {
            e["id"]: e.get("group_id")
            for tier in self._rd_metrics.values() for e in tier
        }
        epic_int_to_piid = {
            e["id"]: e.get("piid")
            for tier in self._rd_metrics.values() for e in tier
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
                if b_vs["id"] != bl_vs["id"] or b_art["id"] == bl_art["id"]:
                    continue
                vs_deps[b_vs["id"]].append({
                    "blocked_title": blocked["title"],
                    "blocked_url":   blocked.get("web_url", ""),
                    "blocked_art":   b_art["name"],
                    "blocked_piid":  b_piid or "—",
                    "blocker_title": blocker["title"],
                    "blocker_url":   blocker.get("web_url", ""),
                    "blocker_art":   bl_art["name"],
                })

        vs_cross_art = []
        for vs_group in self._iter_vs_groups():
            deps = vs_deps.get(vs_group["id"], [])
            vs_cross_art.append({
                "vs_name": vs_group["name"],
                "vs_url":  vs_group.get("web_url", ""),
                "deps":    deps,
            })

        total_cross_art = sum(len(d["deps"]) for d in vs_cross_art)

        portfolio_risk = [
            {
                "title": id_to_ancestor[eid]["title"],
                "url":   id_to_ancestor[eid].get("web_url", ""),
                "blocked_descendants": [
                    {
                        "title": d["title"],
                        "url":   d.get("web_url", ""),
                        "type":  d.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0]),
                        "icon":  self.EPIC_TYPE_ICONS.get(d.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0]), "🏆"),
                    }
                    for d in descendants
                ],
            }
            for eid, descendants in sorted(
                epic_to_blocked_descendants.items(), key=lambda kv: -len(kv[1])
            )
        ]

        blocked_items = []
        t0 = self.EPIC_TYPE_DISPLAY_NAMES[0]
        for rel in rels:
            epic  = rel["blocked_epic"]
            etype = epic.get("type", t0)
            blocked_items.append({
                "title":  epic["title"],
                "url":    epic.get("web_url", ""),
                "type":   etype,
                "icon":   self.EPIC_TYPE_ICONS.get(etype, "🏆"),
                "state":  epic.get("state", "").capitalize(),
                "blockers": [
                    {
                        "title": b["title"],
                        "url":   b.get("web_url", ""),
                        "type":  b.get("type", t0),
                        "icon":  self.EPIC_TYPE_ICONS.get(b.get("type", t0), "🏆"),
                    }
                    for b in rel.get("blocked_by", [])
                ],
                "ancestors": [
                    {
                        "title": a["title"],
                        "url":   a.get("web_url", ""),
                        "type":  a.get("type", t0),
                        "icon":  self.EPIC_TYPE_ICONS.get(a.get("type", t0), "🏆"),
                    }
                    for a in rel.get("at_risk_portfolio_epics", [])
                ],
            })

        return {
            "report_date": today.isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "summary": {
                "total_blocked":        len(rels),
                "total_relationships":  summ.get("total_relationships", 0),
                "total_portfolio_risk": len(epic_to_blocked_descendants),
                "total_cross_art":      total_cross_art,
            },
            "portfolio_risk": portfolio_risk,
            "vs_cross_art":   vs_cross_art,
            "blocked_items":  blocked_items,
        }

    def _data_issue_blocking(self) -> dict:
        group = self._rd_root_obj
        today = date.today()
        rels  = self._rd_issue_blocking.get("relationships", [])
        summ  = self._rd_issue_blocking.get("summary", {})

        blocked_items = []
        for rel in rels:
            issue = rel["blocked_issue"]
            blocked_items.append({
                "title":        issue.get("title", ""),
                "url":          issue.get("web_url", ""),
                "iid":          issue.get("iid"),
                "project_path": issue.get("project_path", ""),
                "state":        (issue.get("state", "") or "").capitalize(),
                "epic_iid":     issue.get("epic_iid"),
                "epic_title":   issue.get("epic_title"),
                "blockers": [
                    {
                        "title":        b.get("title", ""),
                        "url":          b.get("web_url", ""),
                        "iid":          b.get("iid"),
                        "project_path": b.get("project_path", ""),
                    }
                    for b in rel.get("blocked_by", [])
                ],
            })

        return {
            "report_date": today.isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "summary": {
                "total_blocked":       len(rels),
                "total_relationships": summ.get("total_relationships", 0),
            },
            "blocked_items": blocked_items,
        }

    def _data_epic_lifecycle(self) -> dict:
        group = self._rd_root_obj
        today = date.today()

        STATES = [
            ("lifecycle::funnel",       "💡 Funnel",            "Ideas submitted, not yet analyzed",       90),
            ("lifecycle::analyzing",    "🔍 Analyzing",         "Lean Business Case in development",        30),
            ("lifecycle::backlog",      "📋 Portfolio Backlog", "Approved, awaiting capacity",              60),
            ("lifecycle::implementing", "⚙️ Implementing",      "Active in a Program Increment",           None),
            ("lifecycle::done",         "✅ Done",              "Delivered",                               None),
        ]
        STATE_KEYS = {s[0] for s in STATES}

        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]

        def _age(epic):
            raw = epic.get("created_at")
            if not raw:
                return None
            try:
                return (today - date.fromisoformat(str(raw)[:10])).days
            except ValueError:
                return None

        def _group_name(epic):
            gid = epic.get("group_id")
            g   = self._rd_groups_by_id.get(gid) if gid else None
            return g["name"] if g else "—"

        def _epic_row(e, threshold=None):
            age = _age(e)
            return {
                "title": e["title"],
                "url":   e.get("web_url", ""),
                "type":  e.get("type", "Unknown"),
                "icon":  self.EPIC_TYPE_ICONS.get(e.get("type", "Unknown"), "❓"),
                "age":   age,
                "piid":  e.get("piid") or "—",
                "group": _group_name(e),
                "stuck": bool(threshold and age and age > threshold),
            }

        buckets: dict = {key: [] for key, *_ in STATES}
        buckets["_unlabelled"] = []
        for epic in all_typed:
            labels  = set(epic.get("labels", []))
            matched = labels & STATE_KEYS
            if not matched:
                buckets["_unlabelled"].append(epic)
            else:
                for key, *_ in STATES:
                    if key in matched:
                        buckets[key].append(epic)
                        break

        def _avg(epics):
            ages = [a for a in (_age(e) for e in epics) if a is not None]
            return round(sum(ages) / len(ages)) if ages else None

        def _max(epics):
            ages = [a for a in (_age(e) for e in epics) if a is not None]
            return max(ages) if ages else None

        states_out = []
        for key, label, description, threshold in STATES:
            epics    = buckets[key]
            max_age  = _max(epics)
            states_out.append({
                "key":           key,
                "label":         label,
                "description":   description,
                "threshold":     threshold,
                "count":         len(epics),
                "avg_age":       _avg(epics),
                "max_age":       max_age,
                "over_threshold": bool(threshold and max_age and max_age > threshold),
                "url":           f"{group.web_url}/-/epics?state=all&label_name[]={key}",
                "epics": sorted(
                    [_epic_row(e, threshold) for e in epics],
                    key=lambda r: r["age"] or 0, reverse=True,
                ),
            })

        stuck_out = []
        for key, label, description, threshold in STATES:
            if not threshold:
                continue
            stuck = [
                _epic_row(e, threshold) for e in buckets[key]
                if (_age(e) or 0) > threshold
            ]
            if stuck:
                stuck_out.append({
                    "key": key, "label": label, "threshold": threshold,
                    "guidance": {
                        "lifecycle::analyzing": "Lean Business Case is overdue for a decision. Review and either approve to backlog or cancel.",
                        "lifecycle::backlog":   "Approved work waiting too long for capacity. Consider re-sequencing or rescoping.",
                        "lifecycle::funnel":    "Ideas not yet analyzed beyond the threshold. Either analyze or close.",
                    }.get(key, ""),
                    "epics": sorted(stuck, key=lambda r: r["age"] or 0, reverse=True),
                })

        unlabelled = sorted(
            [_epic_row(e) for e in buckets["_unlabelled"]],
            key=lambda r: r["age"] or 0, reverse=True,
        )

        return {
            "report_date": today.isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "states":      states_out,
            "stuck":       stuck_out,
            "unlabelled":  unlabelled,
        }

    def _data_pi_predictability(self) -> dict:
        group = self._rd_root_obj
        today = date.today()

        art_group_ids: dict = {}
        for vs_group, art_group in self._iter_art_groups():
            ids = {art_group["id"]}
            for team in self._rd_groups_by_parent.get(art_group["id"], []):
                ids.add(team["id"])
            art_group_ids[art_group["id"]] = ids

        commitment_epics = [
            e for t in self.EPIC_TYPE_DISPLAY_NAMES[1:]
            for e in self._rd_metrics.get(t, [])
        ]
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

        def _pred(epics):
            total  = len(epics)
            closed = sum(1 for e in epics if e["state"].lower() == "closed")
            pct    = round(closed / total * 100) if total else None
            return closed, total, pct

        def _cell(epics, piid):
            closed, total, pct = _pred(epics)
            if total == 0:
                return {"closed": 0, "total": 0, "pct": None, "icon": "—", "label": "—", "status": "no_data"}
            pct_pi = self._pct_through_pi(piid)
            if pct_pi is None or pct_pi == 0:
                return {"closed": closed, "total": total, "pct": None, "icon": "🔵", "label": f"{total} planned", "status": "future"}
            if pct_pi < 100:
                icon = "✅" if (pct or 0) >= 80 else ("⚠️" if (pct or 0) >= 60 else "🟡")
                return {"closed": closed, "total": total, "pct": pct, "icon": icon, "label": f"{closed}/{total} in progress", "status": "current"}
            icon = "✅" if (pct or 0) >= 80 else ("⚠️" if (pct or 0) >= 60 else "❌")
            return {"closed": closed, "total": total, "pct": pct, "icon": icon, "label": f"{pct}% ({closed}/{total})", "status": "past"}

        rows = []
        portfolio_by_pi: defaultdict = defaultdict(list)
        for vs_group, art_group in self._iter_art_groups():
            art_id  = art_group["id"]
            pi_data = art_pi_data.get(art_id)
            if not pi_data:
                continue
            cells = []
            for piid in all_pis:
                epics = pi_data.get(piid, [])
                portfolio_by_pi[piid].extend(epics)
                cells.append({"piid": piid, **_cell(epics, piid)})
            rows.append({
                "art_name": art_group["name"],
                "art_url":  art_group.get("web_url", ""),
                "vs_name":  vs_group["name"],
                "cells":    cells,
            })

        portfolio_row = [
            {"piid": piid, **_cell(portfolio_by_pi.get(piid, []), piid)}
            for piid in all_pis
        ]

        return {
            "report_date":   today.isoformat(),
            "group":         {"name": group.name, "url": group.web_url},
            "pis":           all_pis,
            "rows":          rows,
            "portfolio_row": portfolio_row,
        }

    def _data_art_capacity_balance(self) -> dict:
        group = self._rd_root_obj

        features = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

        team_hierarchy: dict = {}
        for vs_group, art_group, team_group in self._iter_team_groups():
            team_hierarchy[team_group["id"]] = (vs_group, art_group, team_group)

        art_pi_buckets: defaultdict = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for f in features:
            gid  = f.get("group_id")
            piid = f.get("piid")
            if gid in team_hierarchy and piid:
                _, art_grp, _ = team_hierarchy[gid]
                art_pi_buckets[art_grp["id"]][piid][gid].append(f)

        arts_out = []
        for vs_group, art_group in self._iter_art_groups():
            art_id = art_group["id"]
            if art_id not in art_pi_buckets:
                continue

            sorted_pis = sorted(
                art_pi_buckets[art_id].keys(),
                key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
            )

            total_over = total_under = 0
            pis_out = []
            for piid in sorted_pis:
                team_buckets = art_pi_buckets[art_id][piid]
                start, end   = self._pi_dates_from_label(piid)
                date_range   = (
                    f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
                    if start else ""
                )
                teams_out = []
                for team_id, fs in sorted(
                    team_buckets.items(),
                    key=lambda x: team_hierarchy[x[0]][2]["name"],
                ):
                    _, _, team_group = team_hierarchy[team_id]
                    planned  = sum(f.get("planned_weight", 0) for f in fs)
                    actual   = sum(f.get("actual_weight",  0) for f in fs)
                    delta    = actual - planned
                    load_pct = round(actual / planned * 100) if planned > 0 else 0

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

                    teams_out.append({
                        "name":     team_group["name"],
                        "url":      team_group.get("web_url", ""),
                        "planned":  planned,
                        "actual":   actual,
                        "delta":    delta,
                        "load_pct": load_pct,
                        "status":   status,
                    })
                pis_out.append({
                    "piid":       piid,
                    "date_range": date_range,
                    "teams":      teams_out,
                })

            arts_out.append({
                "vs_name":     vs_group["name"],
                "art_name":    art_group["name"],
                "art_url":     art_group.get("web_url", ""),
                "over_count":  total_over,
                "under_count": total_under,
                "pis":         pis_out,
            })

        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "arts":        arts_out,
        }

    # ------------------------------------------------------------------
    # Phase 4a Quarto data-layer methods
    # ------------------------------------------------------------------

    def _data_piid_project(self) -> dict:
        """Cross-tab: rows = project labels, columns = PIID quarters."""
        group     = self._rd_root_obj
        all_epics = [e for bucket in self._rd_metrics.values() for e in bucket]
        piid_set  = set(self._rd_piid_labels)
        proj_set  = set(self._rd_project_labels)

        cell_data: defaultdict = defaultdict(list)
        for e in all_epics:
            proj = next((l for l in e["labels"] if l in proj_set), None)
            piid = e.get("piid")
            if proj and piid and piid in piid_set:
                cell_data[(proj, piid)].append(e)

        def _agg(epics):
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

        def _status(pct_pi, avg_pct):
            if pct_pi is None or pct_pi == 0:
                return "🔵 Planned"
            if pct_pi >= 100:
                return "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
            return "✅ On Track" if avg_pct >= pct_pi else "⚠️ At Risk"

        piid_meta = {}
        for piid in self._rd_piid_labels:
            start, end = self._pi_dates_from_label(piid)
            pct_pi     = self._pct_through_pi(piid)
            phase      = ("Future" if (pct_pi is None or pct_pi == 0) else
                          ("Past" if pct_pi >= 100 else "Current"))
            piid_meta[piid] = {
                "start": start.isoformat() if start else None,
                "end":   end.isoformat()   if end   else None,
                "pct":   pct_pi,
                "phase": phase,
            }

        cells = {}
        for proj in self._rd_project_labels:
            for piid in self._rd_piid_labels:
                epics = cell_data.get((proj, piid), [])
                key   = f"{proj}|{piid}"
                if not epics:
                    cells[key] = None
                    continue
                total, open_cnt, planned, actual, avg_pct, blocked = _agg(epics)
                pct_pi = piid_meta[piid]["pct"]
                board_url = (
                    f"{group.web_url}/-/epics"
                    f"?label_name[]={quote(piid, safe='')}"
                    f"&label_name[]={quote(proj, safe='')}"
                    f"&state=all"
                )
                cells[key] = {
                    "project":   proj,
                    "piid":      piid,
                    "total":     total,
                    "open":      open_cnt,
                    "planned":   planned,
                    "actual":    actual,
                    "delta":     actual - planned,
                    "avg_pct":   avg_pct,
                    "blocked":   blocked,
                    "status":    _status(pct_pi, avg_pct),
                    "pct_pi":    pct_pi,
                    "board_url": board_url,
                }

        return {
            "report_date":    date.today().isoformat(),
            "group":          {"name": group.name, "url": group.web_url},
            "project_labels": self._rd_project_labels,
            "piid_labels":    self._rd_piid_labels,
            "piid_meta":      piid_meta,
            "cells":          cells,
        }

    def _data_piid_project_detail(self) -> dict:
        """Per-PI section view — one row per project label per PI."""
        group     = self._rd_root_obj
        all_epics = [e for bucket in self._rd_metrics.values() for e in bucket]
        piid_set  = set(self._rd_piid_labels)
        proj_set  = set(self._rd_project_labels)

        cell_data: defaultdict = defaultdict(list)
        for e in all_epics:
            proj = next((l for l in e["labels"] if l in proj_set), None)
            piid = e.get("piid")
            if proj and piid and piid in piid_set:
                cell_data[(proj, piid)].append(e)

        def _agg(epics):
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

        def _status(pct_pi, avg_pct):
            if pct_pi is None or pct_pi == 0:
                return "🔵 Planned"
            if pct_pi >= 100:
                return "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
            return "✅ On Track" if avg_pct >= pct_pi else "⚠️ At Risk"

        pis_out = []
        for piid in self._rd_piid_labels:
            pct_pi     = self._pct_through_pi(piid)
            start, end = self._pi_dates_from_label(piid)
            phase      = ("Future" if (pct_pi is None or pct_pi == 0) else
                          ("Past" if pct_pi >= 100 else "Current"))
            phase_icon = {"Future": "🔵", "Current": "🟢", "Past": "⬜"}.get(phase, "")

            projects_out = []
            for proj in self._rd_project_labels:
                epics    = cell_data.get((proj, piid), [])
                has_data = bool(epics)
                if has_data:
                    total, open_cnt, planned, actual, avg_pct, blocked = _agg(epics)
                    status = _status(pct_pi, avg_pct)
                    board_url = (
                        f"{group.web_url}/-/epics"
                        f"?label_name[]={quote(piid, safe='')}"
                        f"&label_name[]={quote(proj, safe='')}"
                        f"&state=all"
                    )
                else:
                    total = open_cnt = planned = actual = avg_pct = blocked = 0
                    status    = "—"
                    board_url = ""
                projects_out.append({
                    "project":   proj,
                    "board_url": board_url,
                    "total":     total,
                    "open":      open_cnt,
                    "planned":   planned,
                    "actual":    actual,
                    "delta":     actual - planned,
                    "avg_pct":   avg_pct,
                    "blocked":   blocked,
                    "status":    status,
                    "has_data":  has_data,
                })

            pis_out.append({
                "piid":       piid,
                "phase":      phase,
                "phase_icon": phase_icon,
                "pct_pi":     pct_pi,
                "start":      start.isoformat() if start else None,
                "end":        end.isoformat()   if end   else None,
                "projects":   projects_out,
            })

        return {
            "report_date":    date.today().isoformat(),
            "group":          {"name": group.name, "url": group.web_url},
            "project_labels": self._rd_project_labels,
            "pis":            pis_out,
        }

    def _data_portfolio(self) -> dict:
        """Summary counts + recursive Initiative Hierarchy tree."""
        group   = self._rd_root_obj
        metrics = self._rd_metrics
        base    = f"{group.web_url}/-/epics"

        summary = []
        for metric_type in self.EPIC_TYPE_DISPLAY_NAMES:
            data_list = metrics.get(metric_type, [])
            if not data_list:
                continue
            total      = len(data_list)
            open_cnt   = sum(1 for d in data_list if d["state"].lower() == "opened")
            closed_cnt = sum(1 for d in data_list if d["state"].lower() == "closed")
            blocked_by = sum(d.get("blocked_by_count", 0) for d in data_list)
            blocks     = sum(d.get("blocks_count",    0) for d in data_list)
            avg_done   = round(sum(d["pct_complete"] for d in data_list) / total)
            pcts_pi    = [d["pct_through_pi"] for d in data_list if d.get("pct_through_pi") is not None]
            avg_pi     = round(sum(pcts_pi) / len(pcts_pi)) if pcts_pi else None
            summary.append({
                "type":        metric_type,
                "icon":        self.EPIC_TYPE_ICONS.get(metric_type, "🏆"),
                "total":       total,
                "open":        open_cnt,
                "closed":      closed_cnt,
                "blocked_by":  blocked_by,
                "blocks":      blocks,
                "avg_pct_done": avg_done,
                "avg_pct_pi":  avg_pi,
                "at_risk":     avg_pi is not None and avg_done < avg_pi,
                "url_all":    f"{base}?label_name[]={metric_type}&state=all",
                "url_open":   f"{base}?label_name[]={metric_type}&state=opened",
                "url_closed": f"{base}?label_name[]={metric_type}&state=closed",
            })

        all_epics = [e for t in self.EPIC_TYPE_DISPLAY_NAMES for e in metrics.get(t, [])]
        by_parent: defaultdict = defaultdict(list)
        for e in all_epics:
            if e.get("parent_id") is not None:
                by_parent[e["parent_id"]].append(e)

        def _node(epic):
            etype    = epic.get("type", self.EPIC_TYPE_DISPLAY_NAMES[0])
            pw       = epic.get("planned_weight", 0) or 0
            aw       = epic.get("actual_weight",  0) or 0
            pct_done = epic.get("pct_complete", 0)
            pct_pi   = epic.get("pct_through_pi")
            if pct_pi is None:
                status_icon = "🔵"
            elif pct_pi >= 100:
                status_icon = "✅" if pct_done >= 100 else "❌"
            else:
                status_icon = "✅" if pct_done >= pct_pi else "⚠️"
            return {
                "id":             epic["id"],
                "title":          epic["title"],
                "url":            epic.get("web_url", ""),
                "type":           etype,
                "icon":           self.EPIC_TYPE_ICONS.get(etype, "🏆"),
                "state":          epic.get("state", ""),
                "pct_done":       pct_done,
                "pct_pi":         pct_pi,
                "planned_weight": pw,
                "actual_weight":  aw,
                "drift":          aw - pw,
                "blocked":        epic.get("blocked_by_count", 0) > 0,
                "status_icon":    status_icon,
                "children":       [_node(c) for c in by_parent.get(epic["id"], [])],
            }

        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "summary":     summary,
            "hierarchy":   [_node(e) for e in metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[0], [])],
        }

    def _data_workload(self) -> dict:
        """Per-PI workload: one row per GitLab group (ART/team) per PI."""
        group        = self._rd_root_obj
        all_epics    = [e for bucket in self._rd_metrics.values() for e in bucket]
        groups_by_id = self._rd_groups_by_id
        today        = date.today()

        pi_group_epics: defaultdict = defaultdict(lambda: defaultdict(list))
        for e in all_epics:
            piid = e.get("piid")
            gid  = e.get("group_id")
            if piid and gid:
                pi_group_epics[piid][gid].append(e)

        def _phase(piid):
            start, end = self._pi_dates_from_label(piid)
            if not start:
                return "unknown"
            if today < start:
                return "future"
            if today > end:
                return "past"
            return "current"

        sorted_pis = sorted(
            pi_group_epics.keys(),
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        pis_out = []
        for piid in sorted_pis:
            phase      = _phase(piid)
            pct_pi     = self._pct_through_pi(piid) or 0
            start, end = self._pi_dates_from_label(piid)
            group_data = pi_group_epics[piid]

            def _avg_pct(fs, total_planned):
                if total_planned:
                    return round(sum(f["planned_weight"] * f["pct_complete"] for f in fs) / total_planned)
                return round(sum(f["pct_complete"] for f in fs) / len(fs)) if fs else 0

            def _risk_key(gid):
                fs = group_data[gid]
                tp = sum(f["planned_weight"] for f in fs)
                ap = _avg_pct(fs, tp)
                if phase == "past":
                    return (0 if ap < 100 else 2, -len(fs))
                if phase == "current":
                    return (0 if ap < pct_pi else 2, -len(fs))
                return (1, -len(fs))

            groups_out = []
            for gid in sorted(group_data.keys(), key=_risk_key):
                fs            = group_data[gid]
                grp           = groups_by_id.get(gid)
                total_planned = sum(f["planned_weight"] for f in fs)
                total_actual  = sum(f["actual_weight"]  for f in fs)
                avg_pct       = _avg_pct(fs, total_planned)

                if phase == "current":
                    status = "⚠️ At Risk" if avg_pct < pct_pi else "✅ On Track"
                elif phase == "past":
                    status = "✅ Complete" if avg_pct == 100 else "❌ Incomplete"
                else:
                    status = "🔵 Planned"

                epics_url = ""
                if grp and grp.get("full_path"):
                    epics_url = (
                        f"{self.url}/groups/{grp['full_path']}/-/work_items"
                        f"?type[]=8&label_name[]={quote(piid, safe='')}"
                    )

                groups_out.append({
                    "name":       grp["name"] if grp else f"Group {gid}",
                    "url":        grp.get("web_url", "") if grp else "",
                    "epics_url":  epics_url,
                    "epic_count": len(fs),
                    "planned":    total_planned,
                    "actual":     total_actual,
                    "delta":      total_actual - total_planned,
                    "avg_pct":    avg_pct,
                    "status":     status,
                })

            pis_out.append({
                "piid":   piid,
                "phase":  phase,
                "pct_pi": pct_pi,
                "start":  start.isoformat() if start else None,
                "end":    end.isoformat()   if end   else None,
                "groups": groups_out,
            })

        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "pis":         pis_out,
        }

    def _data_flow_metrics(self) -> dict:
        """Flow Metrics: velocity, load, distribution, cycle time, predictability."""
        group     = self._rd_root_obj
        today     = date.today()
        all_typed = [e for bucket in self._rd_metrics.values() for e in bucket]
        piids     = self._rd_piid_labels
        feat_types = set(self.EPIC_TYPE_DISPLAY_NAMES[1:])

        def _parse_dt(s):
            if not s:
                return None
            try:
                return date.fromisoformat(str(s)[:10])
            except ValueError:
                return None

        def _age(epic):
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

        def _pct_str(n, total):
            return f"{round(n / total * 100)}%" if total else "—"

        open_epics   = [e for e in all_typed if e.get("state", "").lower() != "closed"]
        closed_epics = [e for e in all_typed if e.get("state", "").lower() == "closed"]

        # Section 1: velocity
        velocity = []
        for pi in piids:
            pi_closed = [e for e in closed_epics if e.get("piid") == pi and e.get("type") in feat_types]
            feat_c = sum(1 for e in pi_closed if e["type"] == self.EPIC_TYPE_DISPLAY_NAMES[-1])
            cap_c  = sum(1 for e in pi_closed if e["type"] == self.EPIC_TYPE_DISPLAY_NAMES[1])
            velocity.append({"piid": pi, "features": feat_c, "capabilities": cap_c, "total": feat_c + cap_c})

        # Section 2: load (WIP)
        _t0, _t1, _t2 = self.EPIC_TYPE_DISPLAY_NAMES[0], self.EPIC_TYPE_DISPLAY_NAMES[1], self.EPIC_TYPE_DISPLAY_NAMES[-1]
        load = []
        for pi in piids:
            pi_open = [e for e in open_epics if e.get("piid") == pi]
            f  = sum(1 for e in pi_open if e["type"] == _t2)
            c  = sum(1 for e in pi_open if e["type"] == _t1)
            ep = sum(1 for e in pi_open if e["type"] == _t0)
            pw = sum(e.get("planned_weight") or 0 for e in pi_open)
            load.append({"piid": pi, "features": f, "capabilities": c, "epics": ep, "total": f + c + ep, "planned_weight": pw})

        no_pi_open = [e for e in open_epics if not e.get("piid")]
        load_no_pi = None
        if no_pi_open:
            f  = sum(1 for e in no_pi_open if e["type"] == _t2)
            c  = sum(1 for e in no_pi_open if e["type"] == _t1)
            ep = sum(1 for e in no_pi_open if e["type"] == _t0)
            pw = sum(e.get("planned_weight") or 0 for e in no_pi_open)
            load_no_pi = {"features": f, "capabilities": c, "epics": ep, "total": f + c + ep, "planned_weight": pw}

        # Section 3: distribution
        total_epics = len(all_typed)
        total_pw    = sum(e.get("planned_weight") or 0 for e in all_typed)
        by_type = []
        for t in reversed(self.EPIC_TYPE_DISPLAY_NAMES):
            bucket = self._rd_metrics.get(t, [])
            pw     = sum(e.get("planned_weight") or 0 for e in bucket)
            by_type.append({
                "type":           t,
                "count":          len(bucket),
                "pct_items":      _pct_str(len(bucket), total_epics),
                "planned_weight": pw,
                "pct_weight":     _pct_str(pw, total_pw),
            })

        work_type_set = set(self._rd_work_type_labels)
        has_wt = bool(work_type_set)
        by_work_type    = []
        unlabeled_count = 0
        if has_wt:
            labeled         = [e for e in all_typed if set(e.get("labels", [])) & work_type_set]
            unlabeled_count = len(all_typed) - len(labeled)
            n_lab           = len(labeled) or 1
            targets = {
                "type::feature":        "~50%",
                "type::enabler":        "~30%",
                "type::infrastructure": "~20%",
                "type::defect":         "minimize",
            }
            for lbl in sorted(work_type_set):
                epics_lbl = [e for e in all_typed if lbl in e.get("labels", [])]
                by_work_type.append({
                    "label":         lbl,
                    "count":         len(epics_lbl),
                    "pct_labelled":  _pct_str(len(epics_lbl), n_lab),
                    "safe_target":   targets.get(lbl, "—"),
                })

        # Section 4: flow time
        open_ages = []
        for t in reversed(self.EPIC_TYPE_DISPLAY_NAMES):
            bucket = [e for e in open_epics if e.get("type") == t]
            ages   = [a for a in (_age(e) for e in bucket) if a is not None]
            open_ages.append({
                "type":     t,
                "count":    len(bucket),
                "avg_days": _avg(ages),
                "min_days": min(ages) if ages else None,
                "max_days": max(ages) if ages else None,
            })

        closed_cycles = []
        for t in reversed(self.EPIC_TYPE_DISPLAY_NAMES):
            bucket = [e for e in closed_epics if e.get("type") == t]
            times  = [a for a in (_age(e) for e in bucket) if a is not None]
            closed_cycles.append({
                "type":     t,
                "count":    len(bucket),
                "avg_days": _avg(times),
                "min_days": min(times) if times else None,
                "max_days": max(times) if times else None,
            })

        # Section 5: predictability
        predictability = []
        for pi in piids:
            pi_epics  = [e for e in all_typed if e.get("piid") == pi and e.get("type") in feat_types]
            if not pi_epics:
                continue
            committed = len(pi_epics)
            delivered = sum(1 for e in pi_epics if e.get("state", "").lower() == "closed")
            pct       = round(delivered / committed * 100) if committed else 0
            icon      = "🟢" if pct >= 80 else ("🟡" if pct >= 60 else "🔴")
            predictability.append({"piid": pi, "committed": committed, "delivered": delivered, "pct": pct, "icon": icon})

        # Current PI: the PI whose date range contains today; fall back to most recent past PI.
        current_piid = None
        for pi in piids:
            pct_pi = self._pct_through_pi(pi)
            if pct_pi is not None and 0 < pct_pi < 100:
                current_piid = pi
                break
        if current_piid is None:
            past = [pi for pi in piids if (self._pct_through_pi(pi) or 0) >= 100]
            current_piid = past[-1] if past else (piids[-1] if piids else None)

        return {
            "report_date":  today.isoformat(),
            "current_piid": current_piid,
            "group":        {"name": group.name, "url": group.web_url},
            "velocity":     velocity,
            "load":         load,
            "load_no_pi":   load_no_pi,
            "distribution": {
                "total_epics":          total_epics,
                "total_planned_weight": total_pw,
                "by_type":              by_type,
                "has_work_type_labels": has_wt,
                "by_work_type":         by_work_type,
                "unlabeled_count":      unlabeled_count,
            },
            "flow_time": {
                "open_ages":      open_ages,
                "closed_cycles":  closed_cycles,
                "has_closed_data": bool(closed_epics),
            },
            "predictability": predictability,
        }

    def generate_portfolio_health_dashboard(self):
        """Tier 1 executive pulse — single wiki page with per-VS traffic-light status."""
        root_group = self._rd_root_obj
        print(f"Generating Portfolio Health Dashboard for: {root_group.full_path}")

        d = self._data_portfolio_health()

        today      = date.fromisoformat(d["report_date"])
        current_pi = d["pi"]["current"]
        pct_pi     = d["pi"]["pct_elapsed"]
        pi_start   = date.fromisoformat(d["pi"]["start"]) if d["pi"]["start"] else None
        pi_end     = date.fromisoformat(d["pi"]["end"])   if d["pi"]["end"]   else None

        portfolio_epics_total   = d["portfolio"]["epics_total"]
        portfolio_blocked_total = d["portfolio"]["blocked_total"]
        portfolio_risk_epics    = d["portfolio"]["risk_epics"]
        portfolio_unassigned    = d["portfolio"]["unassigned"]
        all_pi_epics_count      = d["portfolio"]["pi_epics_count"]
        port_pct_done           = d["portfolio"]["pct_done"]
        port_tl_sched           = d["portfolio"]["tl_schedule"]
        port_wt_str             = d["portfolio"]["capacity_str"]
        vs_rows                 = d["vs_rows"]
        top_blocked             = d["top_blocked"]
        at_risk_epics           = d["at_risk_epics"]

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
            f"**Group:** {_mlink(root_group.name, root_group.web_url)}"
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

        _epics_base = f"{root_group.web_url}/-/epics"

        def _wi(params):
            parts = [f"{_pquote(k, safe='')}={_pquote(v, safe='')}" for k, v in params]
            return f"{_epics_base}?{'&'.join(parts)}"

        _wi_all   = _wi([("state", "all")])
        _wi_pi    = (
            _wi([("state", "opened"), ("label_name[]", current_pi)])
            if current_pi else _wi_all
        )
        # ROAM risks are linked issues, not labels — no epics-filter URL can show them;
        # link to the Risk Register wiki page instead.
        _wi_risk  = f"{root_group.web_url}/-/wikis/{_wiki_slug(f'{self._wiki_t2}/Risk Register')}"
        _wi_unasn = _wi([("state", "opened")])

        md.append("## Portfolio Summary")
        md.append("")
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Total Epics (all PIs) | <a href=\"{_wi_all}\" target=\"_blank\">{portfolio_epics_total}</a> |")
        md.append(f"| Epics in Current PI | <a href=\"{_wi_pi}\" target=\"_blank\">{all_pi_epics_count}</a> |")
        md.append(
            f"| Current PI Progress | <a href=\"{_wi_pi}\" target=\"_blank\">{port_pct_done}% done</a>  "
            f"({pct_pi}% elapsed) {port_tl_sched} |"
        )
        md.append(f"| Blocked Epics (current PI) | <a href=\"{_wi_pi}\" target=\"_blank\">{portfolio_blocked_total}</a> |")
        md.append(f"| Epics with Active ROAM Risks | <a href=\"{_wi_risk}\" target=\"_blank\">{portfolio_risk_epics}</a> |")
        md.append(f"| Unassigned to PI | <a href=\"{_wi_unasn}\" target=\"_blank\">{portfolio_unassigned}</a> |")
        if port_wt_str != "—":
            md.append(f"| Story Points (current PI) | {port_wt_str} |")
        md.append("")

        md.append("## Value Stream Status")
        md.append("")
        md.append("| Value Stream | Status | Schedule | Capacity | Risk | Blocking | Epics | Unassigned |")
        md.append("|---|---|---|---|---|---|---|---|")

        for row in vs_rows:
            vs      = row["vs"]
            vs_link = _mlink(vs['name'], vs['web_url'])
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
            md.append("| Epic | Blockers | PI |")
            md.append("|------|---------|-----|")
            for item in top_blocked:
                etype = item["type"]
                icon  = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                link  = (
                    f'[{icon} {item["title"]}]({item["url"]})'
                    if item["url"] else f'{icon} {item["title"]}'
                )
                md.append(f"| {link} | {item['n_blockers']} | {item['piid']} |")
        else:
            md.append("✅ No blocked epics found.")
        md.append("")

        md.append("### 🟡 At-Risk Epics (behind schedule)")
        md.append("")
        if at_risk_epics:
            md.append("| Epic | Done | PI Elapsed | Gap | Weight | PI |")
            md.append("|------|------|-----------|-----|--------|-----|")
            for item in at_risk_epics:
                etype = item["type"]
                icon  = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                link  = (
                    f'[{icon} {item["title"]}]({item["url"]})'
                    if item["url"] else f'{icon} {item["title"]}'
                )
                md.append(
                    f"| {link} | {item['pct_done']}% "
                    f"| {item['pct_elapsed']}% | {item['gap']}pp "
                    f"| {item['weight_str']} | {item['piid']} |"
                )
        else:
            md.append("✅ No epics significantly behind schedule.")
        md.append("")

        md.extend(_LEGEND_OPEN + [
            _side_by_side(
                ("Epic Type Icons", [(self.EPIC_TYPE_ICONS.get(t, "?"), t) for t in self.EPIC_TYPE_DISPLAY_NAMES]),
                ("Status Icons",    [("🟢", "On track — within threshold"),
                                     ("🟡", "Watch — approaching threshold"),
                                     ("🔴", "At risk — threshold exceeded"),
                                     ("⬜", "No data"),
                                     ("⛔", "Blocked epic")]),
            ),
            "",
            "### Column Definitions",
            "",
            "**Schedule** — % complete vs % of PI calendar elapsed  ",
            "**Capacity** — issue story-point total vs epic planned weight for current PI; "
            "⬜ = ratio not applicable (no issues yet, no epic weight, or mixed — "
            "some epics estimated via issues, others scoped at epic level only)  ",
            "**Risk** — presence of ROAM risk issues linked to epics in this Value Stream  ",
            "**Blocking** — count of epics with at least one blocker in current PI  ",
            "",
            "### Traffic Light Thresholds",
            "",
            "| Column | 🟢 On Track | 🟡 Watch | 🔴 At Risk |",
            "|--------|------------|---------|-----------|",
            "| Schedule | ≤ 10pp behind PI elapsed | ≤ 20pp behind | > 20pp behind |",
            "| Capacity | 80–110% loaded | 70–120% | Outside 70–120% |",
            "| Risk | No active ROAM risks | 1–2 active risks | 3+ active risks |",
            "| Blocking | 0 blockers | 1–2 blockers | 3+ blockers |",
        ] + _LEGEND_CLOSE)

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
            f"**Group:** {_mlink(gn, group.web_url)}"
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

        epics_base = f"{group.web_url}/-/epics"

        def _wi_lc(lc_key):
            return (
                f"{epics_base}?state=all"
                f"&label_name[]={quote(lc_key, safe='')}"
            )

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
            count   = f'<a href="{_wi_lc(key)}" target="_blank">{len(epics)}</a>' if epics else "0"
            md.append(
                f"| {label} | {count} | {avg_str} | {old_str}{warn} | {t_str} |"
            )
        unlab = buckets["_unlabelled"]
        avg_u = _avg_age(unlab)
        # GitLab epics browser has no URL filter for "no lifecycle label" — link to the
        # dedicated unlabelled section on the Epic Lifecycle wiki page instead.
        _lc_page = (
            f"{group.web_url}/-/wikis/{_wiki_slug(f'{self._wiki_t3}/Epic Lifecycle')}"
            "#unlabelled"
        )
        unlab_count = (
            f'<a href="{_lc_page}" target="_blank">{len(unlab)}</a>'
            if unlab else "0"
        )
        md.append(
            f"| _(unlabelled)_ | {unlab_count} | "
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
            md.append("| Epic | Type | Age | PI | Group |")
            md.append("|------|------|-----|----|-------|")
            for e in sorted(stuck, key=lambda x: _age_days(x) or 0, reverse=True):
                age = _age_days(e) or 0
                md.append(
                    f"| {_mlink(e['title'][:50], e['web_url'])} | {e.get('type','?')} | **{age}d** "
                    f"| {_pi(e)} | {_group_name(e)} |"
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
            md.append("| Epic | Type | Age | PI | Group |")
            md.append("|------|------|-----|----|-------|")
            for e in sorted(epics, key=lambda x: _age_days(x) or 0, reverse=True):
                age     = _age_days(e)
                age_str = f"**{age}d** ⚠️" if (thresh and age and age > thresh) else (f"{age}d" if age else "—")
                md.append(
                    f"| {_mlink(e['title'][:50], e['web_url'])} | {e.get('type','?')} | {age_str} "
                    f"| {_pi(e)} | {_group_name(e)} |"
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
            md.append("| Epic | Type | Age | PI | Group |")
            md.append("|------|------|-----|----|-------|")
            for e in sorted(unlab, key=lambda x: _age_days(x) or 0, reverse=True):
                age = _age_days(e)
                md.append(
                    f"| {_mlink(e['title'][:50], e['web_url'])} | {e.get('type','?')} | {age or '—'} "
                    f"| {_pi(e)} | {_group_name(e)} |"
                )
            md.append("")

        md.append("---")

        # ── About section ─────────────────────────────────────────────── #
        md.extend(["---", "<details>", "<summary>ℹ️ SAFe Portfolio Kanban States</summary>", ""])
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
        md.extend(["", "</details>"])

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
            f"**Group:** {_mlink(gn, group.web_url)}"
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

        feat_types = set(self.EPIC_TYPE_DISPLAY_NAMES[1:])
        _dn = self.EPIC_TYPE_DISPLAY_NAMES
        vel_rows = []
        for pi in piids:
            pi_closed = [
                e for e in closed_epics
                if e.get("piid") == pi and e.get("type") in feat_types
            ]
            counts = {t: sum(1 for e in pi_closed if e["type"] == t) for t in _dn[1:]}
            vel_rows.append((pi, counts))

        md.append("| PI | " + " | ".join(f"{t[:-1]}ies" if t.endswith("y") else f"{t}s" for t in _dn[1:]) + " | Total Delivered |")
        md.append("|----|" + "----------|" * len(_dn[1:]) + "-----------------|")
        for pi, counts in vel_rows:
            cells = " | ".join(str(counts[t]) for t in _dn[1:])
            md.append(f"| `{pi}` | {cells} | **{sum(counts.values())}** |")

        total_delivered = sum(sum(counts.values()) for _, counts in vel_rows)
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

        md.append("| PI | " + " | ".join(_dn) + " | Total | Planned Weight |")
        md.append("|----|" + "----------|" * len(_dn) + "-------|----------------|")
        no_pi_open = [e for e in open_epics if not e.get("piid")]
        for pi in piids:
            pi_open = [e for e in open_epics if e.get("piid") == pi]
            counts = {t: sum(1 for e in pi_open if e["type"] == t) for t in _dn}
            pw  = sum(e.get("planned_weight") or 0 for e in pi_open)
            cells = " | ".join(str(counts[t]) for t in _dn)
            md.append(f"| `{pi}` | {cells} | **{sum(counts.values())}** | {pw:,} |")
        if no_pi_open:
            counts = {t: sum(1 for e in no_pi_open if e["type"] == t) for t in _dn}
            pw  = sum(e.get("planned_weight") or 0 for e in no_pi_open)
            cells = " | ".join(str(counts[t]) for t in _dn)
            md.append(f"| _(no PI)_ | {cells} | **{sum(counts.values())}** | {pw:,} |")
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
        for t in reversed(_dn):
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
        for t in reversed(_dn):
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
            for t in reversed(_dn):
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
            f"{_mlink('PI Predictability Scorecard', f'{base}/{scorecard_slug}')}"
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
        md.extend(["---", "<details>", "<summary>ℹ️ About Flow Metrics</summary>", ""])
        md.append(
            "SAFe 6.0 flow metrics measure *how efficiently* work moves through the portfolio, "
            "not just whether it is on schedule. Six metrics are defined at Team, ART, and Portfolio level:"
        )
        md.append("")
        md.append("| Metric | This Report | Status |")
        md.append("|--------|-------------|--------|")
        md.append("| Flow Velocity | Delivered epics per PI | ✅ |")
        md.append("| Flow Load | Open epics per PI (WIP) | ✅ |")
        md.append("| Flow Distribution | Work type mix | ✅ |")
        md.append("| Flow Time | Cycle time (open age + closed proxy) | ✅ |")
        md.append("| Flow Predictability | % PI objectives met | ✅ (link to Scorecard) |")
        md.append("| Flow Efficiency | Value-added vs wait time | ⬜ Requires time tracking |")
        md.extend(["", "</details>"])

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
            value   = epic.get("business_value")
            urgency = _label_val(labels, "wsjf-urgency::")
            risk    = _label_val(labels, "wsjf-risk::")
            if value is None and urgency is None and risk is None:
                continue
            size  = epic.get("planned_weight") or None  # None → partial score
            v, u, r = (value or 0), (urgency or 0), (risk or 0)
            score = round((v + u + r) / size, 2) if size else None
            candidates.append({
                "epic":    epic,
                "type":    self._epic_type_display(labels),
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
            f"**Group:** {_mlink(group.name, group.web_url)}"
        )
        md.append("")
        md.append(
            "Weighted Shortest Job First (WSJF) ranks portfolio backlog items by the ratio of "
            "Cost of Delay to Job Size. Higher score = should be sequenced first."
        )
        md.append("")

        if not candidates:
            md.append(
                "_No WSJF-scored epics found. Set the Business Value custom field via "
                "`set-business-value`, and apply `wsjf-urgency::N` and `wsjf-risk::N` labels "
                "(Fibonacci scale: 1, 2, 3, 5, 8, 13) to open epics._"
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
            md.append("| Rank | Epic | Type | PI | BV | Urgency | Risk | Size | WSJF |")
            md.append("|------|------|------|----|----|---------|------|------|------|")

            for rank, c in enumerate(candidates, 1):
                epic   = c["epic"]
                icon   = self.EPIC_TYPE_ICONS.get(c["type"], "🏆")
                link   = _mlink(epic['title'], epic['web_url'])
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

        # ── Blocked Business Value ───────────────────────────────────────
        bv_by_id      = {e["id"]: e.get("business_value")
                         for tier in self._rd_metrics.values() for e in tier}
        epic_url_by_id = {e["id"]: e.get("web_url", "")
                          for tier in self._rd_metrics.values() for e in tier}

        # rows: (pe_id, pe_link, pe_bv, blocked_link, type_str, blocker_str)
        bv_rows       = []
        seen_pe_bv    = {}  # pe_id → bv — deduped for total
        seen_pe_link  = {}  # pe_id → link — first-seen
        seen_pe_type  = {}  # pe_id → type string — first-seen
        pe_blocked_ct = {}  # pe_id → count of blocked items

        for rel in self._rd_blocking.get("relationships", []):
            blocked  = rel["blocked_epic"]
            blockers = rel.get("blocked_by", [])
            ancs     = rel.get("at_risk_portfolio_epics", [])

            # Resolve the "Epic at Risk" (Portfolio Epic) distinctly from the
            # "Blocked Item" (Capability/Feature). Expected hierarchy: the blocked
            # Cap/Feature rolls up to a Portfolio Epic, so `ancs` carries the at-risk
            # Portfolio Epic(s) and the columns stay distinct (Refs #108).
            #   • Blocked item IS a Portfolio Epic → it is its own at-risk epic.
            #   • Otherwise → use the resolved ancestors.
            # If a non-Portfolio-Epic blocked item has NO Portfolio Epic ancestor
            # (orphaned data), keep the row but leave "Epic at Risk"/BV blank and
            # exclude it from the BV rollup rather than collapsing the column onto
            # the blocked item (Refs #108). The data generator avoids creating such
            # blocks, so this only surfaces genuinely orphaned real-world data.
            _t0 = self.EPIC_TYPE_DISPLAY_NAMES[0]
            pe_candidates = ([blocked] + ancs) if blocked.get("type") == _t0 else ancs

            blocker_str  = ", ".join(
                _mlink(b['title'], b['web_url']) if b.get("web_url") else b["title"]
                for b in blockers
            )
            b_type  = blocked.get("type", _t0)
            b_icon  = self.EPIC_TYPE_ICONS.get(b_type, "🏆")
            bl_link = (_mlink(blocked['title'], blocked['web_url'])
                       if blocked.get("web_url") else blocked["title"])

            if not pe_candidates:
                # Orphan: no Portfolio Epic at risk — blank "Epic at Risk"/BV and
                # omit from the rollup (pe_id None keeps it out of seen_pe_*).
                bv_rows.append((None, "", None, bl_link, f"{b_icon} {b_type}", blocker_str))
                continue

            for pe in pe_candidates:
                pe_id   = pe.get("id") or pe.get("id_int")
                pe_bv   = bv_by_id.get(pe_id)
                pe_url  = pe.get("web_url") or epic_url_by_id.get(pe_id, "")
                pe_link = _mlink(pe['title'], pe_url) if pe_url else pe["title"]
                pe_type = pe.get("type", _t0)
                bv_rows.append((pe_id, pe_link, pe_bv, bl_link, f"{b_icon} {b_type}", blocker_str))
                if pe_id not in seen_pe_bv:
                    seen_pe_bv[pe_id]   = pe_bv
                    seen_pe_link[pe_id] = pe_link
                    seen_pe_type[pe_id] = pe_type
                pe_blocked_ct[pe_id] = pe_blocked_ct.get(pe_id, 0) + 1

        if bv_rows:
            total_bv    = sum(v for v in seen_pe_bv.values() if v is not None)
            n_pe        = len(seen_pe_bv)
            pe_word     = "Portfolio Epics" if n_pe != 1 else "Portfolio Epic"
            bv_rows.sort(key=lambda x: (x[2] is None, -(x[2] or 0)))

            md.append("## Blocked Business Value")
            md.append("")
            md.append(f"**Total Business Value at Risk: {total_bv}** _(sum of {n_pe} distinct {pe_word})_")
            md.append("")

            pe_summary = sorted(
                [(pid, seen_pe_link[pid], seen_pe_bv[pid], seen_pe_type[pid], pe_blocked_ct[pid])
                 for pid in seen_pe_bv],
                key=lambda x: (x[2] is None, -(x[2] or 0)),
            )
            for _, pe_link, pe_bv, _pe_type, _n_blocked in pe_summary:
                bv_str = str(pe_bv) if pe_bv is not None else "—"
                md.append(f"- {pe_link} — BV: {bv_str}")
            md.append("")

            md.append("### Blocking Detail")
            md.append("")
            md.append("| Epic at Risk | BV | Blocked Item | Type | Blocker(s) |")
            md.append("|---|---|---|---|---|")
            for _, pe_link, pe_bv, bl_link, type_str, blocker_str in bv_rows:
                bv_str = str(pe_bv) if pe_bv is not None else "—"
                md.append(f"| {pe_link} | {bv_str} | {bl_link} | {type_str} | {blocker_str} |")
            md.append("")

        md.extend([
            "---",
            "<details>",
            "<summary>How WSJF Works</summary>",
            "",
            "**WSJF = (Business Value + Time Criticality + Risk Reduction) ÷ Job Size**",
            "",
            "| Component | Source | What it measures |",
            "|-----------|--------|-----------------|",
            "| Business Value | Custom field (Fibonacci 1–21) | Economic benefit — set via `set-business-value` or the GitLab epic UI |",
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
            "</details>",
        ])

        self.upload_to_wiki(group, f"{self._wiki_t2}/WSJF Priority Board", "\n".join(md))
        print(f"  → Wiki: {self._wiki_t2}/WSJF Priority Board")

    # ------------------------------------------------------------------
    # Environment & API Diagnostics
    # ------------------------------------------------------------------

    def generate_diagnostics_report(self):
        """Standalone report: run diagnostics and write quarto-data/diagnostics.json."""
        self._generate_diagnostics_section()

    def _generate_diagnostics_section(self, for_wiki=True) -> list:
        """Return lines for the environment & API diagnostics output.

        for_wiki=True  — markdown in a <details> block; also saves data/diagnostics.json.
        for_wiki=False — plain text formatted for terminal / log-pane reading (no markdown).
        """
        from importlib.metadata import version as _pkg_ver, PackageNotFoundError

        def _pkg(name):
            try:
                return _pkg_ver(name)
            except PackageNotFoundError:
                return "not installed"

        # ── 1. Collect all data (mode-independent) ─────────────────────

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        try:
            gl_version, _ = self.gl.version()
        except Exception as e:
            gl_version = f"error: {e}"
        try:
            _ns_list = self.gl.namespaces.list(search=self.parent_group)
            if _ns_list:
                _ns    = self.gl.namespaces.get(_ns_list[0].id)
                _plan  = getattr(_ns, "plan",  None) or "unknown"
                _trial = getattr(_ns, "trial", False)
                gl_tier = _plan.capitalize() + (" (trial)" if _trial else "")
            else:
                gl_tier = "unknown (namespace not found)"
        except Exception as e:
            gl_tier = f"error: {e}"

        version_rows = [
            ("Python",          py_ver),
            ("python-gitlab",   _pkg("python-gitlab")),
            ("requests",        _pkg("requests")),
            ("pandas",          _pkg("pandas")),
            ("python-dateutil", _pkg("python-dateutil")),
            ("plotly",          _pkg("plotly")),
            ("marimo",          _pkg("marimo")),
            ("jupyter",         _pkg("jupyter")),
            ("nbformat",        _pkg("nbformat")),
            ("GitLab Server",   gl_version),
            ("GitLab Tier",     gl_tier),
        ]

        config_rows = [
            ("GitLab URL",                    self.url),
            ("Parent Group",                  self.parent_group),
            ("Epic Type Labels (reports)",    ", ".join(self.EPIC_TYPE_LABELS) or "none configured"),
            ("Risk Labels (reports)",         ", ".join(self.RISK_LABELS)      or "none configured"),
            ("Lifecycle Labels (reports)",    ", ".join(self.LIFECYCLE_LABELS) or "none configured"),
            ("PIID Labels (create-lorem)",    ", ".join(self.PIID_LABELS)      or "none configured"),
            ("Project Labels (create-lorem)", ", ".join(self.PROJECT_LABELS)   or "none configured"),
        ]

        group = getattr(self, "_rd_root_obj", None) or self.get_group_by_name(self.parent_group)

        def _rest_probe(label, fn, endpoint):
            try:
                fn()
                return (True, label, endpoint, "")
            except Exception as e:
                code   = getattr(e, "response_code", None) or ""
                detail = f"HTTP {code}: {e}" if code else str(e)[:120]
                return (False, label, endpoint, detail)

        r_epics      = _rest_probe("Group Epics",      lambda: group.epics.list(per_page=1, get_all=False),      "GET /groups/:id/epics")
        r_wiki       = _rest_probe("Group Wiki",       lambda: group.wikis.list(per_page=1, get_all=False),      "GET /groups/:id/wikis")
        r_labels     = _rest_probe("Group Labels",     lambda: group.labels.list(per_page=1, get_all=False),     "GET /groups/:id/labels")
        r_milestones = _rest_probe("Group Milestones", lambda: group.milestones.list(per_page=1, get_all=False), "GET /groups/:id/milestones")
        if r_epics[0]:
            try:
                _s = group.epics.list(per_page=1, get_all=False)
                if _s:
                    _s[0].issues.list(per_page=1, get_all=False)
                r_epic_issues = (True, "Epic Issues", "GET /groups/:id/epics/:iid/issues", "")
            except Exception as e:
                r_epic_issues = (False, "Epic Issues", "GET /groups/:id/epics/:iid/issues", str(e)[:120])
        else:
            r_epic_issues = (None, "Epic Issues", "GET /groups/:id/epics/:iid/issues", "skipped — group epics unavailable")
        rest_rows = [r_epics, r_wiki, r_labels, r_milestones, r_epic_issues]

        p = group.full_path

        def _gql_ok(query, variables=None, expect_key=None):
            try:
                r = self.graphql_query(query, variables=variables)
                if r is None:
                    return False
                return expect_key is None or expect_key in r
            except Exception:
                return False

        _blocking_fields_ok = _gql_ok(
            "query D($p:ID!){group(fullPath:$p){epics(first:1){nodes{blocked blockedByCount blockingCount}}}}",
            {"p": p}, "group",
        )
        _blocked_by_ok = _gql_ok(
            "query D($p:ID!){group(fullPath:$p){epics(first:1){nodes{blockedByEpics{edges{node{title}}}}}}}",
            {"p": p}, "group",
        )
        _weight_ok = None
        try:
            _sample = group.epics.list(per_page=1, get_all=False)
            _wid    = getattr(_sample[0], "work_item_id", None) if _sample else None
            if _wid:
                _weight_ok = _gql_ok(
                    "query D($id:WorkItemID!){workItem(id:$id){widgets{...on WorkItemWidgetWeight{weight}}}}",
                    {"id": f"gid://gitlab/WorkItem/{_wid}"}, "workItem",
                )
        except Exception:
            pass
        _custom_fields_ok = _gql_ok(
            "query D($p:ID!){namespace(fullPath:$p){customFields{nodes{id}}}}",
            {"p": p}, "namespace",
        )
        _linked_wi_ok = _gql_ok(
            "query D($p:ID!){group(fullPath:$p){issues(first:1){nodes{linkedWorkItems(first:1){nodes{workItem{id}}}}}}}",
            {"p": p}, "group",
        )
        _wi_types_ok = _gql_ok(
            "query D($p:ID!){group(fullPath:$p){workItemTypes{nodes{id name}}}}",
            {"p": p}, "group",
        )

        gql_rows = [
            (_blocking_fields_ok, "Epic blocking fields",   "Epic.blocked / blockedByCount / blockingCount — Blocking & Cross-ART Risk (Ultimate)"),
            (_blocked_by_ok,      "Epic.blockedByEpics",    "Full blocked-by list — Blocking & Cross-ART Risk (Ultimate)"),
            (_weight_ok,          "WorkItemWidgetWeight",   "Epic/issue weight via workItem GraphQL — WSJF, Capacity, PI Matrix"),
            (_custom_fields_ok,   "Namespace.customFields", "Custom field definitions — Business Value (Ultimate + GitLab 17+)"),
            (_linked_wi_ok,       "Issue.linkedWorkItems",  "Linked work items on issues — ROAM risk linking"),
            (_wi_types_ok,        "Group.workItemTypes",    "Work item type GIDs — required for weight/BV write mutations"),
        ]

        # Only validate labels that reports filter by at query time.
        # PIID_LABELS and PROJECT_LABELS are bootstrap-only; reports discover
        # those dynamically from live epic labels in the snapshot.
        all_configured = sorted(set(self.EPIC_TYPE_LABELS + self.RISK_LABELS))
        label_rows = None
        if all_configured:
            try:
                _existing = {lbl.name for lbl in group.labels.list(get_all=True)}
                label_rows = [(lbl, lbl in _existing) for lbl in all_configured]
            except Exception as e:
                label_rows = [(f"error fetching labels: {e}", None)]

        epics_ok    = r_epics[0]
        wiki_ok     = r_wiki[0]
        blocking_ok = _blocking_fields_ok and _blocked_by_ok

        assess_rows = [
            (epics_ok,          "All reports (read epics)",         "Group Epics REST API — requires Premium/Ultimate"),
            (wiki_ok,           "Wiki publishing",                  "Group Wiki REST API — requires Premium/Ultimate"),
            (_weight_ok,        "Weights (WSJF, Capacity, Matrix)", "WorkItemWidgetWeight via workItem GraphQL"),
            (blocking_ok,       "Blocking & Cross-ART Risk",        "Epic blocking fields + blockedByEpics — requires Ultimate"),
            (_custom_fields_ok, "Business Value / Custom Fields",   "Namespace.customFields — requires Ultimate + GitLab 17+"),
            (_linked_wi_ok,     "ROAM Risk issue linking",          "Issue.linkedWorkItems GraphQL field"),
            (_wi_types_ok,      "Weight / BV write mutations",      "Group.workItemTypes — required to resolve work item type GIDs"),
        ]

        critical = epics_ok and wiki_ok
        full     = critical and bool(_weight_ok) and bool(blocking_ok) and bool(_custom_fields_ok)
        if full:
            verdict_plain = "✅ Full compatibility — all API features detected. Reports should generate correctly."
            verdict_md    = "**✅ Full compatibility** — all API features detected. Reports should generate correctly."
        elif critical:
            verdict_plain = ("⚠️  Partial compatibility — core reports will upload, but some sections may be "
                             "empty (blocking, custom fields, or ROAM risk features not available at this GitLab tier).")
            verdict_md    = ("**⚠️ Partial compatibility** — core reports will upload, but some sections may be "
                             "empty (blocking, custom fields, or ROAM risk features not available at this GitLab tier).")
        elif epics_ok:
            verdict_plain = ("⚠️  Limited compatibility — epics are accessible but wiki publishing failed. "
                             "Check GitLab Premium/Ultimate license and group wiki settings.")
            verdict_md    = ("**⚠️ Limited compatibility** — epics are accessible but wiki publishing failed. "
                             "Check GitLab Premium/Ultimate license and group wiki settings.")
        else:
            verdict_plain = ("❌ Incompatible — the Group Epics API is not accessible. All reports will fail "
                             "or produce empty output. GitLab Premium or Ultimate is required.")
            verdict_md    = ("**❌ Incompatible** — the Group Epics API is not accessible. All reports will fail "
                             "or produce empty output. GitLab Premium or Ultimate is required.")

        # ── 2. Render ──────────────────────────────────────────────────

        def _icon(ok):
            if ok is True:  return "✅"
            if ok is False: return "❌"
            return "⚠️"

        if not for_wiki:
            # Plain text — no markdown syntax, aligned for terminal / log-pane reading
            W   = 64
            out = ["", "🔧  Environment & API Diagnostics", "═" * W, ""]

            # Software versions — two-column aligned
            out += ["Software Versions", "─" * 17]
            kw   = max(len(k) for k, _ in version_rows)
            out += [f"  {k:<{kw}}  {v}" for k, v in version_rows]
            out.append("")

            # Configuration — two-column aligned
            out += ["Configuration", "─" * 13]
            kw   = max(len(k) for k, _ in config_rows)
            out += [f"  {k:<{kw}}  {v}" for k, v in config_rows]
            out.append("")

            # REST probes — icon + name + endpoint [+ detail]
            out += ["REST API Capabilities", "─" * 21]
            nw   = max(len(r[1]) for r in rest_rows)
            for ok, name, endpoint, detail in rest_rows:
                suffix = f"  {detail}" if detail else ""
                out.append(f"  {_icon(ok)}  {name:<{nw}}  {endpoint}{suffix}")
            out.append("")

            # GraphQL probes — icon + name + description
            out += ["GraphQL API Capabilities", "─" * 24]
            nw   = max(len(r[1]) for r in gql_rows)
            for ok, name, desc in gql_rows:
                out.append(f"  {_icon(ok)}  {name:<{nw}}  {desc}")
            out.append("")

            # Label validation — icon + label name
            if label_rows:
                out += ["Key Label Validation", "─" * 20]
                for lbl, present in label_rows:
                    out.append(f"  {_icon(present)}  {lbl}")
                out.append("")

            # Compatibility assessment — icon + feature + requirement
            out += ["Report Compatibility Assessment", "─" * 31]
            fw   = max(len(r[1]) for r in assess_rows)
            for ok, feature, req in assess_rows:
                out.append(f"  {_icon(ok)}  {feature:<{fw}}  {req}")
            out.append("")

            out += ["═" * W, verdict_plain, "═" * W, ""]
            return out

        # ── Markdown for wiki ──────────────────────────────────────────

        def _ok_md(val):
            if val is True:  return "✅"
            if val is False: return "❌"
            return "⚠️"

        def _compat_md(val):
            if val is True:  return "✅ Yes"
            if val is False: return "❌ No"
            return "⚠️ Unknown"

        def _lbl_md(labels):
            return ", ".join(f"`{l}`" for l in labels) if labels else "_none configured_"

        body = []
        body += ["### Software Versions", "", "| Component | Version |", "|-----------|---------|"]
        for k, v in version_rows:
            body.append(f"| {k} | `{v}` |")
        body.append("")

        body += ["### Configuration", "", "| Setting | Value | Used By |", "|---------|-------|---------|",
                 f"| GitLab URL | `{self.url}` | all |",
                 f"| Parent Group | `{self.parent_group}` | all |",
                 f"| Epic Type Labels | {_lbl_md(self.EPIC_TYPE_LABELS)} | reports (filter) |",
                 f"| Risk Labels | {_lbl_md(self.RISK_LABELS)} | reports (filter) |",
                 f"| Lifecycle Labels | {_lbl_md(self.LIFECYCLE_LABELS)} | reports (filter) |",
                 f"| PIID Labels | {_lbl_md(self.PIID_LABELS)} | create-lorem only — reports discover live |",
                 f"| Project Labels | {_lbl_md(self.PROJECT_LABELS)} | create-lorem only — reports discover live |",
                 ""]

        body += ["### REST API Capabilities", "", "| Endpoint | Status | Notes |", "|----------|--------|-------|"]
        for ok, name, endpoint, detail in rest_rows:
            note = f"`{endpoint}`" + (f" — {detail}" if detail else "")
            body.append(f"| {name} | {_ok_md(ok)} | {note} |")
        body.append("")

        body += ["### GraphQL API Capabilities", "", "| Feature | Available | Purpose |", "|---------|-----------|---------|"]
        for ok, name, desc in gql_rows:
            body.append(f"| {name} | {_ok_md(ok)} | {desc} |")
        body.append("")

        if label_rows:
            body += [
                "### Key Label Validation (Group-Level)", "",
                "Labels that exist in the group match epics during report generation. "
                "Missing labels mean the corresponding epics are invisible to reports — "
                "a common cause of empty report cells.", "",
                "| Label | Present in Group |", "|-------|-----------------|",
            ]
            for lbl, present in label_rows:
                body.append(f"| `{lbl}` | {_ok_md(present)} |")
            body.append("")

        body += ["### Report Compatibility Assessment", "",
                 "| Feature / Report Area | Expected to Work | Requirement |",
                 "|----------------------|-----------------|-------------|"]
        for ok, feature, req in assess_rows:
            body.append(f"| {feature} | {_compat_md(ok)} | {req} |")
        body.append("")

        # Save JSON for Marimo/Quarto while we have the rendered markdown body
        try:
            _data_dir = Path("quarto-data")
            _data_dir.mkdir(parents=True, exist_ok=True)
            (_data_dir / "diagnostics.json").write_text(
                json.dumps({
                    "report_date": date.today().strftime("%Y-%m-%d"),
                    "group": {"name": group.name, "url": group.web_url},
                    "content": "\n".join(body),
                    "verdict_md": verdict_md,
                }, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        return ["---", "<details>", "<summary>🔧 Environment &amp; API Diagnostics</summary>", "",
                *body, f"> {verdict_md}", "", "</details>"]

    # ------------------------------------------------------------------
    # Wiki Index
    # ------------------------------------------------------------------

    def generate_wiki_index(self):
        group = self._rd_root_obj
        today = date.today()
        gn    = group.name
        base  = f"{self.url}/groups/{group.full_path}/-/wikis"

        def _wl(page_title, display=None):
            return _mlink(display or page_title, f"{base}/{_wiki_slug(page_title)}")

        md = []
        md.append(f"# {gn} — Portfolio Home")
        md.append(
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  "
            f"**Group:** {_mlink(gn, group.web_url)}"
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
            f"| {_wl(f'{self._wiki_t2}/Issue Blocking', 'Issue Blocking')} "
            f"| Issue-to-issue `is_blocked_by` relationships, with owning project and parent epic |"
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
            f"| {_wl(f'{self._wiki_t3}/Program Workload by Group', 'Program Workload by Group')} "
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
        md.append(
            f"| {_wl(f'{self._wiki_t4}/Premature Closures', 'Premature Closures')} "
            f"| Closed Epics or Capabilities that still have open child epics or open linked issues |"
        )
        md.append("")

        md.extend(self._generate_diagnostics_section())

        self.upload_to_wiki(group, "home", "\n".join(md))
        print(f"  ↳ Wiki home page updated for {gn}")

        home_url  = f"{self.url}/groups/{group.full_path}/-/wikis/home"
        _back     = _mlink("← Portfolio Home", home_url)
        root_name = f"{gn} — Portfolio Home"

        # ── Root folder page (in case GitLab surfaces it as blank) ────────── #
        root_folder_md = [
            f"# {root_name}",
            f"**Updated:** {today.strftime('%Y-%m-%d')}  |  **Group:** {_mlink(gn, group.web_url)}",
            "",
            f"This is the SAFe portfolio wiki for **{gn}**. Reports are organized into four tiers "
            f"by audience and cadence — start with the tier that matches your role, then drill down "
            f"as needed. Return to the {_mlink('Portfolio Home', home_url)} index at any time.",
            "",
            "## How to navigate",
            "",
            "Each tier is a folder in this wiki. Click a tier link to see the landing page with "
            "a full description of that tier's purpose, audience, and questions answered — "
            "then follow the links to individual reports.",
            "",
            f"| Tier | Audience | Cadence | Purpose |",
            f"|------|----------|---------|---------|",
            f"| {_mlink('📊 00 Executive Pulse', f'{base}/{_wiki_slug(self._wiki_t1)}')} "
            f"| Executives, Portfolio Managers | Daily | At-a-glance portfolio health |",
            f"| {_mlink('🗂️ 01 Program Management', f'{base}/{_wiki_slug(self._wiki_t2)}')} "
            f"| Release Train Engineers, PMs | Weekly | Predictability, risk, and prioritisation |",
            f"| {_mlink('🔍 02 Operational Detail', f'{base}/{_wiki_slug(self._wiki_t3)}')} "
            f"| ART and Team leads | On demand | Root-cause drill-down and hierarchy view |",
            f"| {_mlink('🔧 03 Data Quality', f'{base}/{_wiki_slug(self._wiki_t4)}')} "
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
            f"| {_wl(f'{self._wiki_t2}/Issue Blocking', 'Issue Blocking')} "
            f"| Issue-to-issue `is_blocked_by` relationships, with owning project and parent epic |",
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
            "| Business Value | Custom field (Fibonacci 1–21) | Revenue, mission impact, or customer satisfaction — set via `set-business-value` |",
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
            "### Risk Register",
            "Epics with linked ROAM risk issues appear in the Risk Register, grouped by disposition "
            "(`roam::owned`, `roam::accepted`, `roam::mitigated`, `roam::resolved`). "
            "Create a ROAM risk issue in the relevant project, then link it to the threatened epic "
            "via **\"relates to\"**. Epics with no ROAM issues but overdue child Features are also flagged.",
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
            f"| {_wl(f'{self._wiki_t3}/Program Workload by Group', 'Program Workload by Group')} "
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

    def generate_all_reports(self, formats=None):
        self._run_reports(REPORTS, formats=formats)

    def run_reports_menu(self, report_key=None, reuse_data=None, formats=None):
        """Show the reports selection menu or run a specific report by key."""
        if formats is None:
            formats = {"markdown", "plotly", "interactive"}
        if report_key:
            if report_key == "all":
                self._run_reports(REPORTS, reuse_data=reuse_data, formats=formats)
                return
            report = next((r for r in REPORTS if r["key"] == report_key), None)
            if report is None:
                print(f"Unknown report '{report_key}'. Available: all, " + ", ".join(r['key'] for r in REPORTS))
                sys.exit(1)
            self._run_reports([report], reuse_data=reuse_data, formats=formats)
            return

        while True:
            _clear()
            print("Available Reports")
            print("=" * 60)
            for i, report in enumerate(REPORTS, 1):
                print(f"  [{i}] {report['key']:<22} {report['description']}")
            print()
            print("  Enter  — run all reports (default)")
            print("  b      — back    q — quit")
            print()

            raw = input(f"Select [1-{len(REPORTS)}, space-separated, or Enter for all]: ").strip()

            if raw.lower() in ("b", "back"):
                return False
            if raw.lower() in ("q", "quit", "exit"):
                sys.exit(0)

            if not raw:
                self._run_reports(REPORTS, reuse_data=reuse_data, formats=formats)
                return True

            selected = []
            bad = []
            for token in raw.split():
                try:
                    idx = int(token)
                    if 1 <= idx <= len(REPORTS):
                        report = REPORTS[idx - 1]
                        if report not in selected:
                            selected.append(report)
                    else:
                        bad.append(token)
                except ValueError:
                    bad.append(token)

            if bad:
                print(f"  Invalid selection(s): {', '.join(bad)}  "
                      f"(valid range 1–{len(REPORTS)})")
            if not selected:
                continue

            self._run_reports(selected, reuse_data=reuse_data, formats=formats)
            return True

    def _fetch_blocking_graph(self, group):
        """Return the raw blocking relationship graph via the REST related_epics API.

        Uses _all_epics_cache (populated by calculate_portfolio_metrics) to avoid
        an extra hierarchy walk, and queries each epic's /related_epics endpoint
        directly — the same API used to create blocking relationships.
        """
        all_epics_raw = getattr(self, '_all_epics_cache', {}).get(self.parent_group, [])
        if not all_epics_raw:
            print("  WARNING: epic cache empty — cannot collect blocking data.")
            return {"relationships": [], "summary": {}}

        session = self._make_session()

        epic_by_id = {e["id"]: e for e in all_epics_raw}
        parent_of  = {e["id"]: e["parent_id"] for e in all_epics_raw if e.get("parent_id")}

        def _etype(labels):
            for t in self.EPIC_TYPE_DISPLAY_NAMES:
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
                if node and _etype(node.get("labels", [])) == self.EPIC_TYPE_DISPLAY_NAMES[0]:
                    result.append(node)
            return result

        relationships = []
        total_rels    = 0
        fetch_failed  = set()   # epic ids whose /related_epics call failed (Refs #107)

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
                fetch_failed.add(eid)
                continue
            if not resp.ok:
                fetch_failed.add(eid)
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

        # Reconcile blocked_by_count with this graph (Refs #107).
        # The /related_epics graph above is the authoritative source for the blocking
        # report detail (blocking.json).  calculate_portfolio_metrics derives
        # blocked_by_count from the legacy GraphQL blockedByCount (plus a work-items
        # widget fallback), which can disagree with the REST related_epics view — most
        # notably for blocking links set through the GitLab 17+ work-items UI.  Recompute
        # blocked_by_count here from the same relationships so the summary tables and the
        # blocking detail can never diverge.  These epic dicts are shared by object
        # identity with the _metrics_cache buckets, so the update propagates to every
        # report that reads blocked_by_count.
        #
        # Epics whose /related_epics call failed are left untouched: keep their
        # provisional GraphQL count rather than overwriting it with 0, so a transient
        # API error can't silently mark a genuinely-blocked epic as unblocked.
        blocked_by_counts = {
            r["blocked_epic"]["id"]: len(r["blocked_by"]) for r in relationships
        }
        for e in all_epics_raw:
            eid = e["id"]
            if eid in fetch_failed and eid not in blocked_by_counts:
                continue
            e["blocked_by_count"] = blocked_by_counts.get(eid, 0)

        if fetch_failed:
            print(
                f"Warning: {len(fetch_failed)} epic(s) had a failed /related_epics "
                f"fetch; blocked_by_count left at the provisional value (may be stale)."
            )

        return {
            "summary": {
                "total_blocked":           len(relationships),
                "total_relationships":     total_rels,
                "portfolio_epics_at_risk": at_risk,
            },
            "relationships": relationships,
        }

    def _fetch_issue_blocking_graph(self, group):
        """Return the raw issue→issue blocking relationship graph.

        Two-step strategy that mirrors the epic blocking path but stays cheap at
        issue scale:
          1. A single bulk GraphQL query FLAGS which issues are blocked (the
             GitLab ``Issue`` GraphQL type exposes ``blocked`` / ``blockedByCount``).
          2. The REST ``GET /projects/:id/issues/:iid/links`` endpoint is then
             queried ONLY for those flagged issues, keeping links whose
             ``link_type == "is_blocked_by"``.

        Unblocked issues are never REST-fetched, so the cost scales with the
        (small) number of blocked issues rather than the whole backlog.  Every
        network call is wrapped in try/except + ``resp.ok`` so one failed fetch
        can never abort the run.
        """
        issues = getattr(self, '_issues_cache', {}).get(self.parent_group, [])
        if not issues:
            print("  WARNING: issue cache empty — cannot collect issue blocking data.")
            return {"relationships": [], "summary": {"total_blocked": 0, "total_relationships": 0}}

        # ── 1. Bulk GraphQL flag: which issues are blocked? ──────────────── #
        # Keyed by web_url (stable across REST + GraphQL).  If the field isn't
        # available on this schema the query simply returns nothing and we fall
        # back to flagging via blockedByCount, then to an empty result — we do
        # NOT REST-fetch links for every issue.
        blocked_urls: set = set()
        try:
            gql_data = self.graphql_query(
                """
                query IssueBlockStatus($fullPath: ID!) {
                  group(fullPath: $fullPath) {
                    issues(includeSubgroups: true) {
                      nodes { iid webUrl blocked blockedByCount }
                    }
                  }
                }
                """,
                variables={"fullPath": group.full_path},
            )
            if gql_data and gql_data.get("group", {}).get("issues"):
                for n in gql_data["group"]["issues"]["nodes"]:
                    if n.get("blocked") or (n.get("blockedByCount") or 0) > 0:
                        if n.get("webUrl"):
                            blocked_urls.add(n["webUrl"])
        except Exception:
            pass

        if not blocked_urls:
            return {"relationships": [], "summary": {"total_blocked": 0, "total_relationships": 0}}

        # ── 2. REST detail fetch ONLY for flagged issues ─────────────────── #
        session         = self._make_session()
        issue_by_url    = {i.get("web_url"): i for i in issues}
        all_epics_raw   = getattr(self, '_all_epics_cache', {}).get(self.parent_group, [])
        epic_title_by_iid = {e.get("iid"): e.get("title") for e in all_epics_raw}

        relationships = []
        total_rels    = 0

        for url in sorted(blocked_urls):
            issue = issue_by_url.get(url)
            if not issue:
                continue
            proj = issue.get("project_path")
            iid  = issue.get("iid")
            if not (proj and iid):
                continue

            enc       = quote(str(proj), safe="")
            links_url = f"{self.url}/api/v4/projects/{enc}/issues/{iid}/links"
            try:
                resp = session.get(links_url)
            except Exception:
                continue
            if not resp.ok:
                continue

            blockers = []
            for link in resp.json():
                if link.get("link_type") != "is_blocked_by":
                    continue
                refs = link.get("references", {}) or {}
                full = refs.get("full", "") or ""
                bp   = full.split("#")[0] if "#" in full else link.get("project_path", "")
                blockers.append({
                    "id":           link.get("id"),
                    "iid":          link.get("iid"),
                    "title":        link.get("title", ""),
                    "web_url":      link.get("web_url", ""),
                    "project_path": bp,
                })

            if not blockers:
                continue

            total_rels += len(blockers)
            epic_iid = issue.get("epic_iid")
            relationships.append({
                "blocked_issue": {
                    "id":           issue.get("id"),
                    "iid":          iid,
                    "title":        issue.get("title", ""),
                    "web_url":      url,
                    "project_path": proj,
                    "state":        issue.get("state", ""),
                    "epic_iid":     epic_iid,
                    "epic_title":   epic_title_by_iid.get(epic_iid),
                },
                "blocked_by": blockers,
            })

        relationships.sort(key=lambda r: r["blocked_issue"]["title"])

        return {
            "summary": {
                "total_blocked":       len(relationships),
                "total_relationships": total_rels,
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

        # Build the blocking graph up front so each epic's blocked_by_count is reconciled
        # against the /related_epics detail before epics.json is serialized (Refs #107).
        blocking = self._fetch_blocking_graph(group)
        blocking["generated_at"] = ts
        blocking["group"]        = self.parent_group

        # Epics: typed + untyped
        typed_epics = [e for bucket in metrics.values() for e in bucket]
        all_epics_raw = getattr(self, '_all_epics_cache', {}).get(self.parent_group, typed_epics)
        epics_payload = {
            "generated_at":          ts,
            "group":                 self.parent_group,
            "total":                 len(typed_epics),
            "total_raw":             len(all_epics_raw),
            "epics":                 typed_epics,
            "all_epics_raw":         all_epics_raw,
            "epic_type_labels":      self.EPIC_TYPE_LABELS,
            "epic_type_display_names": self.EPIC_TYPE_DISPLAY_NAMES,
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

        (data_dir / "blocking.json").write_text(
            json.dumps(blocking, indent=2, default=str), encoding="utf-8"
        )

        issue_blocking = self._fetch_issue_blocking_graph(group)
        issue_blocking["generated_at"] = ts
        issue_blocking["group"]        = self.parent_group
        (data_dir / "issue_blocking.json").write_text(
            json.dumps(issue_blocking, indent=2, default=str), encoding="utf-8"
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

        n_blocked     = blocking["summary"].get("total_blocked", 0)
        n_iss_blocked = issue_blocking["summary"].get("total_blocked", 0)
        print(f"\n  Data snapshot → {data_dir}/")
        print(f"    epics.json    ({len(typed_epics)} typed + {len(all_epics_raw) - len(typed_epics)} untyped)")
        print(f"    issues.json   ({len(issues)} issues)")
        print(f"    blocking.json ({n_blocked} blocked epics)")
        print(f"    issue_blocking.json ({n_iss_blocked} blocked issues)")
        print(f"    groups.json   ({len(all_groups)} groups)")
        print(f"    projects.json ({len(all_projects)} projects)\n")

    # ------------------------------------------------------------------
    # Phase 4b Quarto data-layer methods
    # ------------------------------------------------------------------

    def _data_art_feature_status(self) -> dict:
        """ART Feature Status: VS → ART → team → feature list."""
        group    = self._rd_root_obj
        features = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

        team_hierarchy: dict = {}
        for vs_group, art_group, team_group in self._iter_team_groups():
            team_hierarchy[team_group["id"]] = (vs_group, art_group, team_group)

        art_buckets: defaultdict = defaultdict(lambda: defaultdict(list))
        for f in features:
            gid = f.get("group_id")
            if gid in team_hierarchy:
                _, art_grp, _ = team_hierarchy[gid]
                art_buckets[art_grp["id"]][gid].append(f)

        vs_out: defaultdict = defaultdict(list)
        for vs_group, art_group in self._iter_art_groups():
            art_id = art_group["id"]
            if art_id not in art_buckets:
                continue
            team_buckets = art_buckets[art_id]
            total_f = at_risk = blocked_c = 0
            teams_out = []
            for team_id, feature_list in sorted(
                team_buckets.items(),
                key=lambda x: team_hierarchy[x[0]][2]["name"],
            ):
                _, _, team_group = team_hierarchy[team_id]
                features_out = []
                for f in sorted(feature_list, key=lambda x: x.get("title", "")):
                    pct_done = f["pct_complete"]
                    pct_pi   = f.get("pct_through_pi")
                    blocked  = f.get("blocked_by_count", 0)
                    if blocked:
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
                    total_f += 1
                    features_out.append({
                        "title":        f["title"],
                        "url":          f["web_url"],
                        "piid":         f.get("piid") or "—",
                        "state":        f["state"].capitalize(),
                        "pct_complete": pct_done,
                        "pct_pi":       pct_pi,
                        "planned":      f.get("planned_weight", 0),
                        "actual":       f.get("actual_weight", 0),
                        "status":       status,
                        "risk_reason":  _item_risk_reasons(f),
                    })
                teams_out.append({
                    "team_name": team_group["name"],
                    "team_url":  team_group.get("web_url", ""),
                    "features":  features_out,
                })
            vs_out[vs_group["name"]].append({
                "art_name":       art_group["name"],
                "art_url":        art_group.get("web_url", ""),
                "total_features": total_f,
                "at_risk":        at_risk,
                "blocked":        blocked_c,
                "teams":          teams_out,
            })

        return {
            "report_date":   date.today().isoformat(),
            "group":         {"name": group.name, "url": group.web_url},
            "value_streams": [
                {"vs_name": vs_name, "arts": arts}
                for vs_name, arts in vs_out.items()
            ],
        }

    def _data_team_backlog(self) -> dict:
        """Team Backlog: per-team issue list grouped by linked Feature."""
        group     = self._rd_root_obj
        teams_out = []

        for vs_group, art_group, team_group in self._iter_team_groups():
            projects        = self._rd_projects_by_nsid.get(team_group["id"], [])
            backlog_project = next(
                (p for p in projects if p["path"].endswith("-backlog")), None
            )

            if not backlog_project:
                teams_out.append({
                    "vs_name":             vs_group["name"],
                    "art_name":            art_group["name"],
                    "team_name":           team_group["name"],
                    "team_url":            team_group.get("web_url", ""),
                    "has_backlog_project": False,
                    "backlog_url":         "",
                    "total":               0,
                    "open":                0,
                    "closed":              0,
                    "total_weight":        0,
                    "closed_weight":       0,
                    "pct_done":            0,
                    "by_feature":          [],
                    "unlinked":            [],
                })
                continue

            all_issues = self._rd_issues_by_project.get(
                backlog_project["path_with_namespace"], []
            )

            by_feature: defaultdict = defaultdict(list)
            unlinked = []
            for issue in all_issues:
                eid = issue.get("epic_id")
                if eid:
                    by_feature[eid].append(issue)
                else:
                    unlinked.append(issue)

            total_w  = sum(i.get("weight") or 0 for i in all_issues)
            closed_w = sum(
                i.get("weight") or 0 for i in all_issues if i["state"] == "closed"
            )
            open_cnt = sum(1 for i in all_issues if i["state"] == "opened")
            pct      = round(closed_w / total_w * 100) if total_w else 0

            def _issue_row(issue):
                return {
                    "iid":    issue["iid"],
                    "title":  issue["title"],
                    "url":    issue["web_url"],
                    "state":  "✅ Closed" if issue["state"] == "closed" else "🔵 Open",
                    "weight": issue.get("weight") or 0,
                }

            by_feature_out = []
            for epic_id, issues in by_feature.items():
                epic_info = self._rd_epics_by_id.get(epic_id, {})
                f_total   = sum(i.get("weight") or 0 for i in issues)
                f_closed  = sum(
                    i.get("weight") or 0 for i in issues if i["state"] == "closed"
                )
                f_pct  = round(f_closed / f_total * 100) if f_total else 0
                f_open = sum(1 for i in issues if i["state"] == "opened")
                by_feature_out.append({
                    "epic_id":       epic_id,
                    "epic_title":    epic_info.get("title", f"Epic {epic_id}"),
                    "epic_url":      epic_info.get("web_url", "#"),
                    "epic_state":    (
                        epic_info.get("state", "").capitalize()
                        if epic_info else "Unknown"
                    ),
                    "total":         len(issues),
                    "open":          f_open,
                    "closed":        len(issues) - f_open,
                    "total_weight":  f_total,
                    "closed_weight": f_closed,
                    "pct_done":      f_pct,
                    "issues": [
                        _issue_row(i)
                        for i in sorted(issues, key=lambda i: i["state"])
                    ],
                })

            teams_out.append({
                "vs_name":             vs_group["name"],
                "art_name":            art_group["name"],
                "team_name":           team_group["name"],
                "team_url":            team_group.get("web_url", ""),
                "has_backlog_project": True,
                "backlog_url":         backlog_project.get("web_url", ""),
                "total":               len(all_issues),
                "open":                open_cnt,
                "closed":              len(all_issues) - open_cnt,
                "total_weight":        total_w,
                "closed_weight":       closed_w,
                "pct_done":            pct,
                "by_feature":          by_feature_out,
                "unlinked":            [_issue_row(i) for i in unlinked],
            })

        return {
            "report_date": date.today().isoformat(),
            "group":       {"name": group.name, "url": group.web_url},
            "teams":       teams_out,
        }

    def _data_vs_capability_dashboard(self) -> dict:
        """VS Capability Dashboard: VS → PI → ART capabilities + direct features."""
        group        = self._rd_root_obj
        capabilities = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[1], [])
        features     = self._rd_metrics.get(self.EPIC_TYPE_DISPLAY_NAMES[-1], [])

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

        def _art_name_url(art_id):
            if art_id in art_hierarchy:
                _, g = art_hierarchy[art_id]
                return g["name"], g.get("web_url", "")
            return f"ART {art_id}", ""

        vs_cap_buckets: defaultdict = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for cap in capabilities:
            vs_g, art_g = _vs_art_for(cap.get("group_id"))
            piid = cap.get("piid")
            if vs_g and art_g and piid:
                vs_cap_buckets[vs_g["id"]][piid][art_g["id"]].append(cap)

        epic_type_by_id = {
            e["id"]: t for t, tier in self._rd_metrics.items() for e in tier
        }
        direct_features = [
            f for f in features
            if epic_type_by_id.get(f.get("parent_id")) != self.EPIC_TYPE_DISPLAY_NAMES[1]
        ]

        vs_direct_buckets: defaultdict = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for feat in direct_features:
            vs_g, art_g = _vs_art_for(feat.get("group_id"))
            piid = feat.get("piid")
            if vs_g and art_g and piid:
                vs_direct_buckets[vs_g["id"]][piid][art_g["id"]].append(feat)

        def _item_rows(items, pct_pi):
            rows = []
            for item in sorted(items, key=lambda x: x.get("title", "")):
                pct_done = item["pct_complete"]
                blocked  = item.get("blocked_by_count", 0)
                if blocked:
                    s = "🔒 Blocked"
                elif pct_pi is None or pct_pi == 0:
                    s = "🔵 Planned"
                elif pct_pi >= 100:
                    s = "✅ Complete" if pct_done >= 100 else "❌ Incomplete"
                elif pct_done >= pct_pi:
                    s = "✅ On Track"
                else:
                    s = "⚠️ At Risk"
                rows.append({
                    "title":        item["title"],
                    "url":          item["web_url"],
                    "state":        item["state"].capitalize(),
                    "pct_complete": pct_done,
                    "planned":      item.get("planned_weight", 0),
                    "actual":       item.get("actual_weight", 0),
                    "status":       s,
                    "risk_reason":  _item_risk_reasons(item),
                })
            return rows

        def _art_section(pi_buckets, piid, pct_pi):
            arts_out  = []
            at_risk_n = blocked_n = 0
            for art_id, items in sorted(
                pi_buckets.get(piid, {}).items(),
                key=lambda x: _art_name_url(x[0])[0],
            ):
                art_name, art_url = _art_name_url(art_id)
                planned  = sum(c.get("planned_weight", 0) for c in items)
                actual   = sum(c.get("actual_weight",  0) for c in items)
                n_blk    = sum(1 for c in items if c.get("blocked_by_count", 0) > 0)
                avg_pct  = (
                    round(sum(c["planned_weight"] * c["pct_complete"] for c in items) / planned)
                    if planned else
                    (round(sum(c["pct_complete"] for c in items) / len(items)) if items else 0)
                )
                if n_blk:
                    s = "🔒 Blocked"
                    blocked_n += n_blk
                elif pct_pi is None or pct_pi == 0:
                    s = "🔵 Planned"
                elif pct_pi >= 100:
                    s = "✅ Complete" if avg_pct >= 100 else "❌ Incomplete"
                elif avg_pct >= pct_pi:
                    s = "✅ On Track"
                else:
                    s = "⚠️ At Risk"
                    at_risk_n += 1
                arts_out.append({
                    "art_name": art_name,
                    "art_url":  art_url,
                    "count":    len(items),
                    "planned":  planned,
                    "actual":   actual,
                    "delta":    actual - planned,
                    "avg_pct":  avg_pct,
                    "status":   s,
                    "items":    _item_rows(items, pct_pi),
                })
            return arts_out, at_risk_n, blocked_n

        value_streams = []
        for vs_group in self._iter_vs_groups():
            vid       = vs_group["id"]
            cap_pi    = vs_cap_buckets.get(vid, {})
            direct_pi = vs_direct_buckets.get(vid, {})
            if not cap_pi and not direct_pi:
                continue

            all_pis = sorted(
                set(cap_pi) | set(direct_pi),
                key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
            )

            total_caps = total_direct = vs_at_risk = vs_blocked = 0
            pis_out = []
            for piid in all_pis:
                pct_pi     = self._pct_through_pi(piid)
                start, end = self._pi_dates_from_label(piid)
                date_range = (
                    f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
                    if start else ""
                )
                caps_out,   ar_c, bl_c = _art_section(cap_pi,    piid, pct_pi)
                direct_out, ar_d, bl_d = _art_section(direct_pi, piid, pct_pi)
                total_caps   += sum(a["count"] for a in caps_out)
                total_direct += sum(a["count"] for a in direct_out)
                vs_at_risk   += ar_c + ar_d
                vs_blocked   += bl_c + bl_d
                pis_out.append({
                    "piid":            piid,
                    "pct_pi":          pct_pi,
                    "date_range":      date_range,
                    "capabilities":    caps_out,
                    "direct_features": direct_out,
                })

            value_streams.append({
                "vs_name":      vs_group["name"],
                "vs_url":       vs_group.get("web_url", ""),
                "total_caps":   total_caps,
                "total_direct": total_direct,
                "at_risk":      vs_at_risk,
                "blocked":      vs_blocked,
                "pis":          pis_out,
            })

        return {
            "report_date":   date.today().isoformat(),
            "group":         {"name": group.name, "url": group.web_url},
            "value_streams": value_streams,
        }

    def write_report_json(self, *data_dirs):
        """Write all Quarto/Marimo data-layer JSON files to one or more directories."""
        dirs = [Path(d) for d in data_dirs]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        for key, fn in (
            ("health-dashboard",         self._data_portfolio_health),
            ("orphan-epics",             self._data_orphan_epics),
            ("orphan-issues",            self._data_orphan_issues),
            ("premature-closures",       self._data_premature_closures),
            ("unassigned-pi",            self._data_unassigned_pi),
            ("risk-register",            self._data_risk_register),
            ("wsjf",                     self._data_wsjf),
            ("blocking",                 self._data_blocking),
            ("issue-blocking",           self._data_issue_blocking),
            ("epic-lifecycle",           self._data_epic_lifecycle),
            ("pi-predictability",        self._data_pi_predictability),
            ("art-capacity-balance",     self._data_art_capacity_balance),
            ("piid-project",             self._data_piid_project),
            ("piid-project-detail",      self._data_piid_project_detail),
            ("portfolio",                self._data_portfolio),
            ("workload",                 self._data_workload),
            ("flow-metrics",             self._data_flow_metrics),
            ("art-feature-status",       self._data_art_feature_status),
            ("team-backlog",             self._data_team_backlog),
            ("vs-capability-dashboard",  self._data_vs_capability_dashboard),
        ):
            payload = json.dumps(fn(), indent=2, default=str)
            for d in dirs:
                out = d / f"{key}.json"
                out.write_text(payload, encoding="utf-8")
                print(f"  → {out}")

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
            t: [e for e in epics_data["epics"] if e.get("type") == t]
            for t in self.EPIC_TYPE_DISPLAY_NAMES
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

        # Issue-to-issue blocking (optional — older snapshots may not have it)
        _ib_path = data_dir / "issue_blocking.json"
        if _ib_path.exists():
            self._rd_issue_blocking: dict = json.loads(_ib_path.read_text(encoding="utf-8"))
        else:
            self._rd_issue_blocking = {"relationships": [], "summary": {}}

        # Derive active label sets from snapshot — not from config
        all_epic_labels = [lbl for e in self._rd_epics_all for lbl in e.get("labels", [])]
        label_set       = set(all_epic_labels)
        self._rd_piid_labels    = sorted(
            {l for l in label_set if l.startswith("PIID::")},
            key=lambda p: (self._pi_dates_from_label(p)[0] or date.min),
        )
        self._rd_project_labels    = sorted({l for l in label_set if l.startswith("project::")})
        self._rd_work_type_labels  = sorted({l for l in label_set if l.startswith("type::")})
        self._rd_lifecycle_labels  = sorted({l for l in label_set if l.startswith("lifecycle::")})

    def _build_site(self, formats=None) -> bool:
        """Run the site build for the requested output formats."""
        if formats is None:
            formats = {"markdown"}
        build_plotly      = "plotly"      in formats
        build_interactive = "interactive" in formats

        if not build_plotly and not build_interactive:
            return True

        print("\n--- Site Build ---")
        ok = True

        if build_plotly and build_interactive:
            marimo_ok, quarto_ok = self._site_build_all()
            ok = marimo_ok and quarto_ok
        elif build_plotly:
            ok = self._site_build_static()
        elif build_interactive:
            n = self._restore_data_layer()
            print(f"\n  Copied {n} JSON file(s) to public/data/")
            ok = self._site_build_interactive()

        return ok

    def _run_reports(self, reports, reuse_data=None, formats=None):
        """Execute a list of report entries from the REPORTS registry.

        reuse_data: Path to an existing data/ directory whose JSON files
        should be loaded instead of hitting the API again.
        formats: set of output types to generate — markdown, plotly, interactive, grafana.
        """
        now      = datetime.now()
        run_dir  = Path("reports") / now.strftime("%Y%m%d") / now.strftime("%H%M%S")
        data_dir = run_dir / "data"
        wiki_dir = run_dir / "wiki"
        data_dir.mkdir(parents=True, exist_ok=True)
        wiki_dir.mkdir(parents=True, exist_ok=True)
        self._report_run_dir = run_dir
        self._wiki_save_dir  = wiki_dir

        if len(reports) == len(REPORTS):
            log_stem = "reports-all"
        elif len(reports) == 1:
            log_stem = f"reports-{reports[0]['key']}"
        else:
            log_stem = f"reports-{len(reports)}-selected"
        log_path = run_dir / f"{log_stem}.log"

        with _tee_to_log(log_path):
            print(f"  log → {log_path}\n")
            self._run_reports_inner(reports, run_dir, data_dir, reuse_data, formats)

    def _run_reports_inner(self, reports, run_dir, data_dir, reuse_data, formats=None):
        if formats is None:
            formats = {"markdown"}
        do_markdown   = "markdown" in formats
        do_site_build = "plotly"   in formats or "interactive" in formats

        # Always start with a clean fetch — stale caches from a prior run in
        # the same session would silently re-publish old data to the wiki.
        for _cache_attr in ('_metrics_cache', '_issues_cache', '_all_epics_cache'):
            if hasattr(self, _cache_attr):
                delattr(self, _cache_attr)

        group = self.get_group_by_name(self.parent_group)
        if group is None:
            ns = self.gitlab_namespace
            full = f"{ns}/{self.parent_group}" if ns else self.parent_group
            print(f"\nError: group '{full}' not found. Check parent_group in config.json.")
            return
        self._rd_root_obj = group
        gn = group.name
        self._wiki_t1 = f"{gn} — Portfolio Home/00 Executive Pulse"
        self._wiki_t2 = f"{gn} — Portfolio Home/01 Program Management"
        self._wiki_t3 = f"{gn} — Portfolio Home/02 Operational Detail"
        self._wiki_t4 = f"{gn} — Portfolio Home/03 Data Quality"
        print(f"\nGenerating reports for group: {group.name}\n")

        # Preload existing wiki pages so upload_to_wiki can look them up without
        # calling wikis.get(slug), which URL-encodes slashes and returns 404 for
        # nested pages that actually exist.  Keyed by group_id so sub-group wikis
        # (e.g. each team's own wiki) are handled correctly via lazy loading.
        if do_markdown:
            try:
                existing = group.wikis.list(all=True)
                self._wiki_page_cache = {group.id: {p.slug: p for p in existing}}
                print(f"  Loaded {len(existing)} existing wiki page(s) into cache.\n")
            except Exception as e:
                print(f"  Warning: could not preload wiki page cache: {e}")
                self._wiki_page_cache = {}

        if reuse_data is not None:
            import shutil
            src = Path(reuse_data)
            print(f"  Reusing data snapshot from: {src}\n")
            self._load_report_data(src)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, data_dir / f.name)
        else:
            self._write_report_data(data_dir)
            self._load_report_data(data_dir)

        print("Writing Grafana dashboard data files...")
        if do_site_build:
            self.write_report_json(data_dir, Path("quarto-data"), Path("public/data"))
            if not do_markdown:
                self.generate_diagnostics_report()
        else:
            self.write_report_json(data_dir)

        (data_dir / "snapshot.complete").touch()

        phases = []

        if do_markdown:
            total = len(reports)
            for report in reports:
                key   = report['key']
                start = datetime.now()
                t0    = time.monotonic()
                print(f"  [{key}] starting")
                self._current_op = f"report: {key}"
                try:
                    method = getattr(self, report["method"])
                    method(group) if report["needs_group"] else method()
                except Exception as exc:
                    print(f"  [{key}] ERROR: {exc}")
                elapsed = time.monotonic() - t0
                end     = datetime.now()
                self._current_op = None
                phases.append((key, start, end, elapsed))
                print(f"  [{key}] done  {_fmt_duration(elapsed)}")

            self._print_timing_table(phases, f"{total} report(s) completed")

        self._build_site(formats=formats)

        # expose aggregate for --all phase summary
        if phases:
            wall  = (phases[-1][2] - phases[0][1]).total_seconds()
            label = f"reports ({len(phases)})" if len(phases) > 1 else f"report: {phases[0][0]}"
            self._last_reports_phase = (label, phases[0][1], phases[-1][2], wall)
