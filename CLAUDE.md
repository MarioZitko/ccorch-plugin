# ccorch-plugin

Claude Code plugin + its own marketplace (GitHub: `MarioZitko/ccorch-plugin`, marketplace name
`ccorch-tools`, plugin id `ccorch@ccorch-tools`). It takes a ticket to a GitLab merge request:
named branch → plan (or quick path) → implementation with a build/test gate → AI review → MR.
A local settings page configures each repo, installs the plugin into repos, turns transcripts
into tickets and updates the plugin.

- User docs: `README.md` (must stay correct for a brand-new user).
- Why this exists: `~/Projects/coding/docs/adr/0001-claude-code-plugin-instead-of-desktop-app.md`.
  `~/Projects/coding` is the old PySide6 app - frozen reference, the ported logic lives here.

## Features (where each one lives)

| Feature | Files |
|---|---|
| `/ccorch:ticket` workflow (steps 0-7, quick vs plan path, flags `quick` `plan` `auto`) | `plugins/ccorch/skills/ticket/SKILL.md` |
| `/ccorch:mr`, `/ccorch:manage` | `skills/mr/SKILL.md`, `skills/manage/SKILL.md` |
| Subagents: planner (opus, read-only), implementer (sonnet), reviewer (opus, read-only); `ccorch review-model` picks the reviewer model (cheaper for small changes) | `plugins/ccorch/agents/*.md`, `cli.cmd_review_model` |
| Build/test gate on Stop + SubagentStop(`ccorch:implementer`) | `hooks/hooks.json` → `ccorch hook stop` → `cli.hook_stop` |
| `ccorch` helper CLI (all deterministic steps) | `bin/ccorch` → `scripts/ccorch.py` → `scripts/ccorch_lib/cli.py` |
| Per-repo config, defaults, validation, TOML writer | `ccorch_lib/config.py` |
| Branch naming (template, type prefix, Croatian transliteration) | `ccorch_lib/branch.py` |
| git wrapper, tree fingerprint (gate cache), push with options | `ccorch_lib/git.py` |
| Gate runner (build/test commands, timeout, output tail) | `ccorch_lib/gate.py` |
| GitLab MR push options (one-line values only) | `ccorch_lib/mr.py` |
| Ticket state + history in `.git/ccorch/` | `ccorch_lib/state.py` |
| Inbox (`.git/ccorch/inbox/*.json`, ids like `T-001`); `ccorch inbox add` | `ccorch_lib/inbox.py` |
| Next ticket number (local / remote branches + base history / Jira), `ccorch next-id`, `GET /api/repos/{id}/next-id`, UI `NumbersSection` + Inbox **+ New ticket** | `ccorch_lib/ticket_ids.py`, `git.ls_remote_heads`; `tests/test_ticket_ids.py` |
| Transcript → tickets (one tool-less headless call, JSON schema) | `ccorch_lib/intake.py`, `ccorch_lib/claude.py` |
| Detect repo defaults; plan/apply install (toml, settings.json merge, .gitignore) | `ccorch_lib/install.py` |
| Open a terminal running `claude "/ccorch:ticket ID"` (macOS/Windows/Linux) | `ccorch_lib/terminal.py` |
| Jira client, credentials (`~/.ccorch/credentials.json` / env), issue ↔ ticket text | `ccorch_lib/jira.py`, `ccorch_lib/home.py` (`ccorch_home()`); events in `cli._jira_event`; `ccorch jira`; UI `JiraSection.tsx`; fake server `tests/fake_jira.py` |
| Plugin version check + update via `claude plugin` CLI | `ccorch_lib/plugin_update.py` |
| Settings page backend (FastAPI, all `/api/*`) + self-replace on version change | `plugins/ccorch/manager/server.py` |
| Settings page UI (React): `App.tsx`, `RepoSettings`, `InboxView`, `ActivityView`, `InstallModal`, `Dialogs`, `VersionsBox`, `ui.tsx`, `api.ts` | `manager-web/src/` → built into `plugins/ccorch/manager/static/` |

## Architecture rules

- `plugins/ccorch/` is what gets installed (copied to `~/.claude/plugins/cache/ccorch-tools/ccorch/<version>/`).
  Everything needed at runtime must live inside it. Write no state there - it is replaced on update.
- **Deterministic work is code, never the model.** Branch names, commits, pushes, MR options and
  the build/test gate are done by `ccorch`. Skills/agents only say *when* to call it. Do not move
  these decisions into prompts.
- `scripts/ccorch_lib/` is **stdlib-only** Python ≥ 3.12, run via `uv run --script` (~0.1 s
  start). No third-party imports there. Only `manager/server.py` may use FastAPI/uvicorn (PEP 723
  header).
- The Stop hook must never crash or hang the session: errors become `systemMessage`; it does
  nothing without an active ticket, while `hold` is set, on another branch, or on a clean tree;
  it gives up after `gate.max_attempts`.
- Config = `config.DEFAULTS` ← `.claude/ccorch.toml` (shared) ← `.claude/ccorch.local.toml`
  (personal). All rules live in `config.validate()`; the UI asks the server to validate.
