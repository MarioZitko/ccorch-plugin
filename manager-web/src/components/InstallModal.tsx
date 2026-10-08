import { useState } from "react";
import type { FileChange, Plan } from "../api";
import { Modal } from "./ui";

type Line = { kind: " " | "+" | "-"; text: string };

/** Line diff via LCS - files here are small (config, settings.json, .gitignore). */
function diffLines(oldText: string, newText: string): Line[] {
  const a = oldText.split("\n");
  const b = newText.split("\n");
  const n = a.length;
  const m = b.length;
  const lcs = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const out: Line[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: " ", text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ kind: "-", text: a[i++] });
    else out.push({ kind: "+", text: b[j++] });
  }
  while (i < n) out.push({ kind: "-", text: a[i++] });
  while (j < m) out.push({ kind: "+", text: b[j++] });
  return out;
}

function FileDiff({ change }: { change: FileChange }) {
  const lines = diffLines(change.old ?? "", change.new);
  return (
    <div className="overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between bg-zinc-100 px-3 py-1.5 font-mono text-xs dark:bg-zinc-800">
        <span>{change.path}</span>
        <span className="text-zinc-500">{change.old === null ? "new file" : "modified"}</span>
      </div>
      <pre className="max-h-80 overflow-auto font-mono text-xs leading-5">
        {lines.map((l, idx) => (
          <div
            key={idx}
            className={
              l.kind === "+"
                ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200"
                : l.kind === "-"
                  ? "bg-red-50 text-red-900 dark:bg-red-950/50 dark:text-red-200"
                  : "text-zinc-500"
            }
          >
            <span className="inline-block w-5 select-none pl-1">{l.kind}</span>
            {l.text}
          </div>
        ))}
      </pre>
    </div>
  );
}

export function InstallModal(props: {
  plan: Plan;
  onClose: () => void;
  onApply: (commit: boolean) => Promise<void>;
}) {
  const [commit, setCommit] = useState(false);
  const [busy, setBusy] = useState(false);
  const { plan } = props;
  return (
    <Modal title="Review changes" onClose={props.onClose} wide>
      {plan.changes.length === 0 ? (
        <p className="text-sm text-zinc-500">Everything is already up to date.</p>
      ) : (
        <div className="grid gap-4">
          {plan.marketplace_missing && (
            <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
              No marketplace URL set, so <code>.claude/settings.json</code> is not updated and
              teammates won't be prompted to install the plugin. Set it under “Marketplace”.
            </p>
          )}
          {plan.changes.map((c) => (
            <FileDiff key={c.path} change={c} />
          ))}
          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={commit} onChange={(e) => setCommit(e.target.checked)} />
              Commit these files on the current branch
            </label>
            <div className="flex gap-2">
              <button type="button" className="btn" onClick={props.onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await props.onApply(commit);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Writing…" : "Write files"}
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
