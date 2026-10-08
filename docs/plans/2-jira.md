# Plan 2 - Jira: fetch, create, and move tickets between columns

## Goal

1. `/ccorch:ticket PROJ-123` reads the issue straight from Jira. This must not depend on an MCP
   tool being installed.
2. Tickets made in the Inbox (from a transcript) can be created as Jira issues. Jira assigns the key
   (`PROJ-456`), and that key becomes the ticket id.
3. Issues move between board columns automatically: **In Progress** when `ccorch start` creates the
   branch, **In Review** when `ccorch mr` opens the MR, optionally somewhere else when abandoned.
   They can also be moved by hand from the settings page.

Every Jira call is deterministic code in `ccorch`, never a prompt. If Jira is down or misconfigured,
nothing else may break: the branch, commit or MR still happens and the user sees a warning.

## Verify first (Atlassian docs, before coding)

- Issue get/create/edit, transitions, comments, `myself`, project: `/rest/api/2/...` should work on
  both Cloud and Server/Data Center, and v2 takes a plain-text (wiki markup) `description`, so no
  ADF is needed. Confirm this still holds for Cloud.
- Search: Jira Cloud replaced `/rest/api/2|3/search` with `/rest/api/3/search/jql`, while
  Server/DC still uses `/rest/api/2/search`. Confirm. Only plan 3 needs search, but put
  `search_last_key` in the client now.
- Auth: Cloud = Basic `email:api_token`. Server/DC = `Authorization: Bearer <personal access token>`.
- A board column maps to one or more statuses. Moving an issue = POST a transition whose `to.name`
  is the target status, picked from `GET /issue/{key}/transitions`.

Write the API version each call uses in a comment next to it.

## Settings

Shared, in `.claude/ccorch.toml` (no secrets), added to `config.DEFAULTS`:

```toml
[jira]
enabled = false
url = ""                 # https://yourcompany.atlassian.net (no trailing slash)
deployment = "cloud"     # cloud | server
project_key = ""         # PROJ
create_issues = false    # Inbox "Save" also creates the issues in Jira
comment_mr_link = true   # add a comment with the MR link when the MR is opened

[jira.issue_types]       # Jira issue type per ccorch ticket type
feature = "Story"
bug = "Bug"
task = "Task"

[jira.move_to]           # target status (= board column) per workflow event; "" = don't move
start = "In Progress"
mr_opened = "In Review"
abandoned = ""
```

`config.validate()`: when `enabled`, require `url` starting with `http://` or `https://`,
`project_key` matching `^[A-Z][A-Z0-9_]{0,19}$`, and `deployment` in (`cloud`, `server`). All
values must be strings or bools of the right type even when disabled. `dumps()` already writes
nested tables. Check that a round-trip test covers `[jira.issue_types]` and `[jira.move_to]`.

**Credentials are personal and never in the repo or the plugin directory.**
- Environment variables win: `CCORCH_JIRA_TOKEN`, plus `CCORCH_JIRA_EMAIL` for Cloud.
- Otherwise `~/.ccorch/credentials.json` stores `{"jira": {"<url>": {"email": "...", "token": "..."}}}`,
  keyed by the normalized URL (lowercase, no trailing slash). Write it with mode 0600 (skip
  `chmod` on Windows). Writes go through a temp file + `replace`, like `StateStore.save`.
- Move the home directory logic out of `server.registry_path()` into a new
  `ccorch_lib/home.py` `ccorch_home()` that still honors `CCORCH_MANAGER_HOME`. The CLI and the
  server must use the same directory.

## Jira client: `ccorch_lib/jira.py` (stdlib only)

- `JiraError(RuntimeError)`, with a short message: HTTP status + Jira's `errorMessages`/`errors`.
  It must never contain the token or the auth header.
- `Creds` dataclass, `load_creds(url) -> Creds | None`, `save_creds(url, email, token)`,
  `creds_status(url) -> {"has_token": bool, "email": str, "from_env": bool}`.
- `Jira(url, deployment, creds, timeout_s=15)`, using `urllib.request` with a JSON body and
  `Accept: application/json`:
  - `myself()`, `project(key)` (name + issue types), `statuses(key)` (status names of the project)
  - `get_issue(key) -> Issue` (key, url `<base>/browse/<key>`, summary, description, type name,
    status name, updated)
  - `create_issue(project, type_name, summary, description) -> key`
  - `update_issue(key, summary, description)` (plan 4 uses it)
  - `transitions(key)`; `move(key, status) -> "moved" | "already" | "no_transition"`, matching the
    status name without case (and accept the transition name as a second choice)
  - `comment(key, text)`
  - `search_last_key(project) -> str | None` (plan 3 uses it; JQL
    `project = X ORDER BY created DESC`, maxResults 1, fields key)
- `client_for(cfg) -> Jira | None`: `None` if disabled or no credentials.
- Text format: `ticket_description(t)` = description + `\n\nh3. Acceptance criteria\n* …`. The
  reverse, `parse_issue(issue) -> inbox ticket dict`, splits the description on that heading when
  present and maps the issue type back via `issue_types` (unknown → `task`).
- `is_jira_key(cfg, ticket_id)`: Jira enabled and the id matches `^{project_key}-\d+$`.

## Where `ccorch` talks to Jira

All calls are best-effort. Wrap them in one helper, `_jira_event(ctx, state, event)`. It prints
`Jira: PROJ-12 → In Progress`, `Jira: PROJ-12 already In Progress`, or
`Jira warning: <reason>` and never changes the exit code. Pass the comment through the same
helper. Ticket state gets `jira_key: str | None`.

