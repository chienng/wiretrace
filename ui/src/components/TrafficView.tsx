import { useState } from 'react';
import { activeChips, type ChipKind, type HostCount, type QuickFilter } from '../logic/filters';
import { storeShowEncrypted } from '../logic/hosts';
import { browserStorage } from '../storage';
import { useDispatch, useStore } from '../store';
import type { FlowSummary, TrafficRow, TunnelRow } from '../types';
import { DecryptHostDialog } from './DecryptHostDialog';
import { DetailPanel, TunnelDetail } from './DetailPanel';
import { LogStrip } from './LogStrip';
import { MapLocalDialog } from './MapLocalDialog';
import { Toggle } from './RuleEditor';
import { Sidebar } from './Sidebar';
import { TrafficList } from './TrafficList';

interface Props {
  rows: TrafficRow[];
  selected: FlowSummary | null;
  selectedTunnel: TunnelRow | null;
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
  clients: ReadonlyMap<string, number>;
  filterError: string | null;
}

export function TrafficView({ rows, selected, selectedTunnel, counts, hosts, clients, filterError }: Props) {
  const { ui, appState, view } = useStore();
  const dispatch = useDispatch();
  const [decrypting, setDecrypting] = useState<{ host: string; choice: string } | null>(null);
  const [mapping, setMapping] = useState<FlowSummary | null>(null);
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });
  const chips = activeChips({ quick: ui.quick, host: ui.host, client: ui.client, text: ui.search }, appState?.default_filter ?? '');
  const remove = (kind: ChipKind) => {
    if (kind === 'host') patch({ host: null });
    else if (kind === 'client') patch({ client: null });
    else if (kind === 'quick') patch({ quick: 'all' });
    else patch({ search: '' });
  };
  const showEncrypted = (show: boolean) => {
    storeShowEncrypted(browserStorage(), show);
    patch(show || ui.quick !== 'encrypted' ? { showEncrypted: show } : { showEncrypted: show, quick: 'all' });
  };

  return (
    <>
      <div className="main-body">
        <Sidebar counts={counts} hosts={hosts} clients={clients} />
        <div className="traffic">
          <div className="filterbar">
            <div className="search">
              <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
                <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
              <input
                type="text"
                value={ui.search}
                onChange={(e) => patch({ search: e.target.value })}
                placeholder="Search URL, headers, bodies…  or filter: ~m POST & ~c 500"
                aria-label="Search requests"
                aria-invalid={filterError !== null}
                spellCheck={false}
              />
            </div>
            {chips.map((c) => (
              <button key={c.kind} type="button" className={`chip ${c.kind}`} onClick={() => remove(c.kind)} title="Remove this filter">
                {c.label}
              </button>
            ))}
            {!view && (
              <label className="toggle-label">
                <Toggle on={ui.showEncrypted} label="Show encrypted" onChange={showEncrypted} />
                Show encrypted
              </label>
            )}
          </div>
          {filterError && (
            <div className="search-error" role="alert">
              {filterError}
            </div>
          )}
          <TrafficList
            rows={rows}
            selectedId={ui.selectedFlowId}
            onSelect={(id) => patch({ selectedFlowId: id })}
            revealKey={ui.selectedFlowId}
            paused={ui.frozen !== null && !view}
            showDevice={appState?.mode === 'proxy' || appState?.mode === 'both'}
            onDecrypt={(host, choice) => setDecrypting({ host, choice })}
            onHideEncrypted={() => showEncrypted(false)}
            onMapLocal={setMapping}
          />
        </div>
        {selectedTunnel ? (
          <TunnelDetail tunnel={selectedTunnel} onDecrypt={(host) => setDecrypting({ host, choice: host })} />
        ) : (
          <DetailPanel flow={selected} onMapLocal={setMapping} />
        )}
      </div>
      <LogStrip requestId={selected?.request_id ?? null} />
      {decrypting && appState && (
        <DecryptHostDialog
          host={decrypting.host}
          initial={decrypting.choice}
          preset={appState.preset}
          apiHosts={appState.api_hosts.length}
          onClose={() => setDecrypting(null)}
        />
      )}
      {mapping && !view && <MapLocalDialog key={mapping.id} flow={mapping} onClose={() => setMapping(null)} />}
    </>
  );
}
