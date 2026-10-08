export type TicketType = "feature" | "bug" | "task";
/** "" = let the workflow decide (repo's planning setting + ticket size). */
export type StartMode = "" | "quick" | "plan";

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
    planning: "auto" | "always" | "never";
    plan_approval: boolean;
    review: boolean;
    review_quick: boolean;
    max_fix_iterations: number;
    small_inline: boolean;
    small_review_max_lines: number;
  };
  intake: { id_prefix: string };
  models: { intake: string; planner: string; implementer: string; reviewer: string; reviewer_small: string };
  jira: {
    enabled: boolean;
    url: string;
    deployment: "cloud" | "server";
    project_key: string;
    create_issues: boolean;
    comment_mr_link: boolean;
    issue_types: Record<TicketType, string>;
    move_to: { start: string; mr_opened: string; abandoned: string };
  };
}

export interface JiraCreds {
  has_token: boolean;
  email: string;
  from_env: boolean;
}

export interface JiraTest {
  ok: boolean;
  user: string;
  project_name: string;
  issue_types: string[];
  statuses: string[];
  problems: string[];
}

export interface JiraIssueInfo {
  key: string;
  status: string;
  url: string;
  targets: string[];
}

export interface TicketDraft {
  id: string;
  type: TicketType;
  title: string;
  description: string;
  acceptance_criteria: string[];
  size: "small" | "big";
}

export interface InboxTicket extends TicketDraft {
  status: "queued" | "started";
  created_at: string;
  branch?: string;
  jira_key?: string;
  jira_url?: string;
  jira_status?: string;
}

export interface IntakeResult {
  tickets: TicketDraft[];
  notes: string;
  cost_usd: number;
  duration_ms: number;
  model: string;
}

export interface PluginInfo {
  running_version: string;
  running_from: string;
  dev_checkout: boolean;
  installed: boolean;
  plugin_id: string | null;
  installed_version: string | null;
  marketplace: string | null;
  available_version: string | null;
  update_available: boolean;
  output?: string;
  relaunching?: boolean;
}

export interface ClaudeInfo {
  path: string | null;
  version: string | null;
  api_key_env: boolean;
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
  jira_key?: string | null;
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
  meta2: () => call<{ version: string }>("GET", "/api/meta"),
  pluginInfo: () => call<PluginInfo>("GET", "/api/plugin"),
  pluginCheck: () => call<PluginInfo>("POST", "/api/plugin/check"),
  pluginUpdate: () => call<PluginInfo>("POST", "/api/plugin/update"),
  claudeInfo: () => call<ClaudeInfo>("GET", "/api/claude"),
  claudeUpdate: () => call<{ output: string; version: string }>("POST", "/api/claude/update"),
  intake: (id: number, text: string) =>
    call<IntakeResult>("POST", `/api/repos/${id}/intake`, { text }),
  inbox: (id: number) => call<InboxTicket[]>("GET", `/api/repos/${id}/inbox`),
  saveInbox: (id: number, tickets: TicketDraft[], create_in_jira = false) =>
    call<{ saved: string[]; failed?: { draft: TicketDraft; error: string }[] }>(
      "POST",
      `/api/repos/${id}/inbox`,
      { tickets, create_in_jira },
    ),
  jiraCreds: (url: string) =>
    call<JiraCreds>("GET", `/api/jira/credentials?url=${encodeURIComponent(url)}`),
  saveJiraCreds: (url: string, email: string, token: string) =>
    call<JiraCreds>("PUT", "/api/jira/credentials", { url, email, token }),
  jiraTest: (id: number, config: Config) =>
    call<JiraTest>("POST", `/api/repos/${id}/jira/test`, { config }),
  jiraIssue: (id: number, key: string) =>
    call<JiraIssueInfo>("GET", `/api/repos/${id}/jira/issue/${encodeURIComponent(key)}`),
  jiraMove: (id: number, key: string, status: string) =>
    call<{ result: string }>("POST", `/api/repos/${id}/jira/issue/${encodeURIComponent(key)}/move`, {
      status,
    }),
  deleteInbox: (id: number, tid: string) =>
    call<{ deleted: boolean }>("DELETE", `/api/repos/${id}/inbox/${encodeURIComponent(tid)}`),
  inboxCommand: (id: number, tid: string, mode: StartMode) =>
    call<{ slash: string; shell: string }>(
      "GET",
      `/api/repos/${id}/inbox/${encodeURIComponent(tid)}/command?mode=${mode}`,
    ),
  launch: (id: number, tid: string, mode: StartMode) =>
    call<{ launched: boolean }>(
      "POST",
      `/api/repos/${id}/inbox/${encodeURIComponent(tid)}/launch?mode=${mode}`,
    ),
  browse: (path: string) =>
    call<DirListing>("GET", `/api/fs?path=${encodeURIComponent(path)}`),
};
