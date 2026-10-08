# ccorch - ticket → GitLab merge request, inside Claude Code

A Claude Code plugin. In any repo you've set up, run:

```
/ccorch:ticket PROJ-123
```

and it will:

1. read the ticket (from the Inbox, pasted text, or your Jira/issue tool),
2. create the branch **with a script** from the repo's naming template, e.g.
   `feature/PROJ-123-add-login`,
3. for bigger work, plan it with an Opus subagent - you approve the plan. Small changes and most
   bug fixes skip planning and are done in one step (the **quick path**),
4. implement it (phase by phase if planned). After each step the repo's build and tests run
   automatically, and Claude cannot finish while they fail,
5. commit each phase (`[PROJ-123] phase 1: …`), review the branch with an Opus subagent and fix
   what it finds,
6. push and open the **GitLab merge request** (no API token needed).

Everything runs in your normal Claude Code session (terminal, VS Code or desktop app), so you see
every step and can steer it. A small settings page lets you configure each repo and turn meeting
transcripts into tickets.

## Requirements

- **Claude Code**, signed in. Keep it updated (`claude update`): the model names `haiku`, `sonnet`
  and `opus` always mean the newest model your installed Claude Code knows.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** - runs the plugin's helper
  scripts and installs Python by itself. No other setup.
- **git**, and a **GitLab** remote for the merge request step.
- **Windows:** run the commands in PowerShell. Claude Code on Windows needs
  [Git for Windows](https://git-scm.com/downloads/win) - the plugin's scripts run in its Git Bash.
- No worktrees: ccorch works in your normal checkout, one ticket at a time per clone, starting from
  a clean working tree (nothing uncommitted).

## Quick start

### 1. Update and sign in to Claude Code

```bash
claude update
```

Start `claude` once and run `/login` if it asks you to sign in.

### 2. Install the plugin

```bash
claude plugin marketplace add MarioZitko/ccorch-plugin
claude plugin install ccorch@ccorch-tools
```

(Inside Claude Code you can do the same with `/plugin marketplace add MarioZitko/ccorch-plugin`
and `/plugin install ccorch@ccorch-tools`.)

### 3. Set up a repo

Open Claude Code in your project and run the settings command:

```bash
cd ~/path/to/your-project
claude
```

```
/ccorch:manage
```

The settings page opens in your browser at http://127.0.0.1:7420 (the first start takes a few
seconds while uv downloads its dependencies). Then:

1. **Add repository** and pick your project.
2. Check what it detected and adjust:
   - **Base branch** - where ticket branches start from,
   - **Branch naming** - template and prefixes, with a live preview,
   - **Build & test gate** - click **Run gate now** to check the commands work,
   - **Merge request** - target branch, title, labels, assignee, draft, squash, delete branch,
   - **Models** - which model plans, codes, reviews and reads transcripts.
3. **Review & install** shows exactly which files will change → **Write files**.
4. Commit the new files (`.claude/ccorch.toml`, `.claude/settings.json`, `.gitignore`).

### 4. Run your first ticket

Back in Claude Code:

```
/ccorch:ticket PROJ-123 Add customer code to the invoice PDF. Acceptance: code shows under the customer name.
```

It creates the branch, decides whether the ticket needs a plan, implements and tests it, reviews,
and opens the merge request. Start with a small ticket.

For a small fix you can skip planning explicitly:

```
/ccorch:ticket PROJ-124 quick Fix typo in the invoice footer
```

Use `plan` instead of `quick` to force a plan, and `auto` to skip asking you to approve the plan.

### 5. Optional: tickets from a meeting transcript

