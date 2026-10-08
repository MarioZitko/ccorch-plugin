"""`ccorch` command: the deterministic steps skills call (branch, gate, commit, MR) + Stop hook."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ccorch_lib import branch, config, gate, install, mr
from ccorch_lib.git import Git, GitError, find_root
from ccorch_lib.state import StateStore, TicketState

HOOK_TAIL_LINES = 80


class CliError(Exception):
    pass


class Ctx:
    """Repo root, merged config, git wrapper and state store for the current directory."""

    def __init__(self, cwd: Path) -> None:
        root = find_root(cwd)
        if root is None:
            raise CliError(f"not inside a git repository: {cwd}")
        self.root = root
        self.cfg = config.load(root)
        self.git = Git(root, self.cfg["repo"]["remote"])
        self.store = StateStore(self.git.git_dir())

    def require_active(self) -> TicketState:
        state = self.store.active()
        if state is None:
            raise CliError("no active ticket; run `ccorch start` first")
        current = self.git.current_branch()
        if current != state.branch:
            raise CliError(
                f"active ticket is on branch {state.branch!r} but you are on {current!r}"
            )
        return state


# --- helpers ------------------------------------------------------------------------------


def _print_gate(result: gate.GateResult, lines: int = 60) -> None:
    if result.skipped:
        print("GATE SKIPPED: no build/test commands configured (.claude/ccorch.toml [gate]).")
        return
    status = "PASSED" if result.passed else f"FAILED (exit {result.exit_code}) in: {result.command}"
    print(f"GATE {status}")
    if not result.passed:
        print(gate.tail(result.output_tail, lines))


def _run_gate(ctx: Ctx) -> gate.GateResult:
    g = ctx.cfg["gate"]
    return gate.run(g["build"], g["test"], ctx.root, g["timeout_s"])


def _gate_current_tree(ctx: Ctx, state: TicketState | None) -> gate.GateResult:
    """Run the gate unless the exact current tree already passed it (cached by fingerprint)."""
    fingerprint = ctx.git.tree_fingerprint()
    if state is not None and state.last_gate_pass == fingerprint:
        return gate.GateResult(True, 0, "unchanged since last passing gate (cached)")
    result = _run_gate(ctx)
    if state is not None:
        if result.passed:
            state.last_gate_pass = fingerprint
            state.gate_failures = 0
        ctx.store.save(state)
    return result


def _fmt(template: str, state: TicketState, **extra: Any) -> str:
    values: dict[str, Any] = {
        "ticket_id": state.ticket_id,
        "title": state.title,
        "type": state.type,
        "branch": state.branch,
        "index": "",
        "iteration": "",
    }
    values.update(extra)
    return template.format(**values)


# --- commands -----------------------------------------------------------------------------


def cmd_context(args: argparse.Namespace) -> int:
    """Markdown summary injected into the /ccorch:ticket skill. Never fails."""
    try:
        ctx = Ctx(Path.cwd())
    except (CliError, config.ConfigError, GitError) as exc:
        print(f"**ccorch context unavailable:** {exc}")
        return 0
    cfg = ctx.cfg
    state = ctx.store.active()
    dirty = ctx.git.status_porcelain().strip()
    print(f"- Repo: `{ctx.root}`")
    has_file = config.has_config(ctx.root)
    print(f"- Config file: {'present' if has_file else 'MISSING (defaults in use)'}")
    print(
        f"- Current branch: `{ctx.git.current_branch()}`; working tree: "
        f"{'DIRTY' if dirty else 'clean'}"
    )
    print(f"- Base branch: `{cfg['repo']['base_branch']}`; MR target: `{config.mr_target(cfg)}`")
    print(
        f"- Gate: build={cfg['gate']['build'] or '(none)'} test={cfg['gate']['test'] or '(none)'}"
    )
    wf = cfg["workflow"]
    print(
        f"- Workflow: plan_approval={wf['plan_approval']} review={wf['review']} "
        f"max_fix_iterations={wf['max_fix_iterations']} small_inline={wf['small_inline']}"
    )
    print(
        "- Models (pass as the Agent tool `model`): "
        + ", ".join(
            f"{role}={cfg['models'][role]}" for role in ("planner", "implementer", "reviewer")
        )
    )
    if state:
        print(
            f'- ACTIVE TICKET: {state.ticket_id} ({state.type}) "{state.title}" on '
            f"`{state.branch}`; phases_done={state.phases_done} "
            f"fix_iterations={state.fix_iterations} hold={state.hold} mr={state.mr_url}"
        )
        for note in state.notes[-5:]:
            print(f"  - note: {note}")
    else:
        print("- Active ticket: none")
    return 0


def cmd_branch_name(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    name = branch.validate(
        branch.from_config(ctx.cfg, args.type, args.id, args.title), ctx.git.is_valid_branch_name
    )
    print(name)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    existing = ctx.store.active()
    if existing and not args.force:
        raise CliError(
            f"ticket {existing.ticket_id} is still active on {existing.branch}; "
            "finish it (`ccorch finish`) or pass --force"
        )
    if not ctx.git.is_clean():
        raise CliError(
            "working tree is not clean; commit or stash your changes first:\n"
            + ctx.git.status_porcelain()
        )
    base = args.base or ctx.cfg["repo"]["base_branch"]
    name = branch.validate(
        branch.from_config(ctx.cfg, args.type, args.id, args.title), ctx.git.is_valid_branch_name
    )
    if not args.no_fetch and ctx.git.has_remote():
        ctx.git.fetch()
    ctx.git.create_branch(base, name)
    state = TicketState(ticket_id=args.id, type=args.type, title=args.title, branch=name, base=base)
    ctx.store.save(state)
    print(f"Created branch {name} from {ctx.git.base_ref(base)}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.store.active()
    result = _gate_current_tree(ctx, state)
    _print_gate(result)
    return 0 if result.passed else 1


def cmd_commit(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.require_active()
    if not args.no_gate:
        result = _gate_current_tree(ctx, state)
        if not result.passed:
            _print_gate(result)
            print("Not committed: fix the gate failure first.")
            return 1
    commit_cfg = ctx.cfg["commit"]
    if args.phase is not None:
        message = _fmt(
            commit_cfg["phase_message"], state, index=args.phase, title=args.title or state.title
        )
    elif args.fix is not None:
        message = _fmt(commit_cfg["fix_message"], state, iteration=args.fix)
    else:
        message = _fmt(commit_cfg["single_message"], state)
    sha = ctx.git.commit_all(message)
    if sha is None:
        print("Nothing to commit.")
        return 0
    state.commits.append(sha)
    if args.phase is not None:
        state.phases_done = max(state.phases_done, args.phase)
    if args.fix is not None:
        state.fix_iterations = max(state.fix_iterations, args.fix)
    if args.note:
        state.notes.append(args.note)
    state.last_gate_pass = ctx.git.tree_fingerprint() if not args.no_gate else state.last_gate_pass
    ctx.store.save(state)
    print(f"Committed {sha[:10]}: {message}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.require_active()
    state.notes.append(args.text)
    ctx.store.save(state)
    print("Note saved.")
    return 0


def cmd_hold(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.require_active()
    state.hold = args.on
    ctx.store.save(state)
    print("Stop-hook gate paused." if args.on else "Stop-hook gate active.")
    return 0


def cmd_review_info(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.require_active()
    base_ref = ctx.git.base_ref(state.base)
    print(f"Diff range: {base_ref}...HEAD  (run `git diff {base_ref}...HEAD` for the full diff)")
    print(ctx.git.run("log", "--oneline", f"{base_ref}..HEAD").stdout)
    print(ctx.git.diff_stat(state.base))
    return 0


def cmd_mr(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.require_active()
    if not ctx.git.is_clean():
        raise CliError("working tree is not clean; commit (`ccorch commit`) before opening the MR")
    if (
        not state.commits
        and not ctx.git.run(
            "log", "--oneline", f"{ctx.git.base_ref(state.base)}..HEAD"
        ).stdout.strip()
    ):
        raise CliError("no commits on this branch; nothing to merge")
    title = args.title or mr.render_title(
        ctx.cfg, ticket_id=state.ticket_id, title=state.title, type=state.type, branch=state.branch
    )
    description = args.description or ""
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")
    options = mr.push_options(ctx.cfg, title=title, description=description)
    if args.dry_run:
        print("git push -u", ctx.git.remote, state.branch, " ".join(f"-o {o!r}" for o in options))
        return 0
    result = ctx.git.push_with_options(state.branch, options)
    state.mr_url = result.mr_url
    ctx.store.finish(state, "mr_opened")
    if result.mr_url:
        print(f"MR: {result.mr_url}")
    else:
        print("Pushed, but no MR link found in the push output (is the remote GitLab?).")
        print(gate.tail(result.output, 20))
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.store.active()
    if state is None:
        print("No active ticket.")
        return 0
    ctx.store.finish(state, args.outcome)
    print(f"Ticket {state.ticket_id} finished ({args.outcome}).")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ctx = Ctx(Path.cwd())
    state = ctx.store.load()
    if args.json:
        print(
            json.dumps(
                {"state": state.__dict__ if state else None, "history": ctx.store.read_history(10)},
                indent=2,
            )
        )
        return 0
    if not state or not state.active:
        print("No active ticket.")
        return 0
    print(json.dumps(state.__dict__, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = find_root(Path.cwd())
    if root is None:
        raise CliError("not inside a git repository")
    if config.has_config(root) and not args.force:
        raise CliError(f"{config.CONFIG_REL} already exists (use --force to overwrite)")
    cfg = install.detect_defaults(root)
    text = config.dumps(cfg)
    if not args.write:
        print(text)
        print("# (dry run - pass --write to save)")
        return 0
    install.apply(root, install.plan(root, cfg, None))
    print(f"Wrote {config.CONFIG_REL} (and .gitignore entry for {config.LOCAL_CONFIG_REL}).")
    return 0


def cmd_manage(args: argparse.Namespace) -> int:
    server = Path(__file__).resolve().parents[2] / "manager" / "server.py"
    argv = ["uv", "run", "--quiet", "--script", str(server), "--port", str(args.port)]
    if args.no_browser:
        argv.append("--no-browser")
    if args.background:
        kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(argv, **kwargs)
        print(f"ccorch manager starting at http://127.0.0.1:{args.port}")
        return 0
    return subprocess.call(argv)


# --- Stop / SubagentStop hook ---------------------------------------------------------------


def hook_stop(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Decide what the Stop hook returns. None = allow the stop silently."""
    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    try:
        ctx = Ctx(cwd)
    except (CliError, config.ConfigError, GitError):
        return None
    state = ctx.store.active()
    if state is None or state.hold:
        return None
    if ctx.git.current_branch() != state.branch or ctx.git.is_clean():
        return None
    max_attempts = ctx.cfg["gate"]["max_attempts"]
    if state.gate_failures >= max_attempts:
        # Give up for this agent run; the next (re)try starts with a fresh budget.
        state.gate_failures = 0
        ctx.store.save(state)
        return {
            "systemMessage": f"ccorch: build/test gate still failing after {max_attempts} "
            "attempts; stopping. Run `ccorch gate` to see the error."
        }
    result = _gate_current_tree(ctx, state)
    if result.passed:
        return None
    state.gate_failures += 1
    ctx.store.save(state)
    reason = (
        f"ccorch build/test gate FAILED (attempt {state.gate_failures}/{max_attempts}) "
        f"running `{result.command}`. Fix the cause, then finish again. Do not commit; do not "
        f"disable tests.\n\n{gate.tail(result.output_tail, HOOK_TAIL_LINES)}"
    )
    return {"decision": "block", "reason": reason}


