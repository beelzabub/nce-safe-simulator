# Runbook — rotating the GitLab and GitHub credentials

Issue #318. Written because the 2026-07-31 weekly deck run died at `git pull` on an
expired token, and rotating it meant finding every copy under time pressure with no
written procedure.

**The short version, on any box with AWS access:**

```sh
nce-credentials check      # what is stored, is it healthy, when does it expire
nce-credentials rotate     # replace it — one write, every box, verified
```

Everything below explains what that does, what to do where it does not apply, and
what changed from the five-location model this runbook used to describe.

---

## The model

One value per credential, stored once in **SSM Parameter Store**, fetched by every
consumer at the moment it is needed:

| Credential | Stored | Read by |
|---|---|---|
| GitLab token | `/nce/gitlab/token` (SecureString) | shells, `git` via the credential helper, `glab`, the app, the weekly deck run |
| GitHub token | `/nce/github/token` (SecureString) | shells, `git` via the credential helper, `gh` |
| AWS | **not stored — cannot be** | the EC2 instance role |

Nothing is written to disk on any box. Rotation is one `put-parameter`, and a rebuilt
workstation is prompted for no token at all — it inherits read access from its instance
role.

### Why AWS is not in the table

You need AWS credentials to read Parameter Store, so the AWS credential is the one that
can never live in it. It is also the credential that *guards* the others: a static key
sitting on disk next to a fetch script does not reduce exposure, it just moves it —
anyone who takes the box takes the key and then reads every token in SSM.

So AWS access comes from the **instance role**: short-lived, machine-bound, rotated by
EC2, and impossible to exfiltrate at rest. `nce-credentials check` verifies this by
asking what *kind* of identity is in play, and flags static IAM user keys as a finding.

### The precedence ladder — SSM is a source, not the source

This must not make the code less portable than it was. The simulator runs in CI, in
containers, on laptops, and on boxes somebody cloned it onto with their own token —
none of which have an instance role or any reason to reach Parameter Store. The
existing precedence is preserved exactly and SSM slots in as a fallback:

1. `$GITLAB_TOKEN` / `$GITHUB_TOKEN` **already in the environment** — a CI/CD masked
   variable, a manual export, `-e` on a container. **Always wins.**
2. **SSM Parameter Store** — fetched into that variable only when it is unset.
3. **`config.json` `private_token`** — the app's own fallback, in `NceGitLab.py`,
   untouched by any of this.
4. **`ACCESS_TOKEN`** — deprecated, still honoured.

Every fetch site is guarded with `[ -n "${GITLAB_TOKEN:-}" ] ||`, so a runner with a CI
variable set never calls AWS at all, and a box with no AWS access falls through to
`config.json` exactly as it does today.

`nce-credentials check` resolves through the same ladder and **reports which rung
answered** — validating a copy the consumers will not use is worse than not checking.

---

## Rotating

### On a box with AWS access (the workstation, the deck box)

1. Mint the new token. GitLab → **Settings → Access Tokens**, scopes `api`,
   `read_repository`, `write_repository`. GitHub → **Settings → Developer settings →
   Personal access tokens**, scope `repo`.
2. `nce-credentials rotate` — prompts for each (hidden input), writes to SSM, then
   verifies every consumer before declaring success.
3. Nothing else. No box is touched, no file is edited, no service is restarted. Shells
   already open still hold the old value in their environment; start a new one.

Rotation is also the exposure fix. Once the old value is dead, **every historic copy is
worthless** — including any that leaked into logs, session transcripts or backups. That
is the argument for rotating all credentials at once rather than only the expired one.

### Anywhere else

A box with no AWS access supplies its own credential through the environment or
`config.json`, and owns replacing it by whatever route it came in — a CI/CD variable is
rotated in the GitLab UI, a container's `-e` flag in whatever launches it.
`nce-credentials rotate` will tell you this rather than pretending to help.

---

## Checking before it breaks

`nce-credentials check` validates each credential **three ways**, and the first is the
weakest:

- **It authenticates.** The check everyone writes.
- **It carries the scopes its consumers need.** A token missing a scope authenticates
  perfectly and then fails on the first push — a green pre-flight followed by a red
  deploy. Override the requirement with `NCE_GITLAB_REQUIRED_SCOPES` when a job
  legitimately needs less (a read-only reporting box run with `read_api`).
- **It is not about to expire.** Default 14 days' warning. *This is the one that
  matters.* A token that authenticates today and lapses on Thursday passes every binary
  valid/invalid test and still kills the Friday deck run — which is exactly the
  2026-07-31 outage. The threshold exceeds the gap between the runs that would reveal
  it.

It runs automatically as the last step of the workstation build (`validate.yml`) and
is the recovery route named by the weekly deck run's pre-flight.

