# Implementation plans (handoff)

Written 2026-10-08 after auditing the repo against `README.md` and `CLAUDE.md`.

## Audit result

Everything the README and CLAUDE.md describe exists and works as far as tests can show:
`/ccorch:ticket` (quick/plan/auto), `/ccorch:mr`, `/ccorch:manage`, the three agents, the Stop and
SubagentStop gate hook, every `ccorch` subcommand listed in the README, config + validation, the
inbox and intake, the install plan, plugin/Claude Code updates, and the settings page (Settings,
Inbox and Activity tabs, versions box, marketplace). `uv run pytest` (30 passed), `ruff check`,
`mypy --strict` and both `claude plugin validate` pass. A fresh `vite build` produces exactly the
committed `static/` files.

Bugs found (fixed in plan 0):

1. Model `inherit` is accepted by validation but breaks: the intake call runs
   `claude -p --model inherit`, and the skill passes `inherit` as the Agent tool `model`, which
   only accepts real model names.
2. **Copy for terminal** builds `cd <path> && …` without quoting, so it breaks on paths with spaces.
3. Saving a draft whose id already exists overwrites the inbox ticket: a *started* ticket goes
   back to `queued` and loses its branch.
4. If `.claude/ccorch.toml` becomes invalid while a ticket is active, the Stop hook turns off the
   gate silently. CLAUDE.md says hook errors should become a `systemMessage`.

Still unverified, as CLAUDE.md already says: a live `/ccorch:ticket` run, a real GitLab push,
Windows, and **Open in Claude Code**. These plans don't change that.

About "a smaller model for the reviewer": you can already choose it. **Settings → Models → Reviewer**
offers opus/sonnet/haiku, and the skill passes your choice to the reviewer. Plan 1 adds the part
that's missing: a smaller reviewer picked automatically for small changes.

## Plans and order

| # | Plan | Size | Depends on |
|---|---|---|---|
| 0 | [Audit fixes](0-audit-fixes.md) | S | - |
| 1 | [Smaller reviewer model for small changes](1-reviewer-model.md) | S | 0 (both touch models) |
| 2 | [Jira: fetch, create, move between columns](2-jira.md) | L | - |
| 3 | [Next ticket number from remote branches / MRs / Jira](3-ticket-numbers.md) | M | 2 for the Jira source (optional) |
| 4 | [Edit tickets after they are launched](4-edit-tickets.md) | M | 0; 2 for Jira sync (optional) |

Run them **one at a time, in this order**, committing each directly on `main` before starting the next.
They all touch the same few files (`config.py`, `cli.py`, `server.py`, `api.ts`,
`RepoSettings.tsx`, `InboxView.tsx`, the ticket skill, README), so running them in parallel
would cause merge conflicts. Plans 3 and 4 check whether plan 2 is already merged
(`plugins/ccorch/scripts/ccorch_lib/jira.py` exists) and only add their Jira parts if it is.
You can give plans 0 and 1 to the same agent.

## Rules for every plan (agents: read this first)

- Read `CLAUDE.md` first. Its architecture rules apply: deterministic work lives in `ccorch` code,
  never in prompts; `scripts/ccorch_lib/` uses only the stdlib (Python ≥ 3.12, so HTTP goes through
  `urllib.request`); state lives in `.git/ccorch/`, never in the working tree or the plugin
  directory; every mutating server endpoint keeps the `guard` middleware (`X-CCorch: 1` + local Host).
- Follow the "How-tos" in CLAUDE.md for each new setting, `ccorch` subcommand or API endpoint. Each
  one has a defined checklist: DEFAULTS + validate + test → `api.ts` → form field → skill → README.
- Tests use real git repos in tmp dirs (`tests/conftest.py`) and fakes for every external program
  or service: a fake `claude` and, for Jira, a local fake HTTP server. Never call real `claude`,
  GitLab or Jira from tests.
- Older Claude Code (2.1.112) must keep working: no new manifest fields, shell-form hooks only.
- User-facing text (README, UI, skill output) uses plain English for someone new to the project.
  Update the README for every user-visible change, and update the CLAUDE.md feature table and the
  "Not yet verified" list.
- Do **not** bump the plugin version. Bump once when releasing after the plans are merged
  (suggested 0.5.0).