- Runtime state lives in the target repo's `.git/ccorch/` (`state.json`, `history.jsonl`,
  `inbox/`), never in the working tree.
- Headless `claude -p` only for one-shot, tool-less calls (intake). `claude.py` strips
  `ANTHROPIC_API_KEY` so it uses the user's subscription. Code changes always happen in an
  interactive session the user can watch. No worktrees. Never `--dangerously-skip-permissions`.
- Plugin self-update only drives the official CLI (`claude plugin list --json`,
  `marketplace update`, `update`). After updating, the server starts the new version's
  `server.py`, which asks the old one to exit (`/api/shutdown`, version check in `main()`).
- Jira credentials live in `~/.ccorch/credentials.json` (0600) or `CCORCH_JIRA_TOKEN`/`_EMAIL`,
  never in the repo or the plugin dir, and never in output or errors. Jira failures are
  warnings (`_jira_event`), never a failed command or blocked session.
- Settings server: binds 127.0.0.1; every mutating request needs header `X-CCorch: 1` and a
  local Host header (middleware `guard`). Keep that for new endpoints.

## How-tos

- **New setting**: `config.DEFAULTS` + `config.validate()` (+ a test in `tests/test_core.py`) →
  `manager-web/src/api.ts` `Config` type → form field in `RepoSettings.tsx` → mention in the skill
  if the workflow uses it (it reads values from `ccorch context`) → README.
- **New `ccorch` subcommand**: `cmd_*` + parser entry in `cli.py`; allowed in skills via
  `Bash(ccorch *)`.
- **New API endpoint**: in `create_app()` in `server.py`, typed client in `api.ts`, test with
  `TestClient` in `tests/test_manager.py`.
- **Workflow behaviour**: edit `skills/ticket/SKILL.md` / `agents/*.md`. Keep the main session
  lean (subagents read code), keep agent output formats stable (the skill parses them).

## Commands

```
uv run pytest
uv run ruff check            # uv run ruff format to fix layout
uv run mypy
claude plugin validate . && claude plugin validate ./plugins/ccorch
cd manager-web && npm install && npm run build   # after any UI change; commit static/ output
```

All must pass before a change is done. Tests use real git repos in tmp dirs and fake `claude`
executables (`tests/test_intake.py`, `tests/test_plugin_update.py`); never call the real
`claude` from tests.

## Manual testing without touching the user's setup

- Load from the checkout: `claude --plugin-dir ./plugins/ccorch` in a scratch git repo.
- Settings page on another port with its own repo list:
  `CCORCH_MANAGER_HOME=/tmp/mhome uv run --script plugins/ccorch/manager/server.py --port 7431 --no-browser`
- Real install/update flow in a throwaway Claude config: `export CLAUDE_CONFIG_DIR=/tmp/ccfg`,
  then `claude plugin marketplace add <path-to-a-clone>`, `claude plugin install ccorch@ccorch-tools`,
  bump the version in the clone, commit, and use **Check for updates** / **Update** in the page.
- Intake without a login: put a fake `claude` first on `PATH` that prints a `result` JSON with
  `structured_output` (see `tests/test_intake.py`).

## Releasing

Bump `version` in `plugins/ccorch/.claude-plugin/plugin.json` (users only get updates when it
changes), rebuild the UI if it changed, commit, push. Users update with the settings page button
or `claude plugin marketplace update ccorch-tools` + `claude plugin update ccorch@ccorch-tools`,
then restart Claude Code.

## Compatibility

- Users may run older Claude Code (seen: 2.1.112). Keep manifests to fields it accepts (no
  `displayName` in plugin.json, no top-level `description` in marketplace.json), use shell-form
  hooks, and validate both manifests after changes.
- Plugin subagents ignore `hooks`, `mcpServers`, `permissionMode` frontmatter - hooks go in
  `hooks/hooks.json`.
- Windows: Claude Code runs commands through Git Bash. Python must avoid POSIX-only calls (see
  creation flags in `git.py`, `gate.py`, `claude.py`).

## Not yet verified (be honest about these)

- A full `/ccorch:ticket` run in a real, signed-in Claude Code session (skill instructions,
  plan/quick decision, subagent hand-offs, hook behaviour inside a live session).
- A real GitLab push creating an MR (tests use a bare repo that accepts push options).
- Ticket numbers from a real GitLab remote (tests use a bare repo) and `id_source = jira` against
  a real Jira (fake server only).
- Everything Jira against a real Jira Cloud and a real Server/Data Center (tests only use
  `tests/fake_jira.py`): auth, v2 plain-text descriptions on Cloud, `search/jql`, workflow moves.
- Anything on Windows: hook execution, `bin/ccorch`, **Open in Claude Code** (`wt`/`cmd`).
- **Open in Claude Code** on macOS was not clicked (it opens Terminal via `osascript`).

## Conventions

- Python: `mypy --strict`, ruff (line length 100). Small, explicit functions; comments only for
  non-obvious *why*.
- UI: React 19 + TypeScript strict + Tailwind v4, no extra UI libraries. Dark/light via
  `prefers-color-scheme`.
- User-facing text (README, UI, skill output) in plain English for someone who has never seen
  the project.
