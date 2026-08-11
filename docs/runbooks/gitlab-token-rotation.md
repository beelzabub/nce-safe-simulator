# Runbook — rotating the GitLab credentials

Issue #318. Written because the 2026-07-31 weekly deck run died at `git pull` on an
expired token, and rotating it meant finding every copy under time pressure with no
written procedure.

**Read this first, before you start editing files:** the boxes do not hold *one* token
in several places. The deck box holds **three distinct GitLab credentials** across five
locations. Replacing "the token" everywhere with a single new value will silently change
what three different consumers authenticate as.

---

## When you need this

- The weekly deck run fails at the **credentials pre-flight** (`git auth pre-flight —
  cannot reach origin over HTTPS`). That is the #258 guard doing its job; this runbook is
  the recovery.
- A token is expiring, was exposed, or is being rotated on schedule.
- `glab` works but `git pull` fails, or vice versa — the classic symptom of a *partial*
  rotation, because each consumer reads a different copy.

---

## The credential map

### Deck box (`powers-dev`, work happens as `root`)

| # | Location | Field | Consumer | Distinct credential |
|---|---|---|---|---|
| 1 | `~/.config/nce/env` | `GITLAB_TOKEN` | interactive shells; anything sourcing it | **A** |
| 2 | `/root/.venv/nce-safe-simulator/config.json` | `private_token` | the app in the live clone | **A** (same value) |
| 3 | `/root/.venv/nce-safe-simulator-2/config.json` | `private_token` | the app the **Friday cron** redeploys | **A** (same value) |
| 4 | `~/.git-credentials` | https password | `git pull` / `git push` over HTTPS | **B** |
| 5 | `~/.config/glab-cli/config.yml` | `hosts.gitlab.com.token` | the `glab` CLI | **C** |

Credential **B** is what failed on 2026-07-31. Credential **C** is a different length and
format from A and B — `glab` keeps its own and will keep working while the others are
stale, which is exactly why a partial rotation is hard to notice.

### Dev workstation (nce-git-ops #32)

| # | Location | Field | Consumer | Distinct credential |
|---|---|---|---|---|
| 1 | `~/.config/nce/env` | `GITLAB_TOKEN` | **everything** | **A** (same value as the deck box) |

The workstation stores the credential **once**. `git` reads it through a host-scoped
credential helper that pulls `$GITLAB_TOKEN` from the environment (nce-git-ops `c71875e`),
`glab` reads the same environment variable, and the simulator clone's `config.json` has
`private_token` deliberately **empty** so the app falls through to the env var.

Because the workstation shares credential **A** with the deck box, rotating A means
updating both machines.

### Confirming the map yourself

Fingerprints are not recorded here — they change on every rotation, and a stale fingerprint
in a doc is worse than none. Derive them when you need them; this prints which locations
agree without revealing any value:

```sh
fp() { printf '%s' "$1" | sha256sum | cut -c1-12; }

fp "$(grep -E '^[[:space:]]*export[[:space:]]+GITLAB_TOKEN=' ~/.config/nce/env \
      | head -1 | sed -E "s/^[^=]*=//; s/^['\"]//; s/['\"]$//")"
fp "$(python3 -c "import json;print(json.load(open('/root/.venv/nce-safe-simulator/config.json'))['private_token'])")"
fp "$(python3 -c "import json;print(json.load(open('/root/.venv/nce-safe-simulator-2/config.json'))['private_token'])")"
fp "$(sed -E 's#^https://[^:]*:##; s#@.*##' ~/.git-credentials | head -1)"
fp "$(awk '/^hosts:/{h=1} h && /^[[:space:]]+token:/{sub(/^[[:space:]]*token:[[:space:]]*/,"");print;exit}' ~/.config/glab-cli/config.yml)"
```

Note `~/.config/nce/env` contains **commented placeholder lines** above the real ones
(`# export GITLAB_TOKEN=''`). Match on `^\s*export`, or a naive `grep | head -1` reads the
placeholder and returns empty.

---

## Rotation procedure

Decide first whether you are rotating **all three** credentials or just the one that
expired. Rotating only the expired one is legitimate and lower-risk; rotating all three
onto a single new token is the cleanup, and it changes behaviour (see *Target state*).

### 0. Mint the new token

GitLab → **Settings → Access Tokens** → scopes `api`, `read_repository`, `write_repository`.
Record the expiry somewhere you will see it before it lapses.

### 1. `~/.config/nce/env` (credential A)

```sh
cp ~/.config/nce/env ~/.config/nce/env.rotate-$(date -u +%Y%m%dT%H%M%SZ)   # see cleanup note
${EDITOR:-vi} ~/.config/nce/env      # replace the value on the `export GITLAB_TOKEN=` line
chmod 600 ~/.config/nce/env
```

**Verify:**
```sh
. ~/.config/nce/env
curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" https://gitlab.com/api/v4/user | python3 -m json.tool | head -5
```

**Cleanup note:** delete that backup once the rotation is verified. Backups of this file
are how three cleartext copies of a dead credential survived until 2026-08-11.

### 2 & 3. Both `config.json` copies (credential A)

Both clones, on the deck box only:

```sh
for d in /root/.venv/nce-safe-simulator /root/.venv/nce-safe-simulator-2; do
  python3 - "$d/config.json" "$GITLAB_TOKEN" <<'PY'
import json, sys
p, tok = sys.argv[1], sys.argv[2]
c = json.load(open(p))
c['private_token'] = tok
json.dump(c, open(p, 'w'), indent=2)
print("updated", p)
PY
done
```

Both files are gitignored, so this is not a repo change.

