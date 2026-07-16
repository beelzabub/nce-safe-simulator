"""get_group_by_name resolution (#256).

A group may be addressed by its display name, its URL path slug, or a full URL
path — users copy any of these from GitLab. Resolution must accept all three
while staying backward-compatible: a unique display-name match still wins first,
so anything that resolved before resolves the same way.
"""
import pytest

from mixins.groups import GroupsMixin

pytestmark = pytest.mark.unit


class _Grp:
    def __init__(self, gid, name, path):
        self.id, self.name, self.path = gid, name, path


class _FakeGroups:
    """Stand-in for gl.groups. `list(search=)` matches name/path substrings
    (as GitLab does); `get(id)` returns the catalog group; `get('a/b/c')`
    resolves a full path from `direct` (or raises, like a real 404)."""

    def __init__(self, catalog, direct=None, direct_raises=False):
        self.catalog = catalog
        self.direct = direct or {}
        self.direct_raises = direct_raises

    def list(self, search=None, all=False):
        s = (search or "").lower()
        return [g for g in self.catalog if s in g.name.lower() or s in g.path.lower()]

    def get(self, key):
        if isinstance(key, str):                       # full-path lookup
            if self.direct_raises or key not in self.direct:
                raise Exception("404 Group Not Found")
            return self.direct[key]
        for g in self.catalog:                         # by id
            if g.id == key:
                return g
        raise Exception("no such id")


class _GL:
    def __init__(self, groups):
        self.groups = groups


class _Host(GroupsMixin):
    def __init__(self, groups):
        self.gl = _GL(groups)


def _host(catalog, **kw):
    return _Host(_FakeGroups(catalog, **kw))


_TWA = _Grp(9, "TWA-122 TestDashboard", "twa-122-testdashboard")


def test_resolves_by_display_name():
    h = _host([_TWA])
    assert h.get_group_by_name("TWA-122 TestDashboard").id == 9


def test_resolves_by_path_slug():
    # the #256 bug: a URL slug (name != slug) must resolve
    h = _host([_TWA])
    assert h.get_group_by_name("twa-122-testdashboard").id == 9


def test_resolves_by_full_url_path():
    full = "gl-demo/twa/twa-122-testdashboard"
    h = _host([_TWA], direct={full: _TWA})
    assert h.get_group_by_name(full).id == 9


def test_full_path_get_failure_falls_back_to_search():
    # a slash-bearing value that isn't a real full path must not raise — it
    # falls through to search (and here matches nothing → None)
    h = _host([_TWA], direct_raises=True)
    assert h.get_group_by_name("no/such/group") is None


def test_display_name_wins_over_a_colliding_path():
    # backward-compat: when one group's NAME and another's PATH both equal the
    # query, the display-name match wins (unchanged pre-#256 behavior).
    a = _Grp(1, "widget", "widget-a")     # name == query
    b = _Grp(2, "Other",  "widget")       # path == query
    h = _host([a, b])
    assert h.get_group_by_name("widget").id == 1


def test_ambiguous_name_returns_none():
    a = _Grp(1, "dup", "dup-a")
    b = _Grp(2, "dup", "dup-b")
    assert _host([a, b]).get_group_by_name("dup") is None


def test_unmatched_returns_none():
    assert _host([_TWA]).get_group_by_name("does-not-exist") is None
