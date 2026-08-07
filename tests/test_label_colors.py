"""The label palette's contract: full taxonomy coverage and readable ramps.

The scheme is "hue says which dimension, lightness says where in that
dimension". These tests pin both halves — every taxonomy value in config.json
gets an explicit colour, and each ordered family stays monotone in perceptual
lightness with visible gaps, so a hand edit that flattens a ramp fails here
rather than on a stakeholder's screen.
"""
import json
import re
from pathlib import Path

import pytest

from mixins.label_colors import (
    DEFAULT_COLOR,
    FAMILY_DEFAULTS,
    LABEL_COLORS,
    color_for,
)

CONFIG = json.loads(
    (Path(__file__).resolve().parent.parent / "config.json").read_text())

#: Families whose values carry an order, and that order. Lightness must track it.
ORDERED = {
    "wsjf-urgency": ["1", "2", "3", "5", "8", "13"],
    "wsjf-risk":    ["1", "2", "3", "5", "8", "13"],
    "lifecycle":    ["funnel", "analyzing", "backlog", "implementing", "done"],
    "epic":         ["feature", "capability", "epic"],
}

#: Minimum OKLCH lightness gap between adjacent steps (the ordinal-ramp floor).
MIN_STEP = 0.06


def oklab_l(hex_color):
    """Perceptual lightness (OKLab L) of an sRGB hex colour."""
    h = hex_color.lstrip("#")
    lin = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (max(0.0, v) ** (1 / 3) for v in (l, m, s))
    return 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_


def taxonomy_labels():
    """Every label name the config's *_labels taxonomies declare."""
    names = []
    for key, raw in CONFIG.items():
        if not key.endswith("_labels"):
            continue
        if isinstance(raw, dict):
            for group in raw.values():
                names.extend(group or [])
        elif isinstance(raw, list):
            names.extend(raw)
    return [n for n in names if isinstance(n, str) and n]


def test_every_taxonomy_label_has_an_explicit_colour():
    missing = [n for n in taxonomy_labels() if n not in LABEL_COLORS]
    assert not missing, f"no palette entry for: {missing}"


def test_all_colours_are_valid_hex():
    bad = [(n, c) for n, c in LABEL_COLORS.items()
           if not re.fullmatch(r"#[0-9a-f]{6}", c)]
    assert not bad, f"malformed colours: {bad}"


@pytest.mark.parametrize("family,order", sorted(ORDERED.items()))
def test_ordered_family_ramps_are_monotone_with_visible_gaps(family, order):
    steps = [LABEL_COLORS[f"{family}::{v}"] for v in order]
    ls = [oklab_l(s) for s in steps]
    assert ls == sorted(ls, reverse=True), (
        f"{family} is not light->dark along its order: "
        f"{list(zip(order, [round(x, 3) for x in ls]))}")
    gaps = [round(a - b, 4) for a, b in zip(ls, ls[1:])]
    assert min(gaps) >= MIN_STEP, f"{family} steps too close to tell apart: {gaps}"


def test_the_current_pi_is_the_darkest_piid_chip():
    """PIID is banded, not ramped: the current PI has to win the scan."""
    piid = {k: v for k, v in LABEL_COLORS.items() if k.startswith("PIID::")}
    darkest = min(piid, key=lambda k: oklab_l(piid[k]))
    assert darkest == "PIID::2026Q3", (
        f"the current PI should be the darkest chip, got {darkest}")


def test_piid_carryover_is_one_flat_colour():
    """Ten historical quarters read as one 'not current' band, not a fake ramp."""
    carry = [LABEL_COLORS[f"PIID::{q}"] for q in
             ("2024Q1", "2024Q4", "2025Q2", "2025Q4", "2026Q1", "2026Q2")]
    assert len(set(carry)) == 1, f"carryover should be flat, got {set(carry)}"


def test_families_do_not_collapse_to_a_single_colour():
    for family in ORDERED:
        used = {c for n, c in LABEL_COLORS.items() if n.startswith(family + "::")}
        assert len(used) > 1, f"{family} collapsed to one colour"


def test_color_for_falls_back_by_family_then_default():
    assert color_for("lifecycle::done") == LABEL_COLORS["lifecycle::done"]
    assert color_for("PIID::2099Q1") == FAMILY_DEFAULTS["PIID"]
    assert color_for("unscoped-label") == DEFAULT_COLOR
    assert color_for("unknown-family::value") == DEFAULT_COLOR
