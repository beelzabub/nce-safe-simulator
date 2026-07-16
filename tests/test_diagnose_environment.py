"""diagnose's environment litmus test (_check_environment).

Verifies the dependency preflight: it runs with no GitLab connection, catches a
missing *native* library that a pip-version check can't (WeasyPrint/Pango), and
gates only on REQUIRED dependencies — optional binaries (graphviz, quarto, the
deploy toolchain) never fail the check.
"""
import pytest
from unittest.mock import patch

from mixins.reports import ReportsMixin

pytestmark = pytest.mark.unit


def _mixin():
    return ReportsMixin.__new__(ReportsMixin)


def test_environment_all_required_present_here():
    lines, missing = _mixin()._check_environment()
    assert isinstance(lines, list) and isinstance(missing, list)
    assert missing == []                                   # this env has the required set
    text = "\n".join(lines)
    assert "Environment Dependencies" in text
    assert "WeasyPrint render" in text                     # the native-lib litmus is shown
    assert "All required dependencies present" in text
    # no GitLab call happened — the method never touches self.gl / self.url


def test_missing_optional_binaries_do_not_fail_the_gate():
    with patch("shutil.which", return_value=None):         # graphviz/quarto/aws/... all absent
        lines, missing = _mixin()._check_environment()
    assert missing == []                                   # optional → gate stays green
    assert "(optional)" in "\n".join(lines)


def test_missing_native_lib_is_caught_and_gates():
    # Simulate a lift-and-shift that installed the pip package but not Pango:
    # the render smoke test raises, so WeasyPrint must land in missing_required.
    import weasyprint
    with patch.object(weasyprint, "HTML", side_effect=OSError("cannot load library 'libpango-1.0.so.0'")):
        lines, missing = _mixin()._check_environment()
    assert any("WeasyPrint" in m for m in missing)
    text = "\n".join(lines)
    assert "❌" in text
    assert "required dependency" in text.lower()
    assert "libpango" in text                               # the fix hint names the package
