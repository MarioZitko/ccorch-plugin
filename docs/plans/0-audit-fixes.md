# Plan 0 - Audit fixes

Four small bugs found while checking the docs against the code. Each one is independent.

## 1. Model `inherit` breaks intake and subagent calls

`config.MODEL_CHOICES` includes `inherit` and the UI offers it, but:

- `claude.ask_json` always passes `--model <model>`, so intake runs `claude -p --model inherit`.
  `inherit` is not a model name.
- The ticket skill says to pass the Models line values as the Agent tool `model` parameter. That
  parameter only accepts real model aliases (`sonnet`, `opus`, `haiku`, ...).

Fix:
- `claude.ask_json`: when `model == "inherit"`, leave out `--model` so the user's default model is
  used. Keep `JsonAnswer.model` showing the model that actually ran (`modelUsage`).
- `cli.cmd_context`: print `inherit` roles as `planner=inherit (omit the model parameter)`.
- `skills/ticket/SKILL.md` step 0: "If a role's model is `inherit`, call the Agent tool without
  `model` (the agent's own default is used)." Note: an agent's frontmatter `model:` is its
  default, so "inherit" in our config really means "the agent file's default". Say that in the
  UI hint of the Models section ("inherit = the agent's built-in default: planner opus,
  implementer sonnet, reviewer opus; for intake: your Claude Code default model").
- Tests: `tests/test_intake.py`. The fake `claude` uses `args.index("--model")`, so make it
  handle a missing `--model`, and add a test that intake with `inherit` sends no `--model`. Add a
  `cmd_context` assertion.

## 2. "Copy for terminal" breaks on paths with spaces

`server.py` `inbox_command` returns `f"cd {path} && {terminal.display_command(prompt)}"` without
quoting. Add `terminal.display_shell(cwd, prompt)` that quotes the path the same way
`display_command` quotes its parts (`shlex.quote`), and use it in the endpoint. Test: a repo path
with a space round-trips through `shlex.split`.

## 3. Saving drafts can overwrite a started inbox ticket

`Inbox.add` writes `status: "queued"` and drops `branch`/`started_at` for an id that already
exists. Re-saving a *queued* ticket (keeps `created_at`) is fine. Overwriting a *started* one
loses which branch it runs on.

Fix: in `Inbox.add`, if an existing record has `status != "queued"`, raise
`InboxError(f"{id} was already started on {branch}; edit it instead of saving a new one")`.
Validate everything before writing anything, so a batch fails as a whole. The UI already shows
the error toast. Test in `tests/test_intake.py`.

(Plan 4 adds the proper edit path.)

## 4. Broken config silently disables the gate during an active ticket

`cli.hook_stop` returns `None` when `Ctx(cwd)` raises `ConfigError`. If a ticket is active, the
user should know the gate didn't run.

Fix: in `hook_stop`, on `config.ConfigError`, find the repo root (`find_root`) and its
`StateStore` (via `Git(root).git_dir()`). If a ticket is active, return
`{"systemMessage": f"ccorch: build/test gate not run - .claude/ccorch.toml is invalid: {exc}"}`.
Do not block. In every other case (no repo, no active ticket, `GitError`), keep returning
`None`. Test in `tests/test_cli_flow.py`: write an invalid toml while a ticket is active.

## Docs

- README Troubleshooting: add "Settings change didn't apply / gate didn't run: check the message
  about `.claude/ccorch.toml`".
- CLAUDE.md: nothing structural changes. Keep the "Stop hook must never crash" rule as is.

## Done when

All checks from `docs/plans/README.md` pass, plus the new tests above.
