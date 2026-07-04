"""Blocked-chain analysis over report snapshots (epic #165, issue #168).

Pure disk reads — joins a snapshot's ``blocking.json`` relationships with
``epics.json``, reconstructs each full hierarchy chain (Portfolio Epic →
Capability → Feature → blocked item) by walking ``parent_id``, and rolls up
the weight and Business Value of blocked work per portfolio epic.

Rollup semantics (mirrors how the WSJF board treats at-risk value):
- A blocked item counts toward *every* portfolio epic it threatens, so each
  portfolio epic's rollup reflects its own exposure.
- Grand totals dedupe blocked items, so the portfolio-wide numbers are not
  inflated when one blocked item threatens several portfolio epics.
- ``blocked_weight`` prefers ``planned_weight`` and falls back to
  ``actual_weight``; missing values contribute 0. ``business_value`` of
  ``null`` likewise contributes 0.
"""

import json
from pathlib import Path

# Epic fields copied into API responses — the UI card/tree needs these and
# nothing else (descriptions in particular can be huge).
_EPIC_FIELDS = (
    "id", "iid", "title", "state", "type", "web_url", "labels", "piid",
    "planned_weight", "actual_weight", "business_value", "pct_complete",
)


def _slim(epic, blocked=False):
    out = {k: epic.get(k) for k in _EPIC_FIELDS}
    out["blocked"] = blocked
    return out


def _blocked_value(epic):
    """Weight a blocked item contributes: planned, else actual, else 0."""
    w = epic.get("planned_weight")
    if w is None:
        w = epic.get("actual_weight")
    return w or 0


def load_snapshot(data_dir: Path):
    """Load epics + blocking graph from a snapshot data/ directory."""
    epics_doc = json.loads((data_dir / "epics.json").read_text())
    epics_by_id = {e["id"]: e for e in epics_doc.get("epics", [])}
    blocking_path = data_dir / "blocking.json"
    blocking = (
        json.loads(blocking_path.read_text()) if blocking_path.is_file() else {}
    )
    return epics_by_id, blocking, epics_doc.get("generated_at")


def _chain_nodes(epics_by_id, blocked_id, portfolio_id):
    """Walk parent_id from the blocked item up to the portfolio epic.

    Returns the chain top-down ([portfolio, ..., blocked]), or None when the
    walk can't reach the ancestor (stale snapshot, missing epic, cycle).
    """
    chain = []
    seen = set()
    cur = blocked_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        epic = epics_by_id.get(cur)
        if epic is None:
            return None
        chain.append(epic)
        if cur == portfolio_id:
            chain.reverse()
            return chain
        cur = epic.get("parent_id")
    return None


def build_blocked_chains(epics_by_id, blocking):
    """Compute the /api/analysis/blocked-chains payload body."""
    per_portfolio = {}       # portfolio id -> {"epic", "chains", blocked ids}
    all_blocked_ids = set()  # distinct blocked items for deduped grand totals

    for rel in blocking.get("relationships", []):
        blocked_id = rel.get("blocked_epic", {}).get("id_int")
        blocked = epics_by_id.get(blocked_id)
        if blocked is None:
            continue

        blockers = [
            {
                "id": b.get("id_int"),
                "title": b.get("title"),
                "type": b.get("type"),
                "web_url": b.get("web_url"),
            }
            for b in rel.get("blocked_by", [])
        ]

        for ancestor in rel.get("at_risk_portfolio_epics", []):
            pid = ancestor.get("id_int")
            portfolio = epics_by_id.get(pid)
            if portfolio is None:
                continue
            nodes = _chain_nodes(epics_by_id, blocked_id, pid)
            if nodes is None:
                continue

            entry = per_portfolio.setdefault(pid, {
                "epic": _slim(portfolio),
                "chains": [],
                "_blocked_ids": set(),
            })
            entry["chains"].append({
                "nodes": [
                    _slim(n, blocked=(n["id"] == blocked_id)) for n in nodes
                ],
                "blockers": blockers,
            })
            entry["_blocked_ids"].add(blocked_id)
            all_blocked_ids.add(blocked_id)

    portfolio_epics = []
    for entry in per_portfolio.values():
        blocked_ids = entry.pop("_blocked_ids")
        entry["rollup"] = {
            "blocked_count": len(blocked_ids),
            "blocked_weight": sum(
                _blocked_value(epics_by_id[i]) for i in blocked_ids
            ),
            "blocked_business_value": sum(
                epics_by_id[i].get("business_value") or 0 for i in blocked_ids
            ),
        }
        portfolio_epics.append(entry)

    # Biggest fires first: BV at risk, then blocked weight.
    portfolio_epics.sort(
        key=lambda e: (
            e["rollup"]["blocked_business_value"],
            e["rollup"]["blocked_weight"],
        ),
        reverse=True,
    )

    return {
        "totals": {
            "portfolio_epics_at_risk": len(portfolio_epics),
            "blocked_items": len(all_blocked_ids),
            "blocked_weight": sum(
                _blocked_value(epics_by_id[i]) for i in all_blocked_ids
            ),
            "blocked_business_value": sum(
                epics_by_id[i].get("business_value") or 0
                for i in all_blocked_ids
            ),
        },
        "portfolio_epics": portfolio_epics,
    }


def blocked_chains_payload(data_dir: Path):
    """Full response for GET /api/analysis/blocked-chains."""
    epics_by_id, blocking, generated_at = load_snapshot(data_dir)
    payload = build_blocked_chains(epics_by_id, blocking)
    run_dir = data_dir.parent
    payload["snapshot"] = {
        "date": run_dir.parent.name,
        "time": run_dir.name,
        "generated_at": generated_at,
    }
    return payload
