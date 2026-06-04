import random
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

import lorem


def _resolve_range(val):
    """Return an int from a scalar, {desired}, or {min, max} config value."""
    if isinstance(val, dict):
        if "desired" in val:
            return int(val["desired"])
        lo = int(val.get("min", 1))
        hi = int(val.get("max", lo))
        return random.randint(min(lo, hi), max(lo, hi))
    return int(val)


def _range_label(cfg_val, resolved):
    """Human-readable label showing how resolved came from cfg_val."""
    if isinstance(cfg_val, dict):
        if "desired" in cfg_val:
            return f"{resolved}  (desired)"
        lo = cfg_val.get("min", "?")
        hi = cfg_val.get("max", "?")
        return f"{resolved}  (random {lo}–{hi})"
    return str(resolved)


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

        print(f"Deleting all issues across group hierarchy ({self.delete_workers} workers)...")

        def _delete_project_issues(project):
            full_project = self.gl.projects.get(project.id)
            issues       = full_project.issues.list(all=True)
            for issue in issues:
                issue.delete()
            if issues:
                print(f"  Deleted {len(issues)} issues from '{project.path_with_namespace}'")

        self._parallel_delete(live_projects, _delete_project_issues)

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

    def _weighted_piid_label(self):
        """Draw a PIID label weighted 65% past / 20% current / 15% future."""
        today = date.today()
        past, current, future = [], [], []
        for p in self.PIID_LABELS:
            start, end = self._pi_dates_from_label(p)
            if start is None:
                future.append(p)
            elif end < today:
                past.append(p)
            elif start <= today <= end:
                current.append(p)
            else:
                future.append(p)
        buckets = [(past, 0.65), (current, 0.20), (future, 0.15)]
        buckets = [(b, w) for b, w in buckets if b]
        if not buckets:
            return random.choice(self.PIID_LABELS)
        total = sum(w for _, w in buckets)
        populations, weights = zip(*buckets)
        chosen = random.choices(populations, weights=[w / total for w in weights])[0]
        return random.choice(chosen)

    def _lorem_epics_in_group(self, group, count, allowed_types=None):
        def next_monday_on_or_after(d):
            while d.weekday() != 0:
                d += timedelta(days=1)
            return d

        type_pool   = allowed_types or self.EPIC_TYPE_LABELS
        weight_pool = self.EPIC_TYPE_PLANNED_WEIGHTS

        created = []
        for _ in range(count):
            piid_label    = self._weighted_piid_label()
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

            lorem_title = lorem.sentence().rstrip('.')
            epic = group.epics.create({
                'title':       lorem_title,
                'description': lorem.paragraph(),
                'start_date':  start.isoformat(),
                'due_date':    due.isoformat(),
                'labels':      [project_label, piid_label, epic_label],
            })
            group.epics.update(epic.iid, {'title': f"{epic.iid} - {lorem_title}"})
            self._set_epic_weight(epic, weight)

            # Set a random Business Value if the custom field is configured
            bv_field   = getattr(self, "_bv_field_gid",   None)
            bv_options = getattr(self, "_bv_option_gids",  [])
            if bv_field and bv_options:
                wid = getattr(epic, "work_item_id", None)
                if wid:
                    self._set_work_item_business_value(wid, bv_field, random.choice(bv_options))

            print(f"  Epic {epic.iid} [{epic_label}] w={weight} → {group.full_path}")
            created.append((epic, epic_label))

        return created

    def _link_risk_to_epic(self, risk_issue, epic, project):
        """Create a 'relates to' work-item link between a risk issue and the epic it threatens."""
        wi_id = getattr(epic, 'work_item_id', None)
        if not wi_id:
            try:
                import requests as _req
                resp = _req.get(
                    f"{self.url}/api/v4/groups/{epic.group_id}/epics/{epic.iid}",
                    headers={"PRIVATE-TOKEN": self.private_token},
                )
                if resp.ok:
                    wi_id = resp.json().get("work_item_id")
            except Exception:
                pass
        if not wi_id:
            return
        # Traditional issues expose their global id via .id; use it as the work item GID
        risk_gid = f"gid://gitlab/WorkItem/{risk_issue.id}"
        epic_gid = f"gid://gitlab/WorkItem/{wi_id}"
        mutation = """
        mutation LinkRisk($epicGid: WorkItemID!, $riskGid: WorkItemID!) {
          workItemAddLinkedItems(input: {
            id: $riskGid
            workItemsIds: [$epicGid]
            linkType: RELATED
          }) {
            workItem { id }
            errors
          }
        }
        """
        result   = self.graphql_query(mutation, variables={"epicGid": epic_gid, "riskGid": risk_gid})
        if result:
            errors = result.get("workItemAddLinkedItems", {}).get("errors", [])
            if errors:
                print(f"      Link warning: {errors}")

    def _lorem_issues_in_project(self, project, count):
        issues = []
        for _ in range(count):
            lorem_title = lorem.sentence().rstrip('.')
            issue = project.issues.create({
                'title':       lorem_title,
                'description': lorem.paragraph(),
                'weight':      random.choice(self.fibonacci_weights),
            })
            project.issues.update(issue.iid, {'title': f"{issue.iid} - {lorem_title}"})
            print(f"  Issue #{issue.iid} → {project.path_with_namespace}")
            issues.append(issue)
        return issues

    def _lorem_populate_group(self, group, epic_count, allowed_types=None):
        epics         = self._lorem_epics_in_group(group, epic_count, allowed_types=allowed_types)
        feature_epics = [(e, lbl) for e, lbl in epics if lbl == "Feature"]
        if not feature_epics:
            return epics, None

        project = None
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
                    ms          = random.choice(milestones) if milestones else None
                    lorem_title = lorem.sentence().rstrip('.')
                    issue = project.issues.create({
                        'title':        lorem_title,
                        'description':  lorem.paragraph(),
                        'weight':       random.choice(issue_weight_pool),
                        'milestone_id': ms.id if ms else None,
                    })
                    project.issues.update(issue.iid, {
                        'title':   f"{issue.iid} - {lorem_title}",
                        'epic_id': feature_epic.id,
                    })

                print(f"    {total_stories} stories → Feature #{feature_epic.iid}")

                # Create 0–2 ROAM risk issues linked to this Feature (Refs #10)
                roam_labels = getattr(self, 'ROAM_LABELS', [])
                if roam_labels:
                    num_risks = random.choices([0, 1, 2], weights=[50, 35, 15])[0]
                    for _ in range(num_risks):
                        roam_label  = random.choice(roam_labels)
                        lorem_title = lorem.sentence().rstrip('.')
                        risk_issue = project.issues.create({
                            'title':       f"Risk: {lorem_title}",
                            'description': lorem.paragraph(),
                            'labels':      [roam_label],
                        })
                        project.issues.update(risk_issue.iid, {'title': f"Risk {risk_issue.iid} - {lorem_title}"})
                        self._link_risk_to_epic(risk_issue, feature_epic, project)
                        print(f"    Risk issue #{risk_issue.iid} [{roam_label}] → Feature #{feature_epic.iid}")

        except Exception as e:
            print(f"  Skipping team backlog for '{group.full_path}': {e}")

        return epics, project

    def create_all_lorem_objects(self,
                                  num_value_streams=None, num_arts=None, num_teams=None,
                                  portfolio_epics=None,
                                  vs_epics=None,
                                  art_epics=None,
                                  team_features=None,
                                  direct_feature_ratio=None):
        _cfg_vs    = num_value_streams if num_value_streams is not None else self.default_num_value_streams
        _cfg_arts  = num_arts          if num_arts          is not None else self.default_num_arts
        _cfg_teams = num_teams         if num_teams         is not None else self.default_num_teams
        _cfg_pe    = portfolio_epics   if portfolio_epics   is not None else self.default_portfolio_epics
        _cfg_vsc   = vs_epics          if vs_epics          is not None else self.default_vs_caps_per_vs
        _cfg_artc  = art_epics         if art_epics         is not None else self.default_art_caps_per_art
        _cfg_tf    = team_features     if team_features     is not None else self.default_features_per_team

        num_value_streams    = _resolve_range(_cfg_vs)
        num_arts             = _resolve_range(_cfg_arts)
        num_teams            = _resolve_range(_cfg_teams)
        portfolio_epics      = _resolve_range(_cfg_pe)
        vs_epics             = _resolve_range(_cfg_vsc)
        art_epics            = _resolve_range(_cfg_artc)
        team_features        = _resolve_range(_cfg_tf)
        direct_feature_ratio = direct_feature_ratio if direct_feature_ratio is not None else self.default_direct_feature_ratio

        print("\nSAFe structure (resolved):")
        print(f"  Value Streams      : {_range_label(_cfg_vs,    num_value_streams)}")
        print(f"  ARTs / VS          : {_range_label(_cfg_arts,  num_arts)}")
        print(f"  Teams / ART        : {_range_label(_cfg_teams, num_teams)}")
        print(f"  Portfolio Epics    : {_range_label(_cfg_pe,    portfolio_epics)}")
        print(f"  VS Capabilities    : {_range_label(_cfg_vsc,   vs_epics)}")
        print(f"  ART Capabilities   : {_range_label(_cfg_artc,  art_epics)}")
        print(f"  Features / Team    : {_range_label(_cfg_tf,    team_features)}")
        print(f"  Direct feature %   : {int(direct_feature_ratio * 100)}%")
        print()

        root_group = self._get_or_create_root_group()
        if root_group is None:
            return

        # Ensure Business Value custom field exists, then cache its option GIDs for
        # use during epic creation so each epic gets a random Fibonacci value.
        print("\nSetting up custom fields...")
        self._ensure_business_value_field(interactive=False)
        self._bv_field_gid   = None
        self._bv_option_gids = []
        if self.gitlab_namespace:
            _fields = self._fetch_custom_fields(self.gitlab_namespace)
            _bv     = next((f for f in _fields if f["name"] == self.BUSINESS_VALUE_FIELD["name"]), None)
            if _bv:
                self._bv_field_gid   = _bv["id"]
                self._bv_option_gids = [o["id"] for o in (_bv.get("selectOptions") or []) if o.get("id")]
        print()

        for label_array in [self.PROJECT_LABELS, self.PIID_LABELS, self.EPIC_TYPE_LABELS, self.RISK_LABELS, self.ROAM_LABELS, self.WSJF_LABELS, self.WORK_TYPE_LABELS, self.LIFECYCLE_LABELS]:
            self.create_and_apply_labels(root_group, label_array)

        all_portfolio_epics = self._lorem_epics_in_group(root_group, portfolio_epics, allowed_types=["Epic"])
        print(f"Portfolio: {portfolio_epics} Epics → {root_group.full_path}")

        vis          = root_group.visibility
        all_vs_caps  = []
        all_art_caps = []
        all_features = []

        vs_counter    = 0  # global so each VS has a unique name/path
        art_counter   = 0  # global across all VSs so each ART has a unique name/path
        team_counter  = 0  # global across all ARTs so each Team has a unique name/path
        art_items_map = {}  # art_group.id → {art, epics, team_projects} for history simulation
        for _ in range(num_value_streams):
            vs_counter += 1
            vs_group = self.gl.groups.create({
                'name':       f"Value Stream {vs_counter:02d}",
                'path':       f"vs-{vs_counter:02d}",
                'parent_id':  root_group.id,
                'visibility': vis,
            })
            print(f"\n[Value Stream] {vs_group.full_path}")
            vs_caps = self._lorem_epics_in_group(vs_group, vs_epics, allowed_types=["Capability"])
            all_vs_caps.extend(vs_caps)

            for _ in range(num_arts):
                art_counter += 1
                art_group = self.gl.groups.create({
                    'name':       f"ART {art_counter:02d}",
                    'path':       f"art-{art_counter:02d}",
                    'parent_id':  vs_group.id,
                    'visibility': vis,
                })
                print(f"\n[ART] {art_group.full_path}")
                art_created = self._lorem_epics_in_group(art_group, art_epics, allowed_types=["Capability"])
                all_art_caps.extend(art_created)
                art_items_map[art_group.id] = {
                    "art":          art_group,
                    "epics":        list(art_created),
                    "team_projects": [],
                }

                for _ in range(num_teams):
                    team_counter += 1
                    team_group = self.gl.groups.create({
                        'name':       f"Team {team_counter:02d}",
                        'path':       f"team-{team_counter:02d}",
                        'parent_id':  art_group.id,
                        'visibility': vis,
                    })
                    print(f"\n[Agile Team] {team_group.full_path}")
                    team_created, team_project = self._lorem_populate_group(team_group, team_features, allowed_types=["Feature"])
                    if team_created:
                        all_features.extend(team_created)
                        art_items_map[art_group.id]["epics"].extend(team_created)
                    if team_project:
                        art_items_map[art_group.id]["team_projects"].append(team_project)

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

        self._simulate_history(art_items_map)

    def _simulate_history(self, art_items_map):
        """Close past-PI epics per ART at a realistic reliability rate; partially close current-PI issues."""
        today = date.today()

        past_piids    = [p for p in self.PIID_LABELS
                         if (lambda s, e: e is not None and e < today)(*self._pi_dates_from_label(p))]
        current_piids = [p for p in self.PIID_LABELS
                         if (lambda s, e: s is not None and s <= today <= e)(*self._pi_dates_from_label(p))]

        if not past_piids and not current_piids:
            print("\nNo past or current PIIDs configured — skipping history simulation.")
            return

        rate_min = self.default_history_close_rate_min
        rate_max = self.default_history_close_rate_max
        curr_pct = self.default_current_pi_issue_close_pct

        # Each ART gets a stable base reliability for the entire run
        reliabilities = {aid: random.uniform(rate_min, rate_max) for aid in art_items_map}

        print("\n--- Historical PI close simulation ---")
        for aid, data in art_items_map.items():
            print(f"  {data['art'].name}: base reliability {reliabilities[aid]:.0%}")

        # Past PIs: close epics per ART at base ± 10%, then close child issues of closed epics
        if past_piids:
            print()
            for aid, data in art_items_map.items():
                reliability = reliabilities[aid]
                projects    = data["team_projects"]

                for piid in past_piids:
                    pi_epics = [e for e, _ in data["epics"] if piid in getattr(e, 'labels', [])]
                    if not pi_epics:
                        continue

                    rate      = min(1.0, max(0.5, reliability + random.uniform(-0.10, 0.10)))
                    n_close   = round(len(pi_epics) * rate)
                    to_close  = random.sample(pi_epics, n_close)
                    closed_ids = set()

                    for epic in to_close:
                        try:
                            epic.state_event = 'close'
                            epic.save()
                            closed_ids.add(epic.id)
                        except Exception as exc:
                            print(f"    Warning: could not close epic {getattr(epic, 'iid', '?')}: {exc}")

                    # Close issues whose parent feature epic was closed
                    for project in projects:
                        try:
                            for issue in project.issues.list(state='opened', all=True):
                                epic_info = getattr(issue, 'epic', None)
                                if isinstance(epic_info, dict) and epic_info.get('id') in closed_ids:
                                    issue.state_event = 'close'
                                    issue.save()
                        except Exception as exc:
                            print(f"    Warning: issue close error in {project.name}: {exc}")

                    print(f"  {data['art'].name} / {piid}: closed {len(to_close)}/{len(pi_epics)} epics ({rate:.0%})")

        # Current PI: partially close issues only — epics stay open to drive health dashboard flags
        if current_piids and curr_pct > 0:
            print(f"\n--- Current PI: closing {curr_pct:.0%} of issues (epics stay open) ---")
            for data in art_items_map.values():
                for project in data["team_projects"]:
                    try:
                        open_issues = project.issues.list(state='opened', all=True)
                        n_close     = round(len(open_issues) * curr_pct)
                        for issue in random.sample(open_issues, min(n_close, len(open_issues))):
                            issue.state_event = 'close'
                            issue.save()
                        print(f"  {project.name}: closed {n_close}/{len(open_issues)} issues")
                    except Exception as exc:
                        print(f"  Warning: issue close error in {project.name}: {exc}")

    def create_safe_hierarchy(self, target_path=None):
        if target_path is None:
            default = self.parent_group
            print(f"\nScaffold SAFe hierarchy")
            print(f"  Default target: {default}")
            raw = input(f"  Group path [press Enter for '{default}']: ").strip()
            target_path = raw if raw else default

        # Resolve target group — try full path first, then by name
        target_group = None
        try:
            target_group = self.gl.groups.get(target_path)
        except Exception:
            pass

        if target_group is None:
            target_group = self.get_group_by_name(target_path)

        if target_group is None:
            if target_path == self.parent_group:
                target_group = self._get_or_create_root_group()
            else:
                parent = self.get_group_by_name(self.parent_group)
                if parent is not None and "/" not in target_path:
                    path_slug = target_path.lower().replace(" ", "-")
                    try:
                        target_group = self.gl.groups.create({
                            'name':       target_path,
                            'path':       path_slug,
                            'parent_id':  parent.id,
                            'visibility': parent.visibility,
                        })
                        print(f"  Created target group: {target_group.full_path}")
                    except Exception as e:
                        print(f"  Failed to create group '{target_path}' under '{parent.full_path}': {e}")
                        return
                else:
                    print(f"  Group '{target_path}' not found. Aborting scaffold.")
                    return

        if target_group is None:
            return

        _cfg_vs    = self.default_num_value_streams
        _cfg_arts  = self.default_num_arts
        _cfg_teams = self.default_num_teams

        num_vs    = _resolve_range(_cfg_vs)
        num_arts  = _resolve_range(_cfg_arts)
        num_teams = _resolve_range(_cfg_teams)

        total_teams    = num_vs * num_arts * num_teams
        total_groups   = num_vs + num_vs * num_arts + total_teams
        total_projects = total_teams

        print(f"\nScaffolding under: {target_group.full_path}")
        print(f"  Value Streams  : {_range_label(_cfg_vs,    num_vs)}")
        print(f"  ARTs / VS      : {_range_label(_cfg_arts,  num_arts)}")
        print(f"  Teams / ART    : {_range_label(_cfg_teams, num_teams)}")
        print(f"  Total groups   : {total_groups}   ({num_vs} VS + {num_vs * num_arts} ART + {total_teams} Team)")
        print(f"  Team Backlogs  : {total_projects}")
        print()

        vis          = target_group.visibility
        vs_counter   = 0  # global so each VS has a unique name/path
        art_counter  = 0  # global across all VSs so each ART has a unique name/path
        team_counter = 0  # global across all ARTs so each Team has a unique name/path

        for _ in range(num_vs):
            vs_counter += 1
            vs_group = self.gl.groups.create({
                'name':       f"Value Stream {vs_counter:02d}",
                'path':       f"vs-{vs_counter:02d}",
                'parent_id':  target_group.id,
                'visibility': vis,
            })
            print(f"  [VS]   {vs_group.full_path}")

            for _ in range(num_arts):
                art_counter += 1
                art_group = self.gl.groups.create({
                    'name':       f"ART {art_counter:02d}",
                    'path':       f"art-{art_counter:02d}",
                    'parent_id':  vs_group.id,
                    'visibility': vis,
                })
                print(f"    [ART]  {art_group.full_path}")

                for _ in range(num_teams):
                    team_counter += 1
                    team_group = self.gl.groups.create({
                        'name':       f"Team {team_counter:02d}",
                        'path':       f"team-{team_counter:02d}",
                        'parent_id':  art_group.id,
                        'visibility': vis,
                    })
                    print(f"      [Team]    {team_group.full_path}")

                    try:
                        project = self.gl.projects.create({
                            'name':         f"{team_group.name} — Team Backlog",
                            'path':         f"{team_group.path}-backlog",
                            'namespace_id': team_group.id,
                        })
                        print(f"      [Backlog]  {project.path_with_namespace}")
                    except Exception as e:
                        print(f"      Failed to create Team Backlog for '{team_group.full_path}': {e}")

        print(f"\nScaffold complete.")

        print("\nSetting up custom fields...")
        self._ensure_business_value_field(interactive=True)

    # ------------------------------------------------------------------
    # Custom field setup
    # ------------------------------------------------------------------

    def _ensure_business_value_field(self, interactive=True, dry_run=False):
        """Create or verify the Business Value custom field at the root namespace.

        Returns: "created" | "ok" | "skipped" | "overwritten"
        Raises SystemExit(0) if the user chooses to quit.
        """
        if not self.gitlab_namespace:
            print("  WARNING: gitlab_namespace not set — cannot manage custom fields.")
            return "skipped"

        cfg            = self.BUSINESS_VALUE_FIELD
        field_name     = cfg["name"]
        field_type     = cfg["field_type"]
        expected_opts  = cfg["select_options"]
        expected_set   = set(expected_opts)

        # Resolve the Epic work item type GID (needed for create/update)
        epic_type_id = self._get_epic_work_item_type_id(self.gitlab_namespace)
        if not epic_type_id:
            print("  WARNING: Could not resolve Epic work item type ID — skipping custom field setup.")
            return "skipped"

        existing = self._fetch_custom_fields(self.gitlab_namespace)
        match    = next((f for f in existing if f["name"] == field_name), None)

        if match is None:
            # Field does not exist — create it
            if dry_run:
                print(f"  DRY  Would create '{field_name}' ({field_type}) with options {expected_opts}")
                return "created"
            self._custom_field_create(
                self.gitlab_namespace, field_name, field_type,
                expected_opts, [epic_type_id],
            )
            print(f"  ✅  Created custom field '{field_name}' ({field_type}): {expected_opts}")
            return "created"

        # Field exists — check if it matches our definition
        actual_opts  = [o["value"] for o in (match.get("selectOptions") or [])]
        actual_set   = set(actual_opts)
        actual_type  = match.get("fieldType", "")
        actual_types = {wt["name"] for wt in (match.get("workItemTypes") or [])}

        type_ok    = actual_type.upper() == field_type.upper()
        options_ok = actual_set == expected_set
        types_ok   = "Epic" in actual_types

        if type_ok and options_ok and types_ok:
            print(f"  ✅  '{field_name}' already matches definition — nothing to do.")
            return "ok"

        # Mismatch — report differences
        print(f"  ⚠️   Custom field '{field_name}' exists but differs:")
        if not type_ok:
            print(f"       field_type : expected={field_type}  found={actual_type}")
        if not options_ok:
            missing = sorted(expected_set - actual_set)
            extra   = sorted(actual_set - expected_set)
            if missing:
                print(f"       missing options : {missing}")
            if extra:
                print(f"       extra options   : {extra}")
        if not types_ok:
            print(f"       work item types: expected Epic, found {sorted(actual_types)}")

        if dry_run:
            print(f"  DRY  Would update '{field_name}' to match definition.")
            return "overwritten"

        if not interactive:
            print("  Skipping (non-interactive mode).")
            return "skipped"

        print()
        print("  (o) Overwrite — update to match definition")
        print("  (s) Skip      — leave as-is and continue")
        print("  (q) Quit      — abort the current operation")
        while True:
            choice = input("  Choice [o/s/q]: ").strip().lower()
            if choice == "o":
                self._custom_field_update(match["id"], field_name, expected_opts, [epic_type_id])
                print(f"  ✅  Updated '{field_name}' to match definition.")
                return "overwritten"
            if choice == "s":
                print("  Skipping.")
                return "skipped"
            if choice == "q":
                print("  Aborting.")
                raise SystemExit(0)
            print("  Please enter o, s, or q.")
