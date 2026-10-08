import { useEffect, useState } from "react";
import { api, type Config, type GateRun, type Meta, type TicketType } from "../api";
import {
  Field,
  ListEditor,
  NumberInput,
  Row,
  Section,
  Select,
  TagInput,
  TextInput,
  Toggle,
} from "./ui";

type Update = (fn: (c: Config) => void) => void;

const PLACEHOLDER_HINT = (names: string[]) => (
  <>
    Placeholders:{" "}
    {names.map((n) => (
      <code key={n} className="mr-1 rounded bg-zinc-100 px-1 dark:bg-zinc-800">{`{${n}}`}</code>
    ))}
  </>
);

export function RepoSettings(props: { repoId: number; meta: Meta; config: Config; update: Update }) {
  const { config: c, update, meta } = props;
  return (
    <div className="grid gap-5">
      <Section title="Repository">
        <Row>
          <Field label="Base branch" hint="Ticket branches are created from here.">
            <TextInput
              value={c.repo.base_branch}
              onChange={(v) => update((x) => void (x.repo.base_branch = v))}
            />
          </Field>
          <Field label="Remote">
            <TextInput value={c.repo.remote} onChange={(v) => update((x) => void (x.repo.remote = v))} />
          </Field>
        </Row>
      </Section>

      <BranchSection config={c} update={update} meta={meta} />

      <GateSection repoId={props.repoId} config={c} update={update} />

      <Section title="Commits" hint="The workflow commits after each phase once the gate passes.">
        <Field label="Phase commit" hint={PLACEHOLDER_HINT(["ticket_id", "index", "title", "type"])}>
          <TextInput
            mono
            value={c.commit.phase_message}
            onChange={(v) => update((x) => void (x.commit.phase_message = v))}
          />
        </Field>
        <Row>
          <Field label="Review-fix commit" hint={PLACEHOLDER_HINT(["ticket_id", "iteration"])}>
            <TextInput
              mono
              value={c.commit.fix_message}
              onChange={(v) => update((x) => void (x.commit.fix_message = v))}
            />
          </Field>
          <Field label="Single-change commit (small tickets)" hint={PLACEHOLDER_HINT(["ticket_id", "title"])}>
            <TextInput
              mono
              value={c.commit.single_message}
              onChange={(v) => update((x) => void (x.commit.single_message = v))}
            />
          </Field>
        </Row>
      </Section>

      <Section title="Merge request" hint="Created with GitLab push options - no API token needed.">
        <Row>
          <Field label="Target branch" hint="Empty = base branch.">
            <TextInput
              value={c.mr.target}
              placeholder={c.repo.base_branch}
              onChange={(v) => update((x) => void (x.mr.target = v))}
            />
          </Field>
          <Field label="Title" hint={PLACEHOLDER_HINT(["ticket_id", "title", "type", "branch"])}>
            <TextInput mono value={c.mr.title} onChange={(v) => update((x) => void (x.mr.title = v))} />
          </Field>
          <Field label="Assignee" hint="GitLab username (optional).">
            <TextInput value={c.mr.assignee} onChange={(v) => update((x) => void (x.mr.assignee = v))} />
          </Field>
        </Row>
        <Field label="Labels">
          <TagInput values={c.mr.labels} onChange={(v) => update((x) => void (x.mr.labels = v))} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            label="Delete source branch after merge"
            checked={c.mr.remove_source_branch}
            onChange={(v) => update((x) => void (x.mr.remove_source_branch = v))}
          />
          <Toggle
            label="Squash commits"
            checked={c.mr.squash}
            onChange={(v) => update((x) => void (x.mr.squash = v))}
          />
          <Toggle
            label="Open as draft"
            checked={c.mr.draft}
            onChange={(v) => update((x) => void (x.mr.draft = v))}
          />
          <Toggle
            label="Auto-merge when pipeline succeeds"
            checked={c.mr.auto_merge}
            onChange={(v) => update((x) => void (x.mr.auto_merge = v))}
          />
        </div>
      </Section>

      <Section title="Workflow">
        <Row>
          <Field
            label="Planning"
            hint={
              {
                auto: "Small changes (most bug fixes, config/copy tweaks) skip planning; bigger ones get a plan.",
                always: "Every ticket gets a plan first.",
                never: "Never plan - always the quick path (one change, one commit).",
              }[c.workflow.planning]
            }
          >
            <Select
              value={c.workflow.planning}
              options={["auto", "always", "never"]}
              onChange={(v) => update((x) => void (x.workflow.planning = v as Config["workflow"]["planning"]))}
            />
          </Field>
        </Row>
        <p className="text-xs text-zinc-500">
          Per ticket you can override it: <code>/ccorch:ticket ID quick</code> or{" "}
          <code>/ccorch:ticket ID plan</code>.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            label="Ask me to approve the plan"
            hint="Pass `auto` to /ccorch:ticket to skip once."
            checked={c.workflow.plan_approval}
            onChange={(v) => update((x) => void (x.workflow.plan_approval = v))}
          />
          <Toggle
            label="AI review before the MR"
            checked={c.workflow.review}
            onChange={(v) => update((x) => void (x.workflow.review = v))}
          />
          <Toggle
            label="Review quick changes too"
            hint="Off = quick-path changes go straight to the MR."
            checked={c.workflow.review_quick}
            onChange={(v) => update((x) => void (x.workflow.review_quick = v))}
          />
          <Toggle
            label="Quick path in the main session"
            hint="Cheaper: no subagent for changes that skip planning."
            checked={c.workflow.small_inline}
            onChange={(v) => update((x) => void (x.workflow.small_inline = v))}
          />
        </div>
        <Row>
          <Field label="Max review-fix rounds">
            <NumberInput
              min={0}
              max={5}
              value={c.workflow.max_fix_iterations}
              onChange={(v) => update((x) => void (x.workflow.max_fix_iterations = v))}
            />
          </Field>
          <Field
            label="Small change = up to N changed lines"
            hint="Quick-path changes and plan-path changes up to this size are reviewed by the small-change reviewer. 0 = only quick-path changes."
          >
            <NumberInput
              min={0}
              max={5000}
              value={c.workflow.small_review_max_lines}
              onChange={(v) => update((x) => void (x.workflow.small_review_max_lines = v))}
            />
          </Field>
        </Row>
      </Section>

      <Section
        title="Models"
        hint="Aliases use the newest model your installed Claude Code knows - keep the CLI updated. inherit = the agent's built-in default (planner opus, implementer sonnet, reviewer opus; for intake, your Claude Code default model). Personal overrides: .claude/ccorch.local.toml."
      >
        <Row>
          {(["intake", "planner", "implementer", "reviewer", "reviewer_small"] as const).map((role) => (
            <Field key={role} label={MODEL_LABELS[role]}>
              <Select
                value={c.models[role]}
                options={meta.model_choices}
                onChange={(v) => update((x) => void (x.models[role] = v))}
              />
            </Field>
          ))}
        </Row>
      </Section>

      <Section title="Tickets from transcripts" hint="Used by the Inbox tab.">
        <Row>
          <Field
            label="ID prefix"
            hint={`Tickets without an id in the transcript get ${c.intake.id_prefix || "T"}-001, -002, …`}
          >
            <TextInput
              mono
              value={c.intake.id_prefix}
              onChange={(v) => update((x) => void (x.intake.id_prefix = v))}
            />
          </Field>
        </Row>
      </Section>
    </div>
  );
}

