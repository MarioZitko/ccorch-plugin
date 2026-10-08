import { useEffect, useState } from "react";
import { api, type Activity, type TicketRecord } from "../api";
import { Badge } from "./ui";

function when(iso?: string) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function TicketCard({ t, live }: { t: TicketRecord; live?: boolean }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm font-semibold">{t.ticket_id}</span>
        <span className="text-sm">{t.title}</span>
        {live ? <Badge tone="indigo">in progress</Badge> : <Badge tone="zinc">{t.outcome}</Badge>}
      </div>
      <div className="mt-1 font-mono text-xs text-zinc-500">{t.branch}</div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
        <span>started {when(t.started_at)}</span>
        {t.finished_at && <span>finished {when(t.finished_at)}</span>}
        <span>{t.commits.length} commits</span>
        <span>{t.phases_done} phases</span>
        <span>{t.fix_iterations} fix rounds</span>
        {t.mr_url && (
          <a className="text-indigo-600 hover:underline" href={t.mr_url} target="_blank" rel="noreferrer">
            merge request ↗
          </a>
        )}
      </div>
      {t.notes.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">
          {t.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ActivityView({ repoId }: { repoId: number }) {
  const [data, setData] = useState<Activity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .activity(repoId)
        .then((d) => alive && setData(d))
        .catch((e: Error) => alive && setError(e.message));
    void load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [repoId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-zinc-500">Loading…</p>;
  return (
    <div className="grid gap-3">
      <p className="text-xs text-zinc-500">
        Tickets run in this clone (from <code>.git/ccorch/</code>). The full conversation of each
        run is in Claude Code itself.
      </p>
      {data.active && <TicketCard t={data.active} live />}
      {data.history.map((t, i) => (
        <TicketCard key={i} t={t} />
      ))}
      {!data.active && data.history.length === 0 && (
        <p className="text-sm text-zinc-500">
          No tickets yet. In Claude Code, run <code>/ccorch:ticket PROJ-123</code>.
        </p>
      )}
    </div>
  );
}
