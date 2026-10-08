import { useEffect, useState } from "react";
import { api, type ClaudeInfo, type PluginInfo } from "../api";

const HINT_KEY = "ccorch-restart-hint";

function rememberHint() {
  try {
    sessionStorage.setItem(HINT_KEY, "1");
  } catch {
    /* storage unavailable - the hint just won't survive the reload */
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Sidebar box: ccorch plugin version + update, Claude Code version + update. */
export function VersionsBox(props: { notify: (m: string, err?: boolean) => void }) {
  const { notify } = props;
  const [plugin, setPlugin] = useState<PluginInfo | null>(null);
  const [cli, setCli] = useState<ClaudeInfo | null>(null);
  const [busy, setBusy] = useState<"check" | "plugin" | "cli" | null>(null);
  const [restartHint, setRestartHint] = useState(() => {
    try {
      return sessionStorage.getItem(HINT_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    api.claudeInfo().then(setCli).catch(() => undefined);
    api.pluginInfo().then(setPlugin).catch(() => undefined);
  }, []);

  const run = async <T,>(kind: "check" | "plugin" | "cli", fn: () => Promise<T>) => {
    setBusy(kind);
    try {
      return await fn();
    } catch (e) {
      notify((e as Error).message, true);
      return undefined;
    } finally {
      setBusy(null);
    }
  };

  const check = () =>
    run("check", async () => {
      const p = await api.pluginCheck();
      setPlugin(p);
      notify(p.update_available ? `ccorch ${p.available_version} is available` : "ccorch is up to date");
    });

  const update = () =>
    run("plugin", async () => {
      const p = await api.pluginUpdate();
      setPlugin(p);
      setRestartHint(true);
      rememberHint();
      if (!p.relaunching) {
        notify(`ccorch updated to ${p.installed_version}`);
        return;
      }
      notify(`ccorch updated to ${p.installed_version} - restarting this page…`);
      for (let i = 0; i < 60; i++) {
        await sleep(500);
        try {
          if ((await api.meta2()).version === p.installed_version) {
            window.location.reload();
            return;
          }
        } catch {
          /* server is switching over */
        }
      }
      notify("Updated, but the page didn't restart - run /ccorch:manage again.", true);
    });

  const updateCli = () =>
    run("cli", async () => {
      const r = await api.claudeUpdate();
      notify(r.output.split("\n").slice(-1)[0] || `Claude Code ${r.version}`);
      setCli(await api.claudeInfo());
      setRestartHint(true);
      rememberHint();
    });

  const row = "flex items-center justify-between gap-2 text-xs";
  return (
    <div className="mt-3 grid gap-2 rounded-md border border-zinc-200 p-2.5 dark:border-zinc-800">
      <div className={row}>
        <span className="truncate text-zinc-500" title={plugin?.running_from}>
          ccorch {plugin?.installed_version ?? plugin?.running_version ?? "…"}
          {plugin?.dev_checkout && " (dev checkout)"}
        </span>
        {plugin?.installed &&
          (plugin.update_available ? (
            <button type="button" className="btn btn-primary px-2 py-0.5 text-xs" disabled={busy !== null} onClick={update}>
              {busy === "plugin" ? "Updating…" : `Update to ${plugin.available_version}`}
            </button>
          ) : (
            <button type="button" className="btn px-2 py-0.5 text-xs" disabled={busy !== null} onClick={check}>
              {busy === "check" ? "Checking…" : "Check for updates"}
            </button>
          ))}
      </div>
      {plugin && !plugin.installed && (
        <p className="text-[11px] text-zinc-500">Not installed as a plugin - updates come from your git checkout.</p>
      )}
      <div className={row}>
        <span className="truncate text-zinc-500" title={cli?.path ?? ""}>
          {cli === null ? "Claude Code …" : cli.path ? `Claude Code ${cli.version}` : "Claude Code not found"}
        </span>
        {cli?.path && (
          <button type="button" className="btn px-2 py-0.5 text-xs" disabled={busy !== null} onClick={updateCli}>
            {busy === "cli" ? "Updating…" : "Update"}
          </button>
        )}
      </div>
      {restartHint && (
        <p className="flex items-start justify-between gap-2 rounded bg-indigo-50 p-2 text-[11px] text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200">
          Restart your open Claude Code sessions to use the new version.
          <button
            type="button"
            onClick={() => {
              setRestartHint(false);
              try {
                sessionStorage.removeItem(HINT_KEY);
              } catch {
                /* ignore */
              }
            }}
          >
            ✕
          </button>
        </p>
      )}
      {cli?.api_key_env && (
        <p className="rounded bg-amber-50 p-2 text-[11px] text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          ANTHROPIC_API_KEY is set on this computer. The settings page removes it for its own calls so they
          use your subscription, but Claude Code started elsewhere would bill that API key.
        </p>
      )}
    </div>
  );
}
