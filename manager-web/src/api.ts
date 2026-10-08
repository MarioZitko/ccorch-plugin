export type TicketType = "feature" | "bug" | "task";

export interface Config {
  repo: { base_branch: string; remote: string };
  branch: { template: string; slug_max_len: number; type_prefix: Record<TicketType, string> };
  gate: { build: string[]; test: string[]; timeout_s: number; max_attempts: number };
  commit: { phase_message: string; fix_message: string; single_message: string };
  mr: {
    target: string;
    title: string;
    remove_source_branch: boolean;
    squash: boolean;
    draft: boolean;
    auto_merge: boolean;
    labels: string[];
    assignee: string;
  };
  workflow: {
    plan_approval: boolean;
    review: boolean;
    max_fix_iterations: number;
    small_inline: boolean;
  };
  models: { planner: string; implementer: string; reviewer: string };
}

export interface Marketplace {
  name: string;
  url: string;
  ref: string;
}

export interface Meta {
  defaults: Config;
  ticket_types: TicketType[];
  model_choices: string[];
  marketplace: Marketplace;
}

export interface RepoSummary {
  id: number;
  path: string;
  name: string;
  exists: boolean;
  is_git: boolean;
  branch?: string;
  remote_url?: string;
  has_config?: boolean;
  plugin_enabled?: boolean;
  active_ticket?: { ticket_id: string; title: string; branch: string } | null;
}

export interface RepoConfig {
  config: Config;
  has_file: boolean;
  detected: Config;
  local_overrides: Record<string, unknown>;
  errors: string[];
}

export interface FileChange {
  path: string;
  old: string | null;
  new: string;
}

export interface Plan {
  errors: string[];
  changes: FileChange[];
  marketplace_missing: boolean;
}

export interface GateRun {
  passed: boolean;
  exit_code: number;
  command: string;
  skipped: boolean;
  output: string;
}

export interface TicketRecord {
  ticket_id: string;
  type: string;
  title: string;
  branch: string;
  base: string;
  started_at: string;
  finished_at?: string;
  outcome?: string;
  phases_done: number;
  fix_iterations: number;
  commits: string[];
  mr_url: string | null;
  notes: string[];
}

export interface Activity {
  active: TicketRecord | null;
  history: TicketRecord[];
}

export interface DirListing {
  path: string;
  parent: string | null;
  is_git: boolean;
  entries: { name: string; path: string; is_git: boolean }[];
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "X-CCorch": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return (await res.json()) as T;
}

export const api = {
  meta: () => call<Meta>("GET", "/api/meta"),
  setMarketplace: (m: Marketplace) => call<Marketplace>("PUT", "/api/marketplace", m),
  repos: () => call<RepoSummary[]>("GET", "/api/repos"),
  addRepo: (path: string) => call<RepoSummary>("POST", "/api/repos", { path }),
  removeRepo: (id: number) => call<{ ok: boolean }>("DELETE", `/api/repos/${id}`),
  config: (id: number) => call<RepoConfig>("GET", `/api/repos/${id}/config`),
  validate: (id: number, config: Config) =>
    call<{ errors: string[] }>("POST", `/api/repos/${id}/validate`, { config }),
  plan: (id: number, config: Config) => call<Plan>("POST", `/api/repos/${id}/plan`, { config }),
  apply: (id: number, config: Config, commit: boolean) =>
    call<{ written: string[]; commit: string | null }>("POST", `/api/repos/${id}/apply`, {
      config,
      commit,
    }),
  testGate: (id: number, config: Config) =>
    call<GateRun>("POST", `/api/repos/${id}/test-gate`, { config }),
  activity: (id: number) => call<Activity>("GET", `/api/repos/${id}/activity`),
  previewBranch: (branch: Config["branch"], type: TicketType, ticket_id: string, title: string) =>
    call<{ name: string; error: string | null }>("POST", "/api/preview/branch", {
      branch,
      type,
      ticket_id,
      title,
    }),
  browse: (path: string) =>
    call<DirListing>("GET", `/api/fs?path=${encodeURIComponent(path)}`),
};
