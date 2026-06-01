import re
import time
import requests
from collections import defaultdict
from datetime import date, datetime
from pprint import pformat


def _fmt_duration(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


class UtilitiesMixin:

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

    def _fetch_wi_supplement(self, group, epics):
        """Use the work-items REST endpoints to correct two gaps in the classic API:

        1. Direct issue weights — groups/:id/epics/:iid/issues captures issues linked
           via the work-items UI that never populate issue.epic on the issue object.
        2. Cross-group child epics — groups/:id/epics/:iid/epics returns children that
           live outside the portfolio group hierarchy; these are invisible to
           group.epics.list(all=True) and are therefore missing from the hierarchy and
           rollup.

        Returns:
            direct_weights  {epic_id: (total_w, closed_w)}
            extra_epics     list of associated_data dicts for cross-group children
            wi_children     {parent_epic_id: [child_epic_id, ...]}
        """
        import requests as _req
        sess = _req.Session()
        sess.headers["PRIVATE-TOKEN"] = self.private_token

        known_ids      = {e.id for e in epics}
        direct_weights = {}
        wi_children    = {}
        extra_raw      = {}   # id → REST dict for cross-group children

        total = len(epics)
        print(f"  Fetching direct issue weights (epics/issues) for {total} epics...")
        for epic in epics:
            url    = f"{self.url}/api/v4/groups/{epic.group_id}/epics/{epic.iid}/issues"
            issues = []
            while url:
                try:
                    resp = sess.get(url, params={"per_page": 100})
                    if not resp.ok:
                        break
                    issues.extend(resp.json())
                    url = resp.links.get("next", {}).get("url")
                except Exception:
                    break
            total_w  = sum(i.get("weight") or 0 for i in issues)
            closed_w = sum(i.get("weight") or 0 for i in issues
                          if i.get("state") == "closed")
            direct_weights[epic.id] = (total_w, closed_w)

        print(f"  Checking for cross-group child epics (epics/epics)...")
        for epic in epics:
            if "Feature" in set(epic.labels):
                continue   # Features are leaves; no child epics
            url      = f"{self.url}/api/v4/groups/{epic.group_id}/epics/{epic.iid}/epics"
            children = []
            while url:
                try:
                    resp = sess.get(url, params={"per_page": 100})
                    if not resp.ok:
                        break
                    children.extend(resp.json())
                    url = resp.links.get("next", {}).get("url")
                except Exception:
                    break
            if children:
                wi_children[epic.id] = [c["id"] for c in children]
                for child in children:
                    cid = child["id"]
                    if cid not in known_ids and cid not in extra_raw:
                        extra_raw[cid] = child

        extra_epics = []
        if extra_raw:
            print(f"  Fetching data for {len(extra_raw)} cross-group child epic(s)...")
        for child_dict in extra_raw.values():
            cid  = child_dict["id"]
            giid = child_dict["iid"]
            grp  = child_dict.get("group_id")
            labels = child_dict.get("labels", [])
            etype  = next((t for t in ["Epic", "Capability", "Feature"] if t in labels), None)
            if not etype:
                continue

            # Issues for this cross-group child
            url    = f"{self.url}/api/v4/groups/{grp}/epics/{giid}/issues"
            issues = []
            while url:
                try:
                    resp = sess.get(url, params={"per_page": 100})
                    if not resp.ok:
                        break
                    issues.extend(resp.json())
                    url = resp.links.get("next", {}).get("url")
                except Exception:
                    break
            total_w  = sum(i.get("weight") or 0 for i in issues)
            closed_w = sum(i.get("weight") or 0 for i in issues
                          if i.get("state") == "closed")
            direct_weights[cid] = (total_w, closed_w)

            piid     = next((l for l in labels if l.startswith("PIID::")), None)
            pct_pi   = self._pct_through_pi(piid)
            pct_done = (round(closed_w / total_w * 100) if total_w > 0
                        else (100 if child_dict.get("state", "").lower() == "closed" else 0))

            extra_epics.append({
                "id":               cid,
                "iid":              giid,
                "title":            child_dict.get("title", ""),
                "description":      child_dict.get("description"),
                "state":            child_dict.get("state", "opened").capitalize(),
                "blocked_by_count": 0,
                "blocks_count":     0,
                "web_url":          child_dict.get("web_url", ""),
                "labels":           labels,
                "parent_id":        child_dict.get("parent_id"),
                "group_id":         grp,
                "planned_weight":   child_dict.get("weight") or 0,
                "actual_weight":    total_w,
                "pct_complete":     pct_done,
                "pct_through_pi":   pct_pi,
                "piid":             piid,
                "start_date":       child_dict.get("start_date"),
                "due_date":         child_dict.get("due_date"),
                "created_at":       child_dict.get("created_at"),
                "updated_at":       child_dict.get("updated_at"),
                "type":             etype,
                "is_cross_group":   True,
            })

        return direct_weights, extra_epics, wi_children

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

    def _discover_labels(self, group, prefix):
        """Return sorted list of label names that exist on the group and start with prefix."""
        return sorted(l.name for l in group.labels.list(all=True) if l.name.startswith(prefix))

    def calculate_portfolio_metrics(self, group_name):
        if hasattr(self, '_metrics_cache') and group_name in self._metrics_cache:
            return self._metrics_cache[group_name]

        group = self.get_group_by_name(group_name)
        if not group:
            print(f"Group '{group_name}' not found.")
            return {}

        gql_data = self.graphql_query(
            """
            query EpicBlockCounts($fullPath: ID!) {
              group(fullPath: $fullPath) {
                epics {
                  nodes { webUrl blocked blockedByCount blockingCount }
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

        print("  Fetching issues...")
        issues_by_epic_id  = defaultdict(list)
        all_issues_snapshot = []
        for project in group.projects.list(all=True, include_subgroups=True):
            try:
                full_project = self.gl.projects.get(project.id)
                for issue in full_project.issues.list(all=True):
                    epic_info = getattr(issue, 'epic', None)
                    if epic_info and epic_info.get('id'):
                        issues_by_epic_id[epic_info['id']].append(issue)
                    all_issues_snapshot.append({
                        "id":           issue.id,
                        "iid":          issue.iid,
                        "title":        issue.title,
                        "description":  getattr(issue, 'description', None),
                        "state":        issue.state,
                        "labels":       getattr(issue, 'labels', []),
                        "weight":       getattr(issue, 'weight', None),
                        "milestone":    issue.milestone['title'] if issue.milestone else None,
                        "assignees":    [a['username'] for a in getattr(issue, 'assignees', [])],
                        "epic_id":      epic_info['id']  if epic_info else None,
                        "epic_iid":     epic_info['iid'] if epic_info else None,
                        "project_path": project.path_with_namespace,
                        "web_url":      issue.web_url,
                        "created_at":   getattr(issue, 'created_at', None),
                        "updated_at":   getattr(issue, 'updated_at', None),
                        "closed_at":    getattr(issue, 'closed_at', None),
                    })
            except Exception as e:
                print(f"  Failed to fetch issues for '{project.name}': {e}")

        all_epics = group.epics.list(all=True)
        epic_weights = self._fetch_epic_weights(all_epics)
        metrics       = {"Epic": [], "Capability": [], "Feature": []}
        all_epics_raw = []

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

            piid   = next((l for l in epic.labels if l.startswith("PIID::")), None)
            pct_pi = self._pct_through_pi(piid)

            associated_data = {
                "id":               epic.id,
                "iid":              epic.iid,
                "title":            epic.title,
                "description":      getattr(epic, 'description', None),
                "state":            epic.state.capitalize(),
                "blocked_by_count": gql.get("blockedByCount") or (1 if gql.get("blocked") else 0),
                "blocks_count":     gql.get("blockingCount", 0),
                "web_url":          epic.web_url,
                "labels":           epic.labels,
                "parent_id":        getattr(epic, 'parent_id', None),
                "group_id":         getattr(epic, 'group_id', None),
                "planned_weight":   epic_weights.get(epic.web_url, 0),
                "actual_weight":    total_w,
                "pct_complete":     pct_done,
                "pct_through_pi":   pct_pi,
                "piid":             piid,
                "start_date":       getattr(epic, 'start_date', None),
                "due_date":         getattr(epic, 'due_date', None),
                "created_at":       getattr(epic, 'created_at', None),
                "updated_at":       getattr(epic, 'updated_at', None),
            }

            if "Epic" in epic.labels:
                epic_type = "Epic"
            elif "Capability" in epic.labels:
                epic_type = "Capability"
            elif "Feature" in epic.labels:
                epic_type = "Feature"
            else:
                print(f"Skipping epic '{epic.title}' — no matching type label.")
                all_epics_raw.append(associated_data)
                continue

            associated_data["type"] = epic_type
            metrics[epic_type].append(associated_data)
            all_epics_raw.append(associated_data)

        # Supplement with work-items hierarchy data (Refs #14)
        direct_weights, extra_epics, wi_children = self._fetch_wi_supplement(group, all_epics)

        # Replace actual_weight / pct_complete with the authoritative epics/issues values
        for etype_list in metrics.values():
            for e in etype_list:
                tw, cw = direct_weights.get(e["id"], (None, None))
                if tw is None:
                    continue
                e["actual_weight"] = tw
                if tw > 0:
                    e["pct_complete"] = round(cw / tw * 100)
                elif e["state"] == "Closed":
                    e["pct_complete"] = 100
                else:
                    e["pct_complete"] = 0

        # Inject cross-group child epics into metrics so the rollup can reach them
        for extra in extra_epics:
            metrics[extra["type"]].append(extra)
            all_epics_raw.append(extra)

        # Build hierarchy — prefer wi_children (correct for WI-linked relationships),
        # fall back to parent_id for epics not covered by the epics/epics endpoint
        id_to_meta      = {e["id"]: e for etype in metrics.values() for e in etype}
        covered_as_child = set()

        hierarchy = defaultdict(list)
        for parent_id, child_ids in wi_children.items():
            for cid in child_ids:
                child_meta = id_to_meta.get(cid)
                if child_meta:
                    hierarchy[parent_id].append(child_meta)
                    covered_as_child.add(cid)

        for etype in metrics.values():
            for e in etype:
                if e["id"] not in covered_as_child and e.get("parent_id") is not None:
                    if e["parent_id"] in id_to_meta:
                        hierarchy[e["parent_id"]].append(e)

        def rollup_pct(e):
            children = hierarchy.get(e["id"], [])
            if not children:
                return e["pct_complete"]
            return round(sum(rollup_pct(c) for c in children) / len(children))

        def rollup_actual(e):
            children = hierarchy.get(e["id"], [])
            return e["actual_weight"] + sum(rollup_actual(c) for c in children)

        for cap in metrics["Capability"]:
            cap["pct_complete"]  = rollup_pct(cap)
            cap["actual_weight"] = rollup_actual(cap)
        for ep in metrics["Epic"]:
            ep["pct_complete"]  = rollup_pct(ep)
            ep["actual_weight"] = rollup_actual(ep)

        if not hasattr(self, '_metrics_cache'):
            self._metrics_cache = {}
        self._metrics_cache[group_name] = metrics

        if not hasattr(self, '_issues_cache'):
            self._issues_cache = {}
        self._issues_cache[group_name] = all_issues_snapshot

        if not hasattr(self, '_all_epics_cache'):
            self._all_epics_cache = {}
        self._all_epics_cache[group_name] = all_epics_raw

        return metrics

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

    def _print_timing_table(self, phases, title=""):
        """Print a formatted timing table.

        phases: list of (label, start_datetime, end_datetime, elapsed_seconds)
        """
        if not phases:
            return
        W = 62
        print()
        print("─" * W)
        if title:
            print(f"  {title}")
        print(f"  {'Phase':<26} {'Started':>8}  {'Finished':>8}  {'Duration':>9}")
        print(f"  {'─'*26} {'─'*8}  {'─'*8}  {'─'*9}")
        for label, start, end, elapsed in phases:
            print(f"  {label:<26} {start.strftime('%H:%M:%S'):>8}  {end.strftime('%H:%M:%S'):>8}  {_fmt_duration(elapsed):>9}")
        if len(phases) > 1:
            wall = (phases[-1][2] - phases[0][1]).total_seconds()
            print(f"  {'─'*26} {'─'*8}  {'─'*8}  {'─'*9}")
            print(f"  {'TOTAL':<26} {phases[0][1].strftime('%H:%M:%S'):>8}  {phases[-1][2].strftime('%H:%M:%S'):>8}  {_fmt_duration(wall):>9}")
        print("─" * W)

    def sanitize_name(self, name):
        return re.sub(r'[^a-z0-9\-]', '', name.lower().replace(' ', '-'))

    def truncate_text(self, text, max_length=20):
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text

    def pprint_obj_attrs(self, obj):
        try:
            if not hasattr(obj, "attributes"):
                return "The provided object does not have 'attributes'. Please provide a valid obj object."
            print(pformat(obj.attributes))
        except Exception as e:
            return f"Error retrieving obj attributes: {e}"
