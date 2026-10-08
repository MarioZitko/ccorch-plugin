import { useEffect, useState } from "react";
import { api, type DirListing, type Marketplace } from "../api";
import { Field, Modal, TextInput } from "./ui";

export function AddRepoModal(props: { onClose: () => void; onAdded: (id: number) => void }) {
  const [path, setPath] = useState("");
  const [listing, setListing] = useState<DirListing | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = (p: string) =>
    api
      .browse(p)
      .then((l) => {
        setListing(l);
        setPath(l.path);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    void open("");
  }, []);

  const add = async (p: string) => {
    try {
      const repo = await api.addRepo(p);
      props.onAdded(repo.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Modal title="Add repository" onClose={props.onClose}>
      <div className="grid gap-3">
        <div className="flex gap-2">
          <TextInput value={path} onChange={setPath} mono placeholder="/path/to/repo" />
          <button type="button" className="btn" onClick={() => open(path)}>
            Go
          </button>
          <button type="button" className="btn btn-primary" onClick={() => add(path)}>
            Add
          </button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {listing && (
          <div className="max-h-80 overflow-auto rounded-md border border-zinc-200 dark:border-zinc-800">
            {listing.parent && (
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                onClick={() => open(listing.parent!)}
              >
                ↰ ..
              </button>
            )}
            {listing.entries.map((e) => (
              <div
                key={e.path}
                className="flex items-center justify-between px-3 py-1.5 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <button type="button" className="flex-1 text-left" onClick={() => open(e.path)}>
                  📁 {e.name}
                </button>
                {e.is_git && (
                  <button type="button" className="btn py-0.5 text-xs" onClick={() => add(e.path)}>
                    Add git repo
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

export function MarketplaceModal(props: {
  value: Marketplace;
  onClose: () => void;
  onSaved: (m: Marketplace) => void;
}) {
  const [m, setM] = useState(props.value);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title="Plugin marketplace" onClose={props.onClose}>
      <div className="grid gap-4">
        <p className="text-sm text-zinc-500">
          The git repository that hosts this plugin (the ccorch-plugin repo). It is written into
          each repo's <code>.claude/settings.json</code>, so teammates who open the repo in Claude
          Code are asked to install ccorch.
        </p>
        <Field label="Git URL">
          <TextInput
            mono
            value={m.url}
            placeholder="https://gitlab.company.com/tools/ccorch-plugin.git"
            onChange={(url) => setM({ ...m, url })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Marketplace name">
            <TextInput mono value={m.name} onChange={(name) => setM({ ...m, name })} />
          </Field>
          <Field label="Branch / tag">
            <TextInput mono value={m.ref} onChange={(ref) => setM({ ...m, ref })} />
          </Field>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={props.onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() =>
              api
                .setMarketplace(m)
                .then(props.onSaved)
                .catch((e: Error) => setError(e.message))
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