In the settings page, open the repo's **Inbox** tab, paste a transcript, notes or an email, and
click **Extract tickets**. Edit the ticket cards, **Save to inbox**, then click
**Open in Claude Code** on a ticket (or **Copy command** and paste `/ccorch:ticket T-001` into
Claude yourself). See [Tickets from transcripts](#tickets-from-transcripts) below.

## Updating ccorch

**From the settings page (easiest):** run `/ccorch:manage`. The box at the top of the sidebar
shows your ccorch version. Click **Check for updates**; if a newer version is on GitHub the button
changes to **Update to x.y.z**. Click it - the settings page installs the update, restarts itself
on the new version and reloads. The same box has an **Update** button for Claude Code itself.
Afterwards, restart your open Claude Code sessions so they use the new version.

**From a terminal:** run these (PowerShell on Windows, Terminal on macOS) from any folder:

```bash
claude plugin marketplace update ccorch-tools
claude plugin update ccorch@ccorch-tools
```

The first command fetches the latest catalog from GitHub, the second installs the new version.
Then **restart Claude Code** (close every open `claude` session and start it again). The next
`/ccorch:manage` replaces a settings page that is still running from the old version - just reload
the browser tab.

Check which version you have with `claude plugin list`.

## Commands

| In Claude Code | What it does |
|---|---|
| `/ccorch:ticket <ID> [quick\|plan] [auto] [text]` | The full workflow. `quick` = no planning, `plan` = always plan, `auto` = don't ask me to approve the plan. |
| `/ccorch:mr [notes]` | Commit pending work (through the gate) and open the merge request. |
| `/ccorch:manage` | Open the settings page. |

While a ticket is running you can watch everything in the session. `/context` shows what is using
your context. To stop tracking a ticket without finishing it, ask Claude to run
`ccorch finish --outcome abandoned` (the branch stays).

## The settings page

Open it with `/ccorch:manage`. It runs only on your computer (`127.0.0.1`).

- **Sidebar** - your ccorch and Claude Code versions with update buttons (see
  [Updating ccorch](#updating-ccorch)); your repos, their status (*installed*, *config only*,
  *not set up*) and any running ticket; **Marketplace** (see
  [Sharing with your team](#sharing-with-your-team)).
- **Settings tab** - everything ccorch does in that repo. Under **Workflow**, **Planning** decides
  when to plan: *auto* (small changes skip planning - the default), *always* or *never*; and
  **Review quick changes too** decides whether quick-path changes still get an AI review.
  **Review & install** writes:
  - `.claude/ccorch.toml` - the repo's settings. Commit it so the team shares them.
  - `.claude/settings.json` - enables the plugin for the repo, so teammates who open it in Claude
    Code are asked to install ccorch (only once a marketplace URL is set).
  - a `.gitignore` entry for `.claude/ccorch.local.toml` - your personal overrides (for example a
    different model), never committed.
- **Inbox tab** - tickets from transcripts (below).
- **Activity tab** - the running ticket and past tickets of that clone: branch, commits, phases,
  merge request link, handoff notes.

## Tickets from transcripts

1. Paste a meeting transcript, notes or an email into the **Inbox** tab and click
   **Extract tickets**.
2. The settings page makes **one** call to the intake model (default `haiku`) through your own
   Claude Code login - in the background (`claude -p`), with no tools and no access to the repo.
   It uses your Claude subscription, not API credits: if `ANTHROPIC_API_KEY` is set on your
   computer, the settings page removes it for this call and shows a warning.
3. Review and edit the cards (id, type, size, title, description, acceptance criteria), remove
   what you don't want, then **Save to inbox**. Tickets without an id get `T-001`, `T-002`, …
   (change the prefix per repo under *Tickets from transcripts* in the Settings tab).
4. Pick how to start it in the dropdown - *auto* (uses the repo's Planning setting and the
   ticket's size), *quick (no plan)* or *with plan* - then **Open in Claude Code** (opens a terminal
   in the repo running `/ccorch:ticket T-001`) or copy the command. The ticket skill reads the full ticket from the
   inbox. Inbox tickets are stored in `.git/ccorch/inbox/` and never committed.

Short one-shot steps like this run in the background and show their result in the settings page.
Everything that changes code runs in Claude Code, where you can watch and steer it.

## Sharing with your team

1. Make sure teammates can access this repo on GitHub.
2. In the settings page, open **Marketplace** and set the Git URL to
   `https://github.com/MarioZitko/ccorch-plugin.git`.
3. **Review & install** each repo again and commit `.claude/settings.json`.

From then on, a teammate who opens that repo in Claude Code is asked to install ccorch, and the
repo's settings come from the committed `.claude/ccorch.toml`. They can also install it directly
with the two commands from [step 2](#2-install-the-plugin).

## Token use

- The commands only run when you type them, so the plugin adds almost nothing to sessions where
  you don't use it.
- Small changes skip planning (the quick path) and are done directly in the main session, without
  subagents (settings: *Planning* and *Quick path in the main session*).
- Each phase runs in a fresh subagent with only the ticket, the plan summary, its own phase and
  short notes from earlier phases, so the main session stays small.
- The build/test result is cached by the exact state of the files, so nothing is rebuilt twice.
- Transcript → tickets is a single small Haiku call.

## Troubleshooting

- **`/ccorch:...` commands don't show up** - check `claude plugin list`, then restart Claude Code.
- **"uv: command not found"** - install uv (link above) and restart your terminal.
- **The wrong or an old model is used** - run `claude update` (or **Update** in the settings page).
- **"working tree is not clean"** - commit or stash your changes before starting a ticket.
- **The push worked but no merge request link** - the remote isn't GitLab, or GitLab rejected a
  push option; open the MR manually from the pushed branch.
- **macOS asks for permission to control Terminal** - that's **Open in Claude Code**; allow it,
  or use **Copy command** instead.

---

## Development

Clone the repo and load the plugin straight from your checkout (no install needed):

```bash
git clone https://github.com/MarioZitko/ccorch-plugin.git
cd ~/path/to/a-test-project
claude --plugin-dir ~/path/to/ccorch-plugin/plugins/ccorch
```

The settings page can also be started from a terminal:
`~/path/to/ccorch-plugin/plugins/ccorch/bin/ccorch manage`.

Checks (from the repo root):

```bash
uv run pytest && uv run ruff check && uv run mypy
claude plugin validate . && claude plugin validate ./plugins/ccorch
```

The settings page is built from `manager-web/` (React + Vite + Tailwind); the built files are
committed so users don't need Node:

```bash
cd manager-web && npm install && npm run build
```

To ship an update, bump `version` in `plugins/ccorch/.claude-plugin/plugin.json`, commit and
push. Users get it as described in [Updating ccorch](#updating-ccorch). Claude Code only
installs a new version when `version` changes.

### Layout

```
.claude-plugin/marketplace.json   this repo is also the plugin marketplace
plugins/ccorch/                   the plugin
  skills/                         /ccorch:ticket, /ccorch:mr, /ccorch:manage
  agents/                         planner (opus), implementer (sonnet), reviewer (opus)
  hooks/hooks.json                Stop/SubagentStop hook = build/test gate
  bin/ccorch, scripts/            the `ccorch` helper (stdlib-only Python, run via uv)
  manager/server.py, static/      settings page backend (FastAPI) + built frontend
manager-web/                      settings page source → builds into plugins/ccorch/manager/static
tests/                            pytest (real git repos in temp dirs, fake `claude`)
```

The `ccorch` helper (on Claude's PATH while the plugin is enabled): `context`, `start`,
`branch-name`, `gate`, `commit`, `note`, `hold`, `resume`, `review-info`, `mr`, `finish`,
`status`, `inbox list|show`, `init`, `manage`, `hook stop`.
