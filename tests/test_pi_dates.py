"""Unit tests for _pi_dates_from_label and _pct_through_pi (mixins/utils.py)."""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

import sys


from mixins.utils import UtilitiesMixin


class ConcreteUtils(UtilitiesMixin):
    """Minimal concrete subclass to access UtilsMixin methods."""
    EPIC_TYPE_LABELS        = ["Epic", "Capability", "Feature"]
    EPIC_TYPE_DISPLAY_NAMES = ["Epic", "Capability", "Feature"]

    def __init__(self):
        self.gl = MagicMock()
        self.url = "https://gitlab.com"
        self.private_token = "test-token"


@pytest.fixture
def utils():
    return ConcreteUtils()


class TestPiDatesFromLabel:
    def test_valid_q1(self, utils):
        start, end = utils._pi_dates_from_label("PIID::2026Q1")
        assert start == date(2026, 1, 1)
        assert end   == date(2026, 3, 31)

    def test_valid_q2(self, utils):
        start, end = utils._pi_dates_from_label("PIID::2026Q2")
        assert start == date(2026, 4, 1)
        assert end   == date(2026, 6, 30)

    def test_valid_q3(self, utils):
        start, end = utils._pi_dates_from_label("PIID::2026Q3")
        assert start == date(2026, 7, 1)
        assert end   == date(2026, 9, 30)

    def test_valid_q4(self, utils):
        start, end = utils._pi_dates_from_label("PIID::2026Q4")
        assert start == date(2026, 10, 1)
        assert end   == date(2026, 12, 31)

    def test_none_returns_none_pair(self, utils):
        start, end = utils._pi_dates_from_label(None)
        assert start is None
        assert end   is None

    def test_bad_format_returns_none_pair(self, utils):
        start, end = utils._pi_dates_from_label("PIID::not-a-pi")
        assert start is None
        assert end   is None

    def test_wrong_prefix_returns_none_pair(self, utils):
        start, end = utils._pi_dates_from_label("PI::2026Q1")
        assert start is None
        assert end   is None


class TestPctThroughPi:
    def test_today_is_start(self, utils):
        with patch("mixins.utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = utils._pct_through_pi("PIID::2026Q1")
        assert result == 0

    def test_today_is_end(self, utils):
        with patch("mixins.utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 31)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = utils._pct_through_pi("PIID::2026Q1")
        assert result == 100

    def test_today_past_end_clamps_to_100(self, utils):
        with patch("mixins.utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = utils._pct_through_pi("PIID::2026Q1")
        assert result == 100

    def test_today_before_start_returns_0(self, utils):
        with patch("mixins.utils.date") as mock_date:
            mock_date.today.return_value = date(2025, 12, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = utils._pct_through_pi("PIID::2026Q1")
        assert result == 0

    def test_midpoint_is_roughly_50(self, utils):
        with patch("mixins.utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 14)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = utils._pct_through_pi("PIID::2026Q1")
        assert 45 <= result <= 55

    def test_none_piid_returns_none(self, utils):
        result = utils._pct_through_pi(None)
        assert result is None
