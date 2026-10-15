import { useState } from 'react';
import { QUICK_FILTERS, type HostCount, type QuickFilter } from '../logic/filters';
import { addSaved, cleanName, loadSaved, removeSaved, renameSaved, storeSaved, type SavedFilter } from '../logic/savedFilters';
import { useDispatch, useStore } from '../store';
import { backToLive } from '../viewing';
import { SessionsList, usePreviousSessions } from './SessionsList';

const HOST_COLORS = ['var(--blue)', 'var(--purple)', 'var(--green)', 'var(--orange)', 'var(--red)', 'var(--faint)'];

interface Props {
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

let nextId = 0;
const newId = () => `${Date.now().toString(36)}-${(nextId++).toString(36)}`;

function SavedFilters({ preset }: { preset: string }) {
  const { ui } = useStore();
  const dispatch = useDispatch();
  const [list, setList] = useState<SavedFilter[]>(() => loadSaved(storage(), preset));
  const [naming, setNaming] = useState<{ id: string | null; name: string } | null>(null);

  const save = (next: SavedFilter[]) => {
    setList(next);
    if (!storeSaved(storage(), preset, next)) dispatch({ type: 'toast', text: 'The browser did not keep the saved filters' });
  };
  const finish = () => {
    if (!naming) return;
    const name = cleanName(naming.name);
    if (name) save(naming.id === null ? addSaved(list, name, ui.search, newId()) : renameSaved(list, naming.id, name));
    setNaming(null);
  };
  const search = ui.search.trim();

  return (
    <>
      <div className="side-h">Saved filters</div>
      {list.length === 0 && !naming && <div className="side-i muted">None yet</div>}
      {list.map((f) =>
        naming?.id === f.id ? (
          <NameInput key={f.id} value={naming.name} onChange={(name) => setNaming({ id: f.id, name })} onDone={finish} onCancel={() => setNaming(null)} />
        ) : (
          <div key={f.id} className={`side-i saved${search === f.search ? ' active' : ''}`}>
            <button type="button" className="h linkish" title={f.search} onClick={() => dispatch({ type: 'ui', patch: { search: f.search } })}>
              {f.name}
            </button>
            <span className="acts">
              <button type="button" className="mini" onClick={() => setNaming({ id: f.id, name: f.name })} aria-label={`Rename ${f.name}`}>
                Rename
              </button>
              <button type="button" className="mini" onClick={() => save(removeSaved(list, f.id))} aria-label={`Delete ${f.name}`}>
                Delete
              </button>
            </span>
          </div>
        ),
      )}
      {naming?.id === null ? (
        <NameInput value={naming.name} onChange={(name) => setNaming({ id: null, name })} onDone={finish} onCancel={() => setNaming(null)} />
      ) : (
        <button
          type="button"
          className="side-i muted add"
          disabled={!search}
          title={search ? `Save "${search}"` : 'Type a search first'}
          onClick={() => setNaming({ id: null, name: '' })}
        >
          + Save current search
        </button>
      )}
    </>
  );
}

function NameInput({ value, onChange, onDone, onCancel }: { value: string; onChange: (v: string) => void; onDone: () => void; onCancel: () => void }) {
  return (
    <input
      className="textin side-in"
      autoFocus
      value={value}
      maxLength={60}
      placeholder="Name"
      aria-label="Filter name"
      onChange={(e) => onChange(e.target.value)}
      onBlur={onDone}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onDone();
        if (e.key === 'Escape') onCancel();
      }}
    />
  );
}

export function Sidebar({ counts, hosts }: Props) {
  const { ui, appState, view } = useStore();
  const dispatch = useDispatch();
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });
  const [open, setOpen] = useState(false);
  const previous = usePreviousSessions();

  const toggle = () => {
    if (!open) previous.reload();
    setOpen(!open);
  };

  return (
    <nav className="sidebar" aria-label="Filters">
      <div className="side-h">Session</div>
      <button type="button" className={`side-i${view ? '' : ' active'}`} title={appState?.session ?? ''} onClick={() => view && void backToLive(dispatch)}>
        <span className="dot" style={{ background: view ? 'var(--faint)' : 'var(--green)' }} />
        <span className="h">Current session</span>
      </button>
      <button type="button" className={`side-i${view ? ' active' : ''}`} aria-expanded={open} onClick={toggle}>
        <span className="caret">{open ? '▾' : '▸'}</span>
        <span className="h">Previous sessions</span>
        <span className="n">{previous.sessions?.length ?? ''}</span>
      </button>
      {open && <SessionsList sessions={previous.sessions} error={previous.error} />}

      <div className="side-h">Quick filters</div>
      {QUICK_FILTERS.map((q) => (
        <button
          key={q.id}
          type="button"
          className={`side-i${ui.quick === q.id ? ' active' : ''}`}
          onClick={() => patch({ quick: q.id })}
        >
          <span className="h">{q.label}</span>
          <span className={`n${q.id === 'errors' && counts.errors > 0 ? ' red' : ''}`}>{counts[q.id]}</span>
        </button>
      ))}

      <div className="side-h">Hosts</div>
      {hosts.length === 0 && <div className="side-i muted">No hosts yet</div>}
      {hosts.map((h, i) => (
        <button
          key={h.host}
          type="button"
          className={`side-i${ui.host === h.host ? ' active' : ''}`}
          title={h.host}
          onClick={() => patch({ host: ui.host === h.host ? null : h.host })}
        >
          <span className="dot" style={{ background: HOST_COLORS[i % HOST_COLORS.length] }} />
          <span className="h">{h.host}</span>
          <span className="n">{h.count}</span>
        </button>
      ))}

      {appState && <SavedFilters key={appState.preset} preset={appState.preset} />}
    </nav>
  );
}