- Definition of done for every plan, all from the repo root:

  ```
  uv run pytest
  uv run ruff check && uv run ruff format --check
  uv run mypy
  claude plugin validate . && claude plugin validate ./plugins/ccorch
  cd manager-web && npm run build   # if any UI file changed; commit plugins/ccorch/manager/static
  ```

## Prompts to hand off

Paste one prompt per agent. Each prompt is self-contained.

### Plan 0 + 1 (one agent)

```
You are working in the ccorch-plugin repo (/Users/mariozitko/Projects/ccorch-plugin).
Read CLAUDE.md, then docs/plans/README.md (audit + rules for every plan), then implement
docs/plans/0-audit-fixes.md and after it docs/plans/1-reviewer-model.md.
Work directly on `main` (no new branch). The plans are the spec; where
they leave a detail open, follow the nearest existing code. Include the tests, UI changes (and
rebuild static/), README and CLAUDE.md updates each plan lists. Run every check in the
"Definition of done" until all pass. Commit (one commit per plan), do not push, do not bump the
plugin version. Finish with: what changed, any deviation from the plan and why, and what you
could not verify.
```

### Plan 2: Jira

```
You are working in the ccorch-plugin repo (/Users/mariozitko/Projects/ccorch-plugin).
Read CLAUDE.md, then docs/plans/README.md (rules for every plan), then implement
docs/plans/2-jira.md: a stdlib Jira client, credentials outside the repo, fetching an issue by
key, creating issues from the inbox, and moving issues between board columns (statuses) when
ccorch starts a ticket, opens the MR or abandons it.
Work directly on `main` (no new branch). Before writing the client, check Atlassian's current
REST docs for the endpoints listed in the plan's "Verify first" section and note in the code
which API version each call uses. Never contact a real Jira: tests use the fake HTTP server the
plan describes. Jira problems must never fail a ccorch command or block a session; they become
warnings. Never log, print, return or commit the API token.
Include the tests, the UI (rebuild static/), skill, README and CLAUDE.md changes the plan lists.
Run every check in the "Definition of done" until all pass. Commit, do not push, do not bump the
plugin version. Finish with: what changed, any deviation from the plan and why, and what still
needs testing against a real Jira.
```

### Plan 3: Ticket numbers

```
You are working in the ccorch-plugin repo (/Users/mariozitko/Projects/ccorch-plugin).
Read CLAUDE.md, then docs/plans/README.md (rules for every plan), then implement
docs/plans/3-ticket-numbers.md: new tickets get the next number after the highest one already
used, taken from remote branches and merged-MR commit history (and from Jira, if
plugins/ccorch/scripts/ccorch_lib/jira.py exists - plan 2 merged), plus `ccorch next-id`,
`ccorch inbox add`, `/ccorch:ticket new ...` and a "New ticket" button in the Inbox.
Work directly on `main` (no new branch). If jira.py does not exist, leave out the
`jira` source exactly as the plan says. Tests use bare git repos and, for Jira, the fake server
from tests/ (never a real service). Include the tests, UI (rebuild static/), skill, README and
CLAUDE.md changes. Run every check in the "Definition of done" until all pass. Commit, do not
push, do not bump the plugin version. Finish with: what changed, any deviation from the plan and
why, and what you could not verify.
```

### Plan 4: Edit tickets after launch

```
You are working in the ccorch-plugin repo (/Users/mariozitko/Projects/ccorch-plugin).
Read CLAUDE.md, then docs/plans/README.md (rules for every plan), then implement
docs/plans/4-edit-tickets.md: inbox tickets can be edited in the settings page at any time,
including after "Open in Claude Code" started them; the running /ccorch:ticket session picks the
change up at its next step through `ccorch ticket-check`.
Work directly on `main` (no new branch). If
plugins/ccorch/scripts/ccorch_lib/jira.py exists (plan 2 merged), also do the plan's Jira sync
part; otherwise skip it. Keep the main session lean: ticket-check prints only what changed.
Include the tests, UI (rebuild static/), skill, README and CLAUDE.md changes. Run every check in
the "Definition of done" until all pass. Commit, do not push, do not bump the plugin version.
Finish with: what changed, any deviation from the plan and why, and what you could not verify.
```
