import { useState } from 'react';
import { copyText } from '../clipboard';
import { QUICK_FILTERS, type HostCount, type QuickFilter } from '../logic/filters';
import { acceptedDevices, TLS_FAILING_TITLE } from '../logic/proxyDevices';
import { addSaved, cleanName, loadSaved, removeSaved, renameSaved, storeSaved, type SavedFilter } from '../logic/savedFilters';
import { useDispatch, useStore } from '../store';
import { backToLive } from '../viewing';
import { ChangePortDialog } from './ChangePortDialog';
import { ContextMenu, type MenuAt } from './ContextMenu';
import { RemoveDeviceDialog } from './RemoveDeviceDialog';
import { SessionsList, usePreviousSessions } from './SessionsList';

const HOST_COLORS = ['var(--blue)', 'var(--purple)', 'var(--green)', 'var(--orange)', 'var(--red)', 'var(--faint)'];

interface Props {
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
  /** Listed requests per device, by the summary's `client`. */
  clients: ReadonlyMap<string, number>;
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

/** The address phones set as their Wi-Fi proxy, and the devices it accepts in this session (spec 022). */
function ProxyDevices({ total, clients }: { total: number; clients: ReadonlyMap<string, number> }) {
  const { ui, appState, view } = useStore();
  const dispatch = useDispatch();
  const [menu, setMenu] = useState<{ address: string; at: MenuAt } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  if (!appState || (appState.mode !== 'proxy' && appState.mode !== 'both')) return null;

  const accepted = acceptedDevices(appState);
  const removable = appState.proxy_pin && !view;
  const pick = (client: string | null) => dispatch({ type: 'ui', patch: { client } });
  const copy = async () => {
    const ok = appState.proxy_address ? await copyText(appState.proxy_address) : false;
    dispatch({ type: 'toast', text: ok ? 'Copied the proxy address' : 'Could not copy' });
  };

  return (
    <>
      <div className="side-h">Wi-Fi proxy</div>
      <div className="proxyaddr">
        <span className="a">{appState.proxy_address ?? 'No Wi-Fi address'}</span>
        <button type="button" className="mini" disabled={!appState.proxy_address} onClick={() => void copy()}>
          Copy
        </button>
        <button
          type="button"
          className="mini"
          disabled={view !== null}
          title={view ? 'Changing the port is off while a previous session is open' : 'Restart on another port'}
          onClick={() => setChanging(true)}
        >
          Change…
        </button>
      </div>
      {appState.proxy_clients.length > 0 && (
        <>
          <div className="side-h sub">Devices</div>
          <button type="button" className={`side-i${ui.client === null ? ' active' : ''}`} onClick={() => pick(null)}>
            <span className="h">All devices</span>
            <span className="n">{total}</span>
          </button>
          {appState.proxy_clients.map((c) => (
            <div
              key={c.address}
              className={`side-i dev${ui.client === c.address ? ' active' : ''}`}
              onContextMenu={(e) => {
                if (!removable) return;
                e.preventDefault();
                setMenu({ address: c.address, at: { x: e.clientX, y: e.clientY } });
              }}
            >
              <button type="button" className="h ip linkish" onClick={() => pick(ui.client === c.address ? null : c.address)}>
                {c.address}
              </button>
              <span className="cnt">
                {c.tls_failures > 0 && (
                  <span className="n warn" title={TLS_FAILING_TITLE}>
                    ⚠ {c.tls_failures}
                  </span>
                )}
                <span className="n">{clients.get(c.address) ?? 0}</span>
              </span>
              {removable && (
                <button
                  type="button"
                  className="rm"
                  title="Remove from this session…"
                  aria-label={`Remove ${c.address} from this session`}
                  onClick={() => setRemoving(c.address)}
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </>
      )}
      {menu && (
        <ContextMenu
          at={menu.at}
          label="Device"
          items={[{ label: 'Remove from this session…', onSelect: () => setRemoving(menu.address) }]}
          onClose={() => setMenu(null)}
        />
      )}
      {removing && <RemoveDeviceDialog address={removing} accepted={accepted} onClose={() => setRemoving(null)} />}
      {changing && <ChangePortDialog current={appState.proxy_port} macIp={appState.mac_ip} onClose={() => setChanging(false)} />}
    </>
  );
}

export function Sidebar({ counts, hosts, clients }: Props) {
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
      <ProxyDevices total={counts.all} clients={clients} />
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
      {QUICK_FILTERS.filter((q) => q.id !== 'encrypted' || !view).map((q) => (
        <button
          key={q.id}
          type="button"
          className={`side-i${ui.quick === q.id ? ' active' : ''}`}
          onClick={() => patch({ quick: q.id })}
        >
          {q.id === 'encrypted' && (
            <span className="lock" aria-hidden="true">
              🔒
            </span>
          )}
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
