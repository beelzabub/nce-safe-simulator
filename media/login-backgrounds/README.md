# Login-page background images

Committed home of the rotating login-page backgrounds (epic #135). Served by
`GET /api/auth/backgrounds` / `GET /api/auth/backgrounds/{name}`.

- Formats: `.jpg` / `.jpeg` / `.png` / `.webp`, optimized to 1920 px wide,
  ~200–500 KB each.
- `credits.json` maps each filename to its credit line, e.g.
  `{"csg-nimitz-01.jpg": "U.S. Navy photo by MC2 ..."}`. Keep it current —
  the API surfaces the credit and the login page displays it.
- Images are curated public-domain U.S. Navy imagery (DVIDS / navy.mil).
  Appearance of DoD visual information does not imply endorsement.
- Curation flows through `scripts/sync_login_backgrounds.py` (stage candidates
  to the S3 staging bucket for live preview, then promote the keepers here).
