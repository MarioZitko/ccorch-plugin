# ccorch-plugin

Claude Code plugin + marketplace: ticket → named branch → plan → gated phases → review → GitLab
MR, plus a local settings page (per-repo config, install into repos, transcript → tickets inbox).
User docs: `README.md`. Why it exists (replaces the PySide6 app in `~/Projects/coding`):
`~/Projects/coding/docs/adr/0001-claude-code-plugin-instead-of-desktop-app.md`.

## Architecture

- `plugins/ccorch/` is what gets installed. Everything it needs at runtime must live inside it
  (installed plugins are copied to a cache; nothing outside this folder ships).
- **Deterministic work is code, never the model.** Branch names, commits, pushes, MR options and
  the build/test gate are done by the `ccorch` helper (`scripts/ccorch_lib/`). Skills and agents
  only tell Claude *when* to call it. Do not move these decisions into prompts.
- `scripts/ccorch_lib/` is **stdlib-only** Python ≥ 3.12 (run via `uv run --script`, starts in
  ~0.1s). Never add third-party imports there. The settings page (`manager/server.py`) may use
  FastAPI/uvicorn, declared in its PEP 723 header.
- `cli.py` is the single entry point (`bin/ccorch` → `scripts/ccorch.py`). The Stop/SubagentStop
  hook calls `ccorch hook stop`; it must never crash or block forever (errors → `systemMessage`).
- Config: `.claude/ccorch.toml` (shared) deep-merged over `config.DEFAULTS`, then
  `.claude/ccorch.local.toml`. All validation lives in `config.validate()`; the UI asks the
  server to validate instead of duplicating rules. New setting = add to `DEFAULTS` + `validate()`
  + `manager-web/src/api.ts` type + form field.
- Runtime state lives in `.git/ccorch/` of the target repo (`state.json`, `history.jsonl`,
  `inbox/`), never in the working tree.
- Headless `claude -p` is only for one-shot, tool-less calls (`claude.py`, transcript intake). It
  strips `ANTHROPIC_API_KEY` so calls use the user's subscription. Code-changing work always runs
  in an interactive Claude Code session.
- No worktrees. Never `--dangerously-skip-permissions`.

## Compatibility

- Users may run older Claude Code (seen: 2.1.112). Keep manifests to fields that version accepts
  (no `displayName` in plugin.json, no top-level `description` in marketplace.json) and use
  shell-form hooks. Run `claude plugin validate` on both manifests after changing them.
- Plugin subagents ignore `hooks`, `mcpServers`, `permissionMode` frontmatter; put hooks in
  `hooks/hooks.json`.
- Windows: commands run through Git Bash; avoid POSIX-only assumptions in Python (see `gate.py`,
  `git.py` creation flags). Windows paths are untested - say so when touching them.

## Commands

```
uv run pytest
uv run ruff check
uv run mypy
claude plugin validate . && claude plugin validate ./plugins/ccorch
cd manager-web && npm run build      # after any UI change; commit the built static/ files
```

All must pass before a change is done. Tests use real git repos in tmp dirs and a fake `claude`
executable; never call the real `claude` from tests.

## Conventions

- Python: `mypy --strict`, ruff (line length 100, `ruff format`).
- UI: React 19 + TypeScript (strict) + Tailwind v4, no extra UI libraries; built output goes to
  `plugins/ccorch/manager/static/` and is committed (users don't need Node).
- The settings server binds to 127.0.0.1 only; mutating requests require the `X-CCorch: 1`
  header and a local Host header. Keep that guard on every new endpoint.
- Bump `version` in `plugins/ccorch/.claude-plugin/plugin.json` when shipping a change.
- Keep `README.md` correct for a brand-new user (install from GitHub first, clone only under
  Development).