- `cmd_inbox show ID`: when the id isn't in the inbox and `is_jira_key`, fetch it, save it to the
  inbox (`source: "jira"`, `jira_key`, `jira_url`, `jira_status`, `jira_updated`, status
  `queued`), and print the markdown plus a `Jira: <url> (status: X)` line. If Jira fails, print
  the reason and exit 1 so the skill falls back to asking the user.
- `cmd_start`: after the branch is created, set `state.jira_key` (from the inbox record or
  `is_jira_key`), then run `_jira_event(..., "start")`.
- `cmd_mr`: after the push, run `_jira_event(..., "mr_opened")`, and if `comment_mr_link` and an
  MR url exists, comment `Merge request: <url>`.
- `cmd_finish`: run `_jira_event(..., outcome)` only when that outcome has a `move_to` entry
  (`abandoned`).
- New `ccorch jira` subcommand: `status [KEY]` (default: the active ticket), `move KEY STATUS`,
  `show KEY`. It's for the user or the skill when asked; allowed through `Bash(ccorch *)`.
- `cmd_context`: add `- Jira: PROJ on <url> (credentials: ok|missing)` when enabled.

## Settings page

Server (`create_app`), all behind `guard`. Add typed clients in `api.ts` and `TestClient` tests.
- `GET /api/jira/credentials?url=` → `creds_status` (never the token).
- `PUT /api/jira/credentials` `{url, email, token}` → saves. An empty token keeps the stored one.
- `POST /api/repos/{id}/jira/test` `{config}` → `{ok, user, project_name, issue_types,
  statuses, problems[]}`. Problems include a configured issue type or move-to status the project
  doesn't have.
- `POST /api/repos/{id}/inbox` accepts `create_in_jira: bool`. Create the issues one by one,
  replace each draft's id with the new key, and save it with its Jira fields. If some fail, save
  the ones that worked and return `{saved, failed: [{draft, error}]}`. The UI keeps the failed
  drafts on screen so nothing typed is lost.
- `GET /api/repos/{id}/jira/issue/{key}` → status + available target statuses.
  `POST /api/repos/{id}/jira/issue/{key}/move` `{status}`.

UI:
- `RepoSettings.tsx`: new **Jira** section with Enabled, URL, Cloud/Server, Project key, Create
  issues from the Inbox, Comment MR link, issue type per ticket type, and "Move to column" for
  start / MR opened / abandoned. After a successful test, those three fields use a datalist of the
  project's statuses. Hint: "A board column shows one or more statuses - enter the status the
  ticket should get."
  Below it, a **Your Jira login** box saved separately, not in the toml: email (Cloud only) and an
  API token (password input; a "saved" badge when one is stored; link to
  https://id.atlassian.com/manage-profile/security/api-tokens for Cloud), with **Save login** and
  **Test connection** buttons.
- `InboxView.tsx`: when Jira is enabled and `create_issues` is on, add a checkbox next to **Save
  to inbox**, "Also create in Jira (PROJ)", checked by default. Queued cards show the Jira key as a
  link and a status badge. When opened, a card shows a **Move to…** select that loads the
  statuses lazily.
- `ActivityView.tsx`: link the Jira key when present.
- Rebuild `static/`.

## Skill

`skills/ticket/SKILL.md` step 1: "Run `ccorch inbox show <ID>`. It finds the ticket in the inbox
or, for Jira keys, in Jira. If it prints nothing useful and another issue tracker tool is
available, use that; otherwise ask the user." Rules: "Never move or edit Jira issues with other
tools; `ccorch` does it." Step 7 report: include the `Jira:` lines.

## Tests: `tests/test_jira.py`

Build a fake Jira with `http.server.ThreadingHTTPServer` on `127.0.0.1:0` in a thread. Keep issues
in memory and implement the endpoints above, so tests can assert on the requests it received
(method, path, auth header, body). Cover:
- the auth header for cloud and server; `JiraError` text never contains the token
- credentials: env beats file, file mode 0600 (POSIX only), the API never returns the token
- create → key; `move` by status name, `already`, `no_transition`
- `ccorch start` / `mr` / `finish --outcome abandoned` move the issue (use the bare-origin repo
  from the flow test; `mr` needs a bare remote that accepts push options, as the existing tests
  do). With the fake server stopped, the same commands still exit 0 and print `Jira warning`.
- `ccorch inbox show PROJ-5` fetches and caches the issue
- server: credentials endpoints, `jira/test` problems, inbox save with `create_in_jira` including
  partial failure
- config validation for the new section

## Docs

- README: new **Jira** section covering setup (token link, where the login is stored, that it's
  never committed), what moves when, how columns map to statuses, and manual moves. Also update
  the Commands table (`ccorch jira …` in the helper list), the settings page section, Tickets from
  transcripts ("Also create in Jira"), and Troubleshooting (401 = wrong email/token; "no
  transition to X" = the workflow can't go there from the current status).
- CLAUDE.md: feature table row (`ccorch_lib/jira.py`, `home.py`), an architecture rule
  ("Credentials live in `~/.ccorch/credentials.json` or env vars, never in the repo or plugin
  dir; Jira failures are warnings"), and "Not yet verified: against a real Jira Cloud and Server".

## Out of scope

OAuth, webhooks or syncing status back from Jira, bulk import of a Jira board into the inbox,
custom fields (e.g. a separate acceptance-criteria field), sprints, assignees.
