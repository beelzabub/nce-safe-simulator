"""Portfolio analysis over report snapshots (epic #165, issues #168/#169).

Pure disk reads — joins a snapshot's ``blocking.json`` relationships with
``epics.json``, reconstructs each full hierarchy chain (Portfolio Epic →
Capability → Feature → blocked item) by walking ``parent_id``, and builds a
portfolio-level view: **every** portfolio epic (the ``epic::epic`` tier,
``type == "Epic"`` in the snapshot), each with attention flags and, where
work is blocked, the chains and weight/BV rollups that quantify it.

Attention semantics:
- ``blocked`` — the epic has a blocked descendant anywhere in its chain.
- ``behind_schedule`` — open epic whose ``pct_complete`` trails
  ``pct_through_pi`` (the repo's standard At Risk rule).

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
    "planned_weight", "actual_weight", "business_value",
    "pct_complete", "pct_through_pi",
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
    """Load epics + blocking graph from a snapshot data/ directory.

    Returns the typed epics plus a raw lookup covering *every* epic —
    including untyped ones (no tier label), which chains must be able to
    traverse so a labeling slip degrades the display instead of hiding
    blocked work (#174).
    """
    epics_doc = json.loads((data_dir / "epics.json").read_text())
    epics_by_id = {e["id"]: e for e in epics_doc.get("epics", [])}
    raw_by_id = {e["id"]: e for e in epics_doc.get("all_epics_raw", [])}
    # blocking_graph.json since #172; blocking.json in older runs was
    # clobbered by the Quarto data layer (no relationships key), which the
    # .get("relationships") consumers degrade to an empty graph.
    blocking_path = data_dir / "blocking_graph.json"
    if not blocking_path.is_file():
        blocking_path = data_dir / "blocking.json"
    blocking = (
        json.loads(blocking_path.read_text()) if blocking_path.is_file() else {}
    )
    return epics_by_id, raw_by_id, blocking, epics_doc.get("generated_at")


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


def _blocked_by_portfolio(epics_by_id, blocking):
    """Group blocked chains by threatened portfolio epic.

    Returns ({portfolio_id: {"chains": [...], "blocked_ids": set}}, all_blocked_ids).
    """
    per_portfolio = {}
    all_blocked_ids = set()

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
                "item_type": b.get("item_type") or "Epic",
                "web_url": b.get("web_url"),
            }
            for b in rel.get("blocked_by", [])
        ]

        for ancestor in rel.get("at_risk_portfolio_epics", []):
            pid = ancestor.get("id_int")
            if pid not in epics_by_id:
                continue
            nodes = _chain_nodes(epics_by_id, blocked_id, pid)
            if nodes is None:
                continue

            entry = per_portfolio.setdefault(
                pid, {"chains": [], "blocked_ids": set()})
            entry["chains"].append({
                "nodes": [
                    _slim(n, blocked=(n["id"] == blocked_id)) for n in nodes
                ],
                "blockers": blockers,
            })
            entry["blocked_ids"].add(blocked_id)
            all_blocked_ids.add(blocked_id)

    return per_portfolio, all_blocked_ids


def _behind_schedule(epic):
    """The repo's standard At Risk rule: % done trails % through PI."""
    if epic.get("state") != "opened":
        return False
    done, through = epic.get("pct_complete"), epic.get("pct_through_pi")
    if done is None or through is None:
        return False
    return done < through


def build_portfolio_view(epics_by_id, blocking, raw_by_id=None):
    """Compute the /api/analysis/portfolio payload body.

    Chains walk a merged lookup — typed epics preferred (they carry the
    resolved tier), raw epics as fallback — so untyped intermediates and
    untyped blocked items render (type: null) rather than dropping the
    chain and silently hiding the risk (#174).
    """
    chain_lookup = {**(raw_by_id or {}), **epics_by_id}
    blocked_by_pid, all_blocked_ids = _blocked_by_portfolio(
        chain_lookup, blocking)

    portfolio_epics = []
    for epic in epics_by_id.values():
        if epic.get("type") != "Epic":
            continue

        pb = blocked_by_pid.get(epic["id"], {"chains": [], "blocked_ids": set()})
        blocked_ids = pb["blocked_ids"]
        flags = {
            "blocked": bool(blocked_ids),
            "behind_schedule": _behind_schedule(epic),
        }
        portfolio_epics.append({
            "epic": _slim(epic),
            "flags": flags,
            "needs_attention": any(flags.values()),
            "rollup": {
                "blocked_count": len(blocked_ids),
                "blocked_weight": sum(
                    _blocked_value(chain_lookup[i]) for i in blocked_ids
                ),
                "blocked_business_value": sum(
                    chain_lookup[i].get("business_value") or 0
                    for i in blocked_ids
                ),
            },
            "chains": pb["chains"],
        })

    # Attention first — biggest BV at risk, then blocked weight, then the
    # heaviest planned work; healthy epics follow by weight.
    portfolio_epics.sort(
        key=lambda e: (
            not e["needs_attention"],
            -e["rollup"]["blocked_business_value"],
            -e["rollup"]["blocked_weight"],
            -(e["epic"].get("planned_weight") or 0),
        )
    )

    untyped_in_chains = len({
        n["id"]
        for e in portfolio_epics
        for c in e["chains"]
        for n in c["nodes"]
        if n.get("type") is None
    })

    return {
        "totals": {
            "portfolio_epics": len(portfolio_epics),
            "needs_attention": sum(
                1 for e in portfolio_epics if e["needs_attention"]
            ),
            "blocked_items": len(all_blocked_ids),
            "blocked_weight": sum(
                _blocked_value(chain_lookup[i]) for i in all_blocked_ids
            ),
            "blocked_business_value": sum(
                chain_lookup[i].get("business_value") or 0
                for i in all_blocked_ids
            ),
            "untyped_in_chains": untyped_in_chains,
        },
        "portfolio_epics": portfolio_epics,
    }


def portfolio_payload(data_dir: Path):
    """Full response for GET /api/analysis/portfolio."""
    epics_by_id, raw_by_id, blocking, generated_at = load_snapshot(data_dir)
    payload = build_portfolio_view(epics_by_id, blocking, raw_by_id)
    run_dir = data_dir.parent
    payload["snapshot"] = {
        "date": run_dir.parent.name,
        "time": run_dir.name,
        "generated_at": generated_at,
    }
    return payload