const MODEL_LABELS = {
  intake: "Intake (transcript → tickets)",
  planner: "Planner",
  implementer: "Implementer",
  reviewer: "Reviewer",
  reviewer_small: "Reviewer for small changes",
} as const;

function BranchSection(props: { config: Config; update: Update; meta: Meta }) {
  const { config: c, update } = props;
  const [sample, setSample] = useState({ type: "feature" as TicketType, id: "PROJ-123", title: "Dodaj šifru kupca na račun" });
  const [preview, setPreview] = useState<{ name: string; error: string | null }>({ name: "", error: null });

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .previewBranch(c.branch, sample.type, sample.id, sample.title)
        .then(setPreview)
        .catch((e: Error) => setPreview({ name: "", error: e.message }));
    }, 200);
    return () => clearTimeout(t);
  }, [c.branch, sample]);

  return (
    <Section title="Branch naming" hint="The branch is created by a script, never by the model.">
      <Row>
        <Field label="Template" hint={PLACEHOLDER_HINT(["type", "ticket_id", "slug"])}>
          <TextInput
            mono
            value={c.branch.template}
            onChange={(v) => update((x) => void (x.branch.template = v))}
          />
        </Field>
        <Field label="Max slug length">
          <NumberInput
            min={5}
            max={100}
            value={c.branch.slug_max_len}
            onChange={(v) => update((x) => void (x.branch.slug_max_len = v))}
          />
        </Field>
      </Row>
      <div>
        <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
          {"{type}"} per ticket type
        </span>
        <div className="mt-1 grid gap-2 sm:grid-cols-3">
          {props.meta.ticket_types.map((t) => (
            <div key={t} className="flex items-center gap-2">
              <span className="w-16 text-xs text-zinc-500">{t}</span>
              <TextInput
                mono
                value={c.branch.type_prefix[t] ?? ""}
                onChange={(v) => update((x) => void (x.branch.type_prefix[t] = v))}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-md border border-dashed border-zinc-300 p-3 dark:border-zinc-700">
        <div className="grid gap-2 sm:grid-cols-[8rem_9rem_1fr]">
          <Select
            value={sample.type}
            options={props.meta.ticket_types}
            onChange={(v) => setSample({ ...sample, type: v as TicketType })}
          />
          <TextInput value={sample.id} onChange={(v) => setSample({ ...sample, id: v })} />
          <TextInput value={sample.title} onChange={(v) => setSample({ ...sample, title: v })} />
        </div>
        <div className="mt-2 font-mono text-sm">
          {preview.error ? (
            <span className="text-red-600">{preview.error}</span>
          ) : (
            <>
              <span className="text-zinc-500">→ </span>
              <span className="text-indigo-700 dark:text-indigo-300">{preview.name}</span>
            </>
          )}
        </div>
      </div>
    </Section>
  );
}

function GateSection(props: { repoId: number; config: Config; update: Update }) {
  const { config: c, update } = props;
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<GateRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.testGate(props.repoId, c));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Section
      title="Build & test gate"
      hint="Run by the app after every phase. Claude cannot finish while it fails."
    >
      <Row>
        <Field label="Build commands">
          <ListEditor
            values={c.gate.build}
            placeholder="dotnet build"
            onChange={(v) => update((x) => void (x.gate.build = v))}
          />
        </Field>
        <Field label="Test commands">
          <ListEditor
            values={c.gate.test}
            placeholder="dotnet test"
            onChange={(v) => update((x) => void (x.gate.test = v))}
          />
        </Field>
        <div className="grid gap-4">
          <Field label="Timeout per command (s)">
            <NumberInput
              min={1}
              value={c.gate.timeout_s}
              onChange={(v) => update((x) => void (x.gate.timeout_s = v))}
            />
          </Field>
          <Field label="Max automatic fix attempts">
            <NumberInput
              min={1}
              max={8}
              value={c.gate.max_attempts}
              onChange={(v) => update((x) => void (x.gate.max_attempts = v))}
            />
          </Field>
        </div>
      </Row>
      <div className="flex items-center gap-3">
        <button type="button" className="btn" disabled={running} onClick={run}>
          {running ? "Running…" : "▶ Run gate now"}
        </button>
        {result && (
          <span className={`text-sm font-medium ${result.passed ? "text-emerald-600" : "text-red-600"}`}>
            {result.skipped
              ? "No commands configured"
              : result.passed
                ? "Passed"
                : `Failed (exit ${result.exit_code}): ${result.command}`}
          </span>
        )}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
      {result && !result.skipped && result.output && (
        <pre className="max-h-64 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs text-zinc-200">
          {result.output}
        </pre>
      )}
    </Section>
  );
}
