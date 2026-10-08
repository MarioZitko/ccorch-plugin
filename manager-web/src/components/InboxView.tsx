import { useCallback, useEffect, useState } from "react";
import {
  api,
  type InboxTicket,
  type IntakeResult,
  type StartMode,
  type TicketDraft,
  type TicketType,
} from "../api";
import { Badge, Select, TextInput } from "./ui";

const TYPES: TicketType[] = ["feature", "bug", "task"];

function DraftCard(props: {
  t: TicketDraft;
  onChange: (t: TicketDraft) => void;
  onRemove: () => void;
}) {
  const { t, onChange } = props;
  return (
    <div className="card grid gap-3 p-4">
      <div className="grid gap-2 sm:grid-cols-[9rem_8rem_6.5rem_1fr_auto]">
        <TextInput mono value={t.id} onChange={(id) => onChange({ ...t, id })} />
        <Select value={t.type} options={TYPES} onChange={(v) => onChange({ ...t, type: v as TicketType })} />
        <Select
          value={t.size}
          options={["small", "big"]}
          onChange={(v) => onChange({ ...t, size: v as "small" | "big" })}
        />
        <TextInput value={t.title} onChange={(title) => onChange({ ...t, title })} />
        <button type="button" className="btn px-2" title="Drop this ticket" onClick={props.onRemove}>
          ✕
        </button>
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

function QueuedCard(props: { repoId: number; t: InboxTicket; onChanged: () => void; notify: (m: string, err?: boolean) => void }) {
  const { t, repoId } = props;
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<StartMode>("");

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
        {t.status === "started" ? <Badge tone="green">started</Badge> : <Badge tone="zinc">queued</Badge>}
        <div className="ml-auto flex gap-1.5 whitespace-nowrap">
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
      {open && (
        <div className="mt-3 grid gap-2 text-sm">
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

export function InboxView(props: { repoId: number; intakeModel: string; notify: (m: string, err?: boolean) => void }) {
  const { repoId, notify } = props;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [drafts, setDrafts] = useState<TicketDraft[]>([]);
  const [queued, setQueued] = useState<InboxTicket[]>([]);

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

  const save = async () => {
    try {
      const clean = drafts.map((d) => ({ ...d, acceptance_criteria: d.acceptance_criteria.filter((c) => c.trim()) }));
      const res = await api.saveInbox(repoId, clean);
      notify(`Saved ${res.saved.join(", ")} to the inbox`);
      setDrafts([]);
      setResult(null);
      setText("");
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
        <div className="flex items-center gap-3">
          <button type="button" className="btn btn-primary" disabled={busy || !text.trim()} onClick={extract}>
            {busy ? "Reading…" : "Extract tickets"}
          </button>
          {result && (
            <span className="text-xs text-zinc-500">
              {result.tickets.length} tickets · {result.model} · {(result.duration_ms / 1000).toFixed(1)}s
              {result.cost_usd ? ` · ~$${result.cost_usd.toFixed(4)} equivalent` : ""}
            </span>
          )}
        </div>
        {result?.notes && (
          <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            {result.notes}
          </p>
        )}
      </section>

      {drafts.length > 0 && (
        <section className="grid gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Review {drafts.length} tickets</h2>
            <div className="flex gap-2">
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
          queued.map((t) => <QueuedCard key={t.id} repoId={repoId} t={t} onChanged={load} notify={notify} />)
        )}
      </section>
    </div>
  );
}
