"""
Assigns planned weights to all epics in the configured group based on their
SAFe hierarchy type label (Epic / Capability / Feature).

Each epic gets a random weight drawn from the pool for its type, as defined
in epic_type_planned_weights in nce_gitlab_config.json.

The GitLab REST API does not expose epic weight; weights are written via the
GraphQL workItemUpdate mutation instead.

Usage:
    python update_epic_weights.py [--config nce_gitlab_config.json] [--dry-run]
"""

import argparse
import json
import random
import sys
from pathlib import Path

import gitlab
import requests


SAFE_TYPES = ["Epic", "Capability", "Feature"]   # highest → lowest

MUTATION = """
mutation UpdateWeight($id: WorkItemID!, $weight: Int!) {
  workItemUpdate(input: {id: $id, weightWidget: {weight: $weight}}) {
    workItem {
      id
      widgets { ... on WorkItemWidgetWeight { weight } }
    }
    errors
  }
}
"""


def load_config(path):
    p = Path(path)
    if not p.exists():
        print(f"ERROR: config file '{path}' not found.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def epic_type(labels):
    for t in SAFE_TYPES:
        if t in labels:
            return t
    return None


def set_weight_gql(session, url, work_item_id, weight):
    gid = f"gid://gitlab/WorkItem/{work_item_id}"
    resp = session.post(
        f"{url}/api/graphql",
        json={"query": MUTATION, "variables": {"id": gid, "weight": weight}},
    )
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("workItemUpdate", {}).get("errors", [])
    if errors:
        raise RuntimeError(f"GraphQL errors: {errors}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="nce_gitlab_config.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be changed without saving")
    args = parser.parse_args()

    cfg = load_config(args.config)

    url          = cfg["url"]
    token        = cfg["private_token"]
    group_name   = cfg["group_name"]
    weight_pools = cfg.get("epic_type_planned_weights", {
        "Feature":    [20, 30, 40, 50, 60, 80, 100],
        "Capability": [100, 150, 200, 300, 400, 500],
        "Epic":       [500, 800, 1000, 1500, 2000, 3000],
    })

    gl = gitlab.Gitlab(url, private_token=token)
    gl.auth()

    groups = [g for g in gl.groups.list(search=group_name, get_all=True)
              if g.name == group_name]
    if not groups:
        print(f"ERROR: group '{group_name}' not found.")
        sys.exit(1)
    group = gl.groups.get(groups[0].id)
    print(f"Group: {group.full_path}")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })

    epics = group.epics.list(get_all=True, include_descendant_groups=True)
    print(f"Fetched {len(epics)} epics\n")

    counts  = {t: 0 for t in SAFE_TYPES}
    skipped = 0

    for epic in epics:
        etype = epic_type(epic.labels)
        if etype is None:
            print(f"  SKIP  [{epic.iid}] '{epic.title[:60]}' — no SAFe type label")
            skipped += 1
            continue

        pool = weight_pools.get(etype, [])
        if not pool:
            print(f"  SKIP  [{epic.iid}] '{epic.title[:60]}' — no weight pool for {etype}")
            skipped += 1
            continue

        weight = random.choice(pool)

        if args.dry_run:
            print(f"  DRY   [{epic.iid}] {etype:12s} weight={weight:>5}  '{epic.title[:50]}'")
        else:
            try:
                set_weight_gql(session, url, epic.work_item_id, weight)
                print(f"  SET   [{epic.iid}] {etype:12s} weight={weight:>5}  '{epic.title[:50]}'")
            except Exception as e:
                print(f"  FAIL  [{epic.iid}] '{epic.title[:50]}': {e}")
                skipped += 1
                continue

        counts[etype] += 1

    print(f"\nDone.  Updated: " +
          ", ".join(f"{t}={counts[t]}" for t in SAFE_TYPES) +
          f"  Skipped: {skipped}")
    if args.dry_run:
        print("(dry-run — no changes saved)")


if __name__ == "__main__":
    main()
