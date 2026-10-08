import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Config,
  type Meta,
  type Plan,
  type RepoConfig,
  type RepoSummary,
} from "./api";
import { ActivityView } from "./components/ActivityView";
import { InboxView } from "./components/InboxView";
import { VersionsBox } from "./components/VersionsBox";
import { AddRepoModal, MarketplaceModal } from "./components/Dialogs";
import { InstallModal } from "./components/InstallModal";
import { RepoSettings } from "./components/RepoSettings";
import { Badge } from "./components/ui";

function status(r: RepoSummary) {
  if (!r.exists || !r.is_git) return <Badge tone="amber">missing</Badge>;
  if (r.has_config && r.plugin_enabled) return <Badge tone="green">installed</Badge>;
  if (r.has_config) return <Badge tone="indigo">config only</Badge>;
  return <Badge tone="zinc">not set up</Badge>;
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [tab, setTab] = useState<"settings" | "inbox" | "activity">("settings");

  const [loaded, setLoaded] = useState<RepoConfig | null>(null);
  const [draft, setDraft] = useState<Config | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [dialog, setDialog] = useState<"add" | "market" | null>(null);
  const [toast, setToast] = useState<{ text: string; tone: "ok" | "err" } | null>(null);

  const notify = (text: string, tone: "ok" | "err" = "ok") => {
    setToast({ text, tone });
    setTimeout(() => setToast(null), 4000);
  };

  const refreshRepos = useCallback(() => api.repos().then(setRepos), []);

  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => notify(e.message, "err"));
    refreshRepos().catch((e: Error) => notify(e.message, "err"));
  }, [refreshRepos]);


  useEffect(() => {
    if (selected === null && repos.length) setSelected(repos[0].id);
  }, [repos, selected]);

  useEffect(() => {
    if (selected === null) return;
    setLoaded(null);
    setDraft(null);
    api
      .config(selected)
      .then((c) => {
        setLoaded(c);
        setDraft(structuredClone(c.config));
        setErrors(c.errors);
      })
      .catch((e: Error) => notify(e.message, "err"));
  }, [selected]);

  // Validate as you type (server is the single source of truth for the rules).
  useEffect(() => {
    if (selected === null || !draft) return;
    const t = setTimeout(() => {
      api.validate(selected, draft).then((r) => setErrors(r.errors)).catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
  }, [draft, selected]);

  const dirty = useMemo(
    () => !!draft && !!loaded && JSON.stringify(draft) !== JSON.stringify(loaded.config),
    [draft, loaded],
  );

  const update = (fn: (c: Config) => void) =>
    setDraft((d) => {
      if (!d) return d;
      const next = structuredClone(d);
      fn(next);
      return next;
    });

  const repo = repos.find((r) => r.id === selected);

  const review = async () => {
    if (selected === null || !draft) return;
    try {
      const p = await api.plan(selected, draft);
      if (p.errors.length) setErrors(p.errors);
      else setPlan(p);
    } catch (e) {
      notify((e as Error).message, "err");
    }
  };

  const applyPlan = async (commit: boolean) => {
    if (selected === null || !draft) return;
    try {
      const res = await api.apply(selected, draft, commit);
      setPlan(null);
      notify(
        res.written.length
          ? `Wrote ${res.written.join(", ")}${res.commit ? ` · committed ${res.commit.slice(0, 8)}` : ""}`
          : "Nothing to write",
      );
      const fresh = await api.config(selected);
      setLoaded(fresh);
      setDraft(structuredClone(fresh.config));
      await refreshRepos();
    } catch (e) {
      notify((e as Error).message, "err");
    }
  };

  const remove = async () => {
    if (selected === null || !repo) return;
    if (!confirm(`Remove ${repo.name} from this list? (Files in the repo are not touched.)`)) return;
    await api.removeRepo(selected);
    setSelected(null);
    await refreshRepos();
  };

  return (
    <div className="flex h-screen">
      <aside className="flex w-72 shrink-0 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <div className="text-sm font-semibold">ccorch manager</div>
          <div className="text-xs text-zinc-500">Per-repo settings for /ccorch:ticket</div>
          <VersionsBox notify={(m, err) => notify(m, err ? "err" : "ok")} />
        </div>
        <nav className="flex-1 overflow-auto p-2">
          {repos.map((r) => (
            <button
              type="button"
              key={r.id}
              onClick={() => {
                if (dirty && !confirm("Discard unsaved changes?")) return;
                setSelected(r.id);
              }}
              className={`mb-1 block w-full rounded-md px-3 py-2 text-left ${
                r.id === selected
                  ? "bg-indigo-50 dark:bg-indigo-950/60"
                  : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{r.name}</span>
                {status(r)}
              </div>
              <div className="truncate font-mono text-[11px] text-zinc-500">
                {r.active_ticket ? `▶ ${r.active_ticket.ticket_id} · ${r.active_ticket.branch}` : r.branch}
              </div>
            </button>
          ))}
          {repos.length === 0 && (
            <p className="px-3 py-2 text-sm text-zinc-500">No repositories yet.</p>
          )}
        </nav>
        <div className="grid gap-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
          <button type="button" className="btn btn-primary justify-center" onClick={() => setDialog("add")}>
            + Add repository
          </button>
          <button type="button" className="btn justify-center" onClick={() => setDialog("market")}>
            Marketplace{meta && !meta.marketplace.url ? " ⚠" : ""}
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        {repo && meta ? (
          <>
            <header className="flex items-center justify-between gap-4 border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold">{repo.name}</h1>
                  {status(repo)}
                </div>
                <div className="truncate font-mono text-xs text-zinc-500">
                  {repo.path} · {repo.branch} {repo.remote_url ? `· ${repo.remote_url}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-1 rounded-md bg-zinc-100 p-0.5 text-sm dark:bg-zinc-800">
                {(["settings", "inbox", "activity"] as const).map((t) => (
                  <button
                    type="button"
                    key={t}
                    onClick={() => setTab(t)}
                    className={`rounded px-3 py-1 capitalize ${
                      tab === t ? "bg-white shadow-xs dark:bg-zinc-950" : "text-zinc-500"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </header>

            <div className="flex-1 overflow-auto">
              <div className="mx-auto max-w-4xl p-6">
                {tab === "activity" ? (
                  <ActivityView repoId={repo.id} />
                ) : tab === "inbox" ? (
                  <InboxView
                    repoId={repo.id}
                    activeTicketId={repo.active_ticket?.ticket_id}
                    intakeModel={loaded?.config.models.intake ?? "haiku"}
                    jira={loaded?.config.jira}
                    notify={(m, err) => notify(m, err ? "err" : "ok")}
                  />
                ) : draft && loaded ? (
                  <>
                    {!loaded.has_file && (
                      <p className="mb-5 rounded-md bg-indigo-50 p-3 text-sm text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200">
                        Not configured yet - these values were detected from the repo. Review them
                        and click <b>Install</b>.
                      </p>
                    )}
                    <RepoSettings repoId={repo.id} meta={meta} config={draft} update={update} />
                    <button type="button" className="mt-6 text-xs text-zinc-500 hover:text-red-600" onClick={remove}>
                      Remove from list
                    </button>
                  </>
                ) : (
                  <p className="text-sm text-zinc-500">Loading…</p>
                )}
              </div>
            </div>

            {tab === "settings" && draft && loaded && (
              <footer className="border-t border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
                <div className="mx-auto flex max-w-4xl items-center justify-between gap-4">
                  <div className="min-w-0 text-sm">
                    {errors.length ? (
                      <ul className="text-red-600">
                        {errors.map((e) => (
                          <li key={e} className="truncate">
                            {e}
                          </li>
                        ))}
                      </ul>
                    ) : dirty ? (
                      <span className="text-amber-600">Unsaved changes</span>
                    ) : (
                      <span className="text-zinc-500">
                        {loaded.has_file ? "Saved in .claude/ccorch.toml" : "Not installed"}
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      className="btn"
                      disabled={!dirty}
                      onClick={() => setDraft(structuredClone(loaded.config))}
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={errors.length > 0}
                      onClick={review}
                    >
                      {loaded.has_file && repo.plugin_enabled ? "Review & save" : "Review & install"}
                    </button>
                  </div>
                </div>
              </footer>
            )}
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-zinc-500">Add a repository to configure ccorch for it.</p>
              <button type="button" className="btn btn-primary mt-3" onClick={() => setDialog("add")}>
                + Add repository
              </button>
            </div>
          </div>
        )}
      </main>

      {plan && <InstallModal plan={plan} onClose={() => setPlan(null)} onApply={applyPlan} />}
      {dialog === "add" && (
        <AddRepoModal
          onClose={() => setDialog(null)}
          onAdded={async (id) => {
            setDialog(null);
            await refreshRepos();
            setSelected(id);
          }}
        />
      )}
      {dialog === "market" && meta && (
        <MarketplaceModal
          value={meta.marketplace}
          onClose={() => setDialog(null)}
          onSaved={(m) => {
            setMeta({ ...meta, marketplace: m });
            setDialog(null);
            notify("Marketplace saved");
          }}
        />
      )}
      {toast && (
        <div
          className={`fixed bottom-20 right-6 z-50 rounded-md px-4 py-2 text-sm text-white shadow-lg ${
            toast.tone === "ok" ? "bg-zinc-900 dark:bg-zinc-700" : "bg-red-600"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}