**Verify:** the running app must be recreated to pick it up — `config.json` is bind-mounted,
but the app reads it at start:
```sh
cd /root/.venv/nce-safe-simulator && ./scripts/redeploy.sh --image nce-safe-simulator:latest
curl -sf -o /dev/null -w '%{http_code}\n' http://localhost:8080/
```

### 4. `~/.git-credentials` (credential B — the one that broke the Friday run)

```sh
${EDITOR:-vi} ~/.git-credentials     # line format: https://oauth2:<TOKEN>@gitlab.com
chmod 600 ~/.git-credentials
```

**Verify — in *both* clones, because the cron uses the `-2` one:**
```sh
git -C /root/.venv/nce-safe-simulator   ls-remote origin HEAD >/dev/null && echo "clone 1 OK"
git -C /root/.venv/nce-safe-simulator-2 ls-remote origin HEAD >/dev/null && echo "clone 2 OK"
```
This is the exact check the weekly pre-flight runs. If it passes here, the Friday run gets
past step 1.

### 5. `~/.config/glab-cli/config.yml` (credential C)

```sh
glab auth login --hostname gitlab.com --token <NEW_TOKEN>
```

**Verify:**
```sh
glab api user | python3 -c 'import json,sys; print(json.load(sys.stdin)["username"])'
```

### 6. Dev workstation

Repeat **step 1 only**. Then verify all three consumers, which on this box all read the
one variable:
```sh
. ~/.config/nce/env
git ls-remote origin HEAD >/dev/null && echo "git OK"
glab api user >/dev/null && echo "glab OK"
```

---

## Full verification checklist

Rotation is not done until every consumer is checked — each reads a different copy, so
one passing tells you nothing about the others.

- [ ] `curl` with `PRIVATE-TOKEN` returns your user (credential A)
- [ ] `git ls-remote` succeeds in **clone 1** (credential B)
- [ ] `git ls-remote` succeeds in **clone 2** — the cron's clone (credential B)
- [ ] `glab api user` returns your username (credential C)
- [ ] app health check returns 200 after redeploy (credential A via `config.json`)
- [ ] workstation `git` + `glab` both succeed (credential A)
- [ ] rotation backups of `~/.config/nce/env` deleted
- [ ] new expiry date recorded

A no-cost end-to-end proof: run the weekly build against a branch without waiting for
Friday — `WEEKLY_REF=<branch> systemctl start nce-status-deck.service`, then watch
`journalctl -u nce-status-deck.service -f`. It exercises the pre-flight, the pull and the
redeploy in the real cron environment.

---

## The `config.json` dependency — do not "fix" this

`deck/systemd/nce-status-deck.service` sets **no** `GITLAB_TOKEN`, and systemd does not read
`~/.bashrc`. So the Friday cron's `scripts/redeploy.sh` passes `-e GITLAB_TOKEN=""` to the
app container.

That is **harmless, not a bug.** `NceGitLab.py` resolves the token as
`GITLAB_TOKEN` env → `config.json` `private_token` → `ACCESS_TOKEN` (deprecated), and the
env check is `if gitlab_token_env:` — an empty string is falsy, so resolution falls through
to `private_token`, which is populated.

**The consequence that costs a Friday:** the app on the deck box silently depends on the
`config.json` copy, *not* the environment. Anyone who removes `private_token` on the
assumption that the environment carries it will break the Friday deploy, and will not find
out until Friday.

If you want the env var to reach the cron path, that is the `EnvironmentFile=` change in
*Target state* below — do it deliberately, with a real timer run to prove it, not as a
drive-by.

---

## Known residue: session transcripts

Rotating does **not** clean historic copies. As of 2026-08-11 the live GitLab token appeared
in cleartext in 10 files under `/root/.claude` and the GitHub token in 6 — session
transcripts (`projects/**/*.jsonl`) and `file-history/` snapshots, written when a session
read the shell config files.

Two consequences worth keeping straight:

- **This is exposure, not just rotation surface.** The config files themselves are
  gitignored or outside the repo, so none of this is a repo leak — but plaintext live
  credentials in append-only logs that nobody audits or rotates is a different problem
  from having too many copies to update.
- **Rotation fixes it for free.** Once the old value is dead, every historic copy is
  worthless. That is the strongest argument for rotating all three credentials rather than
  only the expired one.

If you rotate only the expired credential, purge the matching transcripts instead:
```sh
grep -rl -F "$OLD_TOKEN" /root/.claude          # review before deleting
```

---

## Target state

The dev workstation already implements what the deck box should look like: **one credential,
in one file, with every consumer reading it from the environment.** No `private_token`, no
`~/.git-credentials`, no stored `glab` token.

Two changes would bring the deck box there. Both are optional and neither is required to
rotate a token — they reduce how much work the *next* rotation is:

1. **`EnvironmentFile=-/root/.config/nce/env`** in the systemd unit. Requires the env file to
   drop the `export ` prefixes (systemd wants bare `KEY=value`) and `~/.bashrc` to source it
   with `set -a`. The env var then reaches the cron path, making `private_token` redundant so
   it can be emptied — removing the copy most likely to leak, since `config.json` is exported
   and imported through the web UI.
   **Prove it with a real timer run before trusting it**; the failure mode is a Friday outage.
2. **Point `git` at the same token** via a host-scoped credential helper, as the workstation
   does, so `~/.git-credentials` stops being a separate credential. See nce-git-ops `c71875e`
   — deliberately a helper reading `$GITLAB_TOKEN`, not `~/.git-credentials`, so no second
   copy is written to disk.

Doing both collapses five locations and three credentials into one of each, and this runbook
becomes a single step.
