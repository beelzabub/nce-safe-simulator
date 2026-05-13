import csv
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from collections import defaultdict
import textwrap
import gitlab
import lorem
import json
import markdown
import math
import pandas as pd
from pathlib import Path
from pprint import pformat
from pprint import pprint
import random
import re
import requests
import time

PROJECT_LABELS = ['project::DO', 'project::RTSO', 'project::DCGS', 'project::TestA', 'project::TestB', 'project::TestC']
PIID_LABELS = ['PIID::2026Q3', 'PIID::2026Q4', 'PIID::2027Q1', 'PIID::2027Q2', 'PIID::2027Q3', 'PIID::2027Q4']
EPIC_LABELS = ['Epic', 'Capability', 'Feature']


class NceGitLab:
    # Constructor
    def __init__(self):
        # Setup configuration from the config file
        self.config_file = Path("nec_gitlab_config.json")

        if not self.config_file.exists():
            print(f"Config file '{self.config_file}' not found!")
            print('''Please create gitlab_config.json with:
                    {
                    "url": "https://gitlab.com",
                    "private_token": "glpat-XXXXXXXXXXXXXXXXXXXX",
                    "group_path": "saic-study-group"
                    }''')
            exit(1)

        with open(self.config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        self.url = config.get("url")
        self.private_token = config.get("private_token")
        self.group_name = config.get("group_name")

        if not all([self.url, self.private_token, self.group_name]):
            print("Missing required fields in gitlab_config.json")
            exit(1)

        self.gl = gitlab.Gitlab(self.url, private_token=self.private_token)
        self.gl.auth()  # Authenticate the client

        print(f'''
NceGitLab:
    Version: {self.gl.version()}
    api_url: {self.gl.api_url}
    api_version: {self.gl.api_version}
              ''')
        
    #
    # Group functions
    #
    def list_groups(self):
        groups = self.gl.groups.list(owned=True, all=True)
        print(f"Groups: {len(groups)}")
        for group in groups:
            print(f"id: {group.get_id()}, name: {group.name}, web_url: {group.web_url}")
        print()


    def get_groups(self):
        partial_groups = self.gl.groups.list(owned=True, all=True)
        # Retrieve full group objects, not the lightweight ones returned by list()
        full_groups = [self.gl.groups.get(group.id) for group in partial_groups]
        return full_groups
    

    def get_group_by_id(self, group_id):
        try:
            found_group = None
            groups = self.get_groups()
            for group in groups:
                if group.get_id() == group_id:
                    found_group = group
                    break

            return found_group
        except Exception as e:
            print(f"Error retrieving group for group_id '{group_id}'")
            return None
    

    def get_group_by_name(self, name):
        group = None
        groups = [g for g in self.gl.groups.list(owned=True, all=True) if g.name == name]

        length = len(groups)

        if length == 1:
            subset_group = groups[0]
            group = self.gl.groups.get(subset_group.get_id())

        return group


    # This function is unecessary as the top level group already returns all subgroups
    def get_all_subgroups(self, obj, include_self=True):
        group = None

        if isinstance(obj, str):
            group = self.get_group_by_name(obj)
        else:
            group = obj

        subgroups = group.subgroups.list(all=True)
        all_subgroups = []

        if include_self:
            all_subgroups.append(obj)

        for subgroup in subgroups:
            full_subgroup = self.gl.groups.get(subgroup.id)
            all_subgroups.append(full_subgroup)
            all_subgroups.extend(self.get_all_subgroups(full_subgroup))

        return all_subgroups
    
        
    #
    # Project functions
    #  
    def list_projects(self):
        projects = self.gl.projects.list(owned=True, all=True)
        print(f"Projects: {len(projects)}")
        for project in projects:
            print(f"id: {project.get_id()}, name: {project.name}, web_url: {project.web_url}")
        print()


    def list_projects_recursive(self, group_name=None, level=0):
        if group_name is None:
            group_name = self.group_name


        group = self.get_group_by_name(group_name)
        if group is None:
            # print(f"{'    ' * level}Group with name '{group_name}' could not be found or is not unique.")
            return

        # List all projects in this group
        print(f"{'    ' * level}Group: {group.name} (id: {group.id})")
        projects = group.projects.list(all=True)
        for project in projects:
            print(f"{'    ' * (level + 1)}Project id: {project.id}, Name: {project.name}")

        subgroups = group.subgroups.list(all=True)
        for subgroup in subgroups:
            # Use the 'full_path' to disambiguate subgroup names if necessary
            self.list_projects(subgroup.name, level + 1)


    def get_projects(self):
        partial_projects = self.gl.projects.list(owned=True, all=True)
        # Retrieve full project objects, not the lightweight ones returned by list()
        full_projects = [self.gl.projects.get(project.id) for project in partial_projects]
        return full_projects
    

    def get_projectsxxx(self, project_name=None):
        if project_name is None:
            project_name = self.project_name

        project = self.get_project_by_name(project_name)
        if project is None:
            return []

        all_projects = []
        projects = project.projects.list(all=True)
        all_projects.extend(projects)

        subgroups = project.subgroups.list(all=True)
        for subgroup in subgroups:
            sub_projects = self.get_projects(subgroup.full_path)
            all_projects.extend(sub_projects)

        return all_projects

    def get_project_by_name(self, name):
        project = None
        projects = [p for p in self.gl.projects.list(owned=True, all=True) if p.name == name]

        length = len(projects)

        if length == 1:
            subset_project = projects[0]
            project = self.gl.projects.get(subset_project.get_id())
        else:
            print(f"get_project_by_name: projects len: {len(projects)}")

        return project


    def get_project_by_namexxxx(self, name):
        try:
            projects = self.gl.projects.list(search=name)
            if len(projects) == 1:
                return projects[0]
            elif len(projects) > 1:
                print(f"More than one project found with the name '{name}'. Ensure project names are unique!")
            else:
                print(f"No project found with name '{name}'.")
            return None
        except Exception as e:
            print(f"Error searching for project '{name}': {e}")
            return None

    
    #
    # Epics functions
    #
    def get_epics(self, group_name, recursive=False):
        try:
            group = self.get_group_by_name(group_name)
            if not group:
                raise ValueError(f"Group with name '{group_name}' not found.")

            # Initialize a list to store epics
            epics = group.epics.list(get_all=True)

            if recursive:
                subgroups = group.subgroups.list(get_all=True, owned=True)  # Fetch subgroups

                for subgroup in subgroups:
                    if hasattr(subgroup, "full_path") and subgroup.full_path:
                        try:
                            epics += self.list_group_epics(subgroup.full_path, recursive=True)
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
                'id': epic.id,
                'iid': epic.iid,
                'title': epic.title,
                'description': epic.description,
                'state': epic.state,
                'author': epic.author.get('name') if epic.author else '',
                'created_at': epic.created_at,
                'web_url': epic.web_url,
                'labels': ", ".join(epic.labels)
            })

        df = pd.DataFrame(data)
        output_file = f"{self.sanitize_name(group_name)}-epics.csv"
        df.to_csv(output_file, index=False)

        print(f"Successfully exported {len(data)} epics to {output_file}")
        print()

    #
    # TODO: add labels and maybe other fields
    #       check what is exported by default
    #
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
                    'title': row['title'],
                    'description': row.get('description', ''),  # Optional
                    # Uncomment and handle if labels are needed
                    # 'labels': row.get('labels', ''),  # Optional
                }
                
                group.epics.create(epic_data)
                print(f"  Created Epic: {row['title']}")

            except KeyError as e:
                print(f"Failed to process row {index + 1}: Missing required column {e}")
            except Exception as e:
                print(f"Failed to create epic for row {index + 1}: {e}")

        print(f"Completed importing epics to group {group_name}")
        print()


    def delete_all_group_epics(self, group_name, recursive=False):
        group = self.get_group_by_name(group_name)
        if group is None:
            print(f"Group '{group_name}' not found. Aborting epic deletion.")
            return

        print()
        print(f"Deleting epics from group '{group_name}'{' and its subgroups' if recursive else ''}...")

        try:
            epics = group.epics.list(all=True)
            for epic in epics:
                try:
                    epic.delete()
                    print(f"Deleted Epic: {epic.title} (id: {epic.id}) from group '{group.name}'")
                except Exception as e:
                    print(f"Failed to delete epic: {epic.title} (ID: {epic.id}). Error: {e}")

            if recursive:
                subgroups = group.subgroups.list(all=True)
                for subgroup in subgroups:
                    self.delete_all_group_epics(subgroup.full_path, recursive=True)

        except Exception as e:
            print(f"Failed to delete epics from group '{group_name}': {e}")

        print(f"Completed deleting epics from group '{group_name}'{' and its subgroups' if recursive else ''}.")
        print()


    def create_epics_lorem_before_labels(self, group_name, num_epics=15):
        try:
            group = self.get_group_by_name(group_name)

            fibonacci_weights = [1, 2, 3, 5, 8, 13]

            created_epics = []

            def get_next_month_start_date():
                """Get the start date as the first Monday of the next month."""
                today = datetime.today()
                # Set to the first day of next month
                first_of_next_month = datetime(today.year, today.month, 1) + relativedelta(months=1)

                # Adjust to the next Monday if not already a Monday
                while first_of_next_month.weekday() != 0:  # 0 = Monday
                    first_of_next_month += timedelta(days=1)
                
                return first_of_next_month.date()

            def get_random_end_date_from_start(start_date):
                """Get a random end date between 1 to 6 months from the start date."""
                random_months = random.randint(1, 6)  # Random number of months from 1 to 6
                random_end_date = start_date + relativedelta(months=random_months)

                # Adjust to the nearest Monday after the random date
                while random_end_date.weekday() != 0:  # 0 = Monday
                    random_end_date += timedelta(days=1)

                return random_end_date

            
            print(f"Generating lorem epics for group: {group.name}")
            for i in range(num_epics):
                title = lorem.sentence()
                description = lorem.paragraph()
                weight = random.choice(fibonacci_weights)

                start_date = get_next_month_start_date()
                due_date = get_random_end_date_from_start(start_date)

                start_date_str = start_date.isoformat()
                due_date_str = due_date.isoformat()

                epic = group.epics.create({
                    'title': title,
                    'description': description,
                    'start_date': start_date_str,
                    'due_date': due_date_str,
                    'weight': weight
                })

                print(f"Created epic #{epic.iid} - Title: {title}, Weight: {weight}, Start: {start_date}, End: {due_date}")
                created_epics.append(epic)

            print()
            return created_epics

        except Exception as e:
            print(f"Failed to create epics in group '{group_name}': {e}")
            return []


    def create_epics_lorem(self, group_name, num_epics=5):
        try:
            group = self.get_group_by_name(group_name)

            fibonacci_weights = [1, 2, 3, 5, 8, 13]

            created_epics = []

            def get_next_month_start_date():
                """Get the start date as the first Monday of the next month."""
                today = datetime.today()
                # Set to the first day of next month
                first_of_next_month = datetime(today.year, today.month, 1) + relativedelta(months=1)

                # Adjust to the next Monday if not already a Monday
                while first_of_next_month.weekday() != 0:  # 0 = Monday
                    first_of_next_month += timedelta(days=1)
                
                return first_of_next_month.date()

            def get_random_end_date_from_start(start_date):
                """Get a random end date between 1 to 6 months from the start date."""
                random_months = random.randint(1, 6)  # Random number of months from 1 to 6
                random_end_date = start_date + relativedelta(months=random_months)

                # Adjust to the nearest Monday after the random date
                while random_end_date.weekday() != 0:  # 0 = Monday
                    random_end_date += timedelta(days=1)

                return random_end_date

            print(f"Generating lorem epics for group: {group.name}")
            for i in range(num_epics):
                # Generate random title, description, and other properties
                title = lorem.sentence()
                description = lorem.paragraph()
                weight = random.choice(fibonacci_weights)

                start_date = get_next_month_start_date()
                due_date = get_random_end_date_from_start(start_date)

                start_date_str = start_date.isoformat()
                due_date_str = due_date.isoformat()

                # Randomly select one project label and one PIID label
                project_label = random.choice(PROJECT_LABELS)
                piid_label = random.choice(PIID_LABELS)
                epic_label = random.choice(EPIC_LABELS)

                epic = group.epics.create({
                    'title': title,
                    'description': description,
                    'start_date': start_date_str,
                    'due_date': due_date_str,
                    'weight': weight,
                    'labels': [project_label, piid_label, epic_label]
                })

                print(
                    f"Created epic #{epic.iid} - Title: {title}, Weight: {weight}, Start: {start_date}, End: {due_date}, "
                    f"Project Label: **{project_label}**, PIID Label: {piid_label}"
                )
                created_epics.append(epic)

            return created_epics
        
        except Exception as e:
            print(f"Error creating epics: {e}")
            return []



    def assign_issues_to_epics(self, epics, issues):
        """
        Randomly assigns issues to the given epics.

        Args:
            epics (list): List of epic objects to which issues are assigned.
            issues (list): List of issue objects to be assigned to the epics.

        Returns:
            dict: Dictionary mapping epic titles to their assigned issues.
        """
        if not epics:
            print("No epics available to assign issues to.")
            return {}

        assigned_issues = {}

        for issue in issues:
            # Randomly select an epic from the list of epics
            selected_epic = random.choice(epics)

            try:
                # Assign epic ID to the issue
                issue.epic_id = selected_epic.id
                issue.save()  # Save the changes in GitLab. NOTE: This updates the API
                
                # Map the assigned issue details to the selected epic
                if selected_epic.title not in assigned_issues:
                    assigned_issues[selected_epic.title] = []
                
                assigned_issues[selected_epic.title].append({
                    'issue_id': issue.iid,
                    'issue_title': issue.title,
                    'issue_url': issue.web_url
                })

                print(f"Assigned issue #{issue.iid} ({issue.title}) to epic '{selected_epic.title}'")

            except Exception as e:  # Catch errors and alert the user
                print(f"Failed to assign issue #{issue.iid} ({issue.title}) to epic '{selected_epic.title}': {e}")

        return assigned_issues


    #
    # Issues
    #
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
                            'title': row['Title'],
                            'description': row['Description'],
                            'assignee_ids': [],
                            'labels': row['Labels'].split(",") if row['Labels'] else [],
                            'milestone_id': None,
                            'due_date': row['Due Date'] if row['Due Date'] else None,
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
            issues = project.issues.list(all=True)

            issues_data = []
            for issue in issues:
                issues_data.append({
                    "Issue ID": issue.id,
                    "Title": issue.title,
                    "Description": issue.description,
                    "State": issue.state,
                    "Author": issue.author["name"] if issue.author else "Unknown",
                    "Created At": issue.created_at,
                    "Due Date": issue.due_date if issue.due_date else "None",
                    "Labels": ", ".join(issue.labels) if issue.labels else "None",
                    "Milestone": issue.milestone["title"] if issue.milestone else "None",
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
            project = self.get_project_by_name(project_name)

            fibonacci_weights = [1, 2, 3, 5, 8, 13]

            created_issues = []

            for i in range(num_issues):
                title = lorem.sentence()
                description = lorem.paragraph() 
                weight = random.choice(fibonacci_weights)

                issue = project.issues.create({
                    'title': title,
                    'description': description,
                    'weight': weight
                })
                
                print(f"Created issue #{issue.iid} - Title: {title}, Weight: {weight}")
                created_issues.append(issue)

            return created_issues

        except Exception as e:
            print(f"Failed to create issues in project '{project_name}': {e}")
            return created_issues


    def assign_issues_to_milestones(self, milestones, issues):
        """
        Randomly assigns issues to milestones.

        Args:
            milestones (list): List of milestone objects.
            issues (list): List of issue objects to assign to milestones.

        Returns:
            dict: Dictionary mapping milestone title to assigned issue details.
        """
        if not milestones:
            print("No milestones available to assign issues to.")
            return {}

        if not issues:
            print("No issues provided for assignment.")
            return {}

        assigned_issues = {}

        for issue in issues:
            try:
                # Select a random milestone
                selected_milestone = random.choice(milestones)

                # Assign the milestone to the issue
                issue.milestone_id = selected_milestone.id
                issue.save()  # Save changes to GitLab

                # Track assignments
                if selected_milestone.title not in assigned_issues:
                    assigned_issues[selected_milestone.title] = []
                assigned_issues[selected_milestone.title].append({
                    'issue_id': issue.iid,
                    'issue_title': issue.title,
                    'issue_url': issue.web_url,
                })

                # Print log
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
        fibonacci_weights = [1, 2, 3, 5, 8, 13]

        group = self.get_group_by_name(group_name)
        if group is None:
            print(f"Group '{group_name}' not found. Aborting weight assignment.")
            return

        print()
        print(f"Found Group: {group.name} (id: {group.id})")
        print(f"Now processing issues in projects under the group '{group_name}'{' and its subgroups' if recursive else ''}...")

        # Helper function to process projects in a single group
        def process_projects_in_group(group):
            projects = group.projects.list(all=True)
            for project in projects:
                print(f"Processing project: {project.name}")
                project_full = self.gl.projects.get(project.id)

                issues = project_full.issues.list(all=True)
                for issue in issues:
                    if issue.weight is None:
                        try:
                            issue_weight = random.choice(fibonacci_weights)
                            issue.weight = issue_weight
                            issue.save()
                            print(f"Assigned random weight {issue_weight} to issue: {issue.title} (id: {issue.id})")
                        except Exception as e:
                            print(f"Failed to assign weight for issue '{issue.title}' (id: {issue.id}): {e}")
                    else:
                        print(f"Issue '{issue.title}' (ID: {issue.id}) already has a weight: {issue.weight}")

        # Process projects in the current group
        process_projects_in_group(group)

        if recursive:
            subgroups = group.subgroups.list(all=True)
            for subgroup in subgroups:
                self.assign_random_fibonacci_weights(subgroup.full_path, recursive=True)

        print(f"Completed assigning random weights to all unweighted issues in group '{group_name}'{' and its subgroups' if recursive else ''}.")
        print()


    def md_group_epics_report(self, group_name, wiki_page_slug="home", create_local_file=False):
        group = self.get_group_by_name(group_name)
        epics = group.epics.list(get_all=True)
        
        # Get all subgroups
        all_subgroups = self.get_all_subgroups(group)

        # for subgroup in all_subgroups:
        #     print(f"Group: {subgroup.name}, ID: {subgroup.get_id()}")

        open_epics_count = sum(1 for e in epics if e.state == 'opened')
        total_epics = len(epics)

        # for epic in epics:
        #     print(f"Epic: {epic.title}, Group ID: {epic.attributes['group_id']}")

        # GraphQL setup for epic weights
        session = requests.Session()
        session.headers.update({
            'Authorization': f'Bearer {self.private_token}',
            'Content-Type': 'application/json'
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

        # Variables for grouping
        total_story_points = 0
        open_story_points = 0
        epic_rows = []
        grouped_epics = {}  # Group epics by their parent GitLab subgroup

        for epic in epics:
            # Get the correct full path from the group ID
            group_id = epic.attributes['group_id']
            group = next((g for g in all_subgroups if g.id == group_id), None)

            if not group:
                print(f"Warning: No group found for Epic '{epic.title}' with group ID {group_id}")
                continue  # Skip if the group is not found

            subgroup_name = group.full_path  # The correct group or subgroup name
            subgroup_url = group.web_url     # The group's web URL (used in markdown)

            # Get the direct link of the epic using the subgroup's full path
            epic_url = f"{subgroup_url}/-/epics/{epic.iid}"

            # Get weight via GraphQL
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
                    data = resp.json()
                    widgets = data.get('data', {}).get('workItem', {}).get('widgets', [])
                    for widget in widgets:
                        if isinstance(widget, dict) and widget.get('weight') is not None:
                            planned_weight = widget['weight']
                            break
            except Exception as e:
                print(f"Error fetching weight for Epic '{epic.title}': {e}")

            # Get linked issues
            issues = epic.issues.list(get_all=True)
            actual_total_weight = sum(issue.weight or 0 for issue in issues)
            actual_open_weight = sum(issue.weight or 0 for issue in issues if issue.state == 'opened')

            total_story_points += actual_total_weight
            open_story_points += actual_open_weight

            # Group epics based on subgroup name (from group object)
            if subgroup_name not in grouped_epics:
                grouped_epics[subgroup_name] = []

            grouped_epics[subgroup_name].append({
                "title": epic.title,
                "state": epic.state.capitalize(),
                "planned_weight": planned_weight,
                "actual_total_weight": actual_total_weight,
                "actual_open_weight": actual_open_weight,
                "issues": len(issues),
                "url": epic_url,
                "group_url": subgroup_url,  # URL for the subgroup
            })

        md = self.build_markdown_report(
            group=group,
            total_epics=total_epics,
            open_epics_count=open_epics_count,
            total_story_points=total_story_points,
            open_story_points=open_story_points,
            epic_rows=epic_rows,
            grouped_epics=grouped_epics,
            base_url=self.url
        )

        print(f"Posting the Markdown content to the Group Wiki page '{wiki_page_slug}' in group '{group_name}'...")

        try:
            existing_pages = group.wikis.list()
            wiki_page_exists = any(page.slug == wiki_page_slug for page in existing_pages)

            if wiki_page_exists:
                wiki_page = next(page for page in existing_pages if page.slug == wiki_page_slug)
                wiki_page.content = md
                wiki_page.save()
                print(f"Updated existing Group Wiki page '{wiki_page_slug}' in group '{group_name}'.")
            else:
                group.wikis.create({
                    'title': wiki_page_slug,
                    'content': md
                })
                print(f"Created and posted the new Group Wiki page '{wiki_page_slug}' in group '{group_name}'.")
        except Exception as e:
            print(f"Failed to post content to the Group Wiki page '{wiki_page_slug}': {e}")

        if create_local_file:
            md_filename = f"{group.name.lower()}-epic-report.md"
            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(md)

            print(f"Markdown report saved as '{md_filename}'")


    def build_markdown_report(self, group, total_epics, open_epics_count, total_story_points, open_story_points, epic_rows, grouped_epics, base_url):
        md = textwrap.dedent(f"""
        # GitLab Epic Report - {group.name}
        **Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

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

        # Add separate details sections for each group
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

        # Add quick links section
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


    #
    # Milestones
    #
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
                            # Recursively fetch milestones from the subgroup and add to the current list
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

            if len(milestones) > 0:
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

            # Fetch milestones and epics from the group
            milestones = group.milestones.list(get_all=True)
            all_epics = group.epics.list(get_all=True)
            # print(f"Found {len(milestones)} milestones in the group.")
            # print(f"Found {len(all_epics)} total epics in the group.")

            for milestone in milestones:
                try:
                    # Parse milestone start and end dates to UTC datetime objects (offset-aware)
                    milestone_start_date = datetime.fromisoformat(milestone.start_date).replace(tzinfo=timezone.utc)
                    milestone_end_date = datetime.fromisoformat(milestone.due_date).replace(tzinfo=timezone.utc)
                    # print(f"Processing Milestone: {milestone.title} (Start: {milestone.start_date}, End: {milestone.due_date})")
                except Exception as date_error:
                    # print(f"Skipping Milestone: {milestone.title}, invalid dates (Error: {date_error})")
                    continue

                associated_epics = []
                for epic in all_epics:
                    # Get the start and end dates of the epic from milestones
                    epic_start = epic.start_date_from_milestones or epic.start_date_fixed
                    epic_end = epic.due_date_from_milestones or epic.due_date_fixed

                    if epic_start and epic_end:
                        try:
                            # Parse epic start and end dates into UTC datetime objects (offset-aware)
                            epic_start_date = datetime.fromisoformat(epic_start.replace("Z", "+00:00"))
                            epic_end_date = datetime.fromisoformat(epic_end.replace("Z", "+00:00"))

                            # Check for overlap between the epic and the milestone dates
                            if not (epic_end_date < milestone_start_date or epic_start_date > milestone_end_date):
                                # print(f"  - Adding Epic: {epic.title} (ID: {epic.id})")
                                associated_epics.append({
                                    "id": epic.id,
                                    "title": epic.title,
                                    "state": epic.state,
                                    "web_url": epic.web_url,
                                    "start_date": epic_start_date,
                                    "end_date": epic_end_date,
                                })

                        except Exception as epic_date_error:
                            print(f"Error parsing dates for Epic: {epic.title} (ID: {epic.id}) - {epic_date_error}")
                            continue

                # print(f"Milestone: {milestone.title} has {len(associated_epics)} epics.")
                # for epic in associated_epics:
                #     print(f'. - epic: {epic["title"]}, state: {epic["state"]}')
                # print()

                # Store milestone and its associated epics
                milestones_with_epics[milestone.title] = {
                    "milestone": {
                        "id": milestone.id,
                        "title": milestone.title,
                        "start_date": milestone_start_date,
                        "end_date": milestone_end_date,
                        "description": milestone.description,
                        "state": milestone.state,
                        "web_url": milestone.web_url,
                    },
                    "epics": associated_epics,
                }

            return milestones_with_epics

        except Exception as e:
            print(f"Error: {e}")
            return {}
        

    def upload_milestones_and_epics_to_wiki(self, group, data_structure, wiki_page_title="Milestones_and_Epics"):
        try:
            # Prepare Markdown content
            markdown_content = f"# Milestones and Epics\n\n"

            # Add a summary table header
            markdown_content += "## Summary Table\n\n"
            markdown_content += "| Milestone Title | Open Epics | Closed Epics | Total Epics | Percent Complete |\n"
            markdown_content += "|-----------------|------------|--------------|-------------|------------------|\n"

            # Collect detailed milestone and epic information
            detailed_content = ""

            for milestone_title, milestone_data in data_structure.items():
                milestone = milestone_data['milestone']
                epics = milestone_data['epics']

                # Separate epics into open and closed
                open_epics = [epic for epic in epics if epic['state'] == "opened"]
                closed_epics = [epic for epic in epics if epic['state'] == "closed"]

                # Calculate metrics for the summary table
                total_epics = len(open_epics) + len(closed_epics)
                percent_complete = f"{(len(closed_epics) / total_epics * 100):.2f}%" if total_epics > 0 else "0.00%"

                # Add to summary table
                markdown_content += f"| {milestone['title']} | {len(open_epics)} | {len(closed_epics)} | {total_epics} | {percent_complete} |\n"

                # Add detailed milestone section
                detailed_content += f"\n## 🎯 Milestone: {milestone['title']}\n"
                detailed_content += f"- **State**: {milestone['state']}\n"
                detailed_content += f"- **Description**: {milestone['description'] or 'N/A'}\n"
                detailed_content += f"- **Start Date**: {milestone['start_date'].strftime('%Y-%m-%d') if milestone['start_date'] else 'N/A'}\n"
                detailed_content += f"- **Due Date**: {milestone['end_date'].strftime('%Y-%m-%d') if milestone['end_date'] else 'N/A'}\n"
                detailed_content += f"- **[View Milestone]({milestone['web_url']})**\n"

                # Add list of associated epics
                if epics:
                    detailed_content += f"\n### Associated Epics:\n"
                    for epic in epics:
                        detailed_content += f"- **[View Epic]({epic['web_url']})**: {epic['title']} (State: {epic['state']}, Start: {epic['start_date'].strftime('%Y-%m-%d')}, End: {epic['end_date'].strftime('%Y-%m-%d')})\n"
                else:
                    detailed_content += "\nNo associated epics for this milestone.\n"

            markdown_content += "\n" + detailed_content

            self.upload_to_wiki(
                group,
                wiki_page_title,
                markdown_content
            )
            # print(f"Successfully uploaded milestones and epics to the wiki page '{wiki_page_title}'.")

        except Exception as e:
            print(f"Error creating wiki page for milestones and epics: {e}")
            return


        import random


    def create_lorem_milestones(self, target, num_milestones=12):
        """
        Create lorem milestones spread out over a year, with each milestone lasting 1–4 months.

        Args:
            target (object): GitLab group or project object to create milestones in.
            num_milestones (int): The number of milestones to create.

        Returns:
            list: A list of created milestone objects.
        """
        try:
            # Determine if target is a group or project
            target_type = 'group' if hasattr(target, 'milestones') and hasattr(target, 'projects') else 'project'

            # Set the time frame for milestones (1 year from start)
            current_date = datetime.today()
            year_start = datetime(current_date.year, current_date.month, 1)
            year_end = year_start + relativedelta(months=12)

            created_milestones = []
            milestone_start = year_start

            for i in range(num_milestones):
                # Ensure milestone starts on a Monday
                while milestone_start.weekday() != 0:  # 0 = Monday
                    milestone_start += timedelta(days=1)

                # Random duration between 1-4 months
                milestone_duration = random.randint(1, 4)
                milestone_end = milestone_start + relativedelta(months=milestone_duration) - timedelta(days=1)

                # Validations: Ensure valid date offsets
                if milestone_end <= milestone_start:  # Due date should be greater than the start date
                    milestone_end = milestone_start + timedelta(days=1)

                # Ensure `milestone_end` does not exceed the 1-year time frame
                if milestone_end > year_end:
                    milestone_end = year_end

                # If start and end dates are still invalid, skip this milestone
                if milestone_start >= milestone_end:
                    print(f"Skipping milestone creation: Start={milestone_start.date()} is not before End={milestone_end.date()}")
                    break

                # Debugging: Log calculated dates
                # print(f"Calculated milestone dates: Start={milestone_start.date()}, End={milestone_end.date()}")

                try:
                    # Generate milestone title and description
                    milestone_title = lorem.sentence()  # Random title
                    milestone_description = lorem.paragraph()  # Random description

                    # Create the milestone in the target
                    milestone = target.milestones.create({
                        'title': milestone_title,
                        'description': milestone_description,
                        'start_date': milestone_start.date().isoformat(),
                        'due_date': milestone_end.date().isoformat()
                    })

                    # Append milestone and update start date for the next one
                    created_milestones.append(milestone)
                    print(f"Created {target_type} milestone '{milestone.title}' from {milestone_start.date()} to {milestone_end.date()}")
                    milestone_start = milestone_end + timedelta(days=1)

                except Exception as e:
                    print(f"Failed to create {target_type} milestone '{milestone_title}' with "
                        f"start_date={milestone_start.date()} and due_date={milestone_end.date()}: {e}")

            return created_milestones

        except Exception as e:
            print(f"Failed to create milestones for the {target_type}: {e}")
            return []

      
    def delete_all_milestones(self, target):
        try:
            target_type = 'group' if hasattr(target, 'milestones') and hasattr(target, 'projects') else 'project'

            # Get all milestones from the target
            milestones = target.milestones.list(all=True)  # Get all milestones

            if not milestones:
                print(f"No milestones found in the {target_type}. Nothing to delete.")
                return []

            deleted_milestones = []

            for milestone in milestones:
                try:
                    milestone_object = target.milestones.get(milestone.id)
                    milestone_title = milestone_object.title
                    milestone_object.delete()
                    print(f"Deleted {target_type} milestone: {milestone_title}")
                    deleted_milestones.append(milestone_title)
                except Exception as e:
                    print(f"Failed to delete {target_type} milestone {milestone.title}: {e}")

            print(0)
            return deleted_milestones

        except Exception as e:
            print(f"Failed to delete milestones from the {target_type}: {e}")
            return []


    def assign_epics_to_milestones_not_valid(self, milestones, epics):
        """
        Randomly assigns epics to milestones by syncing their start and end dates with the milestone's dates.

        Args:
            milestones (list): List of milestone objects with start_date and due_date.
            epics (list): List of epic objects to assign to milestones.

        Returns:
            dict: Dictionary mapping milestone titles to their assigned epics.
        """
        if not milestones:
            print("No milestones available to assign epics to.")
            return {}

        assigned_epics = {}

        for epic in epics:
            # Randomly choose a milestone to assign the epic dates from
            selected_milestone = random.choice(milestones)

            try:
                # Assign the milestone's start and due dates to the epic
                epic.start_date = selected_milestone.start_date
                epic.due_date = selected_milestone.due_date
                epic.save()  # Save changes in GitLab

                # Add the epic to the assigned_epics dictionary under the selected milestone
                if selected_milestone.title not in assigned_epics:
                    assigned_epics[selected_milestone.title] = []

                assigned_epics[selected_milestone.title].append({
                    'epic_id': epic.iid,
                    'epic_title': epic.title,
                    'epic_url': epic.web_url
                })

                print(f"Assigned epic '{epic.title}' to milestone '{selected_milestone.title}' "
                    f"(Start Date: {selected_milestone.start_date}, Due Date: {selected_milestone.due_date})")

            except Exception as e:
                print(f"Failed to assign epic '{epic.title}' to milestone '{selected_milestone.title}': {e}")

        return assigned_epics


    #
    # Reports
    #
    def generate_summary_report(self, group):
        """
        Generates a summary Markdown report for a GitLab Group's milestones, epics, and issues.
        Includes both group-level and project-level milestones.

        Args:
            group_name (str): The name of the GitLab group.

        Returns:
            str: A Markdown-formatted string containing the summary report.
        """

        # Fetch the group object using group_name
        try:
            group_name = group.name
        except Exception as e:
            return f"Error fetching group '{group_name}': {e}"

        # Initialize empty lists for milestones, issues, and epics
        milestones = []
        issues = []
        epics = []

        # Fetch group-level milestones and epics
        try:
            milestones = group.milestones.list(all=True)  # Group-level milestones
            epics = group.epics.list(all=True)  # Group-level epics
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        # Collect all project-level milestones and issues
        for project in group.projects.list(all=True):
            try:
                # Fetch the full project object using self.gl
                full_project = self.gl.projects.get(project.id)
                # Fetch project-level milestones and issues
                project_milestones = full_project.milestones.list(all=True)
                project_issues = full_project.issues.list(all=True)

                # Add to the combined lists
                milestones.extend(project_milestones)
                issues.extend(project_issues)

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")
            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        # Debugging: Display the fetched data
        total_milestones = len(milestones)
        total_epics = len(epics)
        total_issues = len(issues)
        print(f"Fetched {total_milestones} milestones")
        print(f"Fetched {total_epics} epics (group-level only)")
        print(f"Fetched {total_issues} issues in total")

        # Count unassigned issues
        assigned_milestone_ids = {
            issue.milestone['id'] for issue in issues if issue.milestone
        }
        unassigned_issues = [
            issue
            for issue in issues
            if not issue.milestone or issue.milestone.get('id') not in assigned_milestone_ids
        ]
        unassigned_issues_count = len(unassigned_issues)

        # Start generating markdown report
        markdown_report = []

        # Add title and high-level summary
        markdown_report.append(f"# Workflow Summary Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Workflow Execution Summary")
        markdown_report.append(f"- **Group Name:** `{group_name}`")
        markdown_report.append(f"- **Date:** {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append(f"- **Number of Milestones Created:** {total_milestones}")
        markdown_report.append(f"- **Number of Epics Created:** {total_epics}")
        markdown_report.append(f"- **Number of Issues Created:** {total_issues}")
        markdown_report.append(f"- **Unassigned Issues:** {unassigned_issues_count}")
        markdown_report.append("")

        # Add unassigned issues (if any)
        if unassigned_issues_count > 0:
            markdown_report.append("## Unassigned Issues")
            for issue in unassigned_issues:
                markdown_report.append(f"- **[{issue.title}]({issue.web_url})**")  # Include link to the issue
            markdown_report.append("")  # Add a blank line for formatting

        md = "\n".join(markdown_report)  # Combine all lines into a single string
        title = f"{group_name.capitalize()} - Summary Report"
        self.upload_to_wiki(self.get_group_by_name(group_name), title, md)


    def generate_detailed_report_first(self, group):
        """
        Generates a detailed Markdown report for a GitLab Group's milestones, issues, and associated epics.
        Includes both group-level and project-level milestones.

        Args:
            group (object): The GitLab group object.

        Returns:
            None: The report will be uploaded to the group's wiki.
        """
        from collections import defaultdict
        from datetime import datetime

        group_name = group.name

        # Initialize empty lists for milestones, issues, epics
        milestones = []
        epics = {}
        project_issues_by_milestone = defaultdict(list)  # Milestone ID -> List of issues
        issue_to_epic_map = {}  # Issue ID -> Epic ID

        # Fetch group-level milestones and epics
        try:
            milestones = group.milestones.list(all=True)  # Group-level milestones
            epics = {epic.id: epic for epic in group.epics.list(all=True)}  # Group-level epics as a dict
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        print(f"Fetched {len(milestones)} group-level milestones")
        print(f"Fetched {len(epics)} group-level epics")

        # Fetch project-level milestones and issues
        for project in group.projects.list(all=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                # Fetch the full project object
                full_project = self.gl.projects.get(project.id)

                # Check if issues are enabled for this project
                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                # Fetch project-level milestones and issues
                project_milestones = full_project.milestones.list(all=True)
                project_issues = full_project.issues.list(all=True)

                # Add project milestones to overall milestones list
                milestones.extend(project_milestones)

                # Map issues to milestones and epics
                for issue in project_issues:
                    if issue.milestone:
                        project_issues_by_milestone[issue.milestone['id']].append(issue)
                    # Check if the issue has an associated epic
                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        issue_to_epic_map[issue.id] = issue.epic_issue

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")

            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        # Log the total numbers fetched
        total_milestones = len(milestones)
        total_issues = sum(len(issues) for issues in project_issues_by_milestone.values())
        print(f"Total milestones fetched: {total_milestones} (group-level + project-level)")
        print(f"Total issues fetched: {total_issues}")

        # Start generating the markdown report
        markdown_report = []

        # Add title and date
        markdown_report.append(f"# Detailed Milestones, Issues, and Epics Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Execution Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")

        # Add milestones and their issues
        for milestone in milestones:
            markdown_report.append(f"## Milestone: **{milestone.title}**")
            markdown_report.append(f"- **Start Date:** {milestone.start_date if milestone.start_date else 'Not Set'}")
            markdown_report.append(f"- **Due Date:** {milestone.due_date if milestone.due_date else 'Not Set'}")
            markdown_report.append(f"- **State:** {milestone.state}")
            markdown_report.append("")

            # Fetch all issues associated with the milestone
            milestone_issues = project_issues_by_milestone.get(milestone.id, [])
            if milestone_issues:
                for issue in milestone_issues:
                    issue_line = f"  - **[{issue.title}]({issue.web_url})** (Status: {issue.state})"
                    # Include the epic associated with the issue, if any
                    if issue.id in issue_to_epic_map:
                        epic_id = issue_to_epic_map[issue.id]
                        epic = epics.get(epic_id)
                        if epic:
                            issue_line += f" (_Epic: [{epic.title}]({epic.web_url})_)"
                        else:
                            issue_line += " (_Epic: Unknown_)"
                    markdown_report.append(issue_line)
            else:
                # No issues linked to this milestone
                markdown_report.append("  - No issues linked to this milestone")
            markdown_report.append("")  # Add a blank line for formatting

        # Handle milestones without issues (if any milestones do not have issues assigned)
        all_milestone_ids_with_issues = set(project_issues_by_milestone.keys())
        unlinked_milestones = [m for m in milestones if m.id not in all_milestone_ids_with_issues]

        if unlinked_milestones:
            markdown_report.append("## Milestones Without Linked Issues")
            for milestone in unlinked_milestones:
                markdown_report.append(f"- **{milestone.title}** (No issues linked)")
            markdown_report.append("")  # Add a blank line for formatting

        # Combine the markdown report into a single string
        md = "\n".join(markdown_report)
        title = f"{group_name} - Detailed Report"

        # Upload the report to the group's wiki
        self.upload_to_wiki(group, title, md)

        return md


    def generate_detailed_report(self, group):
        """
        Generates a detailed Markdown/HTML report for a GitLab Group's milestones, issues, and associated epics.
        Includes both group-level and project-level milestones formatted in an open <details> tag by default,
        with a "View" link to the milestone's URL.

        Args:
            group (object): The GitLab group object.

        Returns:
            None: The report will be uploaded to the group's wiki.
        """
        from collections import defaultdict
        from datetime import datetime

        group_name = group.name

        # Initialize empty lists for milestones, issues, epics
        milestones = []
        epics = {}
        project_issues_by_milestone = defaultdict(list)  # Milestone ID -> List of issues
        issue_to_epic_map = {}  # Issue ID -> Epic ID

        # Fetch group-level milestones and epics
        try:
            milestones = group.milestones.list(all=True)  # Group-level milestones
            epics = {epic.id: epic for epic in group.epics.list(all=True)}  # Group-level epics as a dict
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        print(f"Fetched {len(milestones)} group-level milestones")
        print(f"Fetched {len(epics)} group-level epics")

        # Fetch project-level milestones and issues
        for project in group.projects.list(all=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                # Fetch the full project object
                full_project = self.gl.projects.get(project.id)

                # Check if issues are enabled for this project
                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                # Fetch project-level milestones and issues
                project_milestones = full_project.milestones.list(all=True)
                project_issues = full_project.issues.list(all=True)

                # Add project milestones to the milestones list
                milestones.extend(project_milestones)

                # Map issues to milestones and epics
                for issue in project_issues:
                    if issue.milestone:
                        project_issues_by_milestone[issue.milestone['id']].append(issue)
                    # Check if the issue has an associated epic
                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        issue_to_epic_map[issue.id] = issue.epic_issue

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")

            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        # Log the total numbers fetched
        total_milestones = len(milestones)
        total_issues = sum(len(issues) for issues in project_issues_by_milestone.values())
        print(f"Total milestones fetched: {total_milestones} (group-level + project-level)")
        print(f"Total issues fetched: {total_issues}")

        # Start generating the markdown report with <details open>
        markdown_report = []

        # Add title and date
        markdown_report.append(f"# Detailed Milestones, Issues, and Epics Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Execution Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")

        # Add each milestone in an open <details> tag
        for milestone in milestones:
            markdown_report.append(f"<details open>")
            markdown_report.append(
                f"  <summary><strong>Milestone: {milestone.title}</strong> "
                f"<a href=\"{milestone.web_url}\" target=\"_blank\">[View]</a></summary>"
            )
            markdown_report.append("")
            markdown_report.append(f"  **Start Date:** {milestone.start_date if milestone.start_date else 'Not Set'}  ")
            markdown_report.append(f"  **Due Date:** {milestone.due_date if milestone.due_date else 'Not Set'}  ")
            markdown_report.append(f"  **State:** {milestone.state}  ")
            markdown_report.append("")

            milestone_issues = project_issues_by_milestone.get(milestone.id, [])

            # Add table for milestone issues
            markdown_report.append("  | Issue Title | Status | Epic |")
            markdown_report.append("  |-------------|--------|------|")
            if milestone_issues:
                for issue in milestone_issues:
                    # Format issue title with a link
                    issue_title = f"[{issue.title}]({issue.web_url})"
                    status = issue.state.capitalize()

                    # Check if the issue is linked to an epic
                    if issue.id in issue_to_epic_map:
                        epic_id = issue_to_epic_map[issue.id]
                        epic = epics.get(epic_id)
                        epic_title = f"[{epic.title}]({epic.web_url})" if epic else "Unknown"
                    else:
                        epic_title = "None"

                    markdown_report.append(f"  | {issue_title} | {status} | {epic_title} |")
            else:
                markdown_report.append("  | No issues linked | - | - |")

            markdown_report.append("</details>")  # Close the open details tag
            markdown_report.append("")  # Add a blank line for spacing

        # Add milestones without linked issues in their own section
        all_milestone_ids_with_issues = set(project_issues_by_milestone.keys())
        unlinked_milestones = [m for m in milestones if m.id not in all_milestone_ids_with_issues]

        if unlinked_milestones:
            markdown_report.append("## Milestones Without Linked Issues")
            markdown_report.append("| Milestone | Start Date | Due Date | State |")
            markdown_report.append("|-----------|------------|----------|-------|")
            for milestone in unlinked_milestones:
                markdown_report.append(
                    f"| {milestone.title} | {milestone.start_date or 'Not Set'} | {milestone.due_date or 'Not Set'} | {milestone.state} |"
                )
            markdown_report.append("")  # Add a blank line for spacing

        # Combine the markdown report into a single string
        md = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Detailed Report"

        # Upload the report to the group's wiki
        self.upload_to_wiki(group, title, md)

        return md


    def generate_epics_report(self, group):
        """
        Generates a detailed Markdown/HTML report for a GitLab Group's epics and their associated issues.
        Each epic includes a "View" link, and issues are listed in a table under each epic.
        
        Args:
            group (object): The GitLab group object.

        Returns:
            None: The report will be uploaded to the group's wiki.
        """
        from collections import defaultdict
        from datetime import datetime

        group_name = group.name

        # Fetch all epics in the group
        try:
            epics = group.epics.list(all=True)
            epics_dict = {epic.id: epic for epic in epics}  # Create a dictionary for quick lookup
        except Exception as e:
            print(f"Error fetching group epics: {e}")
            return

        print(f"Fetched {len(epics)} epics for group '{group_name}'")

        # Fetch all issues and map them to their epics
        epic_issues = defaultdict(list)  # Epic ID -> List of issues
        for project in group.projects.list(all=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                # Fetch the full project object
                full_project = self.gl.projects.get(project.id)

                # Check if issues are enabled for the project
                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                # Fetch issues for the project
                project_issues = full_project.issues.list(all=True, include_epics=True)

                # Map issues to their respective epics
                for issue in project_issues:
                    if hasattr(issue, 'epic') and issue.epic:  # If the issue is associated with an epic
                        epic_id = issue.epic['id']
                        epic_issues[epic_id].append((issue, project))  # Save the issue and its associated project

                print(f"  Found {len(project_issues)} issues in project '{project.name}'")

            except Exception as e:
                print(f"Failed to process project '{project.name}': {e}")

        print(f"Total epics with issues fetched: {len(epic_issues)}")

        # Start generating the markdown report
        markdown_report = []

        # Add title and date
        markdown_report.append(f"# Epics and Their Issues Report (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")

        # Organize report content by epic
        for epic_id, epic in epics_dict.items():
            markdown_report.append(f"<details>")
            markdown_report.append(
                f"  <summary><strong>Epic: {epic.title}</strong> "
                f"<a href=\"{epic.web_url}\" target=\"_blank\">[View]</a></summary>"
            )
            markdown_report.append("")
            markdown_report.append(f"  **Start Date:** {epic.start_date or 'Not Set'}  ")
            markdown_report.append(f"  **Due Date:** {epic.due_date or 'Not Set'}  ")
            markdown_report.append(f"  **State:** {epic.state}  ")
            markdown_report.append(f"  **Description:** {epic.description or 'No description provided.'}  ")
            markdown_report.append("")

            # Add table of issues linked to this epic
            markdown_report.append("  | Issue Title | Status | Milestone | Project |")
            markdown_report.append("  |-------------|--------|-----------|---------|")
            if epic_id in epic_issues:
                for issue, project in epic_issues[epic_id]:
                    issue_title = f"[{issue.title}]({issue.web_url})"
                    status = issue.state.capitalize()
                    milestone_title = issue.milestone['title'] if issue.milestone else "None"
                    project_name = project.name

                    markdown_report.append(f"  | {issue_title} | {status} | {milestone_title} | {project_name} |")
            else:
                markdown_report.append("  | No issues linked | - | - | - |")

            markdown_report.append("</details>")  # Close the open details tag
            markdown_report.append("")  # Add a blank line for spacing

        # Handle epics without issues
        epics_without_issues = [epic for epic_id, epic in epics_dict.items() if epic_id not in epic_issues]
        if epics_without_issues:
            markdown_report.append("## Epics Without Linked Issues")
            markdown_report.append("| Epic | Start Date | Due Date | State |")
            markdown_report.append("|------|------------|----------|-------|")
            for epic in epics_without_issues:
                markdown_report.append(
                    f"| [{epic.title}]({epic.web_url}) | {epic.start_date or 'Not Set'} | {epic.due_date or 'Not Set'} | {epic.state} |"
                )
            markdown_report.append("")  # Add a blank line for spacing

        # Combine the markdown report into a single string
        md = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Epics Report"

        # Upload the report to the group's wiki
        self.upload_to_wiki(group, title, md)

        return md


    def generate_issue_progress_report(self, group):
        """
        Generates an Issue Progress and Status Overview report for a GitLab Group.
        The report includes a high-level summary of issue statuses across the group, and
        a detailed breakdown of project-level issue statuses and their milestones.

        Args:
            group (object): The GitLab group object.

        Returns:
            None: The report will be uploaded to the group's wiki.
        """
        from collections import defaultdict
        from datetime import datetime

        group_name = group.name

        # Initialize dictionaries to store project data for the report
        project_status_counts = defaultdict(lambda: defaultdict(int))  # Project -> Status -> Count
        project_issues = defaultdict(list)  # Project -> List of issues
        milestone_mapping = defaultdict(list)  # Project -> Issues by Milestone

        # Fetch issues for all projects in the group
        for project in group.projects.list(all=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                # Fetch the full project object
                full_project = self.gl.projects.get(project.id)

                # Check if issues are enabled for the project
                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                # Fetch all issues in the project
                issues = full_project.issues.list(all=True)

                # Count the issues by status (e.g., open/closed)
                for issue in issues:
                    project_status_counts[project.name][issue.state] += 1
                    project_issues[project.name].append(issue)

                    # Map issues to milestones
                    milestone_id = issue.milestone['id'] if issue.milestone else None
                    milestone_mapping[(project.name, milestone_id)].append(issue)

                print(f"  Found {len(issues)} issues in project '{project.name}'")

            except Exception as e:
                print(f"Failed to process project '{project.name}': {e}")

        # Start generating the markdown report
        markdown_report = []

        # Add title and date
        markdown_report.append(f"# Issue Progress and Status Overview (Group: {group_name})")
        markdown_report.append("")
        markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        markdown_report.append("")

        # High-level summary
        markdown_report.append("## Summary")
        total_open = sum(counts.get('opened', 0) for counts in project_status_counts.values())
        total_closed = sum(counts.get('closed', 0) for counts in project_status_counts.values())
        total_other_states = sum(sum(count.values()) for count in project_status_counts.values()) - total_open - total_closed
        total_issues = total_open + total_closed + total_other_states
        markdown_report.append(f"- **Total Issues:** {total_issues}")
        markdown_report.append(f"- **Open Issues:** {total_open}")
        markdown_report.append(f"- **Closed Issues:** {total_closed}")
        markdown_report.append(f"- **Other States (e.g., in progress):** {total_other_states}")
        markdown_report.append("")

        # Per-project issue summary with details
        for project_name, issue_list in project_issues.items():
            markdown_report.append(f"<details>")
            markdown_report.append(f"  <summary><strong>Project: {project_name}</strong></summary>")
            markdown_report.append("")

            # Per-project summary
            project_open = project_status_counts[project_name].get("opened", 0)
            project_closed = project_status_counts[project_name].get("closed", 0)
            project_other = (
                sum(project_status_counts[project_name].values())
                - project_open
                - project_closed
            )
            markdown_report.append(f"  **Total Issues:** {len(issue_list)}  ")
            markdown_report.append(f"  **Open Issues:** {project_open}  ")
            markdown_report.append(f"  **Closed Issues:** {project_closed}  ")
            markdown_report.append(f"  **Other States:** {project_other}  ")
            markdown_report.append("")

            # Add table of issues
            markdown_report.append("  | Issue Title | Status | Milestone |")
            markdown_report.append("  |-------------|--------|-----------|")
            for issue in issue_list:
                issue_title = f"[{issue.title}]({issue.web_url})"
                status = issue.state.capitalize()
                milestone_title = issue.milestone['title'] if issue.milestone else "None"

                markdown_report.append(f"  | {issue_title} | {status} | {milestone_title} |")

            markdown_report.append("</details>")
            markdown_report.append("")  # Add a blank line for spacing

        # Combine the markdown report into a single string
        md = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Issue Progress and Status Overview"

        # Upload the report to the group's wiki
        self.upload_to_wiki(group, title, md)

        return md


    def generate_and_upload_piid_project_report_to_wiki(self, group):
        """
        Generate and upload a PIID vs Project Labels report to the group's Wiki page.
        The epic status reflects its status as displayed on the Epic Board.
        """
        report_data = {project_label: {piid_label: None for piid_label in PIID_LABELS} for project_label in PROJECT_LABELS}

        try:
            # Step 1: Fetch epics for the group
            print(f"Fetching all epics for group: {group.name}")
            all_epics = [group.epics.get(epic.get_id()) for epic in group.epics.list(all=True)]
            print(f"Fetched {len(all_epics)} total epics.")

            relevant_epics = []
            for epic in all_epics:
                # Match epics with the intersection of PIID and project labels
                project_label = next((label for label in PROJECT_LABELS if label in epic.labels), None)
                piid_label = next((label for label in PIID_LABELS if label in epic.labels), None)
                if project_label and piid_label:
                    relevant_epics.append((epic, project_label, piid_label))

            print(f"Found {len(relevant_epics)} relevant epics with PIID/Project label intersections.")

            # Step 2: Process each relevant epic and calculate metrics
            for epic, project_label, piid_label in relevant_epics:
                # Initialize the cell if it doesn't already exist
                if report_data[project_label][piid_label] is None:
                    report_data[project_label][piid_label] = {
                        "epics_open": 0,
                        "epics_total": 0,
                        "weight_open": 0,
                        "weight_total": 0,
                        "epic_urls": set(),
                    }

                try:
                    # Update the cell metrics
                    report_data[project_label][piid_label]["epics_total"] += 1
                    if epic.state == "opened":  # Use the epic's own state instead of deducing from issues
                        report_data[project_label][piid_label]["epics_open"] += 1

                    # Fetch linked issues and aggregate weight metrics
                    linked_issues = epic.issues.list(all=True)
                    for issue in linked_issues:
                        issue_weight = issue.weight if issue.weight else 0
                        report_data[project_label][piid_label]["weight_total"] += issue_weight
                        if issue.state == "opened":
                            report_data[project_label][piid_label]["weight_open"] += issue_weight

                    # Add the epic URL for this cell
                    report_data[project_label][piid_label]["epic_urls"].add(epic.web_url)

                except Exception as issue_error:
                    print(f"Error processing issues for epic ID {epic.get_id()}: {issue_error}")

            # Generate Markdown Report
            markdown_report = []
            markdown_report.append(f"# PIID vs Project Labels Report (Group: {group.name})")
            markdown_report.append("")
            markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
            markdown_report.append("")

            # Add table headers
            headers = ["| **Project Label → / PIID ↓**"] + [f"| **{piid_label}** " for piid_label in PIID_LABELS]
            markdown_report.append("".join(headers) + "|")
            markdown_report.append("|:" + ":|:".join(["---"] * (len(PIID_LABELS) + 1)) + ":|")

            # Fill the table with data
            for project_label, piid_data in report_data.items():
                row = [f"| **{project_label}** "]
                for piid_label in PIID_LABELS:
                    data = piid_data[piid_label]
                    if data:
                        # Construct metrics for this cell
                        epics_open = data["epics_open"]
                        epics_total = data["epics_total"]
                        weight_open = data["weight_open"]
                        weight_total = data["weight_total"]

                        # Create the board URL
                        board_url = f"{group.web_url}/-/work_items?"\
                            f"label_name={piid_label}&label_name={project_label}&type[]=EPIC&state=all"


                        # Populate the row with the metrics and board link
                        row.append(
                            f"| Epics -  Open: {epics_open} / Total: {epics_total} / "
                            f"Issue Weight Open: {weight_open} / Total Weight: {weight_total} / "
                            f"[View]({board_url}) "
                        )
                    else:
                        row.append("| - ")

                markdown_report.append("".join(row) + "|")

            # Add Quick Links Section
            quick_links = []
            quick_links.append("")
            quick_links.append(f"## Quick Links for {group.name}")
            quick_links.append("")
            quick_links.append(f"- [Work Items]({group.web_url}/-/work_items)")
            quick_links.append(f"- [Issue Boards]({group.web_url}/-/boards)")
            quick_links.append(f"- [Epic Boards]({group.web_url}/-/epics?type[]=EPIC)")
            quick_links.append(f"- [Roadmap]({group.web_url}/-/roadmap)")
            quick_links.append("")
            markdown_report.extend(quick_links)

            # Combine the entire Markdown content
            md_content = "\n".join(markdown_report)

            # Upload to the Wiki
            wiki_title = "PIID_vs_Project_Labels_Report"
            print(f"Uploading report to wiki: {wiki_title}")
            self.upload_to_wiki(group, wiki_title, md_content)

            return md_content

        except Exception as e:
            print(f"An error occurred while generating or uploading the report: {e}")









    #
    # Utilities
    #
    def sanitize_name(self, name):
        sanitized_name = re.sub(r'[^a-z0-9\-]', '', name.lower().replace(' ', '-'))
        return sanitized_name
    

    def pprint_obj_attrs(self, obj):
        try:
            if not hasattr(obj, "attributes"):
                return "The provided object does not have 'attributes'. Please provide a valid obj object."

            print(pformat(obj.attributes))
        except Exception as e:
            return f"Error retrieving obj attributes: {e}"
        
    
    def upload_to_wiki(self, group, page_title, content):
        """
        Uploads content to a GitLab group's wiki. Overwrites the page if it already exists.

        Args:
            group (object): A GitLab group object.
            page_title (str): Title of the wiki page.
            content (str): Markdown content to upload to the wiki.

        Returns:
            None
        """
        try:
            try:
                # Check if the wiki page already exists
                existing_page = group.wikis.get(page_title)
                # Overwrite the existing page
                existing_page.content = content
                existing_page.save()
                print(f"Wiki page '{page_title}' was found and overwritten successfully.")
            except Exception as e:
                if "404" in str(e):
                    # If the page does not exist, create a new one
                    group.wikis.create({
                        'title': page_title,
                        'content': content,
                    })
                    print(f"Wiki page '{page_title}' created successfully.")
                else:
                    # Handle any other errors
                    print(f"Error checking or updating wiki page: {e}")

        except Exception as e:
            print(f"An error occurred while uploading to the wiki: {e}")
        
        print()


    def delete_all_wiki_pages(self, group):
        """
        Deletes all wiki pages for a given GitLab group.

        Args:
            group (object): The GitLab group object.

        Returns:
            None
        """
        try:
            # Fetch the list of all wiki pages for the group
            wiki_pages = group.wikis.list(all=True)  # Fetch all wiki pages in the group
        except Exception as e:
            print(f"Error fetching wiki pages for group '{group.name}': {e}")
            return

        print(f"Found {len(wiki_pages)} wiki pages in the group '{group.name}'")

        # Loop through each wiki page and delete it
        for wiki_page in wiki_pages:
            try:
                print(f"Deleting wiki page: {wiki_page.title}")
                wiki_page.delete()  # Delete the wiki page
                print(f"Successfully deleted wiki page: {wiki_page.title}")
            except Exception as e:
                print(f"Failed to delete wiki page '{wiki_page.title}': {e}")

        print(f"All wiki pages for group '{group.name}' have been deleted.")


    #
    # Labels
    #
    def create_and_apply_labels(self, target, labels):
        try:
            if isinstance(labels, str):
                labels = [label.strip() for label in labels.split(",")]

            if hasattr(target, 'labels'):
                create_label = lambda name: target.labels.create({"name": name, "color": "#4287f5"})
            elif hasattr(target, 'group_labels'):
                create_label = lambda name: target.group_labels.create({"name": name, "color": "#4287f5"})
            else:
                print(f"Unsupported target type: {type(target)}")
                return

            for label in labels:
                try:
                    create_label(label)
                    print(f"Label '{label}' created successfully.")
                except Exception as e:
                    print(f"Failed to create label '{label}': {e}")
        
        except Exception as e:
            print(f"An error occurred: {e}")
   

    def delete_all_labels(self, target):
        try:
            if hasattr(target, 'labels'):  # Project labels endpoint
                # print(f"Fetching and deleting labels for project: {target.name}")
                list_labels = target.labels.list(all=True)
                delete_label = lambda label: label.delete()
            elif hasattr(target, 'group_labels'):  # Group labels endpoint
                # print(f"Fetching and deleting labels for group: {target.name}")
                list_labels = target.group_labels.list(all=True)
                delete_label = lambda label: label.delete()
            else:
                print("Unsupported target type. Please provide a valid GitLab group or project object.")
                return
            
            print(f"Found {len(list_labels)} labels to delete.")
            for label in list_labels:
                try:
                    print(f"Deleting label: {label.name}")
                    delete_label(label)
                except Exception as e:
                    print(f"Failed to delete label '{label.name}': {e}")

            print(f"All labels for the target '{target.name}' have been deleted.")
            print()
        
        except Exception as e:
            print(f"An error occurred: {e}")

    #
    # Bootstrapping
    #
    def cleanup_group(self, group_name, project_name):
        self.delete_all_labels(self.get_group_by_name(group_name))
        self.delete_all_issues_from_project(project_name)
        self.delete_all_group_epics(group_name)
        self.delete_all_milestones(self.get_project_by_name(project_name))
        self.delete_all_wiki_pages(self.get_group_by_name(group_name))


    def create_all_lorem_objects(self, group_name, project_name, epic_count=10, issue_count=40):
        self.create_and_apply_labels(self.get_group_by_name(group_name), PROJECT_LABELS)
        self.create_and_apply_labels(self.get_group_by_name(group_name), PIID_LABELS)
        self.create_and_apply_labels(self.get_group_by_name(group_name), EPIC_LABELS)
        lorem_milestones = self.create_lorem_milestones(self.get_project_by_name(project_name))
        lorem_epics = self.create_epics_lorem(group_name, num_epics=epic_count)
        lorem_issues = self.create_issues_lorem(project_name, num_issues=issue_count)
        self.assign_issues_to_epics(lorem_epics, lorem_issues)
        self.assign_issues_to_milestones(lorem_milestones, lorem_issues)


    def create_all_lorem_reports(self, group_name, project_name):
        # self.generate_summary_report(self.get_group_by_name(group_name))
        # self.generate_detailed_report(self.get_group_by_name(group_name))
        # self.generate_epics_report(self.get_group_by_name(group_name))
        # self.generate_issue_progress_report(self.get_group_by_name(group_name))
        self.generate_and_upload_piid_project_report_to_wiki(self.get_group_by_name(group_name))  



# Main
def main():
    gl = NceGitLab()
    
    #
    # Variables
    #
    issues_csv_filename = "test-3-2-epics"
    epics_csv_filename = "test-3-2-1-epics.csv"

    group_name = "best-1"
    project_name = "best-1-project"

    # epics = gl.get_epics(group_name)
    # for epic in epics:
    #     # print(f"{epic.get_id()} - {epic.issues}")
    #     pprint(epic.issues)
    #     exit(0)

    # epic_issues = gl.get_issues_and_parent_epics(gl.get_group_by_name(group_name))

    # # Summarize the results
    # print("\nEpic Issue Mapping:")
    # for epic_id, issues in epic_issues.items():
    #     if epic_id is None:
    #         print(f"Issues without an epic ({len(issues)} issues):")
    #     else:
    #         print(f"Epic ID {epic_id} ({len(issues)} issues):")
    #     for issue in issues:
    #         print(f"  - Issue #{issue.iid}: {issue.title}")



    # Bootstrap
    # gl.cleanup_group(group_name, project_name)
    # gl.create_all_lorem_objects(group_name, project_name, epic_count=30, issue_count=80)
    # gl.create_all_lorem_reports(group_name, project_name)

    gl.generate_and_upload_piid_project_report_to_wiki(gl.get_group_by_name(group_name))  

    # group_name = "best-1"
    # group = gl.get_group_by_name(group_name)

    # full_epics = [group.epics.get(epic.get_id()) for epic in group.epics.list(get_all=True)]

    # for epic in full_epics:
    #     print(f"id: {epic.get_id()}, labels: [{epic.labels}]")

    # for epic in full_epics:
    #     issues = epic.issues.list()
    #     print(f"Len: {len(issues)}, {epic.get_id()}: {epic.title},")
    #     for issue in issues:
    #         print(f"   - {issue.id} - Weight: {issue.weight}")



    # gl.delete_all_issues_from_project(project_name)
    # gl.create_all_lorem_reports(group_name, project_name)



    # Labels
    # gl.create_and_apply_labels(gl.get_group_by_name(group_name), PROJECT_LABELS)
    # gl.create_and_apply_labels(gl.get_group_by_name(group_name), PIID_LABELS)

    # gl.delete_all_labels(gl.get_group_by_name(group_name))
    # gl.delete_all_group_epics(group_name)

    # lorem_epics = gl.create_epics_lorem(group_name, num_epics=10)



    # gl.md_group_epics_report(group_name, wiki_page_slug="Lorem Group Report")


    #
    # Milestones
    # 
    # epics = gl.get_epics(group_name)
    # for epic in epics:
    #     group_id = epic.attributes['group_id']
    #     group = gl.get_group_by_id(group_id)
    #     # print(f"epic: {epic.title} of group: {group.name}")
    #     print(f"Epic: {epic.title} of group: {group.name if group else f'group_id: {epic.group_id} (not found)'}")

    # gl.list_group_milestones(group_name, recursive=True)
    # milestones = gl.get_group_milestones(group_name, recursive=True)
    # for milestone in milestones:
    #     print(f"milestone: {milestone.title}")
    
    # group = gl.get_group_by_name(group_name)
    # result = gl.get_epics_under_milestones(group_name)
    # gl.upload_milestones_and_epics_to_wiki(group, result)

    
    # groups = gl.get_all_subgroups(group_name)
    # for group in groups:
    #     print(f"group: {group.attributes['full_path']}")
    
    # Markdown report functions
    # gl.md_group_epics_report(group_name)

    #
    # Issues function tests
    #
    # gl.export_project_issues_to_csv(project_name)
    # gl.export_epics_to_csv(group_name)
    # gl.import_epics_from_csv(group_name, epics_csv_filename)
    # gl.delete_all_group_epics(group_name)


    # gl.delete_all_issues_from_project(group_name)
    # gl.delete_all_group_epics(group_name)

    # gl.import_epics_from_csv(group_name, epics_csv_filename)
    # gl.import_issues_into_project(group_name, issues_csv_filename)
    # gl.issues_assign_random_weights(group_name, recursive=True)
    
    # csv_filename = "test-3-2-1-epics.csv"
    # gl.import_epics_from_csv(group_name, csv_filename)
    # gl.delete_all_group_epics(group_name)
    # gl.export_epics_to_csv(group_name)
    # gl.delete_all_issues_from_project(project_name)
    # gl.export_project_issues_to_csv(project_name)

    # Project function tests
    # gl.list_projects()
    # projects = gl.get_projects()
    # print(f"Projects: {len(projects)}")
    # for project in projects:
    #     print(f"project name: {type(project)}, name: {project.name}")
    #     print(f"Milestones:")
    #     milestones = project.milestones.list(get_all=True)
    #     for milestone in milestones:
    #         print(f"title: {milestone.attributes['title']}")
        
    # project = gl.get_project_by_name("test-3-1-project")
    # print(f"project name: {project.name}")

    # milestones = project.milestones
    # print(milestones)

    # project_name = "test-3-2-1-project"
    # gl.import_issues_into_project(project_name, "chatbot-project.csv")

    # Epics function tests
    # group_name = "Test-3-2"
    # gl.export_epics_to_csv(group_name)
    # gl.import_epics_from_csv(group_name, "chatbot-epics.csv")

    # Group function tests
    # gl.list_groups()
    # gl.get_groups()
    # group = gl.get_group_by_name(gl.group_name)
    # print(f"group: {group.name}, type: {type(group)}")
    # groups = gl.get_all_subgroups(group)
    # for g in groups:
    #     print(f"name: {g.name}")

    # Project function tests
    # gl.list_projects()

    # Search for projects by name (globally)
    # gl.get_project_by_name("test-3-1-project")

if __name__ == "__main__":
    main()