### When a box is stale

Failing validation writes `/var/lib/nce/credentials-stale`. Every login then prints a
banner, and the consumers refuse to run.

It is deliberately **not** a lock on the shell or on SSH. Bug #324 was that mistake in a
different costume — a guard that refused to deploy and thereby broke the documented
recovery path it was telling the operator to run (fixed in `e490d0e`, *"Fix the guard
breaking the bring-up it tells you to run"*). A credential gate that can bar you from
the box is a gate that can stop you fixing the credential. So: nothing real works, you
cannot miss why, and the route to fixing it is never blocked.

`nce-credentials rotate` clears the marker on success.

---

## What changed, and what to un-learn

This runbook used to describe **five locations holding three distinct credentials** on
the deck box. If you remember that model, these are the parts that are now wrong:

| Was | Now |
|---|---|
| `~/.config/nce/env` held the token | Holds no secret. Comments only, plus an escape hatch you normally leave empty. |
| `config.json` `private_token` held a second copy | Still read by the app as rung 3, but left empty on migrated boxes. |
| `~/.git-credentials` held a **different** credential | Gone. `git` uses a host-scoped helper reading `$GITLAB_TOKEN`. |
| `glab` held a **third** credential | Gone. `glab` reads the environment. |
| Rotation meant editing five files on two boxes | One `nce-credentials rotate`. |
| `EnvironmentFile=` on the systemd unit was the planned fix | **Not taken, and no longer needed** — see below. |

### The `EnvironmentFile=` change was dropped on purpose

It existed to get `GITLAB_TOKEN` into the Friday cron's process, because systemd does
not read `~/.bashrc`. `deck/weekly-status-deck.sh` now fetches the token itself, which
achieves the same thing without reformatting `~/.config/nce/env` to bare `KEY=value`,
without switching `.bashrc` to `set -a`, and without coupling the deck's systemd unit to
the workstation's ansible — a cross-repo change whose failure mode was an unattended
Friday outage.

### The `config.json` dependency — still worth knowing

`deck/systemd/nce-status-deck.service` sets no `GITLAB_TOKEN`, so before #318 the cron's
`redeploy.sh` passed `-e GITLAB_TOKEN=""` to the app container and `NceGitLab.py` fell
through to `private_token`. That was harmless (an empty string is falsy) but it meant
the Friday run silently depended on a copy nobody rotated.

The fetch removes the dependency. **Verify it with a real run before emptying
`private_token` on the deck box** — the failure mode is still a Friday outage:

```sh
WEEKLY_REF=<branch> systemctl start nce-status-deck.service
journalctl -u nce-status-deck.service -f
```

Look for `credentials: GITLAB_TOKEN fetched from SSM` in the log.

---

## Open: the static AWS keys

`/root/.aws/credentials` on the workstation holds **long-lived keys for the IAM user
`powerja`**. Because file credentials take precedence over IMDS, every `aws` call on the
box runs as that human user rather than as the `nce-workstation` role — which is why
`aws route53` works there while the instance profile has no Route 53 access.

They are not needed for anything this runbook describes: the instance role covers the
SSM reads. What they *are* still needed for is **terraform** and other admin-shaped work
run from the box. A 30-day CloudTrail review of `powerja` shows only read-only describes
— and no Route 53 calls at all — but that is a thin sample, and terraform apply needs
`iam:*` and `ec2:*` writes.

Deliberately **not** resolved here, because the obvious fix is the wrong one: granting
the instance role terraform's permissions would let any compromise of the box escalate
to account admin, which is a worse position than the static key it replaced. The
options, in preference order:

1. Run terraform from an operator machine under short-lived SSO credentials, and delete
   `/root/.aws/credentials` from the box entirely. The box keeps its role for runtime.
2. Keep a static key but move it off the shared boxes.
3. Accept the exposure, knowingly.

`nce-credentials check` will keep reporting it until it is gone.

---

## Verification checklist

- [ ] `nce-credentials check` is green on every box with AWS access
- [ ] a fresh login shell has a non-empty `GITLAB_TOKEN` with nothing on disk:
      `env -i HOME=/root bash -lc 'echo ${#GITLAB_TOKEN}'`
- [ ] `git ls-remote origin HEAD` succeeds in each clone the cron uses
- [ ] `glab api user` returns your username
- [ ] `gh api user` returns your username
- [ ] the app answers after a redeploy
- [ ] a real timer run logs `GITLAB_TOKEN fetched from SSM`
- [ ] no `glpat-`/`ghp_` anywhere in `~/.config/nce/env`, `~/.bashrc`, `~/.git-credentials`
- [ ] new expiry recorded, and `check` reports more than 14 days