def cmd_hook(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        out = hook_stop(payload)
    except Exception as exc:  # a broken hook must never wedge the session
        out = {"systemMessage": f"ccorch stop hook error: {exc}"}
    if out:
        print(json.dumps(out))
    return 0


# --- entry point --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccorch", description="ccorch ticket workflow helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("context", help="markdown summary for the skill").set_defaults(fn=cmd_context)

    def ticket_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--id", required=True, help="ticket id, e.g. ABC-123")
        sp.add_argument("--type", required=True, choices=config.TICKET_TYPES)
        sp.add_argument("--title", required=True)

    sp = sub.add_parser("branch-name", help="preview the branch name")
    ticket_args(sp)
    sp.set_defaults(fn=cmd_branch_name)

    sp = sub.add_parser("start", help="create the ticket branch and start tracking it")
    ticket_args(sp)
    sp.add_argument("--base", help="override repo.base_branch")
    sp.add_argument("--no-fetch", action="store_true")
    sp.add_argument("--force", action="store_true", help="replace an unfinished active ticket")
    sp.set_defaults(fn=cmd_start)

    sub.add_parser("gate", help="run build + test").set_defaults(fn=cmd_gate)

    sp = sub.add_parser("commit", help="gate, then commit everything")
    group = sp.add_mutually_exclusive_group()
    group.add_argument("--phase", type=int, help="phase number (uses commit.phase_message)")
    group.add_argument("--fix", type=int, help="review fix iteration (commit.fix_message)")
    sp.add_argument("--title", help="phase title for the message")
    sp.add_argument("--note", help="handoff note for later phases (decisions, files, caveats)")
    sp.add_argument("--no-gate", action="store_true", help="skip the gate (not recommended)")
    sp.set_defaults(fn=cmd_commit)

    sp = sub.add_parser("note", help="save a handoff note")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_note)

    sp = sub.add_parser("hold", help="pause the Stop-hook gate (while asking the user)")
    sp.set_defaults(fn=cmd_hold, on=True)
    sp = sub.add_parser("resume", help="re-enable the Stop-hook gate")
    sp.set_defaults(fn=cmd_hold, on=False)

    sub.add_parser("review-info", help="commits + diffstat vs base").set_defaults(
        fn=cmd_review_info
    )

    sp = sub.add_parser("mr", help="push and open the GitLab MR via push options")
    sp.add_argument("--title")
    sp.add_argument("--description")
    sp.add_argument("--description-file")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_mr)

    sp = sub.add_parser("finish", help="stop tracking the active ticket")
    sp.add_argument("--outcome", default="abandoned")
    sp.set_defaults(fn=cmd_finish)

    sp = sub.add_parser("status", help="show the active ticket")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("init", help="create .claude/ccorch.toml with detected defaults")
    sp.add_argument("--write", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("manage", help="open the settings UI")
    sp.add_argument("--port", type=int, default=7420)
    sp.add_argument("--no-browser", action="store_true")
    sp.add_argument("--background", action="store_true")
    sp.set_defaults(fn=cmd_manage)

    sp = sub.add_parser("hook", help="hook entry point (reads JSON on stdin)")
    sp.add_argument("event", choices=["stop"])
    sp.set_defaults(fn=cmd_hook)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (CliError, config.ConfigError, branch.BranchNameError, GitError) as exc:
        print(f"ccorch: {exc}", file=sys.stderr)
        return 2
