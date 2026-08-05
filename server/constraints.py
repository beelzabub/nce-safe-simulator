# Static parallelism rules derived from the tool registry.
#
# WRITER_GROUPS: tools within the same group mutually exclude each other —
# only one may run at a time. READONLY_TOOLS may run alongside anything.
#
# check_conflict(running, new_job) returns the list of currently-running job
# keys that would be blocked by starting new_job. An empty return means
# new_job is safe to start.

WRITER_GROUPS: dict[str, list[str]] = {
    "label-writers": [
        "set-lifecycle-labels",
        "strip-lifecycle-labels",
        "set-piid-labels",
        "strip-piid-labels",
        "set-project-labels",
        "strip-project-labels",
        "set-risk-labels",
        "set-wsjf-labels",
        "strip-wsjf-labels",
        "set-work-type-labels",
        "strip-work-type-labels",
        "strip-labels",
    ],
    "weight-writers": [
        "set-issue-weights",
        "strip-issue-weights",
        "update-weights",
        "set-business-value",
        "strip-business-value",
    ],
    "issue-state-writers": [
        "close-percent",
        "set-epic-states",
        "simulate-pi-progress",
        "reset-pi-progress",
    ],
    "epic-structure-writers": [
        "generate-epic-blocks",
        "generate-issue-blocks",
        "clean-epic-blocks",
        "orphan-epics",
        "orphan-issues",
        "generate-issues",
    ],
    "risk-writers": [
        "generate-roam-risks",
        "clean-roam-risks",
        "generate-risk-reasons",
    ],
    "wiki-writers": [
        "clean-wikis",
        "list-wikis",
    ],
    "setup": [
        "scaffold",
        "setup-bv-field",
        "create-lorem-data",
    ],
    "import-export": [
        "export-bundle",
        "import-bundle",
        "export-epics",
        "import-epics",
        "export-issues",
        "import-issues",
        "export-links",
        "import-links",
    ],
    # Grouped for the UI, but see CONCURRENT_GROUPS below — these run on AWS,
    # not GitLab, and VM Import handles many simultaneous tasks by design.
    "image-conversion": [
        "ova-import-setup",
        "ova-fetch",
        "ova-to-ami",
        "ami-to-ova",
        "ova-import-cleanup",
    ],
}

# Groups whose members never conflict — with each other OR with a second run
# of the same tool. The conflict framework exists to protect GitLab data from
# concurrent writers; these tools write to AWS, where per-key resources are
# independent and concurrent import/export tasks are the service's normal
# operating mode (default quota: 20 simultaneous imports). The group still
# exists so the job picker keeps them under one heading.
CONCURRENT_GROUPS: frozenset[str] = frozenset(["image-conversion"])

READONLY_TOOLS: frozenset[str] = frozenset([
    "audit-hierarchy",
    "audit-labels",
    "diagnose",
    "query",
    "validate-weights",
    "weight-drift-check",
    "clean-reports",
    "clean-logs",
])

# Reverse lookup: tool key → group name
_TOOL_GROUP: dict[str, str] = {
    tool: group
    for group, tools in WRITER_GROUPS.items()
    for tool in tools
}


def check_conflict(running: list[str], new_job: str) -> list[str]:
    """Return the subset of *running* jobs that conflict with *new_job*.

    An empty list means new_job is safe to start immediately.
    Reports are treated as read-only by callers passing a job key prefixed
    with 'report:'; any unrecognised key not in READONLY_TOOLS and not in any
    writer group is treated as a writer with no defined group (no conflict).
    """
    if new_job in READONLY_TOOLS:
        return []

    group = _TOOL_GROUP.get(new_job)
    # Concurrent groups skip every check, including the same-tool duplicate
    # rule — two ova-to-ami imports of different OVAs is a supported flow.
    if group in CONCURRENT_GROUPS:
        return []

    if new_job in running:
        return [new_job]

    if group is None:
        return []

    group_members = set(WRITER_GROUPS[group])
    return [job for job in running if job in group_members]
