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
        "description": "ART/Team Workload Report — planned vs actual weight per group per PI",
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

    def generate_and_upload_piid_project_report_to_wiki(self, group):
        report_data = {
            project_label: {piid_label: None for piid_label in self.PIID_LABELS}
            for project_label in self.PROJECT_LABELS
        }

        try:
            print(f"Fetching all epics for group: {group.name}")
            all_epics = [group.epics.get(epic.get_id()) for epic in group.epics.list(all=True)]
            print(f"Fetched {len(all_epics)} total epics.")

            relevant_epics = []
            for epic in all_epics:
                project_label = next((label for label in self.PROJECT_LABELS if label in epic.labels), None)
                piid_label    = next((label for label in self.PIID_LABELS    if label in epic.labels), None)
                if project_label and piid_label:
                    relevant_epics.append((epic, project_label, piid_label))

            print(f"Found {len(relevant_epics)} relevant epics with PIID/Project label intersections.")

            for epic, project_label, piid_label in relevant_epics:
                if report_data[project_label][piid_label] is None:
                    report_data[project_label][piid_label] = {
                        "epics_open":  0,
                        "epics_total": 0,
                        "weight_open": 0,
                        "weight_total": 0,
                        "epic_urls":   set(),
                    }

                try:
                    report_data[project_label][piid_label]["epics_total"] += 1
                    if epic.state == "opened":
                        report_data[project_label][piid_label]["epics_open"] += 1

                    linked_issues = epic.issues.list(all=True)
                    for issue in linked_issues:
                        issue_weight = issue.weight if issue.weight else 0
                        report_data[project_label][piid_label]["weight_total"] += issue_weight
                        if issue.state == "opened":
                            report_data[project_label][piid_label]["weight_open"] += issue_weight

                    report_data[project_label][piid_label]["epic_urls"].add(epic.web_url)

                except Exception as issue_error:
                    print(f"Error processing issues for epic ID {epic.get_id()}: {issue_error}")

            markdown_report = []
            markdown_report.append(f"# PIID vs Project Labels Report (Group: {group.name})")
            markdown_report.append("")
            markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
            markdown_report.append("")

            headers = ["| **Project Label → / PIID ↓**"] + [f"| **{piid_label}** " for piid_label in self.PIID_LABELS]
            markdown_report.append("".join(headers) + "|")
            markdown_report.append("|:" + ":|:".join(["---"] * (len(self.PIID_LABELS) + 1)) + ":|")

            for project_label, piid_data in report_data.items():
                row = [f"| **{project_label}** "]
                for piid_label in self.PIID_LABELS:
                    data = piid_data[piid_label]
                    if data:
                        board_url = (
                            f"{group.web_url}/-/work_items?"
                            f"label_name={piid_label}&label_name={project_label}&type[]=EPIC&state=all"
                        )
                        row.append(
                            f"| Epics -  Open: {data['epics_open']} / Total: {data['epics_total']} / "
                            f"Issue Weight Open: {data['weight_open']} / Total Weight: {data['weight_total']} / "
                            f"[View]({board_url}) "
                        )
                    else:
                        row.append("| - ")
                markdown_report.append("".join(row) + "|")

            markdown_report.extend([
                "",
                f"## Quick Links for {group.name}",
                "",
                f"- [Work Items]({group.web_url}/-/work_items)",
                f"- [Issue Boards]({group.web_url}/-/boards)",
                f"- [Epic Boards]({group.web_url}/-/epics?type[]=EPIC)",
                f"- [Roadmap]({group.web_url}/-/roadmap)",
                "",
            ])

            md_content  = "\n".join(markdown_report)
            wiki_title  = "PIID_vs_Project_Labels_Report"
            print(f"Uploading report to wiki: {wiki_title}")
            self.upload_to_wiki(group, wiki_title, md_content)
            return md_content

        except Exception as e:
            print(f"An error occurred while generating or uploading the report: {e}")

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

        self.upload_to_wiki(group, f"{group.name} - ART/Team Workload Report", "\n".join(md))

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
