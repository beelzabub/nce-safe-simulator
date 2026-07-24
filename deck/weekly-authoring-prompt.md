You are authoring this week's NCE Safe Simulator status-deck content: the "Latest Work" spotlight slides, plus proposed capability-area updates when the background matter has drifted. Work non-interactively and finish by writing at most two YAML files (STEP 4 and STEP 5). Do NOT build the deck, deploy anything, or edit any other file — in particular never edit deck/capabilities.yaml itself.

STEP 1 — get this week's candidate issues. Run exactly:

  python3 -c 'import sys;sys.path.insert(0,"deck");import build_deck as b,json;print(json.dumps(b.fetch_slides_issues(b._window_start_pacific())))'

That prints a JSON list of the issues labeled `slides` that closed since the previous weekly run (the trailing ~7 days incl. the weekend), across BOTH covered repos — nce-safe-simulator and nce-git-ops: each has iid, repo, ref, title, and description. `ref` is the citation form: `#N` for the simulator, `nce-git-ops#N` for the platform repo — use `ref` (never bare iid) whenever you cite a nce-git-ops issue in a title or `issues` list, so numbers from the two trackers can't be confused. Work-state-sync issues are excluded automatically and never get slides.

STEP 2 — see which screenshots exist (for optional images). Run:

  ls deck/screenshots/

There is also a pool of curated, committed art you may reference by its repo-relative path (image paths resolve under deck/screenshots/ first, then repo-relative). Prefer these when a candidate issue matches:

  ls deck/assets/spotlight-extras/           # e.g. make-help-root.png / make-help-cdk.png (Makefile help, #255); epic-cards-portrait.png / epic-cards-landscape.png / epic-cards-largeformat.png (epic cards #249/#254/#241)
  ls slides/243-slide-brief-as-is-to-be/diagrams/   # As-Is / To-Be SDLC architecture diagrams (VM→container brief, #243/#244/#247/#248)

For those issues, use the matching committed image (full repo-relative path, e.g. "deck/assets/spotlight-extras/make-help-root.png") rather than leaving the slide image-less.

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

Keep bullets tight (roughly one line each on a slide). Every feature/enhancement in the candidate list must be covered by some spotlight (alone or grouped).

STEP 5 — propose capability-area updates (the background matter must not drift behind the work). Run:

  python3 deck/build_deck.py --print-coverage-gap

That prints a JSON list of closed issues (both repos) cited in no capability area of deck/capabilities.yaml. If the list is empty, skip this step and do NOT write the file. Otherwise Read deck/capabilities.yaml (area titles, blurbs, existing bullets), decide where each gap issue belongs, and write deck/dist/capabilities-updates.gen.yaml in EXACTLY this schema:

  extend:
    - title: "Engineering Process & CLI UX"    # EXACT title of an existing area
      add_issues: "#280, #283"                 # refs joined by ", " — count is bumped automatically
      add_bullets:                             # optional — flagship-worthy items only
        - "#280 One-line authored bullet."
  new_areas:                                   # only when 4+ gap issues form a genuinely new theme;
    - title: "..."                             # same entry schema as capabilities.yaml
      count: 4
      all_issues: "#281, #282, #284, #285"
      blurb: "..."
      bullets: ["..."]
      image: "..."                             # optional; same resolution rules (screenshots dir, then repo-relative)

Rules: every gap issue lands in exactly one area; use the `ref` citation form from STEP 1 (`#N` simulator, `nce-git-ops#N` platform) in add_issues/all_issues — full refs, never ranges; a new area's `count` equals the number of refs in its `all_issues`. These are PROPOSALS: build_deck.py merges them into this week's deck automatically, and they are reviewed later before being folded into capabilities.yaml — so write presentation-ready bullets, phrased for bugs as the problem fixed. Re-run the gap command afterwards: it must print [] once your file is in place.

When the file(s) are written and valid YAML, reply with a one-line summary: how many spotlight slides (and which issues each covers), plus how many capability extensions / new areas you proposed (or "no capability drift").
