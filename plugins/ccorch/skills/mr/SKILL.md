---
name: mr
description: Open the GitLab merge request for the active ccorch ticket (commit pending work through the gate first).
disable-model-invocation: true
argument-hint: "[extra notes for the MR description]"
allowed-tools: Bash(ccorch *), Bash(git status*), Bash(git diff*), Bash(git log*)
---

Open the merge request for the active ticket.

1. Run `ccorch status`. If there is no active ticket, say so and stop.
2. If `git status` shows uncommitted changes, run `ccorch commit --note "final changes"`. If the
   gate fails, show the output and stop.
3. Run `ccorch review-info` and write a 2-4 sentence description of what changed and why.
   Include these notes from the user if given: $ARGUMENTS
4. Run `ccorch mr --description "<description>"` and report the MR link.
