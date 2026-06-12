import pytest
from server.constraints import (
    READONLY_TOOLS,
    WRITER_GROUPS,
    _TOOL_GROUP,
    check_conflict,
)


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------

def test_all_writer_groups_present():
    expected = {
        "label-writers", "weight-writers", "issue-state-writers",
        "epic-structure-writers", "risk-writers", "wiki-writers",
        "setup", "import-export",
    }
    assert set(WRITER_GROUPS.keys()) == expected


def test_no_overlap_between_readonly_and_writer_groups():
    all_writers = {t for tools in WRITER_GROUPS.values() for t in tools}
    assert READONLY_TOOLS.isdisjoint(all_writers)


def test_reverse_lookup_covers_all_writers():
    for group, tools in WRITER_GROUPS.items():
        for tool in tools:
            assert _TOOL_GROUP[tool] == group


# ---------------------------------------------------------------------------
# Read-only tools never conflict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("readonly", sorted(READONLY_TOOLS))
def test_readonly_never_conflicts(readonly):
    # Even if the entire writer registry is running
    all_writers = [t for tools in WRITER_GROUPS.values() for t in tools]
    assert check_conflict(all_writers, readonly) == []


def test_readonly_against_readonly_is_safe():
    ro = list(READONLY_TOOLS)
    for tool in ro:
        assert check_conflict(ro, tool) == []


# ---------------------------------------------------------------------------
# Within-group conflicts (one representative pair per group)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("group,blocker,new_job", [
    ("label-writers",          "set-lifecycle-labels",  "strip-lifecycle-labels"),
    ("label-writers",          "set-piid-labels",       "strip-labels"),
    ("weight-writers",         "set-issue-weights",     "update-weights"),
    ("weight-writers",         "strip-issue-weights",   "set-business-value"),
    ("issue-state-writers",    "close-percent",         "simulate-pi-progress"),
    ("issue-state-writers",    "set-epic-states",       "reset-pi-progress"),
    ("epic-structure-writers", "generate-epic-blocks",  "orphan-epics"),
    ("epic-structure-writers", "clean-epic-blocks",     "generate-issues"),
    ("risk-writers",           "generate-roam-risks",   "clean-roam-risks"),
    ("risk-writers",           "generate-risk-reasons", "generate-roam-risks"),
    ("wiki-writers",           "clean-wikis",           "list-wikis"),
    ("setup",                  "scaffold",              "setup-bv-field"),
    ("import-export",          "export-epics",          "import-epics"),
    ("import-export",          "import-issues",         "export-issues"),
])
def test_within_group_conflict(group, blocker, new_job):
    result = check_conflict([blocker], new_job)
    assert blocker in result, (
        f"Expected '{blocker}' to block '{new_job}' in group '{group}'"
    )


# ---------------------------------------------------------------------------
# Cross-group tools do not conflict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("running,new_job", [
    ("set-lifecycle-labels",  "set-issue-weights"),
    ("close-percent",         "generate-roam-risks"),
    ("scaffold",              "export-epics"),
    ("clean-wikis",           "orphan-epics"),
    ("import-epics",          "simulate-pi-progress"),
])
def test_cross_group_no_conflict(running, new_job):
    assert check_conflict([running], new_job) == []


# ---------------------------------------------------------------------------
# Multiple blockers returned
# ---------------------------------------------------------------------------

def test_multiple_blockers_returned():
    running = ["set-lifecycle-labels", "set-piid-labels", "set-risk-labels"]
    result = check_conflict(running, "strip-labels")
    assert set(result) == {"set-lifecycle-labels", "set-piid-labels", "set-risk-labels"}


def test_only_same_group_blockers_returned():
    running = ["set-lifecycle-labels", "close-percent", "validate-weights"]
    result = check_conflict(running, "strip-lifecycle-labels")
    assert result == ["set-lifecycle-labels"]


# ---------------------------------------------------------------------------
# Empty running list
# ---------------------------------------------------------------------------

def test_empty_running_list_is_always_safe():
    for group_tools in WRITER_GROUPS.values():
        for tool in group_tools:
            assert check_conflict([], tool) == []


# ---------------------------------------------------------------------------
# Unknown / unclassified job key
# ---------------------------------------------------------------------------

def test_unknown_job_key_does_not_raise():
    result = check_conflict(["set-lifecycle-labels"], "some-future-tool")
    assert result == []


# ---------------------------------------------------------------------------
# All writer groups: every tool in a group conflicts with every other
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("group,tools", [
    (group, tools)
    for group, tools in WRITER_GROUPS.items()
    if len(tools) > 1
])
def test_all_pairs_within_group_conflict(group, tools):
    for i, blocker in enumerate(tools):
        for new_job in tools:
            if blocker == new_job:
                continue
            result = check_conflict([blocker], new_job)
            assert blocker in result, (
                f"Group '{group}': expected '{blocker}' to block '{new_job}'"
            )
