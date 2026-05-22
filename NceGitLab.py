import argparse
import csv
from datetime import datetime, timedelta, timezone, date
from dateutil.relativedelta import relativedelta
from collections import defaultdict
import textwrap
import gitlab
import lorem
import json
import pandas as pd
from pathlib import Path
from pprint import pformat
from pprint import pprint
import random
import re
import requests
import os
import sys
from importlib.metadata import version as pkg_version



class NceGitLab:
    def __init__(self, config_file="nce_gitlab_config.json"):
        self.config_file = Path(config_file)

        if not self.config_file.exists():
            print(f"Config file '{self.config_file}' not found!")
            print('''Please create nec_gitlab_config.json with the following format:
                    {
                        "url": "https://gitlab.com",
                        "private_token": "glpat-XXXXXXXXXXXXXXXXXXXX",
                        "parent_group": "AMW-120",
                        "gitlab_namespace": "gl-demo-ultimate-lmwilliams",
                        "project_labels": ["project::DO", "project::RTSO", "project::DCGS", "project::TestA", "project::TestB", "project::TestC"],
                        "piid_labels": ["PIID::2026Q3", "PIID::2026Q4", "PIID::2027Q1", "PIID::2027Q2", "PIID::2027Q3", "PIID::2027Q4"],
                        "epic_labels": ["Epic", "Capability", "Feature"]
                    }
            ''')
            exit(1)
        
        self.EPIC_TYPE_ICONS = {
            "Epic": "🏆",           # Trophy for strategic goals
            "Capability": "🧩",     # Puzzle piece for capabilities
            "Feature": "🛠️"         # Tools for features
        }

        with open(self.config_file, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)

        def parse_label_env(env_var):
            env_val = os.getenv(env_var)
            return [item.strip() for item in env_val.split(",") if item.strip()] if env_val else None

        def parse_fibonacci_env(env_var):
            env_val = os.getenv(env_var)
            if env_val:
                try:
                    return [int(item.strip()) for item in env_val.split(",") if item.strip()]
                except ValueError:
                    return None
            return None

        self.url              = config.get("url", "")
        self.parent_group     = os.getenv("GROUP_NAME") or config.get("parent_group", "")
        self.gitlab_namespace = config.get("gitlab_namespace", "")
        
        access_token_env = os.getenv("ACCESS_TOKEN")
        if access_token_env:
            self.private_token = access_token_env
            token_source = "env (ACCESS_TOKEN)"
        else:
            self.private_token = config.get("private_token", "")
            token_source = config_file
        
        fibonacci_weights_env = parse_fibonacci_env("FIBONACCI_WEIGHTS")
        if fibonacci_weights_env:
            self.fibonacci_weights = fibonacci_weights_env
            fibonacci_weights_source = "env (FIBONACCI_WEIGHTS)"
        else:
            self.fibonacci_weights = config.get("fibonacci_weights")
            fibonacci_weights_source = config_file

        project_labels_env = parse_label_env("PROJECT_LABELS")
        if project_labels_env:
            self.PROJECT_LABELS = project_labels_env
            project_labels_source = "env (PROJECT_LABELS)"
        else:
            self.PROJECT_LABELS = config.get("project_labels", [])
            project_labels_source = config_file

        piid_labels_env = parse_label_env("PIID_LABELS")
        if piid_labels_env:
            self.PIID_LABELS = piid_labels_env
            piid_labels_source = "env (PIID_LABELS)"
        else: 
            self.PIID_LABELS = config.get("piid_labels", [])
            piid_labels_source = config_file

        epic_labels_env = parse_label_env("EPIC_TYPE_LABELS")
        if epic_labels_env:
            self.EPIC_TYPE_LABELS = epic_labels_env
            epic_labels_source = "env (EPIC_TYPE_LABELS)"
        else:
            self.EPIC_TYPE_LABELS = config.get("epic_type_labels", [])
            epic_labels_source = config_file

        self.EPIC_TYPE_PLANNED_WEIGHTS = config.get("epic_type_planned_weights", {
            "Feature":    [3, 5, 8, 13],
            "Capability": [21, 34, 55, 89],
            "Epic":       [89, 144, 233, 377],
        })

        token_display = "***" + self.private_token[-8:] if len(self.private_token) > 8 else "***"
        # print(f"ACCESS_TOKEN: {token_display} [source: {token_source}]")
        # print(f"FIBONACCI_WEIGHTS: {self.fibonacci_weights} [source: {fibonacci_weights_source}]")
        # print(f"PROJECT_LABELS: {self.PROJECT_LABELS} [source: {project_labels_source}]")
        # print(f"PIID_LABELS: {self.PIID_LABELS} [source: {piid_labels_source}]")
        # print(f"EPIC_TYPE_LABELS: {self.EPIC_TYPE_LABELS} [source: {epic_labels_source}]")

        missing_fields = []
        if not self.url:
            missing_fields.append("url")
        if not self.parent_group:
            missing_fields.append("parent_group")
        if not self.private_token:
            missing_fields.append("private_token")
        if not self.fibonacci_weights:
            missing_fields.append("fibonacci_weights")
        if not self.PROJECT_LABELS:
            missing_fields.append("project_labels")
        if not self.PIID_LABELS:
            missing_fields.append("piid_labels")
        if not self.EPIC_TYPE_LABELS:
            missing_fields.append("epic_labels")

        if missing_fields:
            print(f"ERROR: Missing required fields in nce_gitlab_config.json: {', '.join(missing_fields)}")
            exit(1)

        try:
            self.gl = gitlab.Gitlab(self.url, private_token=self.private_token)
            self.gl.auth()

            version, _ = self.gl.version()
            print(f"GitLab server : {self.gl.api_url}  (v{version})")
            print(f"python-gitlab : v{pkg_version('python-gitlab')}")
            print(f"Python        : {sys.version}")
        except gitlab.GitlabAuthenticationError:
            print("Authentication failed. Please check your private token.")
            exit(1)
        except gitlab.GitlabGetError as e:
            print(f"Failed to fetch group '{self.parent_group}': {e}")
            exit(1)
        
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
        groups = [g for g in self.gl.groups.list(search=name, all=True) if g.name == name]
        if len(groups) == 1:
            return self.gl.groups.get(groups[0].id)
        return None


    def get_all_subgroups(self, obj, include_self=True):
        
        # This function is unecessary as the top level group already returns all subgroups

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


    def list_projects_recursive(self, group_name, level=0):
        if group_name is None:
            group_name = group_name


        group = self.get_group_by_name(group_name)
        if group is None:
            return

        print(f"{'    ' * level}Group: {group.name} (id: {group.id})")
        projects = group.projects.list(all=True)
        for project in projects:
            print(f"{'    ' * (level + 1)}Project id: {project.id}, Name: {project.name}")

        subgroups = group.subgroups.list(all=True)
        for subgroup in subgroups:
            self.list_projects(subgroup.name, level + 1)


    def get_projects(self):
        partial_projects = self.gl.projects.list(owned=True, all=True)
        full_projects = [self.gl.projects.get(project.id) for project in partial_projects]
        return full_projects
    

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

    
    #
    # Epics functions
    #
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

                # TODO: add labels and maybe other fields check what is exported by default
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


    def delete_all_group_epics(self, group_name):
        root = self.get_group_by_name(group_name)
        if root is None:
            print(f"Group '{group_name}' not found. Aborting epic deletion.")
            return

        print()
        print(f"Deleting epics from '{group_name}' and all subgroups...")

        def _delete_epics_in_group(group):
            # Recurse into subgroups first so children are gone before parents.
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


    def create_epics_lorem_before_labels(self, group_name, num_epics=15):
        try:
            group = self.get_group_by_name(group_name)

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
                weight = random.choice(self.fibonacci_weights)

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


    def create_epics_lorem(self, group_name, num_epics=15, create_hierarchy=False):
        try:
            group = self.get_group_by_name(group_name)

            created_epics = []

            def get_next_month_start_date():
                """Get the start date as the first Monday of the next month."""
                today = datetime.today()
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
                weight = random.choice(self.fibonacci_weights)

                start_date = get_next_month_start_date()
                due_date = get_random_end_date_from_start(start_date)

                start_date_str = start_date.isoformat()
                due_date_str = due_date.isoformat()

                # Randomly select one project label, one PIID label, and an Epic type label (`Epic`, `Capability`, `Feature`)
                project_label = random.choice(self.PROJECT_LABELS)
                piid_label = random.choice(self.PIID_LABELS)
                epic_label = random.choice(self.EPIC_TYPE_LABELS)

                epic = group.epics.create({
                    'title': title,
                    'description': description,
                    'start_date': start_date_str,
                    'due_date': due_date_str,
                    'weight': weight,
                    'labels': [project_label, piid_label, epic_label]
                })

                print(
                    f"Created epic {epic.iid} - Title: {title}, Weight: {weight}, Start: {start_date}, End: {due_date}, "
                    f"Project Label: {project_label}, PIID Label: {piid_label}, Type Label: {epic_label}"
                )

                created_epics.append((epic, epic_label))

            # If a hierarchy is requested, assign relationships
            if create_hierarchy:
                self.build_epic_hierarchy(group, created_epics)

            return created_epics

        except Exception as e:
            print(f"Error creating epics: {e}")
            return []


    def build_epic_hierarchy(self, group, epics):
        try:
            print(f"Building epic hierarchy for group '{group.name}'")

            # Separate epics by type
            epic_dict = defaultdict(list)
            for epic, label in epics:
                epic_dict[label].append(epic)

            # Assign relationships: Epics → Capabilities → Features
            for epic in epic_dict.get("Epic", []):  # Loop through top-level Epics
                # Randomly assign capabilities to epics
                capabilities = random.sample(epic_dict.get("Capability", []), k=min(len(epic_dict.get("Capability", [])), 2))
                for capability in capabilities:
                    try:
                        capability.parent_id = epic.id
                        capability.save()
                        print(f"Linked Capability '{capability.title}' as child of Epic '{epic.title}'")
                    except Exception as e:
                        print(f"Failed to link Capability '{capability.title}' to Epic '{epic.title}': {e}")

                    # Randomly assign features to capabilities
                    features = random.sample(epic_dict.get("Feature", []), k=min(len(epic_dict.get("Feature", [])), 3))
                    for feature in features:
                        try:
                            feature.parent_id = capability.id
                            feature.save()
                            print(f"Linked Feature '{feature.title}' as child of Capability '{capability.title}'")
                        except Exception as e:
                            print(f"Failed to link Feature '{feature.title}' to Capability '{capability.title}': {e}")

        except Exception as e:
            print(f"Error building epic hierarchy: {e}")


    def create_feature_placeholders(self, group_name, num_features):
        """Create placeholder issues (Open and Closed) for each feature in a given group."""
        group = self.get_group_by_name(group_name)
        features = [epic for epic in group.epics.list(all=True) if "Feature" in epic.labels]
        
        placeholder_issues = []

        for feature in features:
            try:
                # Create placeholder issue (Open)
                open_issue = feature.issues.create({
                    "title": f"Placeholder: Open Issue for {feature.title}",
                    "description": "This is a placeholder issue to simulate open work for this feature.",
                    "weight": random.randint(1, 8),  # Assign a random weight to simulate work remaining
                })
                placeholder_issues.append(open_issue)

                # Create placeholder issue (Closed)
                closed_issue = feature.issues.create({
                    "title": f"Placeholder: Closed Issue for {feature.title}",
                    "description": "This is a placeholder issue to simulate completed work for this feature.",
                    "state_event": "close",  # Mark it as closed
                    "weight": random.randint(1, 8),  # Assign a random weight for completed work
                })
                placeholder_issues.append(closed_issue)

                print(f"Created placeholder issues for Feature: {feature.title} (Open: {open_issue.iid}, Closed: {closed_issue.iid})")
            
            except Exception as e:
                print(f"Failed to create placeholder issues for Feature: {feature.title}. Error: {e}")
            
        return placeholder_issues



    def assign_issues_to_epics(self, epics, issues):
        if not epics:
            print("No epics available to assign issues to.")
            return {}

        # Extract just the epic objects from the epics with labels
        epic_objects = [epic_tuple[0] for epic_tuple in epics]

        assigned_issues = {}

        for issue in issues:
            selected_epic = random.choice(epic_objects)

            try:
                issue.epic_id = selected_epic.id
                issue.save()

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

            created_issues = []

            for i in range(num_issues):
                title = lorem.sentence()
                description = lorem.paragraph() 
                weight = random.choice(self.fibonacci_weights)

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

                # Track assignments
                if selected_milestone.title not in assigned_issues:
                    assigned_issues[selected_milestone.title] = []
                assigned_issues[selected_milestone.title].append({
                    'issue_id': issue.iid,
                    'issue_title': issue.title,
                    'issue_url': issue.web_url,
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
                            issue_weight = random.choice(self.fibonacci_weights)
                            issue.weight = issue_weight
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
                self.assign_random_fibonacci_weights(subgroup.full_path, recursive=True)

        print(f"Completed assigning random weights to all unweighted issues in group '{group_name}'{' and its subgroups' if recursive else ''}.")
        print()


    def md_group_epics_report(self, group_name, wiki_page_slug="home", create_local_file=False):
        group = self.get_group_by_name(group_name)
        epics = group.epics.list(get_all=True)
        
        all_subgroups = self.get_all_subgroups(group)

        open_epics_count = sum(1 for e in epics if e.state == 'opened')
        total_epics = len(epics)

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
        grouped_epics = {}

        for epic in epics:
            group_id = epic.attributes['group_id']
            group = next((g for g in all_subgroups if g.id == group_id), None)

            if not group:
                print(f"Warning: No group found for Epic '{epic.title}' with group ID {group_id}")
                continue

            subgroup_name = group.full_path
            subgroup_url = group.web_url

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

            milestones = group.milestones.list(get_all=True)
            all_epics = group.epics.list(get_all=True)

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


    def create_lorem_milestones(self, target, num_milestones=12):
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

                # print(f"Calculated milestone dates: Start={milestone_start.date()}, End={milestone_end.date()}")

                try:
                    milestone_title = lorem.sentence()
                    milestone_description = lorem.paragraph()

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

            milestones = target.milestones.list(all=True)

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
        if not milestones:
            print("No milestones available to assign epics to.")
            return {}

        assigned_epics = {}

        for epic in epics:
            selected_milestone = random.choice(milestones)

            try:
                epic.start_date = selected_milestone.start_date
                epic.due_date = selected_milestone.due_date
                epic.save()

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
        try:
            group_name = group.name
        except Exception as e:
            return f"Error fetching group '{group_name}': {e}"
        
        milestones = []
        issues = []
        epics = []

        try:
            milestones = group.milestones.list(all=True)
            epics = group.epics.list(all=True)
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                full_project = self.gl.projects.get(project.id)
                project_milestones = full_project.milestones.list(all=True)
                project_issues = full_project.issues.list(all=True)

                milestones.extend(project_milestones)
                issues.extend(project_issues)

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")
            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

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

        markdown_report = []
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


        if unassigned_issues_count > 0:
            markdown_report.append("## Unassigned Issues")
            for issue in unassigned_issues:
                markdown_report.append(f"- **[{issue.title}]({issue.web_url})**")
            markdown_report.append("")

        md = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Summary Report"
        self.upload_to_wiki(self.get_group_by_name(group_name), title, md)


    def generate_detailed_report(self, group):
        group_name = group.name

        milestones = []
        epics = {}
        project_issues_by_milestone = defaultdict(list)
        epic_to_issue_map = defaultdict(list)

        try:
            # Fetch group-level milestones and epics
            milestones = group.milestones.list(all=True)
            epics = {epic.id: epic for epic in group.epics.list(all=True)}
        except Exception as e:
            print(f"Error fetching group milestones or epics: {e}")

        print(f"Fetched {len(milestones)} group-level milestones")
        print(f"Fetched {len(epics)} group-level epics")

        # Fetch project-level milestones, issues, and create an epic-to-issues mapping
        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                full_project = self.gl.projects.get(project.id)

                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

                project_milestones = full_project.milestones.list(all=True)
                project_issues = full_project.issues.list(all=True)

                milestones.extend(project_milestones)

                for issue in project_issues:
                    if issue.milestone:
                        project_issues_by_milestone[issue.milestone['id']].append(issue)

                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        epic_id = issue.epic_issue['epic_id']
                        epic_to_issue_map[epic_id].append(issue)

                print(f"Fetched {len(project_milestones)} milestones and {len(project_issues)} issues from project '{project.name}'")

            except Exception as e:
                print(f"Failed to fetch data from project '{project.name}': {e}")

        total_milestones = len(milestones)
        total_issues = sum(len(issues) for issues in project_issues_by_milestone.values())
        print(f"Total milestones fetched: {total_milestones} (group-level + project-level)")
        print(f"Total issues fetched: {total_issues}")

        markdown_report = []
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

            # Fetch issues associated with this milestone
            milestone_issues = project_issues_by_milestone.get(milestone.id, [])
            if milestone_issues:
                for issue in milestone_issues:
                    issue_line = f"  - **[{issue.title}]({issue.web_url})** (Status: {issue.state})"
                    
                    # Include epic details if the issue is linked to one
                    if hasattr(issue, 'epic_issue') and issue.epic_issue:
                        epic_id = issue.epic_issue['epic_id']
                        epic = epics.get(epic_id)
                        if epic:
                            # Infer the epic state dynamically based on the issues' states
                            linked_issues = epic_to_issue_map.get(epic_id, [])
                            all_issues_closed = all(i.state in ["closed", "done"] for i in linked_issues)

                            # Override the Epic's state if all its issues are closed
                            inferred_epic_state = "closed" if all_issues_closed else epic.state

                            # Append accurate data to the issue line
                            issue_line += f" (_Epic: [{epic.title}]({epic.web_url}) - **State:** {inferred_epic_state}_)"
                        else:
                            issue_line += " (_Epic: Unknown_)"
                    markdown_report.append(issue_line)
            else:
                markdown_report.append("  - No issues linked to this milestone")
            markdown_report.append("")

        # Handle milestones without issues (if any milestones do not have issues assigned)
        all_milestone_ids_with_issues = set(project_issues_by_milestone.keys())
        unlinked_milestones = [m for m in milestones if m.id not in all_milestone_ids_with_issues]

        if unlinked_milestones:
            markdown_report.append("## Milestones Without Linked Issues")
            for milestone in unlinked_milestones:
                markdown_report.append(f"- **{milestone.title}** (No issues linked)")
            markdown_report.append("")

        # Append summary of epic states
        markdown_report.append("## Epics Overview")
        for epic_id, epic in epics.items():
            # Infer epic state based on its issues
            linked_issues = epic_to_issue_map.get(epic_id, [])
            all_issues_closed = all(issue.state in ["closed", "done"] for issue in linked_issues)

            # Override the epic state dynamically
            # Removing inferred_epic_state
            inferred_epic_state = "closed" if all_issues_closed else epic.state

            # Report dynamically inferred state in the summary
            markdown_report.append(f"- **Epic: [{epic.title}]({epic.web_url})**")
            markdown_report.append(f"  - **State:** {epic.state}")
            markdown_report.append(f"  - **Linked Issues:** {len(linked_issues)} issue(s)")
            for issue in linked_issues:
                markdown_report.append(f"    - **[{issue.title}]({issue.web_url})** (State: {issue.state})")
            markdown_report.append("")

        # Join Markdown content for uploading to the wiki
        md = "\n".join(markdown_report)
        title = f"{group_name} - Detailed Report"
        self.upload_to_wiki(group, title, md)

        return md


    def generate_issue_progress_report(self, group):
        group_name = group.name

        project_status_counts = defaultdict(lambda: defaultdict(int))
        project_issues = defaultdict(list)
        milestone_mapping = defaultdict(list)

        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                print(f"Processing project: {project.name} (ID: {project.id})")

                full_project = self.gl.projects.get(project.id)

                if not full_project.issues_enabled:
                    print(f"Issues are disabled for project '{project.name}'. Skipping.")
                    continue

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


        markdown_report = []
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
            markdown_report.append("")


        md = "\n".join(markdown_report)
        title = f"{group_name.capitalize()} - Issue Progress and Status Overview"
        self.upload_to_wiki(group, title, md)

        return md


    def generate_and_upload_piid_project_report_to_wiki(self, group):
        report_data = {project_label: {piid_label: None for piid_label in self.PIID_LABELS} for project_label in self.PROJECT_LABELS}

        try:
            print(f"Fetching all epics for group: {group.name}")
            all_epics = [group.epics.get(epic.get_id()) for epic in group.epics.list(all=True)]
            print(f"Fetched {len(all_epics)} total epics.")

            relevant_epics = []
            for epic in all_epics:
                # Match epics with the intersection of PIID and project labels
                project_label = next((label for label in self.PROJECT_LABELS if label in epic.labels), None)
                piid_label = next((label for label in self.PIID_LABELS if label in epic.labels), None)
                if project_label and piid_label:
                    relevant_epics.append((epic, project_label, piid_label))

            print(f"Found {len(relevant_epics)} relevant epics with PIID/Project label intersections.")

            for epic, project_label, piid_label in relevant_epics:
                if report_data[project_label][piid_label] is None:
                    report_data[project_label][piid_label] = {
                        "epics_open": 0,
                        "epics_total": 0,
                        "weight_open": 0,
                        "weight_total": 0,
                        "epic_urls": set(),
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

                    # Add the epic URL for this cell
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

            md_content = "\n".join(markdown_report)

            # Upload to the Wiki
            wiki_title = "PIID_vs_Project_Labels_Report"
            print(f"Uploading report to wiki: {wiki_title}")
            self.upload_to_wiki(group, wiki_title, md_content)

            return md_content

        except Exception as e:
            print(f"An error occurred while generating or uploading the report: {e}")


    def upload_to_wiki(self, group, page_title, content):
        try:
            page_slug = page_title.replace(" ", "-").lower()
            try:
                group.wikis.get(page_slug).delete()
            except gitlab.exceptions.GitlabGetError as e:
                if e.response_code != 404:
                    print(f"Error fetching wiki page '{page_title}': {e}")
                    return
            group.wikis.create({'title': page_title, 'content': content})
            print(f"  → Wiki: {page_title}")
        except Exception as e:
            print(f"Failed to upload wiki page '{page_title}': {e}")


    def delete_all_wiki_pages(self, group):
        try:
            wiki_pages = group.wikis.list(all=True)
        except Exception as e:
            print(f"Error fetching wiki pages for group '{group.name}': {e}")
            return

        print(f"Found {len(wiki_pages)} wiki pages in the group '{group.name}'")

        for wiki_page in wiki_pages:
            try:
                print(f"Deleting wiki page: {wiki_page.title}")
                wiki_page.delete()
                print(f"Successfully deleted wiki page: {wiki_page.title}")
            except Exception as e:
                print(f"Failed to delete wiki page '{wiki_page.title}': {e}")

        print(f"All wiki pages for group '{group.name}' have been deleted.")


    def generate_portfolio_report(self, group):
        group_name = group.name

        print(f"  Generating SAFe Portfolio Report...")

        try:
            # Step 1: Calculate portfolio metrics
            metrics = self.calculate_portfolio_metrics(group_name)

            # pprint(metrics)

            # Step 2: Generate portfolio-level summary
            summary_report = self.generate_portfolio_summary(metrics, group)

            # Start building Markdown
            markdown_report = []
            markdown_report.append(f"# SAFe Portfolio Report (Group: {group_name})")
            markdown_report.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
            markdown_report.append("")
            markdown_report.append(summary_report)
            markdown_report.append("")
            markdown_report.append("")
            markdown_report.append("")
            markdown_report.append("## Initiative Hierarchy")
            markdown_report.append("")

            # Organize epics into a hierarchy
            all_epics = metrics["Epic"] + metrics["Capability"] + metrics["Feature"]
            epic_hierarchy = defaultdict(list)

            # Build the hierarchy: map parent_id to its children
            for epic in all_epics:
                if epic.get("parent_id") is not None:
                    epic_hierarchy[epic["parent_id"]].append(epic)

            # Define the helper function to render epics hierarchically
            def render_epic_details(epic, indent_level=0):
                nonlocal markdown_report

                epic_type = next((t for t in ["Epic", "Capability", "Feature"] if t in epic.get("labels", [])), "Epic")
                icon     = self.EPIC_TYPE_ICONS.get(epic_type, "🏆")
                children = epic_hierarchy.get(epic['id'], [])

                blocked    = epic.get('blocked_by_count', 0) > 0
                block_icon = '<span style="font-size:0.62em;">⛔</span> ' if blocked else ""

                pct_done   = epic.get('pct_complete', 0)
                pct_pi     = epic.get('pct_through_pi')
                planned_w  = epic.get('planned_weight', 0)
                actual_w   = epic.get('actual_weight', 0)

                pi_str  = f" | PI: {pct_pi}%" if pct_pi is not None else ""
                risk    = " ⚠️" if pct_pi is not None and pct_done < pct_pi else ""

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
                    # No leading-space indentation on HTML tags or content — CommonMark treats
                    # 4+ leading spaces as a code block, which breaks rendering at nesting depth >= 2.
                    markdown_report.append("<details>")
                    markdown_report.append(f"<summary>{label}</summary>")
                    markdown_report.append("")

                    for child_epic in children:
                        render_epic_details(child_epic, indent_level + 1)

                    markdown_report.append("</details>")
                    markdown_report.append("")

            # Only Epics are top-level — Capabilities/Features with no parent_id
            # are unlinked orphans in GitLab and should not appear at the root.
            for epic in metrics["Epic"]:
                render_epic_details(epic)

            markdown_report.append("")
            markdown_report.append("")
            markdown_report.append("")
            markdown_report.append("---")
            markdown_report.append("## Legend")
            markdown_report.append("- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)")
            markdown_report.append("- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs")
            markdown_report.append("- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes")
            markdown_report.append("")

            # Final markdown generation
            md = "\n".join(markdown_report)
            # print("Generated Markdown:")  # For debugging purposes
            # print(md)

            # Upload the Markdown to the group's Wiki
            self.upload_to_wiki(group, f"{group_name} - SAFe Portfolio Report", md)

        except Exception as e:
            print(f"Failed to generate epics report for group '{group_name}': {e}")


    def generate_workload_report(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"  Generating ART/Team Workload Report...")

        metrics  = self.calculate_portfolio_metrics(self.parent_group)
        all_epics = metrics.get("Epic", []) + metrics.get("Capability", []) + metrics.get("Feature", [])
        if not all_epics:
            print("No epics found — skipping workload report.")
            return

        # Fetch only the groups that own epics.
        group_ids = {e["group_id"] for e in all_epics if e.get("group_id")}
        groups_by_id = {}
        for gid in group_ids:
            try:
                groups_by_id[gid] = self.gl.groups.get(gid)
            except Exception as e:
                print(f"  Could not fetch group {gid}: {e}")

        # Bucket all epics by (piid, group_id).
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
            key=lambda p: self._pi_dates_from_label(p)[0] or date.min
        )

        md = []
        md.append(f"# ART/Team Workload Report (Group: {group.name})")
        md.append(f"## Report Date: {datetime.today().strftime('%Y-%m-%d')}")
        md.append("")

        for piid in sorted_pis:
            phase    = pi_phase(piid)
            pct_pi   = self._pct_through_pi(piid) or 0
            start, end = self._pi_dates_from_label(piid)
            date_range = f"_{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}_" if start else ""

            phase_label = {"current": f"🟢 Current PI — {pct_pi}% elapsed",
                           "future":  "🔵 Future PI",
                           "past":    "⚫ Past PI"}.get(phase, "")

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

                delta_str = f"▲{delta}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "=")
                risk_flag = " ⚠️" if (phase == "current" and avg_pct < pct_pi) else ""

                if phase == "current":
                    status_str = "⚠️ At Risk"  if avg_pct < pct_pi  else "✅ On Track"
                elif phase == "past":
                    status_str = "✅ Complete"  if avg_pct == 100    else f"❌ Incomplete"
                else:
                    status_str = "🔵 Planned"

                grp_link = f'<a href="{grp_url}" target="_blank" rel="noopener noreferrer">{grp_name}</a>' if grp_url else grp_name

                md.append(
                    f"| {grp_link} | {len(fs)} | {total_planned} pt | {total_actual} pt "
                    f"| {delta_str} | {avg_pct}%{risk_flag} | {status_str} |"
                )

            md.append("")

        md.append("---")
        md.append("## Legend")
        md.append("- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)")
        md.append("- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs")
        md.append("- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes")
        md.append("- **Planned**: sum of epic planned weights committed to this PI in this group")
        md.append("- **Actual**: sum of issue weights for those Features (team-entered estimate)")
        md.append("- **Δ**: Actual − Planned (▲ more work than planned, ▼ less, = matched)")
        md.append("- **% Done**: weighted average completion across Features (by planned weight)")
        md.append("- **Status**: ✅ On Track if % Done ≥ % elapsed through PI · ⚠️ At Risk if behind · ❌ Incomplete if PI ended with work remaining")
        md.append("")

        self.upload_to_wiki(group, f"{group.name} - ART/Team Workload Report", "\n".join(md))


    def graphql_query(self, query, variables=None):
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        response = requests.post(
            f"{self.url}/api/graphql",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.private_token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            for err in data["errors"]:
                print(f"GraphQL error: {err['message']}")
            return None
        return data["data"]


    def list_blocking_epics(self):
        group = self.get_group_by_name(self.parent_group)
        full_path = group.full_path

        query = """
        query ListAllEpics($fullPath: ID!) {
          group(fullPath: $fullPath) {
            epics {
              nodes {
                title
                blocked
                blockingCount
                webUrl
                blockedByCount
                labels {
                  nodes {
                    title
                  }
                }
                blockedByEpics {
                  edges {
                    node {
                      id
                      title
                      webUrl
                      labels {
                        nodes {
                          title
                        }
                      }
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

        nodes = data["group"]["epics"]["nodes"]
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
            blocking_cnt   = epic.get("blockingCount", 0)
            etype          = epic_type(epic)
            icon           = self.EPIC_TYPE_ICONS.get(etype, "🏆")

            print(f"⛔ {epic['title']}  [{icon} {etype}]")
            print(f"   State: {state}  |  Blocked by: {blocked_by_cnt}")
            print(f"   {epic['webUrl']}")

            blockers = epic.get("blockedByEpics", {}).get("edges", [])
            last = len(blockers) - 1
            for i, edge in enumerate(blockers):
                node = edge["node"]
                connector  = "└─" if i == last else "├─"
                btype      = epic_type(node)
                bicon      = self.EPIC_TYPE_ICONS.get(btype, "🏆")
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
                id
                title
                blocked
                blockingCount
                webUrl
                blockedByCount
                labels {
                  nodes {
                    title
                  }
                }
                parent {
                  id
                  title
                  webUrl
                  labels {
                    nodes {
                      title
                    }
                  }
                }
                blockedByEpics {
                  edges {
                    node {
                      id
                      title
                      webUrl
                      labels {
                        nodes {
                          title
                        }
                      }
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

        nodes        = data["group"]["epics"]["nodes"]
        blocked_epics = [n for n in nodes if n.get("blockedByCount", 0) > 0]

        total_relationships = sum(n.get("blockedByCount", 0) for n in blocked_epics)

        # Build id→node and child→parent maps for ancestor walking.
        id_to_node = {n["id"]: n for n in nodes}
        parent_of  = {n["id"]: n["parent"]["id"] for n in nodes if n.get("parent")}

        def get_ancestors(epic_id):
            """Walk up the hierarchy and return ordered list of ancestor nodes (nearest first)."""
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

        # For each top-level Epic, collect all blocked descendants so we can
        # build a portfolio-level risk summary.
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

        # Portfolio-level risk summary — which Epics are indirectly at risk.
        if epic_to_blocked_descendants:
            md.append("## Portfolio-Level Risk Summary")
            md.append("")
            md.append("Top-level Epics that contain one or more blocked descendants:")
            md.append("")
            md.append("| Epic | Blocked Descendants |")
            md.append("|------|---------------------|")
            for epic_id, descendants in sorted(
                epic_to_blocked_descendants.items(),
                key=lambda kv: -len(kv[1])
            ):
                epic_node  = id_to_node[epic_id]
                def _short(title):
                    return title[:12] + "…" if len(title) > 12 else title
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

        md.append("---")
        md.append("## Legend")
        md.append("- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)")
        md.append("- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs")
        md.append("- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes")
        md.append("")

        title = f"{group.name} - Blocking Relationships Report"
        self.upload_to_wiki(group, title, "\n".join(md))


    def _set_epic_weight(self, epic, weight):
        """Set weight on an epic via GraphQL workItemUpdate (REST API silently ignores weight)."""
        wid = getattr(epic, 'work_item_id', None)
        if not wid:
            return
        mutation = """
        mutation UpdateWeight($id: WorkItemID!, $weight: Int!) {
          workItemUpdate(input: {id: $id, weightWidget: {weight: $weight}}) {
            workItem { id }
            errors
          }
        }
        """
        data = self.graphql_query(mutation, variables={"id": f"gid://gitlab/WorkItem/{wid}", "weight": weight})
        if data:
            errors = data.get("workItemUpdate", {}).get("errors", [])
            if errors:
                print(f"  Weight error for epic {epic.iid}: {errors}")


    def _fetch_epic_weights(self, epics):
        """Return {web_url: weight} for a list of REST epic objects via GraphQL WorkItem queries."""
        query = """
        query GetWorkItemWeight($id: WorkItemID!) {
            workItem(id: $id) {
                widgets { ... on WorkItemWidgetWeight { weight } }
            }
        }
        """
        print(f"  Fetching planned weights for {len(epics)} epics...")
        weights = {}
        for epic in epics:
            wid = getattr(epic, 'work_item_id', None)
            if not wid:
                continue
            gid = f"gid://gitlab/WorkItem/{wid}"
            try:
                data = self.graphql_query(query, variables={"id": gid})
                if data:
                    for w in data.get("workItem", {}).get("widgets", []):
                        if isinstance(w, dict) and w.get("weight") is not None:
                            weights[epic.web_url] = w["weight"]
                            break
            except Exception:
                pass
        return weights

    def calculate_portfolio_metrics(self, group_name):
        if hasattr(self, '_metrics_cache') and group_name in self._metrics_cache:
            return self._metrics_cache[group_name]

        group = self.get_group_by_name(group_name)
        if not group:
            print(f"Group '{group_name}' not found.")
            return {}

        # GraphQL: block counts per epic (accurate, cheap).
        gql_data = self.graphql_query(
            """
            query EpicBlockCounts($fullPath: ID!) {
              group(fullPath: $fullPath) {
                epics {
                  nodes { webUrl blockedByCount blockingCount }
                }
              }
            }
            """,
            variables={"fullPath": group.full_path},
        )
        epic_blocks = {}
        if gql_data:
            epic_blocks = {
                n["webUrl"]: n for n in gql_data["group"]["epics"]["nodes"]
            }

        # Issue weights indexed by directly-assigned epic id (for % complete).
        print("  Fetching issue weights...")
        issues_by_epic_id = defaultdict(list)
        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                full_project = self.gl.projects.get(project.id)
                for issue in full_project.issues.list(all=True):
                    epic_info = getattr(issue, 'epic', None)
                    if epic_info and epic_info.get('id'):
                        issues_by_epic_id[epic_info['id']].append(issue)
            except Exception as e:
                print(f"  Failed to fetch issues for '{project.name}': {e}")

        all_epics = group.epics.list(all=True)
        epic_weights = self._fetch_epic_weights(all_epics)
        metrics   = {"Epic": [], "Capability": [], "Feature": []}
        epic_by_id = {}

        print(f"  Processing {len(all_epics)} epics...")
        for epic in all_epics:
            gql    = epic_blocks.get(epic.web_url, {})
            issues = issues_by_epic_id.get(epic.id, [])

            total_w  = sum(i.weight or 0 for i in issues)
            closed_w = sum(i.weight or 0 for i in issues if i.state == 'closed')
            if total_w > 0:
                pct_done = round(closed_w / total_w * 100)
            elif epic.state == 'closed':
                pct_done = 100
            else:
                pct_done = 0

            piid    = next((l for l in epic.labels if l.startswith("PIID::")), None)
            pct_pi  = self._pct_through_pi(piid)

            associated_data = {
                "id":               epic.id,
                "title":            epic.title,
                "state":            epic.state.capitalize(),
                "blocked_by_count": gql.get("blockedByCount", 0),
                "blocks_count":     gql.get("blockingCount", 0),
                "web_url":          epic.web_url,
                "labels":           epic.labels,
                "parent_id":        getattr(epic, 'parent_id', None),
                "planned_weight":   epic_weights.get(epic.web_url, 0),
                "actual_weight":    total_w,
                "pct_complete":     pct_done,
                "pct_through_pi":   pct_pi,
                "piid":             piid,
                "group_id":         getattr(epic, 'group_id', None),
            }

            if "Epic" in epic.labels:
                epic_type = "Epic"
            elif "Capability" in epic.labels:
                epic_type = "Capability"
            elif "Feature" in epic.labels:
                epic_type = "Feature"
            else:
                print(f"Skipping epic '{epic.title}' — no matching type label.")
                continue

            metrics[epic_type].append(associated_data)
            epic_by_id[epic.id] = associated_data

        # Roll % complete up through the hierarchy:
        # Capability % = weighted avg of its Features; Epic % = weighted avg of its Capabilities.
        hierarchy = defaultdict(list)
        for etype in metrics.values():
            for e in etype:
                if e["parent_id"] is not None:
                    hierarchy[e["parent_id"]].append(e)

        def rollup_pct(e):
            children = hierarchy.get(e["id"], [])
            if not children:
                return e["pct_complete"]
            child_pcts = [rollup_pct(c) for c in children]
            return round(sum(child_pcts) / len(child_pcts))

        def rollup_actual(e):
            children = hierarchy.get(e["id"], [])
            if not children:
                return e["actual_weight"]
            return sum(rollup_actual(c) for c in children)

        for cap in metrics["Capability"]:
            cap["pct_complete"]  = rollup_pct(cap)
            cap["actual_weight"] = rollup_actual(cap)
        for ep in metrics["Epic"]:
            ep["pct_complete"]  = rollup_pct(ep)
            ep["actual_weight"] = rollup_actual(ep)

        if not hasattr(self, '_metrics_cache'):
            self._metrics_cache = {}
        self._metrics_cache[group_name] = metrics
        return metrics




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

            total       = len(data_list)
            open_count  = sum(1 for d in data_list if d["state"] == "Opened")
            closed_count = sum(1 for d in data_list if d["state"] == "Closed")
            total_blocked_by = sum(d["blocked_by_count"] for d in data_list)
            total_blocks     = sum(d["blocks_count"] for d in data_list)

            pcts_done = [d["pct_complete"] for d in data_list]
            avg_done  = round(sum(pcts_done) / len(pcts_done)) if pcts_done else 0

            pcts_pi   = [d["pct_through_pi"] for d in data_list if d["pct_through_pi"] is not None]
            avg_pi    = round(sum(pcts_pi) / len(pcts_pi)) if pcts_pi else None

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





    #
    # Utilities
    #
    def _pi_dates_from_label(self, piid):
        """Parse a PIID::YYYYQn label into (start_date, end_date). Returns (None, None) on failure."""
        if not piid:
            return None, None
        m = re.match(r'PIID::(\d{4})Q([1-4])$', piid)
        if not m:
            return None, None
        year, quarter = int(m.group(1)), int(m.group(2))
        q_starts = {1: (1, 1),  2: (4, 1),  3: (7, 1),  4: (10, 1)}
        q_ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        return date(year, *q_starts[quarter]), date(year, *q_ends[quarter])

    def _pct_through_pi(self, piid):
        """Return integer % elapsed through the PI quarter, or None if label can't be parsed."""
        start, end = self._pi_dates_from_label(piid)
        if start is None:
            return None
        today = date.today()
        if today < start:
            return 0
        if today >= end:
            return 100
        return round((today - start).days / (end - start).days * 100)

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
        

    def truncate_text(self, text, max_length=20):
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text

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
            if hasattr(target, 'labels'):
                list_labels = target.labels.list(all=True)
                delete_label = lambda label: label.delete()
            elif hasattr(target, 'group_labels'): 
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
    def _get_or_create_root_group(self):
        """Return the root group, creating it if absent.

        Parent selection is automatic when only one top-level group is accessible;
        otherwise the user is prompted to choose.
        """
        group = self.get_group_by_name(self.parent_group)
        if group is not None:
            return group

        print(f"\nRoot group '{self.parent_group}' not found — creating it.")

        if self.gitlab_namespace:
            parent = self.get_group_by_name(self.gitlab_namespace)
            if parent is None:
                print(f"gitlab_namespace '{self.gitlab_namespace}' not found. Aborting.")
                return None
            print(f"  Using namespace: {parent.full_path}")
        else:
            candidates = [g for g in self.gl.groups.list(all=True, top_level_only=True)
                          if g.visibility in ('public', 'internal', 'private')]
            if not candidates:
                print("No accessible parent groups found. Aborting.")
                return None

            if len(candidates) == 1:
                parent = candidates[0]
                print(f"  Using parent: {parent.full_path}")
            else:
                print("\nAvailable parent groups:")
                for i, g in enumerate(candidates, 1):
                    print(f"  [{i}] {g.full_path}  ({g.visibility})")
                choice = input(f"\nSelect parent [1-{len(candidates)}]: ").strip()
                try:
                    parent = candidates[int(choice) - 1]
                except (ValueError, IndexError):
                    print("Invalid selection. Aborting.")
                    return None

        path  = self.parent_group.lower().replace(" ", "-")
        group = self.gl.groups.create({
            'name':       self.parent_group,
            'path':       path,
            'parent_id':  parent.id,
            'visibility': parent.visibility,
        })
        print(f"Created root group: {group.full_path}")
        return group


    def cleanup_group(self):
        group = self.get_group_by_name(self.parent_group)
        if group is None:
            print(f"Root group '{self.parent_group}' not found. Nothing to clean up.")
            return

        # Post-order traversal: every subgroup with its children listed before itself,
        # so each group is empty (no child groups) when we attempt to delete it.
        subgroups = self._groups_deepest_first(group)

        # Snapshot live projects once; reuse for issues, labels, and project deletion.
        print("Collecting all projects...")
        all_projects = group.projects.list(all=True, include_subgroups=True)
        live_projects = [p for p in all_projects if '_deletion_scheduled' not in p.path]
        skipped = len(all_projects) - len(live_projects)
        if skipped:
            print(f"  Skipping {skipped} pending-deletion project(s).")

        # 1. Wiki pages — root group only (subgroup wikis are cascade-deleted with the group).
        self.delete_all_wiki_pages(group)

        # 2. Epics — recursive helper already handles children before parents.
        self.delete_all_group_epics(self.parent_group)

        # 3. Milestones — root group and every subgroup.
        self.delete_all_milestones(group)
        for sg in subgroups:
            self.delete_all_milestones(sg)

        # 4. Issues — every live project across the full hierarchy.
        # GitLab group/project deletion is async; explicit issue deletion makes
        # cleanup synchronous so issues disappear immediately.
        print("Deleting all issues across group hierarchy...")
        for project in live_projects:
            try:
                full_project = self.gl.projects.get(project.id)
                issues = full_project.issues.list(all=True)
                for issue in issues:
                    try:
                        issue.delete()
                    except Exception as e:
                        print(f"  Failed to delete issue #{issue.iid} in '{project.path_with_namespace}': {e}")
                if issues:
                    print(f"  Deleted {len(issues)} issues from '{project.path_with_namespace}'")
            except Exception as e:
                print(f"  Failed to fetch issues for '{project.path_with_namespace}': {e}")

        # 5. Labels — root group, every subgroup, every live project.
        self.delete_all_labels(group)
        for sg in subgroups:
            self.delete_all_labels(sg)
        for project in live_projects:
            try:
                full_project = self.gl.projects.get(project.id)
                self.delete_all_labels(full_project)
            except Exception as e:
                print(f"  Failed to delete labels from project '{project.path_with_namespace}': {e}")

        # 6. Projects.
        for project in live_projects:
            try:
                self.gl.projects.delete(project.id)
                print(f"Deleted project: {project.path_with_namespace}")
            except Exception as e:
                print(f"Failed to delete project '{project.path_with_namespace}': {e}")

        # 7. Subgroups depth-first (leaves first, so each parent is empty when deleted).
        for sg in subgroups:
            try:
                self.gl.groups.delete(sg.id)
                print(f"Deleted subgroup: {sg.full_path}")
            except Exception as e:
                print(f"Failed to delete subgroup '{sg.full_path}': {e}")

        # 8. Root group.
        try:
            self.gl.groups.delete(group.id)
            print(f"Deleted root group: {group.full_path}")
        except Exception as e:
            print(f"Failed to delete root group '{group.full_path}': {e}")

    def _groups_deepest_first(self, group):
        """Return all subgroups of `group` in post-order (deepest/leaves first).

        Does not include `group` itself. Used by cleanup_group so every group is
        empty of child groups before we attempt to delete it.
        """
        result = []
        for sg in group.subgroups.list(all=True):
            full_sg = self.gl.groups.get(sg.id)
            result.extend(self._groups_deepest_first(full_sg))
            result.append(full_sg)
        return result


    def _lorem_epics_in_group(self, group, count, allowed_types=None):
        """Create lorem epics directly in a group object. Returns [(epic, label)].
        allowed_types restricts which epic type labels are used (default: all three)."""
        def next_monday_on_or_after(d):
            while d.weekday() != 0:
                d += timedelta(days=1)
            return d

        type_pool  = allowed_types or self.EPIC_TYPE_LABELS
        weight_pool = self.EPIC_TYPE_PLANNED_WEIGHTS

        created = []
        for _ in range(count):
            piid_label    = random.choice(self.PIID_LABELS)
            epic_label    = random.choice(type_pool)
            project_label = random.choice(self.PROJECT_LABELS)

            # Align start/due dates to the PI quarter so data reflects real planning.
            pi_start, pi_end = self._pi_dates_from_label(piid_label)
            if pi_start:
                pi_days = (pi_end - pi_start).days
                start   = next_monday_on_or_after(
                    pi_start + timedelta(days=random.randint(0, pi_days // 4))
                )
                due     = next_monday_on_or_after(
                    pi_start + timedelta(days=random.randint(pi_days // 2, pi_days))
                )
                if due > pi_end:
                    due = pi_end
            else:
                start = next_monday_on_or_after(
                    (datetime.today().replace(day=1) + relativedelta(months=1)).date()
                )
                due = next_monday_on_or_after(start + relativedelta(months=random.randint(1, 6)))

            weight = random.choice(weight_pool.get(epic_label, self.fibonacci_weights))

            epic = group.epics.create({
                'title':       lorem.sentence().rstrip('.'),
                'description': lorem.paragraph(),
                'start_date':  start.isoformat(),
                'due_date':    due.isoformat(),
                'labels':      [project_label, piid_label, epic_label],
            })
            self._set_epic_weight(epic, weight)
            print(f"  Epic {epic.iid} [{epic_label}] w={weight} → {group.full_path}")
            created.append((epic, epic_label))

        return created


    def _lorem_issues_in_project(self, project, count):
        """Create lorem issues directly in a project object. Returns [issue]."""
        issues = []
        for _ in range(count):
            issue = project.issues.create({
                'title':       lorem.sentence().rstrip('.'),
                'description': lorem.paragraph(),
                'weight':      random.choice(self.fibonacci_weights),
            })
            print(f"  Issue #{issue.iid} → {project.path_with_namespace}")
            issues.append(issue)
        return issues


    def _lorem_populate_group(self, group, epic_count, allowed_types=None):
        """Create epics in a group and a team backlog project with stories per Feature."""
        epics = self._lorem_epics_in_group(group, epic_count, allowed_types=allowed_types)

        feature_epics = [(e, lbl) for e, lbl in epics if lbl == "Feature"]
        if not feature_epics:
            return

        try:
            project = self.gl.projects.create({
                'name':         f"{group.name} — Team Backlog",
                'path':         f"{group.path}-backlog",
                'namespace_id': group.id,
            })
            print(f"  Team Backlog → {project.path_with_namespace}")
            milestones = self.create_lorem_milestones(project)
            issue_weight_pool = [1, 2, 3, 5, 8, 13]

            for feature_epic, _ in feature_epics:
                total_stories = random.randint(8, 15)

                for i in range(total_stories):
                    ms    = random.choice(milestones) if milestones else None
                    issue = project.issues.create({
                        'title':        lorem.sentence().rstrip('.'),
                        'description':  lorem.paragraph(),
                        'weight':       random.choice(issue_weight_pool),
                        'milestone_id': ms.id if ms else None,
                    })
                    issue.epic_id = feature_epic.id
                    issue.save()

                print(f"    {total_stories} stories → Feature #{feature_epic.iid}")

        except Exception as e:
            print(f"  Skipping team backlog for '{group.full_path}': {e}")

        return epics


    def create_all_lorem_objects(self,
                                  num_value_streams=2, num_arts=2, num_teams=2,
                                  portfolio_epics=5,
                                  vs_epics=3,
                                  art_epics=4,
                                  team_features=4):
        """
        SAFe level → epic type mapping:
          Portfolio    → Epic only
          Value Stream → Capability only
          ART          → Capability only
          Team         → Feature only  (each gets 8–15 stories linked to issues)
        """
        root_group = self._get_or_create_root_group()
        if root_group is None:
            return

        # Labels defined on the root group are inherited by all subgroups.
        for label_array in [self.PROJECT_LABELS, self.PIID_LABELS, self.EPIC_TYPE_LABELS]:
            self.create_and_apply_labels(root_group, label_array)

        # Portfolio level: Epics only, no backlog project (strategic, not execution)
        all_portfolio_epics = self._lorem_epics_in_group(root_group, portfolio_epics, allowed_types=["Epic"])
        print(f"Portfolio: {portfolio_epics} Epics → {root_group.full_path}")

        vis = root_group.visibility

        all_vs_caps   = []
        all_art_caps  = []
        all_features  = []

        for vs in range(1, num_value_streams + 1):
            vs_path = f"vs-{vs:02d}"
            vs_name = f"Value Stream {vs:02d}"
            vs_group = self.gl.groups.create({
                'name':       vs_name,
                'path':       vs_path,
                'parent_id':  root_group.id,
                'visibility': vis,
            })
            print(f"\n[Value Stream] {vs_group.full_path}")
            vs_caps = self._lorem_epics_in_group(vs_group, vs_epics, allowed_types=["Capability"])
            all_vs_caps.extend(vs_caps)

            for a in range(1, num_arts + 1):
                art_path = f"art-{a:02d}"
                art_name = f"ART {a:02d}"
                art_group = self.gl.groups.create({
                    'name':       art_name,
                    'path':       art_path,
                    'parent_id':  vs_group.id,
                    'visibility': vis,
                })
                print(f"\n[ART] {art_group.full_path}")
                art_created = self._lorem_epics_in_group(art_group, art_epics,
                                                         allowed_types=["Capability"])
                all_art_caps.extend(art_created)

                for t in range(1, num_teams + 1):
                    team_path = f"team-{t:02d}"
                    team_name = f"Team {t:02d}"
                    team_group = self.gl.groups.create({
                        'name':       team_name,
                        'path':       team_path,
                        'parent_id':  art_group.id,
                        'visibility': vis,
                    })
                    print(f"\n[Agile Team] {team_group.full_path}")
                    team_created = self._lorem_populate_group(team_group, team_features,
                                                              allowed_types=["Feature"])
                    if team_created:
                        all_features.extend(team_created)

        # Link the SAFe hierarchy across group boundaries.
        # Each child is randomly assigned to one parent at the level above it.
        def _link_to_parents(children, parents):
            if not parents or not children:
                return
            parent_epics = [e for e, _ in parents]
            for child_epic, _ in children:
                parent = random.choice(parent_epics)
                try:
                    child_epic.parent_id = parent.id
                    child_epic.save()
                    print(f"  Linked '{child_epic.title[:40]}' → '{parent.title[:40]}'")
                except Exception as e:
                    print(f"  Failed to link '{child_epic.title[:40]}': {e}")

        print("\nLinking cross-group hierarchy...")
        _link_to_parents(all_vs_caps,  all_portfolio_epics)   # VS Capabilities → Portfolio Epics
        _link_to_parents(all_art_caps, all_vs_caps)            # ART Capabilities → VS Capabilities
        _link_to_parents(all_features, all_art_caps)           # Features → ART Capabilities


    def generate_orphan_epics_report(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"Generating orphan report for {group.name}...")

        all_epics = group.epics.list(all=True)

        # Build parent→children map
        epic_hierarchy = defaultdict(list)
        for epic in all_epics:
            pid = getattr(epic, 'parent_id', None)
            if pid is not None:
                epic_hierarchy[pid].append(epic)

        epic_ids_with_children = set(epic_hierarchy.keys())

        # Orphan: no parent AND no children — completely disconnected from the hierarchy
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
                epic_type = next((t for t in ("Epic", "Capability", "Feature") if t in epic.labels), "Unknown")
                icon      = self.EPIC_TYPE_ICONS.get(epic_type, "❓")
                title_link = f"[{epic.title}]({epic.web_url})"
                md.append(f"| {icon} {epic_type} | {title_link} | {epic.state.capitalize()} |")

        self.upload_to_wiki(group, f"{group.name} - Orphaned Epics Report", "\n".join(md))


    def generate_orphan_issues_report(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"Generating orphan issues report for {group.name}...")

        # Collect issues with no epic, grouped by project
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
        print(f"  Generating Unassigned PI Report...")

        all_epics = group.epics.list(all=True)

        # Build parent id → title map for showing hierarchy position.
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

        md.append("---")
        md.append("## Legend")
        md.append("- **🏆 Epic** — a Portfolio-level initiative that may span multiple Program Increments (PIs) and Agile Release Trains (ARTs)")
        md.append("- **🧩 Capability** — a Large Solution-level deliverable decomposed from an Epic; sized to fit within a PI across one or more ARTs")
        md.append("- **🛠️ Feature** — a service or function delivered by a single ART within one PI; directly enables business or technical outcomes")
        md.append("- **Parent**: the direct parent epic in the hierarchy, if one exists")
        md.append("- Items with no parent and no children are also captured by the Orphaned Epics report")
        md.append("")

        self.upload_to_wiki(group, f"{group.name} - Unassigned PI Report", "\n".join(md))


    def generate_all_reports(self):
        group = self.get_group_by_name(self.parent_group)
        print(f"\nGenerating reports for group: {group.full_path}\n")

        print("[1/4] SAFe Portfolio Report")
        self.generate_portfolio_report(group)

        print("[2/4] Blocking Relationships Report")
        self.generate_blocking_report()

        print("[3/4] ART/Team Workload Report")
        self.generate_workload_report()

        print("[4/4] Unassigned PI Report")
        self.generate_unassigned_pi_report()

        print("\nAll reports uploaded to wiki.")



# Main
def main():
    parser = argparse.ArgumentParser(description="NCE GitLab SAFe tooling")
    parser.add_argument("--clean",  action="store_true", help="Delete all group data")
    parser.add_argument("--create", action="store_true", help="Bootstrap lorem SAFe data")
    parser.add_argument("--report", action="store_true", help="Generate all reports")
    parser.add_argument("--all",    action="store_true", help="Run clean, create, and report in sequence")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        return

    gl = NceGitLab()

    if args.all or args.clean:
        gl.cleanup_group()
    if args.all or args.create:
        gl.create_all_lorem_objects()
    if args.all or args.report:
        gl.generate_all_reports()


if __name__ == "__main__":
    main()

