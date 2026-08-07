"""Label colours for the SAFe label taxonomies.

Hue says *which dimension* a chip belongs to; lightness says *where in that
dimension* it sits. Cross-family identity is carried by the scope text GitLab
prints on every chip ("PIID::2026Q3") -- six families share a result row, and
no six hues stay mutually distinguishable once each one also spends lightness
on its own ordering, so colour is not asked to carry that job.

Every ramp below passes the ordinal checks (monotone lightness, adjacent
delta-L >= 0.06, lightest step >= 2:1 on white, single hue).
"""

#: Used for a label outside every taxonomy below.
DEFAULT_COLOR = "#4287f5"

#: Per-family fallback, so a taxonomy value added to config.json later still
#: lands in its family's palette instead of the generic blue.
FAMILY_DEFAULTS = {
    "PIID":           "#96a6bb",
    "wsjf-urgency":   "#dd5c25",
    "wsjf-risk":      "#d26790",
    "lifecycle":      "#029465",
    "epic":           "#9787fb",
    "project":        "#8b8375",
    "roam":           "#fab219",
    "risk":           "#fab219",
    "type":           "#52514e",
}

LABEL_COLORS = {
    # PIID -- blue - carryover flat and muted, current PI darkest, future steps back out
    "PIID::2024Q1":                   "#96a6bb",
    "PIID::2024Q2":                   "#96a6bb",
    "PIID::2024Q3":                   "#96a6bb",
    "PIID::2024Q4":                   "#96a6bb",
    "PIID::2025Q1":                   "#96a6bb",
    "PIID::2025Q2":                   "#96a6bb",
    "PIID::2025Q3":                   "#96a6bb",
    "PIID::2025Q4":                   "#96a6bb",
    "PIID::2026Q1":                   "#96a6bb",
    "PIID::2026Q2":                   "#96a6bb",
    "PIID::2026Q3":                   "#0153a6",
    "PIID::2026Q4":                   "#3270be",
    "PIID::2027Q1":                   "#4887d7",
    "PIID::2027Q2":                   "#5f9ff1",
    # wsjf-urgency -- orange - pale to deep as urgency climbs 1 -> 13
    "wsjf-urgency::1":                "#ff8d64",
    "wsjf-urgency::2":                "#f4703d",
    "wsjf-urgency::3":                "#dd5c25",
    "wsjf-urgency::5":                "#c74702",
    "wsjf-urgency::8":                "#a93b02",
    "wsjf-urgency::13":               "#8c3002",
    # wsjf-risk -- magenta - pale to deep as risk climbs 1 -> 13
    "wsjf-risk::1":                   "#fe8fb8",
    "wsjf-risk::2":                   "#e87ba4",
    "wsjf-risk::3":                   "#d26790",
    "wsjf-risk::5":                   "#bc547d",
    "wsjf-risk::8":                   "#a7406b",
    "wsjf-risk::13":                  "#912d59",
    # lifecycle -- aqua - light to dark along the flow funnel -> done
    "lifecycle::funnel":              "#40c68f",
    "lifecycle::analyzing":           "#18ae79",
    "lifecycle::backlog":             "#029465",
    "lifecycle::implementing":        "#077b54",
    "lifecycle::done":                "#046242",
    # epic -- violet - light to dark as scope widens feature -> epic
    "epic::feature":                  "#b3abfe",
    "epic::capability":               "#9787fb",
    "epic::epic":                     "#7d6bdc",
    # project -- warm neutral - identity only; the steps imply no rank
    "project::DO":                    "#b2aa9c",
    "project::RTSO":                  "#9e9688",
    "project::DCGS":                  "#8b8375",
    "project::TestA":                 "#787063",
    "project::TestB":                 "#655e51",
    "project::TestC":                 "#544c40",
    # roam -- reserved status scale - unhandled (red) to handled (green)
    "roam::owned":                    "#d03b3b",
    "roam::accepted":                 "#ec835a",
    "roam::mitigated":                "#fab219",
    "roam::resolved":                 "#0ca30c",
    # risk -- reserved status scale
    "risk::high":                     "#d03b3b",
    "risk::medium":                   "#fab219",
    "risk::low":                      "#0ca30c",
    # type -- distinct hues; no order implied
    "type::feature":                  "#eda100",
    "type::enabler":                  "#4a3aa7",
    "type::infrastructure":           "#52514e",
    "type::defect":                   "#e34948",
}


def color_for(name):
    """Palette colour for a label name, falling back by family then default."""
    color = LABEL_COLORS.get(name)
    if color is not None:
        return color
    family = name.split("::", 1)[0] if "::" in name else None
    return FAMILY_DEFAULTS.get(family, DEFAULT_COLOR)
