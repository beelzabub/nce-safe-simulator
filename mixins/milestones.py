import random
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

import lorem


class MilestonesMixin:

    def get_group_milestones(self, group_name, recursive=False):
        try:
            group = self.get_group_by_name(group_name)
            if not group:
                raise ValueError(f"Group with name '{group_name}' not found.")

            milestones = group.milestones.list(get_all=True)

            if recursive:
                subgroups = group.subgroups.list(get_all=True, owned=True)
                for subgroup in subgroups:
                    if hasattr(subgroup, "full_path") and subgroup.full_path:
                        try:
                            milestones += self.get_group_milestones(subgroup.name, recursive=True)
                        except Exception as recursive_error:
                            print(f"Error retrieving milestones for subgroup '{subgroup.name}': {recursive_error}")
                    else:
                        print(f"Subgroup '{subgroup.name}' does not have a valid full path. Skipping...")

            return milestones

        except Exception as e:
            print(f"Error retrieving milestones for group '{group_name}': {e}")
            return []

    def list_group_milestones(self, group_name, recursive=False):
        try:
            group = self.get_group_by_name(group_name)
            if not group:
                raise ValueError(f"Group with name '{group_name}' not found.")

            milestones = group.milestones.list(get_all=True)

            for milestone in milestones:
                print(f"- [Milestone: {milestone.title}]({milestone.web_url}): {milestone.state} (ID: {milestone.id})")

            if recursive:
                subgroups = group.subgroups.list(get_all=True, owned=True)
                for subgroup in subgroups:
                    if hasattr(subgroup, "full_path") and subgroup.full_path:
                        try:
                            self.list_group_milestones(subgroup.name, recursive=True)
                        except Exception as recursive_error:
                            print(f"Error retrieving milestones for subgroup '{subgroup.name}': {recursive_error}")
                    else:
                        print(f"Subgroup '{subgroup.name}' does not have a valid full path. Skipping...")
        except Exception as e:
            print(f"Error retrieving milestones for group '{group_name}': {e}")

    def get_epics_under_milestones(self, group_name):
        try:
            group = self.get_group_by_name(group_name)
            if not group:
                raise ValueError(f"Group with name '{group_name}' not found.")

            milestones_with_epics = {}
            milestones = group.milestones.list(get_all=True)
            all_epics  = group.epics.list(get_all=True)

            for milestone in milestones:
                try:
                    milestone_start_date = datetime.fromisoformat(milestone.start_date).replace(tzinfo=timezone.utc)
                    milestone_end_date   = datetime.fromisoformat(milestone.due_date).replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                associated_epics = []
                for epic in all_epics:
                    epic_start = epic.start_date_from_milestones or epic.start_date_fixed
                    epic_end   = epic.due_date_from_milestones or epic.due_date_fixed

                    if epic_start and epic_end:
                        try:
                            epic_start_date = datetime.fromisoformat(epic_start.replace("Z", "+00:00"))
                            epic_end_date   = datetime.fromisoformat(epic_end.replace("Z", "+00:00"))

                            if not (epic_end_date < milestone_start_date or epic_start_date > milestone_end_date):
                                associated_epics.append({
                                    "id":         epic.id,
                                    "title":      epic.title,
                                    "state":      epic.state,
                                    "web_url":    epic.web_url,
                                    "start_date": epic_start_date,
                                    "end_date":   epic_end_date,
                                })
                        except Exception as epic_date_error:
                            print(f"Error parsing dates for Epic: {epic.title} (ID: {epic.id}) - {epic_date_error}")
                            continue

                milestones_with_epics[milestone.title] = {
                    "milestone": {
                        "id":          milestone.id,
                        "title":       milestone.title,
                        "start_date":  milestone_start_date,
                        "end_date":    milestone_end_date,
                        "description": milestone.description,
                        "state":       milestone.state,
                        "web_url":     milestone.web_url,
                    },
                    "epics": associated_epics,
                }

            return milestones_with_epics

        except Exception as e:
            print(f"Error: {e}")
            return {}

    def upload_milestones_and_epics_to_wiki(self, group, data_structure, wiki_page_title="Milestones_and_Epics"):
        try:
            markdown_content  = "# Milestones and Epics\n\n"
            markdown_content += "## Summary Table\n\n"
            markdown_content += "| Milestone Title | Open Epics | Closed Epics | Total Epics | Percent Complete |\n"
            markdown_content += "|-----------------|------------|--------------|-------------|------------------|\n"

            detailed_content = ""

            for milestone_title, milestone_data in data_structure.items():
                milestone    = milestone_data['milestone']
                epics        = milestone_data['epics']
                open_epics   = [epic for epic in epics if epic['state'] == "opened"]
                closed_epics = [epic for epic in epics if epic['state'] == "closed"]
                total_epics  = len(open_epics) + len(closed_epics)
                percent_complete = f"{(len(closed_epics) / total_epics * 100):.2f}%" if total_epics > 0 else "0.00%"

                markdown_content += f"| {milestone['title']} | {len(open_epics)} | {len(closed_epics)} | {total_epics} | {percent_complete} |\n"

                detailed_content += f"\n## 🎯 Milestone: {milestone['title']}\n"
                detailed_content += f"- **State**: {milestone['state']}\n"
                detailed_content += f"- **Description**: {milestone['description'] or 'N/A'}\n"
                detailed_content += f"- **Start Date**: {milestone['start_date'].strftime('%Y-%m-%d') if milestone['start_date'] else 'N/A'}\n"
                detailed_content += f"- **Due Date**: {milestone['end_date'].strftime('%Y-%m-%d') if milestone['end_date'] else 'N/A'}\n"
                detailed_content += f"- **[View Milestone]({milestone['web_url']})**\n"

                if epics:
                    detailed_content += "\n### Associated Epics:\n"
                    for epic in epics:
                        detailed_content += (
                            f"- **[View Epic]({epic['web_url']})**: {epic['title']} "
                            f"(State: {epic['state']}, Start: {epic['start_date'].strftime('%Y-%m-%d')}, "
                            f"End: {epic['end_date'].strftime('%Y-%m-%d')})\n"
                        )
                else:
                    detailed_content += "\nNo associated epics for this milestone.\n"

            markdown_content += "\n" + detailed_content

            self.upload_to_wiki(group, wiki_page_title, markdown_content)

        except Exception as e:
            print(f"Error creating wiki page for milestones and epics: {e}")
            return

    def create_lorem_milestones(self, target, num_milestones=12):
        try:
            target_type = 'group' if hasattr(target, 'milestones') and hasattr(target, 'projects') else 'project'

            current_date    = datetime.today()
            year_start      = datetime(current_date.year, current_date.month, 1)
            year_end        = year_start + relativedelta(months=12)
            created_milestones = []
            milestone_start = year_start

            for i in range(num_milestones):
                while milestone_start.weekday() != 0:
                    milestone_start += timedelta(days=1)

                milestone_duration = random.randint(1, 4)
                milestone_end      = milestone_start + relativedelta(months=milestone_duration) - timedelta(days=1)

                if milestone_end <= milestone_start:
                    milestone_end = milestone_start + timedelta(days=1)

                if milestone_end > year_end:
                    milestone_end = year_end

                if milestone_start >= milestone_end:
                    print(f"Skipping milestone creation: Start={milestone_start.date()} is not before End={milestone_end.date()}")
                    break

                try:
                    milestone_title       = lorem.sentence()
                    milestone_description = lorem.paragraph()

                    milestone = target.milestones.create({
                        'title':       milestone_title,
                        'description': milestone_description,
                        'start_date':  milestone_start.date().isoformat(),
                        'due_date':    milestone_end.date().isoformat(),
                    })

                    created_milestones.append(milestone)
                    print(f"Created {target_type} milestone '{milestone.title}' from {milestone_start.date()} to {milestone_end.date()}")
                    milestone_start = milestone_end + timedelta(days=1)

                except Exception as e:
                    print(
                        f"Failed to create {target_type} milestone '{milestone_title}' with "
                        f"start_date={milestone_start.date()} and due_date={milestone_end.date()}: {e}"
                    )

            return created_milestones

        except Exception as e:
            print(f"Failed to create milestones for the target: {e}")
            return []

    def delete_all_milestones(self, target):
        try:
            target_type = 'group' if hasattr(target, 'milestones') and hasattr(target, 'projects') else 'project'
            milestones  = target.milestones.list(all=True)

            if not milestones:
                print(f"No milestones found in the {target_type}. Nothing to delete.")
                return []

            deleted_milestones = []

            for milestone in milestones:
                try:
                    milestone_object = target.milestones.get(milestone.id)
                    milestone_title  = milestone_object.title
                    milestone_object.delete()
                    print(f"Deleted {target_type} milestone: {milestone_title}")
                    deleted_milestones.append(milestone_title)
                except Exception as e:
                    print(f"Failed to delete {target_type} milestone {milestone.title}: {e}")

            return deleted_milestones

        except Exception as e:
            print(f"Failed to delete milestones from the target: {e}")
            return []
