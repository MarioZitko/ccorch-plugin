# Plan 1 - Smaller reviewer model for small changes

## What exists today

`models.reviewer` (opus/sonnet/haiku/inherit) is already in `.claude/ccorch.toml`, in
**Settings → Models → Reviewer**, and in the `ccorch context` Models line. The ticket skill passes
it as the Agent tool `model` for `ccorch:reviewer`. So one reviewer model per repo can be chosen.

## Goal

Small changes get a cheaper reviewer automatically, big ones keep the strong one. Code makes the
decision (CLAUDE.md: "deterministic work is code"), not the model.

## Design

New settings (`config.DEFAULTS`):

```toml
[models]
reviewer_small = "sonnet"     # used for small changes (see below)

[workflow]
small_review_max_lines = 150  # plan-path changes up to this many changed lines use reviewer_small; 0 = never by size
```

Rule, implemented in `ccorch` (first match wins):
1. The model was already chosen for this ticket → reuse it. Store it as `TicketState.review_model`
   so every review round uses the same reviewer; otherwise the "same findings again = no progress"
   check in skill step 6 compares two different models.
2. `--quick` (the quick path) → `reviewer_small`.
3. `small_review_max_lines > 0` and changed lines (insertions + deletions in
   `git diff --numstat <base_ref>...HEAD`, binary files count 0) ≤ `small_review_max_lines`
   → `reviewer_small`.
4. Otherwise → `reviewer`.

To turn the feature off, set `reviewer_small` to the same value as `reviewer`.

## Steps

1. `config.py`: add both defaults. Add `reviewer_small` to `MODEL_ROLES` (validation loop) and
   validate `small_review_max_lines` as an int between 0 and 5000. Add tests in
   `tests/test_core.py`.
2. `git.py`: `Git.changed_lines(base) -> int` from `diff --numstat`.
3. `state.py`: `review_model: str | None = None` on `TicketState`. Old state files must still load
   (`load` already ignores unknown keys, and new fields have defaults).
4. `cli.py`: new subcommand `ccorch review-model [--quick]`. It needs an active ticket
   (`require_active`), applies the rule, saves the choice, and prints exactly:
   ```
   MODEL: sonnet
   REASON: quick path | 42 changed lines (<= 150) | 900 changed lines | same as earlier review rounds
   ```
   If the chosen value is `inherit`, print `MODEL: inherit (omit the model parameter)` (the same
   wording as plan 0).
   `cmd_context` Models line: add `reviewer_small=<m> (quick path or <= N changed lines)`.
5. `skills/ticket/SKILL.md` step 6: "Run `ccorch review-model` (add `--quick` on the quick path)
   and use its MODEL for every `ccorch:reviewer` call of this ticket." Remove "(model: reviewer)".
6. UI: `api.ts` `Config` type. In `RepoSettings.tsx`, add **Reviewer for small changes** to the
   Models section (`MODEL_LABELS`) and, in Workflow, a NumberInput **Small change = up to N changed
   lines**. Hint: "Quick-path changes and plan-path changes up to this size are reviewed by the
   small-change reviewer. 0 = only quick-path changes." Rebuild `static/`.
7. README: in Quick start step 2, change "Models - which model plans, codes, reviews and reads
   transcripts" to mention the small-change reviewer. Add a "Token use" bullet: "Small changes are
   reviewed by a cheaper model (default sonnet); big ones by the reviewer model (default opus)."
   Add `review-model` to the helper command list in the Layout section.
8. CLAUDE.md feature table: mention `review-model` next to the reviewer.

## Tests (`tests/test_cli_flow.py`)

Use a real repo with a bare origin, as in the existing flow test.
- A small committed diff → `MODEL: sonnet`. A diff over the limit → `MODEL: opus`.
  `--quick` → sonnet regardless of size.
- The second call returns the stored model even after the diff grows past the limit.
- `small_review_max_lines = 0` and no `--quick` → reviewer.
- `inherit` output wording.

## Out of scope

A per-run flag on `/ccorch:ticket`. Changing the reviewer agent's `effort` (the frontmatter can't
be overridden per call).
