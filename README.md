# ccorch - ticket → GitLab merge request, inside Claude Code

A Claude Code plugin (and its own marketplace). In any configured repo:

```
/ccorch:ticket PROJ-123
```

1. reads the ticket (pasted text, or your Jira/issue MCP tool),
2. creates the branch **by script** from the repo's template, e.g. `feature/PROJ-123-add-login`,
3. plans with an Opus subagent (you approve the plan),
4. implements phase by phase with a Sonnet subagent - each phase is **gated**: a Stop hook runs
   the repo's build + tests and Claude cannot finish while they fail,
5. commits each phase (`[PROJ-123] phase 1: …`), reviews with an Opus subagent, fixes,
6. pushes and opens the **GitLab MR** with push options (no API token).

Everything happens in your normal Claude Code session (terminal, VS Code or desktop), so every
step, tool call and subagent run is visible, and `/context` shows what is using your context.

## Requirements

- Claude Code (keep it updated: `claude update` - model aliases like `opus` resolve to the newest
  model *your installed CLI* knows).
- [`uv`](https://docs.astral.sh/uv/) - runs the helper scripts and installs Python by itself.
- git; a GitLab remote for the MR step.
- Runs in your normal checkout (no worktrees): one active ticket per clone, clean tree to start.

## Getting started

### 1. Update Claude Code and sign in

```bash
claude update
```

Then start `claude` and run `/login` if it asks you to sign in.

### 2. Open a repo with the plugin loaded (no install needed yet)

```bash
cd ~/Projects/your-repo
claude --plugin-dir ~/Projects/ccorch-plugin/plugins/ccorch
```

Use any git repo whose working tree is clean (nothing uncommitted).

### 3. Set up the repo

Inside that Claude session, run `/ccorch:manage`. The settings page opens in your browser at
http://127.0.0.1:7420. Then:

- **Add repository** and pick the repo.
- Check the base branch, the build/test commands (**Run gate now** shows whether they work), and
  the branch/MR rules.
- **Review & install**, then **Write files**.
- Commit the new `.claude/ccorch.toml`.

You can also open the settings page from a normal terminal, without Claude:

```bash
~/Projects/ccorch-plugin/plugins/ccorch/bin/ccorch manage
```

### 4. Run a ticket

Back in the Claude session:

```
/ccorch:ticket PROJ-123 Add customer code to the invoice PDF. Acceptance: code shows under the customer name.
```

It creates the branch, shows you the plan to approve, implements and tests each phase, reviews,
and opens the MR. Add `auto` after the ticket ID to skip the plan approval. Start with a small
ticket.

### 5. Install it permanently

When you're happy with it, install it so you no longer need `--plugin-dir`:

```bash
claude plugin marketplace add ~/Projects/ccorch-plugin
claude plugin install ccorch@ccorch-tools
```

(or `/plugin marketplace add …` and `/plugin install ccorch@ccorch-tools` inside Claude Code).

### Sharing with the team

The plugin lives at https://github.com/MarioZitko/ccorch-plugin. Teammates install it from there:

```bash
claude plugin marketplace add MarioZitko/ccorch-plugin
claude plugin install ccorch@ccorch-tools
```

Paste `https://github.com/MarioZitko/ccorch-plugin.git` under **Marketplace** in the settings page. Every repo you install after that
writes it into `.claude/settings.json`, so teammates who open the repo in Claude Code are asked
to install the plugin.

## Configure a repo

Run `/ccorch:manage` (or `ccorch manage`) - a local web UI at http://127.0.0.1:7420:

- add repos, edit branch naming (live preview), build/test commands (with a **Run gate now**
  button), commit and MR rules (target, title, labels, assignee, draft, squash, delete source
  branch, auto-merge), workflow switches and models per role;
- **Review & install** shows the exact file diffs, then writes:
  - `.claude/ccorch.toml` - the repo's settings (commit it, shared with the team),
  - `.claude/settings.json` - registers this marketplace and enables the plugin, so teammates who
    open the repo are prompted to install it (set the marketplace URL once under *Marketplace*),
  - `.gitignore` entry for `.claude/ccorch.local.toml` (personal overrides, e.g. models);
- **Activity** shows the active ticket and past runs of that clone.

Without the UI: `ccorch init --write` writes a config with detected defaults.

## Commands

| | |
|---|---|
| `/ccorch:ticket <ID> [auto] [text]` | full workflow (`auto` skips plan approval) |
| `/ccorch:mr [notes]` | commit pending work through the gate and open the MR |
| `/ccorch:manage` | open the settings UI |

The skills drive the deterministic `ccorch` helper (on Claude's PATH while the plugin is
enabled): `ccorch context | start | gate | commit | note | hold | resume | review-info | mr |
finish | status | init | manage`. Ticket state lives in `.git/ccorch/` (never committed).

## Token use

- Skills are user-invoked only (`disable-model-invocation`), so the plugin adds almost nothing to
  sessions where you don't use it.
- Small tickets are done inline in the main session (no subagents) when `small_inline` is on.
- Each phase runs in a fresh subagent context with only the ticket, plan summary, its phase and
  short handoff notes - the main session stays small.
- The gate result is cached by working-tree hash, so the commit after a passing hook does not
  rebuild.

## Layout

```
.claude-plugin/marketplace.json   this repo is the marketplace
plugins/ccorch/                   the plugin
  skills/ agents/ hooks/          workflow, planner/implementer/reviewer, Stop-hook gate
  bin/ccorch  scripts/            the helper (stdlib-only Python, run via uv)
  manager/server.py  static/      settings UI backend (FastAPI) + built frontend
manager-web/                      UI source (React + Vite + Tailwind) → builds into static/
tests/                            pytest (real git repos in tmp dirs)
```

## Development

```bash
uv run pytest && uv run ruff check && uv run mypy
cd manager-web && npm install && npm run build   # rebuild the UI after changing it
claude plugin validate . && claude plugin validate ./plugins/ccorch
```

Bump `version` in `plugins/ccorch/.claude-plugin/plugin.json` to ship an update to everyone.
