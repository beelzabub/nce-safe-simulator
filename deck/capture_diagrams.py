"""
Render the architecture diagrams (the DoD/DoDAF view set from diagrams/*.py) into
the deck screenshots dir so build_deck.py can drop them onto slides. This is the
diagram counterpart to capture_screenshots.py — a prerequisite generator whose
output (deck/screenshots/architecture/*.png) is git-ignored and rebuilt on demand.

Same diagrams the container renders at build time (Dockerfile stage 2 / `make
dod-diagrams`), just written where the deck expects them.

Requires: the `diagrams` Python package (in requirements.txt) and the Graphviz
`dot` binary on PATH (system prerequisite).

Usage:
  python3 deck/capture_diagrams.py [--out-dir deck/screenshots/architecture]
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DIAGRAMS_DIR = os.path.join(REPO_ROOT, "diagrams")

# (script in diagrams/, output PNG basename) — matches the names build_deck.py and
# the Dockerfile use. Each script takes the output path as its one argument.
DIAGRAMS = [
    ("ov1_operational_concept.py", "ov1-architecture.png"),
    ("sv1_system_interfaces.py",   "sv1-architecture.png"),
    ("sv2_deployment_eks.py",      "sv2-eks-architecture.png"),
    ("sv2_deployment_ecs.py",      "sv2-ecs-architecture.png"),
    ("dataflow_architecture.py",   "dataflow-architecture.png"),
    ("devsecops_pipeline.py",      "devsecops-architecture.png"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(HERE, "screenshots", "architecture"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    failures = []
    for script, out_name in DIAGRAMS:
        script_path = os.path.join(DIAGRAMS_DIR, script)
        out_path = os.path.join(args.out_dir, out_name)
        # Run each script with sys.executable. sys.path[0] becomes diagrams/, which
        # does NOT shadow the installed `diagrams` package (no diagrams/diagrams).
        proc = subprocess.run([sys.executable, script_path, out_path], capture_output=True, text=True)
        if proc.returncode == 0 and os.path.exists(out_path):
            print(f"OK   {out_path}")
        else:
            failures.append(script)
            print(f"FAIL {script}\n{(proc.stderr or proc.stdout).strip()[-500:]}", file=sys.stderr)
        # diagrams leaves a Graphviz source file next to the PNG; drop it.
        gv = out_path.rsplit(".", 1)[0]
        if os.path.exists(gv):
            os.remove(gv)

    if failures:
        raise SystemExit(f"{len(failures)} diagram(s) failed: {', '.join(failures)} "
                         "(is the `diagrams` package installed and `dot` on PATH?)")
    print(f"Rendered {len(DIAGRAMS)} architecture diagrams to {args.out_dir}")


if __name__ == "__main__":
    main()
