import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import lorem


class BootstrapMixin:

    def _get_or_create_root_group(self):
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

        subgroups    = self._groups_deepest_first(group)

        print("Collecting all projects...")
        all_projects  = group.projects.list(all=True, include_subgroups=True)
        live_projects = [p for p in all_projects if '_deletion_scheduled' not in p.path]
        skipped       = len(all_projects) - len(live_projects)
        if skipped:
            print(f"  Skipping {skipped} pending-deletion project(s).")

        self.delete_all_wiki_pages(group)
        self.delete_all_group_epics(self.parent_group)
        self.delete_all_milestones(group)
        for sg in subgroups:
            self.delete_all_milestones(sg)

        print("Deleting all issues across group hierarchy...")
        for project in live_projects:
            try:
                full_project = self.gl.projects.get(project.id)
                issues       = full_project.issues.list(all=True)
                for issue in issues:
                    try:
                        issue.delete()
                    except Exception as e:
                        print(f"  Failed to delete issue #{issue.iid} in '{project.path_with_namespace}': {e}")
                if issues:
                    print(f"  Deleted {len(issues)} issues from '{project.path_with_namespace}'")
            except Exception as e:
                print(f"  Failed to fetch issues for '{project.path_with_namespace}': {e}")

        self.delete_all_labels(group)
        for sg in subgroups:
            self.delete_all_labels(sg)
        for project in live_projects:
            try:
                full_project = self.gl.projects.get(project.id)
                self.delete_all_labels(full_project)
            except Exception as e:
                print(f"  Failed to delete labels from project '{project.path_with_namespace}': {e}")

        for project in live_projects:
            try:
                self.gl.projects.delete(project.id)
                print(f"Deleted project: {project.path_with_namespace}")
            except Exception as e:
                print(f"Failed to delete project '{project.path_with_namespace}': {e}")

        for sg in subgroups:
            try:
                self.gl.groups.delete(sg.id)
                print(f"Deleted subgroup: {sg.full_path}")
            except Exception as e:
                print(f"Failed to delete subgroup '{sg.full_path}': {e}")

        try:
            self.gl.groups.delete(group.id)
            print(f"Deleted root group: {group.full_path}")
        except Exception as e:
            print(f"Failed to delete root group '{group.full_path}': {e}")

    def _groups_deepest_first(self, group):
        result = []
        for sg in group.subgroups.list(all=True):
            full_sg = self.gl.groups.get(sg.id)
            result.extend(self._groups_deepest_first(full_sg))
            result.append(full_sg)
        return result

    def _lorem_epics_in_group(self, group, count, allowed_types=None):
        def next_monday_on_or_after(d):
            while d.weekday() != 0:
                d += timedelta(days=1)
            return d

        type_pool   = allowed_types or self.EPIC_TYPE_LABELS
        weight_pool = self.EPIC_TYPE_PLANNED_WEIGHTS

        created = []
        for _ in range(count):
            piid_label    = random.choice(self.PIID_LABELS)
            epic_label    = random.choice(type_pool)
            project_label = random.choice(self.PROJECT_LABELS)

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
        epics         = self._lorem_epics_in_group(group, epic_count, allowed_types=allowed_types)
        feature_epics = [(e, lbl) for e, lbl in epics if lbl == "Feature"]
        if not feature_epics:
            return epics

        try:
            project = self.gl.projects.create({
                'name':         f"{group.name} — Team Backlog",
                'path':         f"{group.path}-backlog",
                'namespace_id': group.id,
            })
            print(f"  Team Backlog → {project.path_with_namespace}")
            milestones        = self.create_lorem_milestones(project)
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
                                  num_value_streams=None, num_arts=None, num_teams=None,
                                  portfolio_epics=None,
                                  vs_epics=None,
                                  art_epics=None,
                                  team_features=None,
                                  direct_feature_ratio=None):
        num_value_streams    = num_value_streams    if num_value_streams    is not None else self.default_num_value_streams
        num_arts             = num_arts             if num_arts             is not None else self.default_num_arts
        num_teams            = num_teams            if num_teams            is not None else self.default_num_teams
        portfolio_epics      = portfolio_epics      if portfolio_epics      is not None else self.default_portfolio_epics
        vs_epics             = vs_epics             if vs_epics             is not None else self.default_vs_caps_per_vs
        art_epics            = art_epics            if art_epics            is not None else self.default_art_caps_per_art
        team_features        = team_features        if team_features        is not None else self.default_features_per_team
        direct_feature_ratio = direct_feature_ratio if direct_feature_ratio is not None else self.default_direct_feature_ratio

        root_group = self._get_or_create_root_group()
        if root_group is None:
            return

        for label_array in [self.PROJECT_LABELS, self.PIID_LABELS, self.EPIC_TYPE_LABELS]:
            self.create_and_apply_labels(root_group, label_array)

        all_portfolio_epics = self._lorem_epics_in_group(root_group, portfolio_epics, allowed_types=["Epic"])
        print(f"Portfolio: {portfolio_epics} Epics → {root_group.full_path}")

        vis          = root_group.visibility
        all_vs_caps  = []
        all_art_caps = []
        all_features = []

        for vs in range(1, num_value_streams + 1):
            vs_group = self.gl.groups.create({
                'name':       f"Value Stream {vs:02d}",
                'path':       f"vs-{vs:02d}",
                'parent_id':  root_group.id,
                'visibility': vis,
            })
            print(f"\n[Value Stream] {vs_group.full_path}")
            vs_caps = self._lorem_epics_in_group(vs_group, vs_epics, allowed_types=["Capability"])
            all_vs_caps.extend(vs_caps)

            for a in range(1, num_arts + 1):
                art_group = self.gl.groups.create({
                    'name':       f"ART {a:02d}",
                    'path':       f"art-{a:02d}",
                    'parent_id':  vs_group.id,
                    'visibility': vis,
                })
                print(f"\n[ART] {art_group.full_path}")
                art_created = self._lorem_epics_in_group(art_group, art_epics, allowed_types=["Capability"])
                all_art_caps.extend(art_created)

                for t in range(1, num_teams + 1):
                    team_group = self.gl.groups.create({
                        'name':       f"Team {t:02d}",
                        'path':       f"team-{t:02d}",
                        'parent_id':  art_group.id,
                        'visibility': vis,
                    })
                    print(f"\n[Agile Team] {team_group.full_path}")
                    team_created = self._lorem_populate_group(team_group, team_features, allowed_types=["Feature"])
                    if team_created:
                        all_features.extend(team_created)

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
        _link_to_parents(all_vs_caps, all_portfolio_epics)
        _link_to_parents(all_art_caps, all_vs_caps)

        # Split Features: majority direct to Portfolio Epics, minority via Capability chain
        random.shuffle(all_features)
        split           = max(1, round(len(all_features) * direct_feature_ratio)) if all_features else 0
        direct_features = all_features[:split]
        cap_features    = all_features[split:]
        print(f"\nFeature routing: {len(direct_features)} direct → Epic  |  {len(cap_features)} via Capability chain  ({int(direct_feature_ratio*100)}% direct)")
        _link_to_parents(direct_features, all_portfolio_epics)
        _link_to_parents(cap_features,    all_art_caps)
