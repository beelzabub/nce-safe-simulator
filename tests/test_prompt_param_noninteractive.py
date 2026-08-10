"""_prompt_param must not block on input() when stdin is not a TTY.

A CI runner has no interactive stdin, so calling input() raises EOFError and
aborts the tool. Instead each unspecified param should resolve to what a blank
interactive answer would give (its default, else None for optionals), and a
genuinely required param with no default must fail loudly by name.
"""
import pytest
from unittest.mock import patch

from mixins.tools import _prompt_param

pytestmark = pytest.mark.unit


def _run(param, isatty):
    with patch("mixins.tools.sys.stdin") as stdin:
        stdin.isatty.return_value = isatty
        return _prompt_param(param)


def test_optional_str_returns_none_non_interactive():
    p = {"name": "card_spec", "prompt": "Card spec", "type": str, "optional": True}
    assert _run(p, isatty=False) is None


def test_default_is_used_non_interactive():
    p = {"name": "per_page", "prompt": "Cards per page", "type": str, "default": "1"}
    assert _run(p, isatty=False) == "1"


def test_optional_bool_returns_false_non_interactive():
    p = {"name": "dry_run", "prompt": "Dry run?", "type": bool}
    assert _run(p, isatty=False) is False


def test_required_without_default_raises_non_interactive():
    p = {"name": "input_path", "prompt": "Input file", "type": str, "optional": False}
    with pytest.raises(ValueError) as e:
        _run(p, isatty=False)
    assert "input_path" in str(e.value)      # the message names the missing param


def test_interactive_still_prompts():
    p = {"name": "card_spec", "prompt": "Card spec", "type": str, "optional": True}
    with patch("mixins.tools.sys.stdin") as stdin:
        stdin.isatty.return_value = True
        with patch("builtins.input", return_value="") as inp:
            assert _prompt_param(p) is None      # blank → None for optional
        inp.assert_called_once()                 # it really did prompt


# ─── #253: pseudo-TTY (docker exec -t, no -i) — isatty() True but input() EOFs ──
# A pseudo-TTY makes isatty() return True, so the non-interactive guard is
# skipped, but the first input() hits EOF. That EOFError must be handled exactly
# like a non-interactive stdin, not bubble up as an unhandled traceback.

def _run_eof(param):
    with patch("mixins.tools.sys.stdin") as stdin:
        stdin.isatty.return_value = True                     # pseudo-TTY lies
        with patch("builtins.input", side_effect=EOFError):  # but stdin is at EOF
            return _prompt_param(param)


def test_optional_str_returns_none_on_eof():
    p = {"name": "label_filter", "prompt": "Labels", "type": str, "optional": True}
    assert _run_eof(p) is None


def test_default_is_used_on_eof():
    p = {"name": "per_page", "prompt": "Cards per page", "type": str, "default": "1"}
    assert _run_eof(p) == "1"


def test_optional_bool_returns_false_on_eof():
    p = {"name": "dry_run", "prompt": "Dry run?", "type": bool}
    assert _run_eof(p) is False


def test_required_without_default_raises_on_eof():
    p = {"name": "input_path", "prompt": "Input file", "type": str, "optional": False}
    with pytest.raises(ValueError) as e:
        _run_eof(p)
    assert "input_path" in str(e.value)          # names the missing param, not EOFError


# --- cli_only dry_run params must not block the web UI from doing real work ---
# The web UI strips cli_only params from the payload and never passes them on
# the argv it launches, so every hidden dry_run param resolves here, from its
# registry default, against a non-TTY stdin. A default of True therefore makes
# the tool permanently preview-only from the web UI while its confirmation
# banner still promises objects will be created. Guard every tool at once so a
# future param keeps the property without anyone having to remember this.

def test_hidden_dry_run_params_default_to_doing_the_work():
    from mixins.tools import TOOLS

    preview_only = [
        (tool["key"], p["name"])
        for tool in TOOLS
        for p in tool.get("params", [])
        if p.get("cli_only") and p["type"] is bool
        and p["name"].startswith("dry_run")
        and _run(p, isatty=False) is not False
    ]
    assert preview_only == [], (
        "hidden dry_run params default to True, so the web UI can only ever "
        f"preview: {preview_only}"
    )
