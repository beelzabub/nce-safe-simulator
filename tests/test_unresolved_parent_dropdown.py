"""unresolved_parent as a dropdown (#136).

Web dialog offers label/skip via a select widget with a help tooltip; the CLI
keeps ask/label/skip. 'ask' is interactive, so a non-interactive run (web job)
must degrade to 'label' instead of blocking/crashing on input().
"""
import pytest
from unittest.mock import MagicMock, patch

from mixins.importexport import ImportExportMixin
from server.app import _tool_payload
from mixins.tools import TOOLS

pytestmark = pytest.mark.unit


class H(ImportExportMixin):
    def __init__(self):
        self.gl = MagicMock()
        self.pick_called = False

    def _pick_fallback_parent(self, root_group):
        self.pick_called = True
        return 999, "Chosen Parent"


def _rows():
    return [{"title": "E1", "parent_id": "555"}]   # 555 not in valid ids → unresolvable


def test_ask_degrades_to_label_when_non_interactive():
    h = H()
    with patch("mixins.importexport.sys.stdin") as stdin:
        stdin.isatty.return_value = False
        pmap, orphans = h._resolve_parent_ids(_rows(), set(), MagicMock(), "ask")
    assert h.pick_called is False        # never prompts
    assert orphans == {1}                # row → import::needs-parent
    assert pmap == {1: None}


def test_ask_interactive_uses_picker():
    h = H()
    with patch("mixins.importexport.sys.stdin") as stdin:
        stdin.isatty.return_value = True
        pmap, orphans = h._resolve_parent_ids(_rows(), set(), MagicMock(), "ask")
    assert h.pick_called is True
    assert pmap == {1: 999}              # all affected rows → chosen fallback
    assert orphans == set()


def test_label_and_skip_are_non_interactive():
    for action, expect_orphan in (("label", True), ("skip", False)):
        h = H()
        with patch("mixins.importexport.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            pmap, orphans = h._resolve_parent_ids(_rows(), set(), MagicMock(), action)
        assert h.pick_called is False
        assert (orphans == {1}) is expect_orphan


def test_import_epics_unresolved_parent_is_select_with_help():
    t = next(t for t in TOOLS if t["key"] == "import-epics")
    p = next(p for p in _tool_payload(t)["params"] if p["name"] == "unresolved_parent")
    assert p["widget"] == "select"
    assert p["options"] == ["label", "skip"]     # ask omitted from the web dropdown
    assert p["default"] == "label"
    assert p["help"] and "ask" in p["help"] and "label" in p["help"] and "skip" in p["help"]


def test_cli_prompt_still_lists_all_three():
    # CLI (free-text via _prompt_param) must keep offering ask/label/skip.
    raw = next(pp for t in TOOLS if t["key"] == "import-epics"
               for pp in t["params"] if pp["name"] == "unresolved_parent")
    assert "ask" in raw["prompt"] and "label" in raw["prompt"] and "skip" in raw["prompt"]
