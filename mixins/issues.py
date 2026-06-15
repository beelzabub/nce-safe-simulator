import csv
import random

import lorem


class IssuesMixin:

    def import_issues_into_project(self, project_name, csv_file):
        project = self.get_project_by_name(project_name)
        if not project:
            print(f"Project '{project_name}' not found. Aborting issue import.")
            return

        print()
        print(f"Found Project id: {project.id}, name: {project.name}")
        print(f"Importing issues into project '{project_name}' from '{csv_file}'...")

        try:
            with open(csv_file, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    try:
                        issue_data = {
                            'title':       row['Title'],
                            'description': row['Description'],
                            'assignee_ids': [],
                            'labels':      row['Labels'].split(",") if row['Labels'] else [],
                            'milestone_id': None,
                            'due_date':    row['Due Date'] if row['Due Date'] else None,
                        }

                        if row['Milestone']:
                            milestones = project.milestones.list(search=row['Milestone'])
                            if milestones:
                                issue_data['milestone_id'] = milestones[0].id

                        issue = project.issues.create(issue_data)
                        print(f"Successfully created issue: {issue.title}")
                    except Exception as e:
                        print(f"Failed to create issue from row '{row['Title']}': {e}")

                print()

        except FileNotFoundError:
            print(f"File '{csv_file}' not found. Please check the path.")
        except Exception as e:
            print(f"Error processing the CSV file: {e}")

        print(f"Completed importing issues into project '{project_name}'.")
        print()

    def export_project_issues_to_csv(self, project_name):
        project = self.get_project_by_name(project_name)

        if project is None:
            print(f"Project '{project_name}' not found. Cannot export issues.\n")
            return

        output_file = f"{self.sanitize_name(project.name)}-issues.csv"

        print()
        print(f"Found Project: {project.name} (ID: {project.id})")
        print(f"Exporting issues to '{output_file}'...")

        try:
            issues     = project.issues.list(all=True)
            issues_data = []

            for issue in issues:
                issues_data.append({
                    "Issue ID":    issue.id,
                    "Title":       issue.title,
                    "Description": issue.description,
                    "State":       issue.state,
                    "Author":      issue.author["name"] if issue.author else "Unknown",
                    "Created At":  issue.created_at,
                    "Due Date":    issue.due_date if issue.due_date else "None",
                    "Labels":      ", ".join(issue.labels) if issue.labels else "None",
                    "Milestone":   issue.milestone["title"] if issue.milestone else "None",
                })

            with open(output_file, mode="w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=issues_data[0].keys())
                writer.writeheader()
                writer.writerows(issues_data)

            print(f"Successfully exported {len(issues_data)} issues to '{output_file}'.")
            print()
        except Exception as e:
            print(f"Failed to export issues: {e}")

    def create_issues_lorem(self, project_name, num_issues=5):
        try:
            project       = self.get_project_by_name(project_name)
            created_issues = []

            for i in range(num_issues):
                title       = lorem.sentence()
                description = lorem.paragraph()
                weight      = random.choice(self.fibonacci_weights)

                issue_data = {
                    'title':       title,
                    'description': description,
                    'weight':      weight,
                }

                issue = project.issues.create(issue_data)

                print(f"Created issue #{issue.iid} - Title: {title}, Weight: {weight}")
                created_issues.append(issue)

            return created_issues

        except Exception as e:
            print(f"Failed to create issues in project '{project_name}': {e}")
            return []

    def assign_issues_to_milestones(self, milestones, issues):
        if not milestones:
            print("No milestones available to assign issues to.")
            return {}

        if not issues:
            print("No issues provided for assignment.")
            return {}

        assigned_issues = {}

        for issue in issues:
            try:
                selected_milestone = random.choice(milestones)

                issue.milestone_id = selected_milestone.id
                issue.save()

                if selected_milestone.title not in assigned_issues:
                    assigned_issues[selected_milestone.title] = []
                assigned_issues[selected_milestone.title].append({
                    'issue_id':    issue.iid,
                    'issue_title': issue.title,
                    'issue_url':   issue.web_url,
                })

                print(f"Assigned issue '{issue.title}' to milestone '{selected_milestone.title}'")

            except Exception as e:
                print(f"Failed to assign issue '{issue.title}' to milestone '{selected_milestone.title}': {e}")

        print()
        return assigned_issues

    def delete_all_issues_from_project(self, project_name):
        project = self.get_project_by_name(project_name)
        if project is None:
            print(f"Project '{project_name}' not found. Cannot delete issues.")
            return

        print()
        print(f"Deleting all issues from project '{project_name}'...")

        try:
            issues = project.issues.list(all=True)

            for issue in issues:
                try:
                    issue.delete()
                    print(f"Deleted Issue: {issue.title} (id: {issue.id})")
                except Exception as e:
                    print(f"Failed to delete issue: {issue.title} (id: {issue.id}). Error: {e}\n")

            print(f"Successfully deleted all issues from project '{project_name}'")
            print()
        except Exception as e:
            print(f"Failed to delete issues from the project: {e}\n")

    def issues_assign_random_weights(self, group_name, recursive=False):
        group = self.get_group_by_name(group_name)
        if group is None:
            print(f"Group '{group_name}' not found. Aborting weight assignment.")
            return

        print()
        print(f"Found Group: {group.name} (id: {group.id})")
        print(
            f"Now processing issues in projects under the group '{group_name}'"
            f"{' and its subgroups' if recursive else ''}..."
        )

        def process_projects_in_group(group):
            projects = group.projects.list(all=True)
            for project in projects:
                print(f"Processing project: {project.name}")
                project_full = self.gl.projects.get(project.id)

                issues = project_full.issues.list(all=True)
                for issue in issues:
                    if issue.weight is None:
                        try:
                            issue_weight  = random.choice(self.fibonacci_weights)
                            issue.weight  = issue_weight
                            issue.save()
                            print(f"Assigned random weight {issue_weight} to issue: {issue.title} (id: {issue.id})")
                        except Exception as e:
                            print(f"Failed to assign weight for issue '{issue.title}' (id: {issue.id}): {e}")
                    else:
                        print(f"Issue '{issue.title}' (ID: {issue.id}) already has a weight: {issue.weight}")

        process_projects_in_group(group)

        if recursive:
            subgroups = group.subgroups.list(all=True)
            for subgroup in subgroups:
                self.issues_assign_random_weights(subgroup.full_path, recursive=True)

        print(
            f"Completed assigning random weights to all unweighted issues in group '{group_name}'"
            f"{' and its subgroups' if recursive else ''}."
        )
        print()
