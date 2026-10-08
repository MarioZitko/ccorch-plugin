# Plan 4 - Edit tickets after they are launched

## Goal

In the settings page Inbox, any saved ticket can be edited: queued, started (a Claude Code session
is working on it), or finished. When the ticket is running, the session picks up the change at its
next step (next phase, review, or MR) without the user typing anything into it. The check that
detects a change is deterministic code; the skill only says when to call it.

## Rules

- Editable fields: type, size, title, description, acceptance criteria.
- The id can change only while the ticket is `queued` and the new id is free (rename = write new
  file + delete old). After start, the id is locked because the branch is named after it.
- Editing a started ticket never renames the branch. A new **title** is copied into the active
  `TicketState.title`, so later commit and MR titles use it. A new **type** does not change the
  branch prefix; the UI says so.
- Each save increments `revision` (new tickets start at 1) and sets `updated_at`. Keep the
  previous version in `history: [{revision, updated_at, title, description,
  acceptance_criteria, type, size}]` (last 10) so `ticket-check` can say what changed.
- When the MR is opened or the ticket is abandoned, the inbox record gets
  `status: "done" | "abandoned"` and `mr_url`, via a new `Inbox.mark_finished` called from
  `cmd_mr` and `cmd_finish`. A finished ticket can still be edited, but the UI says the change
  won't reach the MR.

(Plan 0 already stops "Save to inbox" from overwriting a started ticket. This plan adds the
real edit path.)

## Backend

- `inbox.py`: `Inbox.update(tid, changes) -> dict`. Reuse `normalize` for validation, apply the
  rules above, raise `InboxError` on violations, write atomically (temp file + `replace`).
  `add()` sets `revision: 1`. Old records without `revision` count as 1.
- `state.py`: `ticket_revision: int = 0`, the revision the session last saw. `cmd_start` sets it
  from the inbox record, or 0 if there is no record.
- `cli.py`: new `ccorch ticket-check`:
  - Needs an active ticket. If the inbox record's `revision` > `state.ticket_revision`, print
    ```
    TICKET UPDATED (revision 3, edited 2026-10-08 14:02):
    Changed: title, acceptance criteria
    <full ticket markdown, as `inbox show` prints it>
    ```
    then set `state.ticket_revision` and, if the title changed, `state.title`. Otherwise print
    `Ticket unchanged.` and nothing else, to keep the main session lean.
  - Jira part, only if plan 2 is merged and the ticket has a `jira_key`: also fetch the issue. If
    Jira's `updated` is newer than the record's `jira_updated`, write the Jira text into the record
    as a new revision first (someone edited it in Jira). A Jira failure prints one `Jira warning:`
    line and the check continues with local data.
- `cmd_context`: when a revision is pending, print
  `- TICKET UPDATED since the session last read it - run \`ccorch ticket-check\``.
- Server: `PUT /api/repos/{id}/inbox/{tid}` with the ticket fields (and optional new `id`) →
  `{ticket, running: bool}`. `running` = the repo's active state has this ticket id.
  Jira part (plan 2 merged): if the record has a `jira_key`, also `update_issue` (summary +
  description) and return `jira: "updated" | "<warning>"`. A Jira failure doesn't fail the save.
  Add the typed client in `api.ts`.

## Skill (`skills/ticket/SKILL.md`)

Add one rule and the call sites:
- Rules: "The user can edit the ticket in the settings page while you work. Run
  `ccorch ticket-check` before step 5.1 of every phase, before step 6, and before step 7. On
  the quick path, run it before `ccorch commit`."
- If it prints `TICKET UPDATED`, use the new text from then on:
  - Plan path: if the change affects phases not yet done, update those phases yourself when the
    change is small. If it's substantial (new scope, contradicts finished phases), run
    `ccorch hold`, show the user what changed and your proposed plan change, then `ccorch resume`.
    Finished phases are not redone; anything missing becomes an extra phase.
  - Review: give the reviewer the updated ticket (acceptance criteria are what it checks against).
  - MR: the MR title comes from the updated state title automatically.

Keep the existing output formats of the agents unchanged.

## UI (`InboxView.tsx`)

- Move the fields of `DraftCard` into a shared `TicketFields` component used by both draft cards
  and the editor.
- `QueuedCard`: an **Edit** button opens the card in edit mode (TicketFields + **Save** /
  **Cancel**). The id input is disabled when the ticket isn't queued, with the tooltip "The branch
  is named after the id".
- Banners in edit mode:
  - running: "Claude Code is working on this ticket. It picks up your change before its next step
    (next phase, review or merge request)."
  - started but not running in this clone: "Started on <branch>."
  - done or abandoned: "The merge request is already open - this change won't reach it."
- Show `edited · rev N` when `revision > 1`, and the status badges `done` / `abandoned`.
- Status type in `api.ts`: `"queued" | "started" | "done" | "abandoned"`, plus `revision`,
  `updated_at`, `mr_url`.
- Rebuild `static/`.

## Tests

- `tests/test_intake.py` (or a new `tests/test_inbox.py`): update rules (id rename only when
  queued and free, revision/history, finished tickets still editable).
- `tests/test_cli_flow.py`: add an inbox ticket, `ccorch start`, edit it via `Inbox.update` (new
  title + criterion). `ticket-check` prints `TICKET UPDATED` with `Changed: title, acceptance
  criteria`, and the second call prints `Ticket unchanged.` `context` shows the pending line
  before the check and not after. A commit + `mr --dry-run` uses the new title. `mr`/`finish` mark
  the inbox record done/abandoned.
- `tests/test_manager.py`: the PUT endpoint, including `running` and a 400 on a locked id change.
- With plan 2 merged: the fake Jira receives the update on save, and `ticket-check` picks up a
  change made "in Jira" (bump the fake issue's `updated`).

## Docs

README: in "Tickets from transcripts", add a step "Edit a ticket any time - even while Claude Code
is working on it…", plus the new statuses. Add `ticket-check` to the helper command list.
CLAUDE.md: feature table (inbox editing, `ticket-check`) and "Not yet verified: a running session
picking up an edit".

## Out of scope

Pushing an edit into an already open MR description. Renaming the branch after a type change.
Live push of edits into an idle session; the session only sees an edit at its next step or when
the user writes to it.
