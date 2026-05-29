## GitLab Project
Remote: gitlab.com/saic-study-group/beelzabub-project
Issues and MRs live here. Epics live at the saic-study-group level.

## Workflow — Issue-First, User-Gated
1. Before writing any code, create a GitLab issue with: what, why, acceptance criteria.
2. Wait for user to review and approve the issue in GitLab before starting.
3. Propose branch name — wait for user approval, then create it via the GitLab API
   (not `git checkout -b`), so it appears in the issue's Development section immediately:
   ```python
   project.branches.create({'branch': 'feature/NNN-short-description', 'ref': 'main'})
   ```
   Then check out locally: `git fetch origin && git checkout feature/NNN-short-description`
   Branch prefixes: `feature/` for features, `bugfix/` for bugs.
4. Commit with `Refs #NNN` throughout. Final commit or MR: `Closes #NNN`.
5. When implementation is complete, open a Merge Request and wait for user approval
   before merging.
6. Update the issue description with what was actually implemented — design decisions,
   approach taken, any deviations from the original plan.

## Session Start (Standup)
Each session opens with:
- Issues closed since last session
- What's currently in progress
- Any blockers

## Claude Configuration Branch
All changes to `CLAUDE.md`, `.claude/` settings, skills, and hooks go on the
persistent `config/claude` branch — never committed directly to main.
The branch is never deleted; MRs from it to main are opened when a batch of
config changes is ready, then the branch continues for future work.
No GitLab issue is required for config-only changes.

## Labels (dev tracking)
Issues use: type::feature, type::bug, type::chore
Status tracked via GitLab issue open/close state + milestone.
