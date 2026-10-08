import { useEffect, useState } from "react";
import { api, type Config, type JiraCreds, type JiraTest, type TicketType } from "../api";
import { Badge, Field, Row, Section, Select, TextInput, Toggle } from "./ui";

const TYPES: TicketType[] = ["feature", "bug", "task"];
const EVENTS = [
  ["start", "When work starts"],
  ["mr_opened", "When the MR is opened"],
  ["abandoned", "When abandoned"],
] as const;

export function JiraSection(props: {
  repoId: number;
  config: Config;
  update: (fn: (c: Config) => void) => void;
}) {
  const j = props.config.jira;
  const { update } = props;
  const [creds, setCreds] = useState<JiraCreds | null>(null);
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [test, setTest] = useState<JiraTest | null>(null);
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    if (!j.url.trim()) return setCreds(null);
    const t = setTimeout(() => {
      api
        .jiraCreds(j.url)
        .then((c) => {
          setCreds(c);
          setEmail(c.email);
        })
        .catch(() => setCreds(null));
    }, 300);
    return () => clearTimeout(t);
  }, [j.url]);

  const saveLogin = () =>
    api
      .saveJiraCreds(j.url, email, token)
      .then((c) => {
        setCreds(c);
        setToken("");
        setMsg({ text: "Login saved on this computer.", error: false });
      })
      .catch((e: Error) => setMsg({ text: e.message, error: true }));

  const runTest = () =>
    api
      .jiraTest(props.repoId, props.config)
      .then((r) => {
        setTest(r);
        setMsg(
          r.ok
            ? { text: `Connected as ${r.user} - project ${r.project_name}`, error: false }
            : { text: "Not connected", error: true },
        );
      })
      .catch((e: Error) => setMsg({ text: e.message, error: true }));

  return (
    <Section
      title="Jira"
      hint="Read tickets from Jira and move them across the board automatically. Your login is stored on this computer only, never in the repo."
    >
      <Toggle label="Use Jira" checked={j.enabled} onChange={(v) => update((x) => void (x.jira.enabled = v))} />
      {j.enabled && (
        <>
          <Row>
            <Field label="Jira URL" hint="e.g. https://yourcompany.atlassian.net (no trailing slash)">
              <TextInput mono value={j.url} onChange={(v) => update((x) => void (x.jira.url = v))} />
            </Field>
            <Field label="Kind">
              <Select
                value={j.deployment}
                options={["cloud", "server"]}
                onChange={(v) => update((x) => void (x.jira.deployment = v as "cloud" | "server"))}
              />
            </Field>
            <Field label="Project key" hint="The letters before the number, e.g. PROJ in PROJ-123.">
              <TextInput mono value={j.project_key} onChange={(v) => update((x) => void (x.jira.project_key = v))} />
            </Field>
          </Row>
          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle
              label="Create issues from the Inbox"
              hint="Adds an “Also create in Jira” option when saving tickets from a transcript."
              checked={j.create_issues}
              onChange={(v) => update((x) => void (x.jira.create_issues = v))}
            />
            <Toggle
              label="Comment the MR link on the issue"
              checked={j.comment_mr_link}
              onChange={(v) => update((x) => void (x.jira.comment_mr_link = v))}
            />
          </div>
          <div>
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Issue type per ticket type</span>
            <div className="mt-1 grid gap-2 sm:grid-cols-3">
              {TYPES.map((t) => (
                <div key={t} className="flex items-center gap-2">
                  <span className="w-16 text-xs text-zinc-500">{t}</span>
                  <TextInput value={j.issue_types[t]} onChange={(v) => update((x) => void (x.jira.issue_types[t] = v))} />
                </div>
              ))}
            </div>
          </div>
          <div>
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Move to column</span>
            <p className="text-xs text-zinc-500">
              A board column shows one or more statuses - enter the status the ticket should get.
              Empty = don&apos;t move.
            </p>
            <datalist id="jira-statuses">
              {(test?.statuses ?? []).map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <div className="mt-1 grid gap-2 sm:grid-cols-3">
              {EVENTS.map(([k, label]) => (
                <label key={k} className="grid gap-1">
                  <span className="text-xs text-zinc-500">{label}</span>
                  <input
                    className="input"
                    list="jira-statuses"
                    value={j.move_to[k]}
                    onChange={(e) => update((x) => void (x.jira.move_to[k] = e.target.value))}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-3 rounded-md border border-dashed border-zinc-300 p-3 dark:border-zinc-700">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-semibold">Your Jira login</h3>
              {creds?.has_token && <Badge tone="green">{creds.from_env ? "from environment" : "saved"}</Badge>}
            </div>
            <Row>
              {j.deployment === "cloud" && (
                <Field label="Atlassian account email">
                  <TextInput value={email} onChange={setEmail} />
                </Field>
              )}
              <Field
                label={j.deployment === "cloud" ? "API token" : "Personal access token"}
                hint={
                  j.deployment === "cloud" ? (
                    <a
                      className="text-indigo-600 hover:underline"
                      href="https://id.atlassian.com/manage-profile/security/api-tokens"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Create an API token ↗
                    </a>
                  ) : (
                    "Create one under your Jira profile > Personal Access Tokens."
                  )
                }
              >
                <input
                  type="password"
                  autoComplete="off"
                  className="input"
                  placeholder={creds?.has_token ? "(saved - leave empty to keep)" : ""}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </Field>
            </Row>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className="btn" disabled={!j.url.trim()} onClick={saveLogin}>
                Save login
              </button>
              <button type="button" className="btn" onClick={runTest}>
                Test connection
              </button>
              {msg && <span className={`text-sm ${msg.error ? "text-red-600" : "text-emerald-600"}`}>{msg.text}</span>}
            </div>
            {test && test.problems.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-amber-700 dark:text-amber-300">
                {test.problems.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
            <p className="text-xs text-zinc-500">
              Test connection uses the settings above, saved or not. Your login is saved separately
              from the rest of the settings.
            </p>
          </div>
        </>
      )}
    </Section>
  );
}
