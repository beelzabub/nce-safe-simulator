import random
import textwrap
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import lorem
import pandas as pd
import requests


class EpicsMixin:

    def get_epics(self, group_name, recursive=False):
        try:
            group = self.get_group_by_name(group_name)
            if not group:
                raise ValueError(f"Group with name '{group_name}' not found.")

            epics = group.epics.list(get_all=True)

            if recursive:
                subgroups = group.subgroups.list(get_all=True, owned=True)
                for subgroup in subgroups:
                    if hasattr(subgroup, "full_path") and subgroup.full_path:
                        try:
                            epics += self.get_epics(subgroup.full_path, recursive=True)
                        except Exception as recursive_error:
                            print(f"Error retrieving epics for subgroup '{subgroup.name}': {recursive_error}")
                    else:
                        print(f"Subgroup '{subgroup.name}' does not have a valid full path. Skipping...")

            return epics

        except Exception as e:
            print(f"Error retrieving epics for group '{group_name}': {e}")
            return []

    def export_epics_to_csv(self, group_name):
        group = self.get_group_by_name(group_name)
        epics = group.epics.list(get_all=True)

        print()
        print(f"Exporting epics for group {group_name} ...")

        data = []
        for epic in epics:
            data.append({
                'id':          epic.id,
                'iid':         epic.iid,
                'title':       epic.title,
                'description': epic.description,
                'state':       epic.state,
                'author':      epic.author.get('name') if epic.author else '',
                'created_at':  epic.created_at,
                'web_url':     epic.web_url,
                'labels':      ", ".join(epic.labels),
            })

        df = pd.DataFrame(data)
        output_file = f"{self.sanitize_name(group_name)}-epics.csv"
        df.to_csv(output_file, index=False)

        print(f"Successfully exported {len(data)} epics to {output_file}")
        print()

    def import_epics_from_csv(self, group_name, csv_file):
        group = self.get_group_by_name(group_name)

        print()
        print(f"Importing epics into group {self.sanitize_name(group_name)} from {csv_file} ...")

        try:
            df = pd.read_csv(csv_file)
        except pd.errors.ParserError as e:
            print(f"Error reading CSV file '{csv_file}': {e}")
            print("Ensure the file has a consistent number of columns and proper format.")
            return
        except FileNotFoundError:
            print(f"CSV file '{csv_file}' not found. Please check the file path.")
            return

        for index, row in df.iterrows():
            try:
                if 'title' not in row or pd.isna(row['title']):
                    print(f"Skipping row {index + 1} due to missing title.")
                    continue

                epic_data = {
                    'title':       row['title'],
                    'description': row.get('description', ''),
                }
                group.epics.create(epic_data)
                print(f"  Created Epic: {row['title']}")

            except KeyError as e:
                print(f"Failed to process row {index + 1}: Missing required column {e}")
            except Exception as e:
                print(f"Failed to create epic for row {index + 1}: {e}")

        print(f"Completed importing epics to group {group_name}")
        print()

    def delete_all_group_epics(self, group_name):
        root = self.get_group_by_name(group_name)
        if root is None:
            print(f"Group '{group_name}' not found. Aborting epic deletion.")
            return

        print()
        print(f"Deleting epics from '{group_name}' and all subgroups...")

        def _delete_epics_in_group(group):
            for sg in group.subgroups.list(all=True):
                full_sg = self.gl.groups.get(sg.id)
                _delete_epics_in_group(full_sg)
            for epic in group.epics.list(all=True):
                try:
                    epic.delete()
                    print(f"  Deleted epic '{epic.title}' (id: {epic.id}) from '{group.full_path}'")
                except Exception as e:
                    print(f"  Failed to delete epic '{epic.title}' (id: {epic.id}): {e}")

        try:
            _delete_epics_in_group(root)
        except Exception as e:
            print(f"Failed to delete epics: {e}")

        print(f"Completed deleting epics from '{group_name}'.")
        print()

    def create_epics_lorem(self, group_name, num_epics=15, create_hierarchy=False):
        try:
            group = self.get_group_by_name(group_name)
            created_epics = []

            def get_next_monday():
                today = datetime.today()
                first_of_next_month = datetime(today.year, today.month, 1) + relativedelta(months=1)
                while first_of_next_month.weekday() != 0:
                    first_of_next_month += timedelta(days=1)
                return first_of_next_month.date()

            def get_random_end_date(start_date):
                end = start_date + relativedelta(months=random.randint(1, 6))
                while end.weekday() != 0:
                    end += timedelta(days=1)
                return end

            print(f"Generating lorem epics for group: {group.name}")
            for i in range(num_epics):
                title         = lorem.sentence()
                description   = lorem.paragraph()
                weight        = random.choice(self.fibonacci_weights)
                start_date    = get_next_monday()
                due_date      = get_random_end_date(start_date)
                project_label = random.choice(self.PROJECT_LABELS)
                piid_label    = random.choice(self.PIID_LABELS)
                epic_label    = random.choice(self.EPIC_TYPE_LABELS)

                epic = group.epics.create({
                    'title':       title,
                    'description': description,
                    'start_date':  start_date.isoformat(),
                    'due_date':    due_date.isoformat(),
                    'weight':      weight,
                    'labels':      [project_label, piid_label, epic_label],
                })

                print(
                    f"Created epic {epic.iid} - Title: {title}, Weight: {weight}, "
                    f"Start: {start_date}, End: {due_date}, "
                    f"Project Label: {project_label}, PIID Label: {piid_label}, Type Label: {epic_label}"
                )
                created_epics.append((epic, epic_label))

            if create_hierarchy:
                self.build_epic_hierarchy(group, created_epics)

            return created_epics

        except Exception as e:
            print(f"Error creating epics: {e}")
            return []

    def build_epic_hierarchy(self, group, epics):
        try:
            print(f"Building epic hierarchy for group '{group.name}'")

            epic_dict = defaultdict(list)
            for epic, label in epics:
                epic_dict[label].append(epic)

            for epic in epic_dict.get("Epic", []):
                capabilities = random.sample(
                    epic_dict.get("Capability", []),
                    k=min(len(epic_dict.get("Capability", [])), 2)
                )
                for capability in capabilities:
                    try:
                        capability.parent_id = epic.id
                        capability.save()
                        print(f"Linked Capability '{capability.title}' as child of Epic '{epic.title}'")
                    except Exception as e:
                        print(f"Failed to link Capability '{capability.title}' to Epic '{epic.title}': {e}")

                    features = random.sample(
                        epic_dict.get("Feature", []),
                        k=min(len(epic_dict.get("Feature", [])), 3)
                    )
                    for feature in features:
                        try:
                            feature.parent_id = capability.id
                            feature.save()
                            print(f"Linked Feature '{feature.title}' as child of Capability '{capability.title}'")
                        except Exception as e:
                            print(f"Failed to link Feature '{feature.title}' to Capability '{capability.title}': {e}")

        except Exception as e:
            print(f"Error building epic hierarchy: {e}")

    def assign_issues_to_epics(self, epics, issues):
        if not epics:
            print("No epics available to assign issues to.")
            return {}

        epic_objects  = [epic_tuple[0] for epic_tuple in epics]
        assigned_issues = {}

        for issue in issues:
            selected_epic = random.choice(epic_objects)
            try:
                issue.epic_id = selected_epic.id
                issue.save()

                if selected_epic.title not in assigned_issues:
                    assigned_issues[selected_epic.title] = []

                assigned_issues[selected_epic.title].append({
                    'issue_id':    issue.iid,
                    'issue_title': issue.title,
                    'issue_url':   issue.web_url,
                })

                print(f"Assigned issue #{issue.iid} ({issue.title}) to epic '{selected_epic.title}'")

            except Exception as e:
                print(f"Failed to assign issue #{issue.iid} ({issue.title}) to epic '{selected_epic.title}': {e}")

        return assigned_issues

    def md_group_epics_report(self, group_name, wiki_page_slug="home", create_local_file=False):
        group = self.get_group_by_name(group_name)
        epics = group.epics.list(get_all=True)

        all_subgroups = self.get_all_subgroups(group)

        open_epics_count  = sum(1 for e in epics if e.state == 'opened')
        total_epics       = len(epics)

        session = requests.Session()
        session.headers.update({
            'Authorization': f'Bearer {self.private_token}',
            'Content-Type': 'application/json',
        })

        graphql_query = """
        query GetWorkItemWeight($id: ID!) {
            workItem(id: $id) {
                id
                widgets {
                    ... on WorkItemWidgetWeight {
                        weight
                    }
                }
            }
        }
        """

        total_story_points = 0
        open_story_points  = 0
        epic_rows          = []
        grouped_epics      = {}

        for epic in epics:
            group_id    = epic.attributes['group_id']
            epic_group  = next((g for g in all_subgroups if g.id == group_id), None)

            if not epic_group:
                print(f"Warning: No group found for Epic '{epic.title}' with group ID {group_id}")
                continue

            subgroup_name = epic_group.full_path
            subgroup_url  = epic_group.web_url
            epic_url      = f"{subgroup_url}/-/epics/{epic.iid}"

            work_item_id = getattr(epic, 'work_item_id', None)
            if not work_item_id:
                work_item_id = f"gid://gitlab/WorkItem/{epic.id}"

            planned_weight = 0
            try:
                resp = session.post(
                    f"{self.url}/api/graphql",
                    json={"query": graphql_query, "variables": {"id": work_item_id}}
                )
                if resp.ok:
                    data    = resp.json()
                    widgets = data.get('data', {}).get('workItem', {}).get('widgets', [])
                    for widget in widgets:
                        if isinstance(widget, dict) and widget.get('weight') is not None:
                            planned_weight = widget['weight']
                            break
            except Exception as e:
                print(f"Error fetching weight for Epic '{epic.title}': {e}")

            issues             = epic.issues.list(get_all=True)
            actual_total_weight = sum(issue.weight or 0 for issue in issues)
            actual_open_weight  = sum(issue.weight or 0 for issue in issues if issue.state == 'opened')

            total_story_points += actual_total_weight
            open_story_points  += actual_open_weight

            if subgroup_name not in grouped_epics:
                grouped_epics[subgroup_name] = []

            grouped_epics[subgroup_name].append({
                "title":               epic.title,
                "state":               epic.state.capitalize(),
                "planned_weight":      planned_weight,
                "actual_total_weight": actual_total_weight,
                "actual_open_weight":  actual_open_weight,
                "issues":              len(issues),
                "url":                 epic_url,
                "group_url":           subgroup_url,
            })

        md = self.build_markdown_report(
            group=group,
            total_epics=total_epics,
            open_epics_count=open_epics_count,
            total_story_points=total_story_points,
            open_story_points=open_story_points,
            epic_rows=epic_rows,
            grouped_epics=grouped_epics,
            base_url=self.url,
        )

        print(f"Posting the Markdown content to the Group Wiki page '{wiki_page_slug}' in group '{group_name}'...")

        try:
            existing_pages    = group.wikis.list()
            wiki_page_exists  = any(page.slug == wiki_page_slug for page in existing_pages)

            if wiki_page_exists:
                wiki_page         = next(page for page in existing_pages if page.slug == wiki_page_slug)
                wiki_page.content = md
                wiki_page.save()
                print(f"Updated existing Group Wiki page '{wiki_page_slug}' in group '{group_name}'.")
            else:
                group.wikis.create({'title': wiki_page_slug, 'content': md})
                print(f"Created and posted the new Group Wiki page '{wiki_page_slug}' in group '{group_name}'.")
        except Exception as e:
            print(f"Failed to post content to the Group Wiki page '{wiki_page_slug}': {e}")

        if create_local_file:
            md_filename = f"{group.name.lower()}-epic-report.md"
            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"Markdown report saved as '{md_filename}'")

    def build_markdown_report(self, group, total_epics, open_epics_count,
                               total_story_points, open_story_points,
                               epic_rows, grouped_epics, base_url):
        from datetime import datetime as _dt

        md = textwrap.dedent(f"""
        # GitLab Epic Report - {group.name}
        **Generated:** {_dt.now().strftime("%Y-%m-%d %H:%M:%S")}

        **Author:** Jamie Powers

        ## 📊 Summary

        | Metric                          | Value |
        |---------------------------------|-------|
        | **Total Epics**                 | {total_epics} |
        | **Open Epics**                  | {open_epics_count} |
        | **Total Actual Story Points**   | {total_story_points} |
        | **Open Actual Story Points**    | {open_story_points} |

        ---
        """)

        for subgroup, epics in grouped_epics.items():
            web_url = epics[0]['group_url'] if 'group_url' in epics[0] else f"{base_url}/groups/{subgroup}"

            md += textwrap.dedent(f"""
            <details>
            <summary><strong>{subgroup} - <a href="{web_url}" target="_blank" rel="noopener noreferrer">View</a></strong></summary>


            | Epic Title | State | **Planned Weight**<br>(on Epic) | Actual Total Weight<br>(Issues) | Actual Open Weight | Linked Issues |
            |------------|-------|--------------------------------|---------------------------------|---------------------|---------------|
            """)

            for epic in epics:
                epic_link = f'<a href="{epic["url"]}" target="_blank" rel="noopener noreferrer">{epic["title"]}</a>'
                md += (
                    f"| {epic_link} | {epic['state']} | **{epic['planned_weight']}** | "
                    f"{epic['actual_total_weight']} | {epic['actual_open_weight']} | "
                    f"{epic['issues']} |\n"
                )

            md += "</details>\n\n"

        all_epics_url = f"{base_url}/groups/{group.full_path}/-/epics?state=all"
        md += textwrap.dedent(f"""
        ---

        ## 🔗 Quick Links

        - **[All Epics]({all_epics_url})**
        - **[Open Epics]({base_url}/groups/{group.full_path}/-/epics?state=opened)**
        - **[Group Roadmap]({base_url}/groups/{group.full_path}/-/roadmap)**

        ---
        **Notes:**
        - **Planned Weight**: Weight set directly on the Epic (via GraphQL)
        - **Actual Weights**: Sum of `weight` from linked issues.

        Generated by ***Jamie Powers***
        """)

        return md
