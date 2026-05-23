import sys
from collections import defaultdict
from datetime import date, datetime
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Report registry — each entry describes one runnable report.
# needs_group: True  → method signature is  method(self, group)
# needs_group: False → method signature is  method(self)
# ---------------------------------------------------------------------------
REPORTS = [
    {
        "key":         "portfolio",
        "description": "SAFe Portfolio Report — Epic → Capability → Feature hierarchy with % complete",
        "method":      "generate_portfolio_report",
        "needs_group": True,
    },
    {
        "key":         "workload",
        "description": "ART-Team Workload Report — planned vs actual weight per group per PI",
        "method":      "generate_workload_report",
        "needs_group": False,
    },
    {
        "key":         "blocking",
        "description": "Blocking Relationships Report — blocked epics and ancestor risk propagation",
        "method":      "generate_blocking_report",
        "needs_group": False,
    },
    {
        "key":         "unassigned-pi",
        "description": "Unassigned PI Report — epics with no PIID label, broken down by type",
        "method":      "generate_unassigned_pi_report",
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
        "key":         "team-backlog",
        "description": "Team Backlog Report — issues grouped by Feature for every Team, with weight and completion",
        "method":      "generate_team_backlog_report",
        "needs_group": False,
    },
    {
        "key":         "art-feature-status",
        "description": "ART Feature Status Report — all Features per ART grouped by Team, with completion, weight, and risk",
        "method":      "generate_art_feature_status_report",
        "needs_group": False,
    },
    {
        "key":         "art-capacity-balance",
        "description": "ART Capacity Balance Report — per-team planned vs actual weight per PI with over/under capacity flags",
        "method":      "generate_art_capacity_balance_report",
        "needs_group": False,
    },
]


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
        """Program × PI cross-tab: rows = project labels, columns = PIID quarters.

        Each cell shows status, epic counts, % done vs PI elapsed, and planned vs
        actual weight delta.  Data comes from calculate_portfolio_metrics so no
        extra API calls are needed beyond what other reports already do.
        """
        group   = self.get_group_by_name(self.parent_group)
        metrics = self.calculate_portfolio_metrics(self.parent_group)

        # Flatten all types into one list
        all_epics = [e for epics in metrics.values() for e in epics]

        # Index by (project_label, piid) → list of epic metric dicts
        piid_set    = set(self.PIID_LABELS)
        proj_set    = set(self.PROJECT_LABELS)
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

        md = []
        md.append(f"# Program × PI Report (Group: {group.name})")
        md.append(f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("Each cell shows: **Status · Epics (open/total) · % Done (PI elapsed%) · Planned pt → Actual pt**")
        md.append("")

        # Header row
        header = "| Program |" + "".join(f" {p} |" for p in self.PIID_LABELS)
        sep    = "|---|" + "".join("---|" for _ in self.PIID_LABELS)
        md.append(header)
        md.append(sep)

        for proj in self.PROJECT_LABELS:
            cells = []
            for piid in self.PIID_LABELS:
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

        self.upload_to_wiki(group, f"{group.name} - Program PI Report", "\n".join(md))

    def generate_portfolio_report(self, group):
        group_name = group.name
        print("  Generating SAFe Portfolio Report...")

        try:
            metrics   = self.calculate_portfolio_metrics(group_name)
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
            self.upload_to_wiki(group, f"{group_name} - SAFe Portfolio Report", md)

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
        group = self.get_group_by_name(self.parent_group)
        print("  Generating ART/Team Workload Report...")

        metrics   = self.calculate_portfolio_metrics(self.parent_group)
        all_epics = metrics.get("Epic", []) + metrics.get("Capability", []) + metrics.get("Feature", [])
        if not all_epics:
            print("No epics found — skipping workload report.")
            return

        group_ids    = {e["group_id"] for e in all_epics if e.get("group_id")}
        groups_by_id = {}
        for gid in group_ids:
            try:
                groups_by_id[gid] = self.gl.groups.get(gid)
            except Exception as e:
                print(f"  Could not fetch group {gid}: {e}")

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
                grp_name      = grp.name    if grp else f"Group {gid}"
                grp_url       = grp.web_url if grp else ""
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
                        f"{self.url}/groups/{grp.full_path}/-/work_items"
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

        self.upload_to_wiki(group, f"{group.name} - ART-Team Workload Report", "\n".join(md))

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
        group     = self.get_group_by_name(self.parent_group)
        full_path = group.full_path

        query = """
        query ListAllEpics($fullPath: ID!) {
          group(fullPath: $fullPath) {
            epics {
              nodes {
                id title blocked blockingCount webUrl blockedByCount
                labels { nodes { title } }
                parent {
                  id title webUrl
                  labels { nodes { title } }
                }
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

        def link(title, url):
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'

        data = self.graphql_query(query, variables={"fullPath": full_path})
        if data is None:
            return

        nodes         = data["group"]["epics"]["nodes"]
        blocked_epics = [n for n in nodes if n.get("blockedByCount", 0) > 0]

        total_relationships = sum(n.get("blockedByCount", 0) for n in blocked_epics)

        id_to_node = {n["id"]: n for n in nodes}
        parent_of  = {n["id"]: n["parent"]["id"] for n in nodes if n.get("parent")}

        def get_ancestors(epic_id):
            ancestors = []
            current   = epic_id
            visited   = set()
            while current in parent_of:
                current = parent_of[current]
                if current in visited:
                    break
                visited.add(current)
                if current in id_to_node:
                    ancestors.append(id_to_node[current])
            return ancestors

        epic_to_blocked_descendants = defaultdict(list)
        for blocked in blocked_epics:
            for ancestor in get_ancestors(blocked["id"]):
                if epic_type(ancestor) == "Epic":
                    epic_to_blocked_descendants[ancestor["id"]].append(blocked)

        md = []
        md.append(f"# Blocking Relationships Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")
        md.append("## Summary")
        md.append(f"- **Directly blocked items:** {len(blocked_epics)}")
        md.append(f"- **Total blocking relationships:** {total_relationships}")
        md.append(f"- **Top-level Epics with blocked descendants:** {len(epic_to_blocked_descendants)}")
        md.append("")

        if epic_to_blocked_descendants:
            md.append("## Portfolio-Level Risk Summary")
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
                epic_node  = id_to_node[epic_id]
                desc_links = ", ".join(
                    f"{self.EPIC_TYPE_ICONS.get(epic_type(d), '🏆')} {link(_short(d['title']), d['webUrl'])}"
                    for d in descendants
                )
                md.append(
                    f"| ⚠️ 🏆 **{link(epic_node['title'], epic_node['webUrl'])}** "
                    f"| **{len(descendants)}:** {desc_links} |"
                )
            md.append("")

        if not blocked_epics:
            md.append("_No blocked epics found._")
        else:
            md.append("## Blocked Items (Detail)")
            md.append("")
            for epic in blocked_epics:
                etype          = epic_type(epic)
                icon           = self.EPIC_TYPE_ICONS.get(etype, "🏆")
                state          = epic.get("state", "").capitalize()
                blocked_by_cnt = epic.get("blockedByCount", 0)

                md.append("<details>")
                md.append(
                    f"<summary>⛔ {icon} **{link(epic['title'], epic['webUrl'])}**"
                    f" ({etype}) — State: {state}"
                    f" — Blocked by: {blocked_by_cnt}</summary>"
                )
                md.append("")

                for edge in epic.get("blockedByEpics", {}).get("edges", []):
                    node  = edge["node"]
                    btype = epic_type(node)
                    bicon = self.EPIC_TYPE_ICONS.get(btype, "🏆")
                    md.append(f"🔒 {bicon} **{link(node['title'], node['webUrl'])}** ({btype})")
                    md.append("")

                ancestors = get_ancestors(epic["id"])
                if ancestors:
                    md.append("**Risk propagates up to:**")
                    md.append("")
                    for ancestor in ancestors:
                        atype = epic_type(ancestor)
                        aicon = self.EPIC_TYPE_ICONS.get(atype, "🏆")
                        md.append(f"⬆️ {aicon} **{link(ancestor['title'], ancestor['webUrl'])}** ({atype})")
                        md.append("")

                md.append("</details>")
                md.append("")

        md.extend([
            "---",
            "## Legend",
            "- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)",
            "- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs",
            "- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes",
            "",
        ])

        self.upload_to_wiki(group, f"{group.name} - Blocking Relationships Report", "\n".join(md))

    def generate_orphan_epics_report(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"Generating orphan report for {group.name}...")

        all_epics     = group.epics.list(all=True)
        epic_hierarchy = defaultdict(list)
        for epic in all_epics:
            pid = getattr(epic, 'parent_id', None)
            if pid is not None:
                epic_hierarchy[pid].append(epic)

        epic_ids_with_children = set(epic_hierarchy.keys())

        orphans = [
            e for e in all_epics
            if getattr(e, 'parent_id', None) is None and e.id not in epic_ids_with_children
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
                etype      = next((t for t in ("Epic", "Capability", "Feature") if t in epic.labels), "Unknown")
                icon       = self.EPIC_TYPE_ICONS.get(etype, "❓")
                title_link = f"[{epic.title}]({epic.web_url})"
                md.append(f"| {icon} {etype} | {title_link} | {epic.state.capitalize()} |")

        self.upload_to_wiki(group, f"{group.name} - Orphaned Epics Report", "\n".join(md))

    def generate_orphan_issues_report(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"Generating orphan issues report for {group.name}...")

        orphans_by_project = {}
        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                full_project = self.gl.projects.get(project.id)
                if not full_project.issues_enabled:
                    continue
                orphaned = [
                    i for i in full_project.issues.list(all=True)
                    if not getattr(i, 'epic', None)
                ]
                if orphaned:
                    orphans_by_project[full_project] = orphaned
            except Exception as e:
                print(f"Failed to fetch issues for project '{project.name}': {e}")

        total = sum(len(v) for v in orphans_by_project.values())

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

            for project, issues in sorted(orphans_by_project.items(), key=lambda x: x[0].name_with_namespace):
                md.append(f"### {project.name_with_namespace}")
                md.append("")
                md.append("| # | Title | State | Milestone | Assignees |")
                md.append("|---|-------|-------|-----------|-----------|")
                for issue in issues:
                    title_link = f"[{issue.title}]({issue.web_url})"
                    state      = issue.state.capitalize()
                    milestone  = issue.milestone['title'] if issue.milestone else "_None_"
                    assignees  = ", ".join(a['name'] for a in issue.assignees) if issue.assignees else "_Unassigned_"
                    md.append(f"| #{issue.iid} | {title_link} | {state} | {milestone} | {assignees} |")
                md.append("")

        self.upload_to_wiki(group, f"{group.name} - Orphaned Issues Report", "\n".join(md))

    def generate_unassigned_pi_report(self):
        group = self.get_group_by_name(self.parent_group)
        print("  Generating Unassigned PI Report...")

        all_epics        = group.epics.list(all=True)
        epic_title_by_id = {e.id: e.title for e in all_epics}

        unassigned = [e for e in all_epics if not any(l.startswith("PIID::") for l in e.labels)]

        by_type = {"Epic": [], "Capability": [], "Feature": [], "Unknown": []}
        for e in unassigned:
            etype = next((t for t in ("Epic", "Capability", "Feature") if t in e.labels), "Unknown")
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
            for e in sorted(items, key=lambda x: x.title):
                title_link = f"[{e.title}]({e.web_url})"
                state      = e.state.capitalize()
                parent_id  = getattr(e, 'parent_id', None)
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

        self.upload_to_wiki(group, f"{group.name} - Unassigned PI Report", "\n".join(md))

    # ------------------------------------------------------------------
    # Hierarchy traversal helpers (shared by team/ART/VS reports)
    # ------------------------------------------------------------------

    def _iter_team_groups(self, root_group):
        """Yield (vs_group, art_group, team_group) for every team in the hierarchy."""
        for vs_sg in root_group.subgroups.list(all=True):
            vs_group = self.gl.groups.get(vs_sg.id)
            for art_sg in vs_group.subgroups.list(all=True):
                art_group = self.gl.groups.get(art_sg.id)
                for team_sg in art_group.subgroups.list(all=True):
                    team_group = self.gl.groups.get(team_sg.id)
                    yield vs_group, art_group, team_group

    def _iter_art_groups(self, root_group):
        """Yield (vs_group, art_group) for every ART in the hierarchy."""
        for vs_sg in root_group.subgroups.list(all=True):
            vs_group = self.gl.groups.get(vs_sg.id)
            for art_sg in vs_group.subgroups.list(all=True):
                art_group = self.gl.groups.get(art_sg.id)
                yield vs_group, art_group

    def _iter_vs_groups(self, root_group):
        """Yield vs_group for every Value Stream under root."""
        for vs_sg in root_group.subgroups.list(all=True):
            yield self.gl.groups.get(vs_sg.id)

    # ------------------------------------------------------------------
    # Team-level reports
    # ------------------------------------------------------------------

    def generate_team_backlog_report(self):
        """One wiki page per team (on each team's own wiki) plus a root-level index page."""
        root_group = self.get_group_by_name(self.parent_group)
        print(f"Generating Team Backlog Reports under: {root_group.full_path}")

        index_entries = []  # (vs_name, art_name, team_name, wiki_url, summary_line)

        for vs_group, art_group, team_group in self._iter_team_groups(root_group):
            print(f"  Processing {team_group.full_path}")
            entry = self._generate_team_backlog_page(vs_group, art_group, team_group)
            if entry:
                index_entries.append(entry)

        # Build the root-level index page
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
        self.upload_to_wiki(root_group, f"{root_group.name} - Team Backlog Index", "\n".join(md))
        print(f"  → Root wiki: {root_group.name} - Team Backlog Index")

    def _generate_team_backlog_page(self, vs_group, art_group, team_group):
        """Upload the team backlog page to the team's own wiki. Returns an index entry tuple."""
        projects = team_group.projects.list(all=True)
        backlog_project = next(
            (self.gl.projects.get(p.id) for p in projects if p.path.endswith("-backlog")),
            None
        )

        breadcrumb = f"{vs_group.name} / {art_group.name} / {team_group.name}"
        wiki_title = "Team Backlog"
        wiki_url   = f"{team_group.web_url}/-/wikis/team-backlog"

        if not backlog_project:
            md = [
                f"# Team Backlog — {team_group.name}",
                f"**{breadcrumb}**  |  **Report Date:** {datetime.today().strftime('%Y-%m-%d')}",
                "",
                "_No Team Backlog project found for this team._",
            ]
            self.upload_to_wiki(team_group, wiki_title, "\n".join(md))
            print(f"    → {team_group.full_path} wiki: {wiki_title}")
            return (vs_group.name, art_group.name, team_group.name, wiki_url, "_(no backlog project)_")


        all_issues = backlog_project.issues.list(all=True)

        # Group by linked Feature epic
        by_feature  = defaultdict(list)
        unlinked    = []
        for issue in all_issues:
            epic = getattr(issue, "epic", None)
            if epic:
                by_feature[epic["id"]].append((epic, issue))
            else:
                unlinked.append(issue)

        total_w  = sum(i.weight or 0 for i in all_issues)
        closed_w = sum(i.weight or 0 for i in all_issues if i.state == "closed")
        open_cnt = sum(1 for i in all_issues if i.state == "opened")

        md = []
        md.append(f"# Team Backlog — {team_group.name}")
        md.append(
            f"**{breadcrumb}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[**View Project**]({backlog_project.web_url})"
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
            for epic_id, pairs in by_feature.items():
                epic_info = pairs[0][0]
                issues    = [i for _, i in pairs]
                f_total   = sum(i.weight or 0 for i in issues)
                f_closed  = sum(i.weight or 0 for i in issues if i.state == "closed")
                f_pct     = round(f_closed / f_total * 100) if f_total else 0
                f_open    = sum(1 for i in issues if i.state == "opened")
                f_state   = epic_info.get("state", "").capitalize()

                md.append(
                    f"<details><summary>🛠️ "
                    f"<a href=\"{epic_info.get('url', '#')}\">{epic_info.get('title', 'Unknown Feature')}</a>"
                    f" — {f_open} open · {f_pct}% done · {f_closed}/{f_total} pt</summary>"
                )
                md.append("")
                md.append(f"**Feature state:** {f_state}")
                md.append("")
                md.append("| Issue | State | Weight | Milestone |")
                md.append("|-------|-------|--------|-----------|")
                for issue in sorted(issues, key=lambda i: i.state):
                    ms    = issue.milestone["title"] if issue.milestone else "—"
                    w     = issue.weight or "—"
                    state = "✅ Closed" if issue.state == "closed" else "🔵 Open"
                    md.append(
                        f"| [{issue.title}]({issue.web_url}) "
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
                ms    = issue.milestone["title"] if issue.milestone else "—"
                w     = issue.weight or "—"
                state = "✅ Closed" if issue.state == "closed" else "🔵 Open"
                md.append(
                    f"| [{issue.title}]({issue.web_url}) "
                    f"| {state} | {w} pt | {ms} |"
                )
            md.append("")

        self.upload_to_wiki(team_group, wiki_title, "\n".join(md))
        print(f"    → {team_group.full_path} wiki: {wiki_title}")

        summary = f"· {len(all_issues)} issues · {pct}% done · {total_w} pt total"
        return (vs_group.name, art_group.name, team_group.name, wiki_url, summary)

    # ------------------------------------------------------------------
    # ART-level reports
    # ------------------------------------------------------------------

    def generate_art_feature_status_report(self):
        """One wiki page per ART showing all Features grouped by Team, plus a root index."""
        root_group = self.get_group_by_name(self.parent_group)
        print(f"Generating ART Feature Status Reports under: {root_group.full_path}")

        metrics  = self.calculate_portfolio_metrics(self.parent_group)
        features = metrics.get("Feature", [])

        # Map team_group_id → (vs_group, art_group, team_group)
        team_hierarchy = {}
        for vs_group, art_group, team_group in self._iter_team_groups(root_group):
            team_hierarchy[team_group.id] = (vs_group, art_group, team_group)

        # Bucket features: art_id → team_id → [feature_metric]
        art_buckets = defaultdict(lambda: defaultdict(list))
        for f in features:
            gid = f.get("group_id")
            if gid in team_hierarchy:
                _, art_grp, _ = team_hierarchy[gid]
                art_buckets[art_grp.id][gid].append(f)

        index_entries = []
        for vs_group, art_group in self._iter_art_groups(root_group):
            if art_group.id not in art_buckets:
                continue
            entry = self._generate_art_feature_status_page(
                root_group, vs_group, art_group,
                art_buckets[art_group.id], team_hierarchy,
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
        self.upload_to_wiki(root_group, f"{root_group.name} - ART Feature Status Index", "\n".join(md))
        print(f"  → Root wiki: {root_group.name} - ART Feature Status Index")

    def _generate_art_feature_status_page(self, root_group, vs_group, art_group, team_buckets, team_hierarchy):
        wiki_title = f"ART Feature Status/{vs_group.name}/{art_group.name}"
        wiki_url   = (
            f"{root_group.web_url}/-/wikis/ART-Feature-Status"
            f"/{vs_group.name.replace(' ', '-')}/{art_group.name.replace(' ', '-')}"
        )

        md = []
        md.append(f"# ART Feature Status — {art_group.name}")
        md.append(
            f"**{vs_group.name} / {art_group.name}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View ART Group]({art_group.web_url})"
        )
        md.append("")

        total_f   = 0
        at_risk   = 0
        blocked_c = 0

        for team_id, feature_list in sorted(team_buckets.items(), key=lambda x: team_hierarchy[x[0]][2].name):
            _, _, team_group = team_hierarchy[team_id]
            md.append(f"## {team_group.name}")
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

        return (vs_group.name, art_group.name, wiki_url, total_f, at_risk, blocked_c)

    def generate_art_capacity_balance_report(self):
        """One wiki page per ART showing per-team capacity balance by PI, plus a root index."""
        root_group = self.get_group_by_name(self.parent_group)
        print(f"Generating ART Capacity Balance Reports under: {root_group.full_path}")

        metrics  = self.calculate_portfolio_metrics(self.parent_group)
        features = metrics.get("Feature", [])

        team_hierarchy = {}
        for vs_group, art_group, team_group in self._iter_team_groups(root_group):
            team_hierarchy[team_group.id] = (vs_group, art_group, team_group)

        # art_id → pi → team_id → [feature_metric]
        art_pi_buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for f in features:
            gid  = f.get("group_id")
            piid = f.get("piid")
            if gid in team_hierarchy and piid:
                _, art_grp, _ = team_hierarchy[gid]
                art_pi_buckets[art_grp.id][piid][gid].append(f)

        index_entries = []
        for vs_group, art_group in self._iter_art_groups(root_group):
            if art_group.id not in art_pi_buckets:
                continue
            entry = self._generate_art_capacity_balance_page(
                root_group, vs_group, art_group,
                art_pi_buckets[art_group.id], team_hierarchy,
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
        self.upload_to_wiki(root_group, f"{root_group.name} - ART Capacity Balance Index", "\n".join(md))
        print(f"  → Root wiki: {root_group.name} - ART Capacity Balance Index")

    def _generate_art_capacity_balance_page(self, root_group, vs_group, art_group, pi_buckets, team_hierarchy):
        wiki_title = f"ART Capacity Balance/{vs_group.name}/{art_group.name}"
        wiki_url   = (
            f"{root_group.web_url}/-/wikis/ART-Capacity-Balance"
            f"/{vs_group.name.replace(' ', '-')}/{art_group.name.replace(' ', '-')}"
        )

        sorted_pis = sorted(
            pi_buckets.keys(),
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min,
        )

        md = []
        md.append(f"# ART Capacity Balance — {art_group.name}")
        md.append(
            f"**{vs_group.name} / {art_group.name}**  |  "
            f"**Report Date:** {datetime.today().strftime('%Y-%m-%d')}  |  "
            f"[View ART Group]({art_group.web_url})"
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

            for team_id, fs in sorted(team_buckets.items(), key=lambda x: team_hierarchy[x[0]][2].name):
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

                team_link = f'<a href="{team_group.web_url}">{team_group.name}</a>'
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

        return (vs_group.name, art_group.name, wiki_url, total_over, total_under)

    def generate_all_reports(self):
        self._run_reports(REPORTS)

    def run_reports_menu(self, report_key=None):
        """Show the reports selection menu or run a specific report by key."""
        if report_key:
            report = next((r for r in REPORTS if r["key"] == report_key), None)
            if report is None:
                print(f"Unknown report '{report_key}'. Available reports:")
                for r in REPORTS:
                    print(f"  {r['key']}")
                sys.exit(1)
            self._run_reports([report])
            return

        print()
        print("Available Reports")
        print("=" * 60)
        print(f"  [0] {'all':<22} Run all reports (default)")
        for i, report in enumerate(REPORTS, 1):
            print(f"  [{i}] {report['key']:<22} {report['description']}")
        print()

        raw = input(f"Select reports [0-{len(REPORTS)}, space-separated, or Enter for all]: ").strip()

        if not raw:
            self._run_reports(REPORTS)
            return

        selected = []
        for token in raw.split():
            try:
                idx = int(token)
                if idx == 0:
                    selected = REPORTS
                    break
                elif 1 <= idx <= len(REPORTS):
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

    def _run_reports(self, reports):
        """Execute a list of report entries from the REPORTS registry."""
        group = self.get_group_by_name(self.parent_group)
        print(f"\nGenerating reports for group: {group.full_path}\n")

        total = len(reports)
        for i, report in enumerate(reports, 1):
            print(f"[{i}/{total}] {report['description']}")
            try:
                method = getattr(self, report["method"])
                method(group) if report["needs_group"] else method()
            except Exception as e:
                print(f"  ERROR running '{report['key']}': {e}")

        print(f"\n{total} report(s) uploaded to wiki.")
