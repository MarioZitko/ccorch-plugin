---
name: ticket
description: Take a ticket from id to GitLab merge request - named branch, plan (or a quick no-plan path for small fixes), implementation with a build/test gate, review, MR.
disable-model-invocation: true
argument-hint: <TICKET-ID> [quick|plan] [auto] [ticket text...]
allowed-tools: Bash(ccorch *), Bash(git status*), Bash(git diff*), Bash(git log*)
---

# Ticket → merge request

Arguments: `$ARGUMENTS` - the first word is the ticket id. Flags anywhere after it:
- `quick` - small change: no planning, implement directly (step 3).
- `plan` - always plan, even if it looks small.
- `auto` - don't stop to ask me to approve the plan.

Any other text is the ticket content.

You orchestrate; subagents do the heavy reading and coding. Keep this main session lean: do not
read source files yourself unless you are doing a small ticket inline.

## 0. Context

Run `ccorch context`.
- If it shows an ACTIVE TICKET with a different id, stop and ask: continue that one, or
  `ccorch finish` it first.
- If the config file is MISSING, tell the user to open the settings UI (`/ccorch:manage`) or run
  `ccorch init --write`, and continue with defaults only if they say so.
- Use the Models line for every subagent call below (Agent tool `model` parameter). If a role's
  model is `inherit`, call the Agent tool without `model` (the agent's own default is used).

## 1. Ticket

Run `ccorch inbox show <ID>`. It finds the ticket in the inbox or, for Jira keys, in Jira, and
prints it (including its type and title). If it prints nothing useful, use the ticket text that was
passed, or another issue tracker tool if one is available; otherwise ask the user to paste title,
description and acceptance criteria.
Decide the type: `feature`, `bug` or `task`, and a short title (under ~8 words).

## 2. Branch

Run `ccorch start --id <ID> --type <type> --title "<short title>"`. It names the branch from the
repo's template, fetches and branches from the base. Never create or switch branches with git
yourself. If it fails (dirty tree, branch exists, bad config), show the error and stop.

## 3. Plan or quick?

Decide in this order (the first rule that applies wins):

1. `quick` was passed → **quick**. `plan` was passed → **plan**.
2. `planning=never` → **quick**. `planning=always` → **plan**.
3. `planning=auto`: the inbox ticket's size (`looks small` / `looks big`) if there is one,
   otherwise your own judgement: **small** = one coherent change in a handful of files with no
   design decisions (most bug fixes, copy/config changes, small UI tweaks) → **quick**;
   anything else → **plan**. When unsure, plan.

Say in one line which path you chose and why (e.g. "Quick path: one-file bug fix").

**Quick path** - no planner, one change, one commit:
- `small_inline=True`: implement it yourself in this session. Read only the files you need and
  keep the change focused.
- `small_inline=False`: delegate to `ccorch:implementer` (model: implementer) with the ticket
  as a single phase.
- Then run `ccorch commit --note "<1-2 line handoff>"` (uses the single-change commit message;
  it runs the build/test gate first - on failure fix it, at most twice, then `ccorch hold`,
  report and stop).
- If the change turns out bigger than expected (design decisions, many files), stop, say so,
  and continue with step 4 instead - keep what you already changed.
- Then go to step 6.

**Plan path** - step 4.

## 4. Plan

Delegate to the `ccorch:planner` subagent (model: planner) with the full ticket text. It returns
SUMMARY, PHASEs and RISKS.

If `plan_approval=True` and `auto` was not passed: run `ccorch hold`, show the plan (summary,
phase titles with goals, risks) and ask the user to approve or change it. Apply their changes,
then run `ccorch resume`.

## 5. Phases

For each phase *i* in order:

1. Delegate to `ccorch:implementer` (model: implementer). The prompt contains only: the ticket
   (title, description, acceptance criteria), the plan SUMMARY, phase *i* in full, and the
   handoff notes shown by `ccorch context` from earlier phases. Do not paste other phases.
2. When it returns, run
   `ccorch commit --phase <i> --title "<phase title>" --note "<its HANDOFF, condensed to 1-3 lines>"`.
   The commit runs the build/test gate first (cached if the implementer's own gate already
   passed on the same tree).
3. If the commit reports a gate failure: send the implementer back with the failure output
   (fresh call, same phase, plus "your previous attempt is in the working tree; fix it, do not
   start over"). Try at most twice. If it still fails, run `ccorch hold`, report, and stop.

## 6. Review

Skip if `review=False`, or if this was the quick path and `review_quick=False`. Otherwise run `ccorch review-model` (add `--quick` on the quick
path) and use its MODEL for every `ccorch:reviewer` call of this ticket (if it says `inherit`, omit
the `model` parameter). Delegate to `ccorch:reviewer` with the
ticket and the plan SUMMARY (or "single-phase change" for small tickets).

- Blocking findings = high and medium. If none: go to step 7.
- Otherwise delegate only the blocking findings to `ccorch:implementer`, then
  `ccorch commit --fix <k>`, and review again with the previous findings included.
- Stop after `max_fix_iterations` fix rounds, or earlier if the reviewer returns the same
  blocking findings as last time (no progress). Then run `ccorch hold`, report the remaining
  findings, and ask whether to open the MR anyway.

## 7. Merge request

Run `ccorch mr --description "<2-4 sentences: what changed and why, notable decisions>"`.
It pushes the branch and opens the MR with the repo's MR rules (target, labels, draft, ...).

Finish with a short report: MR link, branch, commits, low-severity findings left, anything the
reviewer or implementer flagged as open, and any `Jira:` lines `ccorch` printed.

## Rules

- Only `ccorch` creates branches, commits and pushes. Never run `git commit`, `push`,
  `checkout`, `switch`, `reset`, `stash` or `rebase` yourself.
- Before you ask the user anything while there are uncommitted changes, run `ccorch hold`; run
  `ccorch resume` once they answer. (Otherwise the gate hook keeps you working.)
- If a step fails twice, stop and summarise instead of looping.
- Never move or edit Jira issues with other tools; `ccorch` does it (start, MR, abandon). If
  `ccorch` prints a `Jira warning`, mention it in your report and carry on.
- To abandon: `ccorch finish --outcome abandoned` (the branch stays).
