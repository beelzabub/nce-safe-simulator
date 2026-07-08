You are authoring the "Latest Work" spotlight slides for this week's NCE Safe Simulator status deck. Work non-interactively and finish by writing one YAML file. Do NOT build the deck, deploy anything, or edit any other file.

STEP 1 — get this week's candidate issues. Run exactly:

  python3 -c 'import sys;sys.path.insert(0,"deck");import build_deck as b,json;print(json.dumps(b.fetch_slides_issues(b._window_start_pacific())))'

That prints a JSON list of the issues labeled `slides` that closed since the previous weekly run (the trailing ~7 days incl. the weekend): each has iid, title, and description.

STEP 2 — see which screenshots exist (for optional images). Run:

  ls deck/screenshots/

STEP 3 — author spotlights. Group closely-related issues onto ONE slide (for example, an import/export hardening arc of many small issues becomes a single "Full-Fidelity Hardening" slide); give genuinely distinct work its own slide. For each spotlight write:
  - a short title (you may cite the issue number(s), e.g. "… (#206)");
  - a one-line subtitle;
  - 2–4 concise, presentation-ready bullets that you AUTHOR — summarize and sharpen; do not paste the issue description verbatim;
  - optionally `images` (1, or 2 for a side-by-side) — use ONLY filenames that exist under deck/screenshots/ (light-theme `_light.png` shots read best); add `image_labels` for a 2-image slide or a `caption` for a 1-image slide.

STEP 4 — write the result to deck/dist/latest-work-spotlights.gen.yaml in EXACTLY this schema (a top-level `spotlights:` list). Example shape:

  spotlights:
    - title: "New Capability — Bundle Export / Import  (#206)"
      subtitle: "One-file transfer of an entire portfolio slice"
      issues: [206]
      images: ["05a-import-export-export-bundle_light.png", "05b-import-export-import-bundle_light.png"]
      image_labels: ["Export Bundle dialog", "Import Bundle dialog"]
      bullets:
        - "First bullet …"
        - "Second bullet …"
    - title: "Import / Export — Full-Fidelity Hardening"
      subtitle: "The transfer arc behind the bundle"
      issues: [193, 195, 196, 198, 200, 201, 202, 211]
      images: ["05-import-export-import-epics_light.png"]
      caption: "Import Epics — one of the hardened dialogs"
      bullets:
        - "…"

Keep bullets tight (roughly one line each on a slide). Every feature/enhancement in the candidate list must be covered by some spotlight (alone or grouped). When the file is written and valid YAML, reply with a one-line summary of how many spotlight slides you wrote and which issues each covers.
