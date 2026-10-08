import type React from "react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Config,
  type InboxTicket,
  type IntakeResult,
  type StartMode,
  type TicketDraft,
  type TicketType,
} from "../api";
import { Badge, Select, TextInput } from "./ui";

const TYPES: TicketType[] = ["feature", "bug", "task"];

function TicketFields(props: {
  t: TicketDraft;
  onChange: (t: TicketDraft) => void;
  onRemove?: () => void;
  idLockedReason?: string;
}) {
  const { t, onChange } = props;
  return (
    <div className="grid gap-3">
      <div className="grid gap-2 sm:grid-cols-[9rem_8rem_6.5rem_1fr_auto]">
        <div title={props.idLockedReason}>
          <TextInput
            mono
            value={t.id}
            disabled={!!props.idLockedReason}
            onChange={(id) => onChange({ ...t, id })}
          />
        </div>
        <Select value={t.type} options={TYPES} onChange={(v) => onChange({ ...t, type: v as TicketType })} />
        <Select
          value={t.size}
          options={["small", "big"]}
          onChange={(v) => onChange({ ...t, size: v as "small" | "big" })}
        />
        <TextInput value={t.title} onChange={(title) => onChange({ ...t, title })} />
        {props.onRemove && (
          <button type="button" className="btn px-2" title="Drop this ticket" onClick={props.onRemove}>
            ✕
          </button>
        )}
      </div>
      <textarea
        className="input min-h-20 text-sm"
        placeholder="Description"
        value={t.description}
        onChange={(e) => onChange({ ...t, description: e.target.value })}
      />
      <textarea
        className="input min-h-16 font-mono text-xs"
        placeholder="Acceptance criteria, one per line"
        value={t.acceptance_criteria.join("\n")}
        onChange={(e) => onChange({ ...t, acceptance_criteria: e.target.value.split("\n") })}
      />
    </div>
  );
}

function DraftCard(props: {
  t: TicketDraft;
  onChange: (t: TicketDraft) => void;
  onRemove: () => void;
}) {
  return (
    <div className="card p-4">
      <TicketFields t={props.t} onChange={props.onChange} onRemove={props.onRemove} />
    </div>
  );
}

