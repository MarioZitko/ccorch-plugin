import { useState, type ReactNode } from "react";

export function Section(props: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="text-sm font-semibold">{props.title}</h2>
      {props.hint && <p className="mt-0.5 text-xs text-zinc-500">{props.hint}</p>}
      <div className="mt-4 grid gap-4">{props.children}</div>
    </section>
  );
}

export function Field(props: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="grid content-start gap-1">
      <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{props.label}</span>
      {props.children}
      {props.hint && <span className="text-xs text-zinc-500">{props.hint}</span>}
    </label>
  );
}

export function Row(props: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{props.children}</div>;
}

export function Toggle(props: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={props.checked}
        onClick={() => props.onChange(!props.checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition ${
          props.checked ? "bg-indigo-600" : "bg-zinc-300 dark:bg-zinc-700"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${
            props.checked ? "left-4.5" : "left-0.5"
          }`}
        />
      </button>
      <span className="grid">
        <span className="text-sm">{props.label}</span>
        {props.hint && <span className="text-xs text-zinc-500">{props.hint}</span>}
      </span>
    </label>
  );
}

export function TextInput(props: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  disabled?: boolean;
}) {
  return (
    <input
      className={`input ${props.mono ? "font-mono" : ""}`}
      disabled={props.disabled}
      value={props.value}
      placeholder={props.placeholder}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
}

export function NumberInput(props: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <input
      type="number"
      className="input"
      value={props.value}
      min={props.min}
      max={props.max}
      onChange={(e) => props.onChange(Number(e.target.value))}
    />
  );
}

export function Select(props: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select className="input" value={props.value} onChange={(e) => props.onChange(e.target.value)}>
      {props.options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

/** Editable list of command strings (one per row). */
export function ListEditor(props: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
}) {
  const set = (i: number, v: string) => props.onChange(props.values.map((x, j) => (j === i ? v : x)));
  return (
    <div className="grid gap-2">
      {props.values.map((v, i) => (
        <div key={i} className="flex gap-2">
          <TextInput value={v} onChange={(x) => set(i, x)} mono placeholder={props.placeholder} />
          <button
            type="button"
            className="btn px-2"
            title="Remove"
            onClick={() => props.onChange(props.values.filter((_, j) => j !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn w-fit text-xs"
        onClick={() => props.onChange([...props.values, ""])}
      >
        + Add command
      </button>
    </div>
  );
}

/** Comma/enter separated tags. */
export function TagInput(props: { values: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const commit = () => {
    const t = draft.trim();
    if (t && !props.values.includes(t)) props.onChange([...props.values, t]);
    setDraft("");
  };
  return (
    <div className="input flex flex-wrap items-center gap-1.5">
      {props.values.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200"
        >
          {t}
          <button type="button" onClick={() => props.onChange(props.values.filter((x) => x !== t))}>
            ✕
          </button>
        </span>
      ))}
      <input
        className="min-w-24 flex-1 bg-transparent text-sm outline-none"
        value={draft}
        placeholder={props.values.length ? "" : "type and press Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          }
        }}
      />
    </div>
  );
}

export function Badge(props: { tone: "green" | "amber" | "zinc" | "indigo"; children: ReactNode }) {
  const tones = {
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    zinc: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${tones[props.tone]}`}>
      {props.children}
    </span>
  );
}

export function Modal(props: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}
    >
      <div className={`card flex max-h-[90vh] w-full flex-col shadow-xl ${props.wide ? "max-w-5xl" : "max-w-xl"}`}>
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
          <h3 className="text-sm font-semibold">{props.title}</h3>
          <button type="button" className="text-zinc-500 hover:text-zinc-900 dark:hover:text-white" onClick={props.onClose}>
            ✕
          </button>
        </div>
        <div className="overflow-auto p-5">{props.children}</div>
      </div>
    </div>
  );
}
