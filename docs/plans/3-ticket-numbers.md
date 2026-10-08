# Plan 3 - Next ticket number from remote branches, merged MRs or Jira

## Assumed meaning (check before handing off)

"Get the last ticket number from the remote repo (last MR or branch) or from Jira": a new ticket's
id should continue after the **highest number already used by the team**, not after this clone's
local counter. Today `Inbox.next_ids` only looks at this clone's inbox, history and active ticket,
so two people (or two clones) both create `T-001`.

## Settings

Add to `[intake]` (the UI section becomes **Ticket numbers**):

```toml
[intake]
id_prefix = "T"
id_source = "local"   # local | git | jira
```

- `local`: today's behaviour.
- `git`: the highest `<prefix>-<n>` found in remote branches + the base branch's commit history +
  local data.
- `jira`: the highest key in `jira.project_key` + local data. Only add this option if
  `ccorch_lib/jira.py` exists (plan 2 merged). Otherwise leave it out of the enum entirely.
  With `jira`, the prefix is `jira.project_key`: validation requires them to be equal (or the
  UI fills it in and locks the field).

## Module `ccorch_lib/ticket_ids.py` (stdlib only)

`next_ids(cfg, root, store, count) -> NextIds(ids: list[str], source: str, last: str | None,
warning: str | None)`

- `numbers_local(store, prefix)`: move today's logic out of `Inbox.next_ids` and keep
  `Inbox.next_ids` as a thin wrapper, or replace its callers.
- `numbers_git(git, cfg, prefix)`:
  - Open work: `git ls-remote --heads <remote>` (no fetch needed). Match branch names with
    `(?<![A-Za-z0-9])<prefix>-(\d+)(?!\d)`.
  - Merged MRs: their source branches are usually deleted (`mr.remove_source_branch = true`), but
    the ticket id survives in commit messages on the base branch: ccorch's
    `[PROJ-12] …` commits, GitLab's "Merge branch 'feature/PROJ-12-…' into 'main'", and squash
    commits carrying the MR title. Run `git fetch <remote> <base>` (quiet, uses the
    `GIT_TIMEOUT_S` timeout), then scan `git log -n 2000 --format=%s%n%b <remote>/<base>`.
  - Add a `Git.ls_remote_heads()` helper. Keep everything going through the `Git.run` wrapper.
- `numbers_jira(cfg, prefix)`: `client_for(cfg).search_last_key(project)` (it already returns the
  highest key, ordered by key).
- The result is always `max(local, source) + 1`, so local tickets are never reused. Pad to at least
  3 digits only when the source doesn't already use unpadded numbers: `T-001` stays as today, but
  if the remote highest is `PROJ-1412`, the next is `PROJ-1413`. Rule: use padding 3 for
  `local`; for other sources, copy the width of the highest match.
- If the source fails (offline, no remote, Jira down), fall back to local, set `warning` (e.g.
  "Couldn't read origin: … - numbered from this clone only"), and never raise.

## Where it's used

- `server.run_intake`: replace `inbox.next_ids(...)` with `ticket_ids.next_ids(...)` and return
  `id_source` and `id_warning` with the result. The Inbox shows the warning in the amber notes box.
  When plan 2's `create_in_jira` is on, the ids are previews that Jira replaces on save. Label them
  "(Jira assigns the key on save)".
- `GET /api/repos/{id}/next-id?count=1` → `{ids, source, last, warning}`. Used by the **Check**
  button and the **New ticket** button.
- New `ccorch next-id [--count N]`: prints the ids one per line, then
  `# source: git (highest PROJ-141 on origin)` or the warning.
- New `ccorch inbox add --type T --title "…" [--description "…"] [--criteria "…" ...]
  [--size small|big] [--id ID]`: without `--id`, takes the next id. If plan 2 is merged and
  `jira.create_issues` is on, creates the Jira issue and uses its key. Saves to the inbox and
  prints the id on the first line.
- Skill (`skills/ticket/SKILL.md`): accept `new` as the first word,
  `/ccorch:ticket new Fix the invoice footer`. In that case, step 1 is: draft type, short title,
  description and acceptance criteria from the text, run `ccorch inbox add …`, and use the printed
  id from then on. Update `argument-hint` to `<TICKET-ID|new> [quick|plan] [auto] [ticket
  text...]`.

## UI

- `RepoSettings.tsx` **Ticket numbers** section: ID prefix, Source select (local / remote git /
  Jira), and a **Check** button showing "Last used: PROJ-141 (origin) → next PROJ-142" or the
  warning. Hints: local = "this clone only"; git = "open branches on the remote + the base
  branch's history, so merged MRs count too".
- `InboxView.tsx`: a **+ New ticket** button that adds an empty draft card with the next id (from
  `next-id`) to the review list, so a ticket can be written by hand and saved like extracted ones.
- `api.ts` types. Rebuild `static/`.

## Tests

- `tests/test_ticket_ids.py` with a bare origin (fixtures in `tests/conftest.py`): push branch
  `feature/PROJ-7-x`; on main, commit `[PROJ-12] y` and a message "Merge branch
  'fix/PROJ-15-z' into 'main'" whose branch no longer exists; add local inbox `PROJ-3` → next is
  `PROJ-16` (highest is `PROJ-15`; width copied from it).
- No remote / unreachable remote → local numbering + warning.
- Prefix matching doesn't match `XPROJ-99` or `PROJ-12a`.
- `ccorch next-id`, `ccorch inbox add` (without Jira; with the fake Jira from `tests/` if plan 2 is
  merged).
- Server `next-id` endpoint and intake returning `id_warning`.
- Config validation for `id_source` (and the prefix = project key rule for `jira`).

## Docs

README: the "Tickets from transcripts" step 3 text about `T-001` gets a short "Ticket numbers"
paragraph (sources, and that merged MRs count because their commits are on the base branch).
Also: the Commands table (`/ccorch:ticket new …`), the helper command list (`next-id`,
`inbox add`), and the settings page section. CLAUDE.md: feature table row for `ticket_ids.py`.

## Out of scope

The GitLab API (no token; `refs/merge-requests/*` only gives SHAs, which is why merged MRs are
found through base-branch history instead). Reserving numbers across people, which would need a
server.