function JiraMove(props: { repoId: number; t: InboxTicket; notify: (m: string, err?: boolean) => void }) {
  const { t, repoId } = props;
  const [targets, setTargets] = useState<string[] | null>(null);
  const [status, setStatus] = useState(t.jira_status ?? "");
  const key = t.jira_key ?? "";

  useEffect(() => {
    api
      .jiraIssue(repoId, key)
      .then((i) => {
        setTargets(i.targets);
        setStatus(i.status);
      })
      .catch((e: Error) => props.notify(`Jira: ${e.message}`, true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, key]);

  const move = (to: string) =>
    api
      .jiraMove(repoId, key, to)
      .then(() => {
        setStatus(to);
        props.notify(`${key} moved to ${to}`);
        return api.jiraIssue(repoId, key).then((i) => setTargets(i.targets));
      })
      .catch((e: Error) => props.notify(e.message, true));

  return (
    <div className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
      <span>Jira status: {status || "…"}</span>
      <select
        className="input py-1 text-xs"
        style={{ width: "auto" }}
        value=""
        disabled={!targets?.length}
        onChange={(e) => e.target.value && void move(e.target.value)}
      >
        <option value="">{targets === null ? "Loading…" : "Move to…"}</option>
        {(targets ?? []).map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}

function Banner(props: { children: React.ReactNode }) {
  return (
    <p className="rounded-md bg-indigo-50 p-3 text-sm text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200">
      {props.children}
    </p>
  );
}

function QueuedCard(props: {
  repoId: number;
  t: InboxTicket;
  running: boolean;
  onChanged: () => void;
  notify: (m: string, err?: boolean) => void;
}) {
  const { t, repoId } = props;
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<StartMode>("");
  const [edit, setEdit] = useState<TicketDraft | null>(null);
  const finished = t.status === "done" || t.status === "abandoned";

  const save = async () => {
    if (!edit) return;
    try {
      const res = await api.updateInbox(repoId, t.id, {
        ...edit,
        acceptance_criteria: edit.acceptance_criteria.filter((c) => c.trim()),
      });
      setEdit(null);
      props.onChanged();
      if (res.jira && res.jira !== "updated") props.notify(res.jira, true);
      else
        props.notify(
          res.running
            ? `Saved ${t.id}. Claude Code picks it up at its next step.`
            : `Saved ${t.id}${res.jira ? " (and updated in Jira)" : ""}`,
        );
    } catch (e) {
      props.notify((e as Error).message, true);
    }
  };

  const copy = async (shell: boolean) => {
    const cmd = await api.inboxCommand(repoId, t.id, mode);
    await navigator.clipboard.writeText(shell ? cmd.shell : cmd.slash);
    props.notify(shell ? "Terminal command copied" : `Copied: ${cmd.slash}`);
  };

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{t.id}</span>
        <Badge tone={t.type === "bug" ? "amber" : "indigo"}>{t.type}</Badge>
        <Badge tone="zinc">{t.size}</Badge>
        {t.status === "started" ? (
          <Badge tone="green">started</Badge>
        ) : finished ? (
          <Badge tone={t.status === "done" ? "indigo" : "amber"}>{t.status}</Badge>
        ) : (
          <Badge tone="zinc">queued</Badge>
        )}
        {(t.revision ?? 1) > 1 && <span className="text-xs text-zinc-500">edited · rev {t.revision}</span>}
        {t.jira_url && (
          <a className="text-xs text-indigo-600 hover:underline" href={t.jira_url} target="_blank" rel="noreferrer">
            Jira ↗
          </a>
        )}
        {t.jira_status && <Badge tone="indigo">{t.jira_status}</Badge>}
        <div className="ml-auto flex flex-wrap justify-end gap-1.5 whitespace-nowrap">
          <button
            type="button"
            className="btn py-1 text-xs"
            disabled={edit !== null}
            onClick={() => {
              setOpen(true);
              setEdit({
                id: t.id,
                type: t.type,
                size: t.size,
                title: t.title,
                description: t.description,
                acceptance_criteria: t.acceptance_criteria,
              });
            }}
          >
            Edit
          </button>
          {!finished && (<>
          <select
            className="input py-1 text-xs"
            style={{ width: "auto" }}
            title="How to start: let the workflow decide, skip planning, or always plan"
            value={mode}
            onChange={(e) => setMode(e.target.value as StartMode)}
          >
            <option value="">auto (looks {t.size})</option>
            <option value="quick">quick (no plan)</option>
            <option value="plan">with plan</option>
          </select>
          <button
            type="button"
            className="btn btn-primary py-1 text-xs"
            title="Opens a terminal in the repo running Claude Code with /ccorch:ticket"
            onClick={() =>
              api
                .launch(repoId, t.id, mode)
                .then(() => props.notify("Opening Claude Code in a new terminal…"))
                .catch((e: Error) => props.notify(e.message, true))
            }
          >
            ▶ Open in Claude Code
          </button>
          <button type="button" className="btn py-1 text-xs" onClick={() => copy(false)} title="Copy /ccorch:ticket command">
            Copy command
          </button>
          <button type="button" className="btn py-1 text-xs" onClick={() => copy(true)} title="Copy a shell command that starts Claude Code with it">
            Copy for terminal
          </button>
          </>)}
          <button
            type="button"
            className="btn px-2 py-1 text-xs"
            title="Delete from inbox"
            onClick={() => api.deleteInbox(repoId, t.id).then(props.onChanged)}
          >
            ✕
          </button>
        </div>
      </div>
      <button type="button" className="mt-2 block w-full text-left text-sm hover:underline" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {t.title}
      </button>
      {t.branch && <div className="mt-1 font-mono text-xs text-zinc-500">{t.branch}</div>}
      {t.mr_url && (
        <a className="text-xs text-indigo-600 hover:underline" href={t.mr_url} target="_blank" rel="noreferrer">
          Merge request ↗
        </a>
      )}
      {edit && (
        <div className="mt-3 grid gap-3">
          {props.running ? (
            <Banner>
              Claude Code is working on this ticket. It picks up your change before its next step
              (next phase, review or merge request).
            </Banner>
          ) : t.status === "done" ? (
            <Banner>The merge request is already open - this change won&apos;t reach it.</Banner>
          ) : t.status === "abandoned" ? (
            <Banner>This ticket was abandoned - nothing is working on it.</Banner>
          ) : t.status === "started" ? (
            <Banner>Started on {t.branch}.</Banner>
          ) : null}
          {t.status === "started" && (
            <p className="text-xs text-zinc-500">
              The branch keeps its name, so a new type won&apos;t change the branch prefix. A new
              title is used for later commits and the merge request.
            </p>
          )}
          <TicketFields
            t={edit}
            onChange={setEdit}
            idLockedReason={
              t.status !== "queued"
                ? "The branch is named after the id"
                : t.jira_key
                  ? "The id is the Jira key"
                  : undefined
            }
          />
          <div className="flex gap-2">
            <button type="button" className="btn btn-primary" onClick={save}>
              Save
            </button>
            <button type="button" className="btn" onClick={() => setEdit(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {open && !edit && (
        <div className="mt-3 grid gap-2 text-sm">
          {t.jira_key && <JiraMove repoId={repoId} t={t} notify={props.notify} />}
          <p className="whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">{t.description || "(no description)"}</p>
          {t.acceptance_criteria.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">
              {t.acceptance_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function InboxView(props: { repoId: number; activeTicketId?: string; intakeModel: string; jira?: Config["jira"]; notify: (m: string, err?: boolean) => void }) {
  const { repoId, notify } = props;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [drafts, setDrafts] = useState<TicketDraft[]>([]);
  const [queued, setQueued] = useState<InboxTicket[]>([]);
  const jiraOn = !!props.jira?.enabled && props.jira.create_issues;
  const [alsoJira, setAlsoJira] = useState(true);

  const load = useCallback(() => api.inbox(repoId).then(setQueued).catch(() => undefined), [repoId]);
  useEffect(() => {
    void load();
    setResult(null);
    setDrafts([]);
  }, [load]);

  const extract = async () => {
    setBusy(true);
    try {
      const r = await api.intake(repoId, text);
      setResult(r);
      setDrafts(r.tickets);
      if (!r.tickets.length) notify("No tickets found in the text");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  const newTicket = async () => {
    try {
      const n = await api.nextId(repoId, drafts.length + 1);
      // Skip ids already on screen (a draft may have been removed from the middle).
      const used = new Set(drafts.map((d) => d.id));
      const id = n.ids.find((i) => !used.has(i)) ?? n.ids[n.ids.length - 1];
      setDrafts([
        ...drafts,
        { id, type: "task", title: "", description: "", acceptance_criteria: [], size: "big" },
      ]);
      if (n.warning) notify(n.warning, true);
    } catch (e) {
      notify((e as Error).message, true);
    }
  };

  const save = async () => {
    try {
      const clean = drafts.map((d) => ({ ...d, acceptance_criteria: d.acceptance_criteria.filter((c) => c.trim()) }));
      const res = await api.saveInbox(repoId, clean, jiraOn && alsoJira);
      const failed = res.failed ?? [];
      if (res.saved.length) notify(`Saved ${res.saved.join(", ")} to the inbox`);
      if (failed.length) {
        // Keep what did not work on screen so nothing typed is lost.
        setDrafts(failed.map((f) => f.draft));
        notify(failed.map((f) => `${f.draft.id}: ${f.error}`).join(" | "), true);
      } else {
        setDrafts([]);
        setResult(null);
        setText("");
      }
      await load();
    } catch (e) {
      notify((e as Error).message, true);
    }
  };

  return (
    <div className="grid gap-6">
      <section className="card grid gap-3 p-5">
        <div>
          <h2 className="text-sm font-semibold">Transcript → tickets</h2>
          <p className="text-xs text-zinc-500">
            Paste a meeting transcript, notes or an email. One {props.intakeModel} call through your
            local Claude Code (your subscription, no tools, no repo access) turns it into tickets.
          </p>
        </div>
        <textarea
          className="input min-h-40 text-sm"
          placeholder="Paste the transcript here…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn btn-primary" disabled={busy || !text.trim()} onClick={extract}>
            {busy ? "Reading…" : "Extract tickets"}
          </button>
          <button type="button" className="btn" onClick={newTicket}>
            + New ticket
          </button>
          {result && (
            <span className="text-xs text-zinc-500">
              {result.tickets.length} tickets · {result.model} · {(result.duration_ms / 1000).toFixed(1)}s
              {result.cost_usd ? ` · ~$${result.cost_usd.toFixed(4)} equivalent` : ""}
            </span>
          )}
        </div>
        {result?.id_warning && (
          <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            {result.id_warning}
          </p>
        )}
        {result?.notes && (
          <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            {result.notes}
          </p>
        )}
      </section>

      {drafts.length > 0 && (
        <section className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Review {drafts.length} tickets</h2>
            <div className="flex flex-wrap items-center gap-2">
              {jiraOn && (
                <label className="flex items-center gap-1.5 text-xs">
                  <input type="checkbox" checked={alsoJira} onChange={(e) => setAlsoJira(e.target.checked)} />
                  Also create in Jira ({props.jira?.project_key}; Jira assigns the key on save)
                </label>
              )}
              <button type="button" className="btn" onClick={() => setDrafts([])}>
                Discard
              </button>
              <button type="button" className="btn btn-primary" onClick={save}>
                Save to inbox
              </button>
            </div>
          </div>
          {drafts.map((d, i) => (
            <DraftCard
              key={i}
              t={d}
              onChange={(t) => setDrafts(drafts.map((x, j) => (j === i ? t : x)))}
              onRemove={() => setDrafts(drafts.filter((_, j) => j !== i))}
            />
          ))}
        </section>
      )}

      <section className="grid gap-3">
        <h2 className="text-sm font-semibold">Inbox</h2>
        {queued.length === 0 ? (
          <p className="text-sm text-zinc-500">No tickets waiting.</p>
        ) : (
          queued.map((t) => <QueuedCard key={t.id} repoId={repoId} t={t} running={t.id === props.activeTicketId} onChanged={load} notify={notify} />)
        )}
      </section>
    </div>
  );
}
