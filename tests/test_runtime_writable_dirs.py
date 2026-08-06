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


def _public_subdirs_written_by_source():
    """Every public/<name> directory the source treats as a path root.

    Matches ``Path("public/<name>")`` only — a bare two-segment directory the
    code builds paths from, which is how each of these is written to. Deeper
    literals like ``Path("public/app/index.html")`` are reads of the shipped
    frontend bundle, not directories the app creates, so they stay out.
    """
    found = set()
    for path in SOURCE_FILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for name in re.findall(r'Path\("public/([a-z_]+)"\)', line):
                found.add(name)
    return found


def test_public_subdirs_are_precreated_and_chowned():
    prep = _runtime_stage_prep()
    mkdir = re.search(r"mkdir -p ([^&\\]+)", prep)
    chown = re.search(r"chown -R app:app ([^&\\]+)", prep)
    assert mkdir and chown, "runtime prep layer must both mkdir -p and chown -R"

    made = set(mkdir.group(1).split())
    owned = set(chown.group(1).split())

    for name in sorted(_public_subdirs_written_by_source()):
        target = f"public/{name}"
        assert target in made, (
            f"{target} is written at runtime but is not created in the image. "
            f"public/ is root-owned, so uid 1000 cannot create it — add it to mkdir -p."
        )
        assert target in owned, (
            f"{target} is created in the image but not chowned to app — "
            f"uid 1000 cannot write into it."
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
