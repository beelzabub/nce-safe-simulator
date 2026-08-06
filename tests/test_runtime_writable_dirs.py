"""The image must pre-create every directory the app writes to at runtime.

The runtime stage drops to uid 1000 (#304) and deliberately leaves the code —
public/ included — root-owned. A directory under public/ therefore cannot be
created at runtime: mkdir needs write permission on public/ itself, which the
app does not have. Each one has to exist and be app-owned in the image.

This is not hypothetical. public/data was missed when the container went
non-root, and every full report run died on
``PermissionError: [Errno 13] Permission denied: 'public/data'`` at the point
where it writes the Quarto/Marimo data layer.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "Dockerfile").read_text()

SOURCE_FILES = [
    *(REPO / "mixins").rglob("*.py"),
    *(REPO / "server").rglob("*.py"),
    REPO / "NceGitLab.py",
]


def _runtime_stage_prep():
    """The RUN layer that creates the app user and the writable dirs."""
    m = re.search(
        r"RUN useradd --create-home --uid 1000 --user-group app.*?(?=\n(?:[A-Z]+ |\n))",
        DOCKERFILE,
        re.S,
    )
    assert m, "could not locate the uid-1000 useradd/chown layer in the Dockerfile"
    return m.group(0)


def _runtime_written_dirs():
    """Every directory literal the app writes its data layer into.

    Two sources, because the failure mode differs and both have now bitten:

    * ``Path("public/<name>")`` — a two-segment directory under the root-owned
      public/ bundle, which the app cannot create at runtime. Deeper literals
      like ``Path("public/app/index.html")`` are reads of the shipped frontend,
      not directories the app creates, so they stay out.
    * the directory arguments of ``write_report_json(...)`` — these are written
      into directly. quarto-data ships in the repo, so it already exists and
      ``mkdir -p`` succeeds; the *write* inside it is what fails when it is
      root-owned. Existence is not the contract — ownership is.
    """
    found = set()
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for name in re.findall(r'Path\("(public/[a-z_]+)"\)', line):
                found.add(name)
        for call in re.findall(r"write_report_json\(([^)]*)\)", text):
            for name in re.findall(r'Path\("([a-z][a-z_/-]*)"\)', call):
                found.add(name)
    return found


def test_public_subdirs_are_precreated_and_chowned():
    prep = _runtime_stage_prep()
    mkdir = re.search(r"mkdir -p ([^&\\]+)", prep)
    chown = re.search(r"chown -R app:app ([^&\\]+)", prep)
    assert mkdir and chown, "runtime prep layer must both mkdir -p and chown -R"

    made = set(mkdir.group(1).split())
    owned = set(chown.group(1).split())

    for target in sorted(_runtime_written_dirs()):
        assert target in made, (
            f"{target} is written at runtime but is not created in the image — "
            f"add it to mkdir -p."
        )
        assert target in owned, (
            f"{target} is not chowned to app, so uid 1000 cannot write into it. "
            f"Shipping in the build context is not enough: COPY lands it "
            f"root-owned and mkdir -p then succeeds without granting a write."
        )


def test_public_itself_is_not_handed_to_app():
    """Guard the tighter fix: grant the subdirectory, never the parent.

    chown-ing public/ would let the app rewrite the served frontend bundle;
    pre-creating each subdirectory keeps the static assets read-only.
    """
    prep = _runtime_stage_prep()
    chown_targets = set()
    for m in re.finditer(r"chown (?:-R )?app:app ([^&\\]+)", prep):
        chown_targets.update(m.group(1).split())
    assert "public" not in chown_targets, (
        "public/ must stay root-owned — pre-create the specific subdirectory instead"
    )


def test_runtime_stage_still_drops_root():
    """The whole reason these directories need pre-creating."""
    assert re.search(r"(?m)^USER app$", DOCKERFILE), "runtime stage must drop to the app user"
