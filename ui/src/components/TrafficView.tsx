import { useCallback, useRef, useState, type CSSProperties } from 'react';
import { activeChips, type ChipKind, type HostCount, type QuickFilter } from '../logic/filters';
import { storeShowEncrypted } from '../logic/hosts';
import { LIST_MIN, LIST_MIN_DEFAULT, TRAFFIC_DETAIL, TRAFFIC_SIDEBAR, useBoxWidth, usePaneWidth } from '../logic/paneWidth';
import { loadLayout, loadSidebarHidden, storeLayout, storeSidebarHidden, type TrafficLayout } from '../logic/viewPrefs';
import { browserStorage } from '../storage';
import { useDispatch, useStore } from '../store';
import type { FlowSummary, TrafficRow, TunnelRow } from '../types';
import { DecryptHostDialog } from './DecryptHostDialog';
import { DetailPanel, TunnelDetail } from './DetailPanel';
import { LogStrip } from './LogStrip';
import { MapLocalDialog } from './MapLocalDialog';
import { Toggle } from './RuleEditor';
import { Sidebar } from './Sidebar';
import { Splitter } from './Splitter';
import { TrafficList } from './TrafficList';
import { TrafficTree } from './TrafficTree';

const LAYOUTS: { id: TrafficLayout; label: string }[] = [
  { id: 'list', label: 'List' },
  { id: 'tree', label: 'Tree' },
];

interface Props {
  rows: TrafficRow[];
  selected: FlowSummary | null;
  selectedTunnel: TunnelRow | null;
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
  encryptedHosts: HostCount[];
  clients: ReadonlyMap<string, number>;
  filterError: string | null;
}

export function TrafficView({ rows, selected, selectedTunnel, counts, hosts, encryptedHosts, clients, filterError }: Props) {
  const { ui, appState, view } = useStore();
  const dispatch = useDispatch();
  const [decrypting, setDecrypting] = useState<{ host: string; choice: string } | null>(null);
  const [mapping, setMapping] = useState<FlowSummary | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const size = useBoxWidth(bodyRef);
  // The detail panel gives way before the sidebar when the window is too narrow for both. Only a
  // detail width the tester chose may take the list below its default minimum.
  const sidebar = usePaneWidth(TRAFFIC_SIDEBAR, size.box - LIST_MIN_DEFAULT, size.window);
  const [sidebarHidden, setSidebarHidden] = useState(() => loadSidebarHidden(browserStorage()));
  const hideSidebar = (hidden: boolean) => {
    setSidebarHidden(hidden);
    storeSidebarHidden(browserStorage(), hidden);
  };
  const sidebarWidth = sidebarHidden ? 0 : sidebar.width;
  const detail = usePaneWidth(TRAFFIC_DETAIL, size.box - LIST_MIN - sidebarWidth, size.window, size.box - LIST_MIN_DEFAULT - sidebarWidth);
  const widths = { '--sidebar-w': `${sidebarWidth}px`, '--detail-w': `${detail.width}px` } as CSSProperties;
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
  const [layout, setLayout] = useState(() => loadLayout(browserStorage()));
  const chooseLayout = (next: TrafficLayout) => {
    setLayout(next);
    storeLayout(browserStorage(), next);
  };
  const [follow, setFollow] = useState(true);
  const select = useCallback((id: string) => dispatch({ type: 'ui', patch: { selectedFlowId: id } }), [dispatch]);
  const menuActions = {
    onDecrypt: (host: string, choice: string) => setDecrypting({ host, choice }),
    onHideEncrypted: () => showEncrypted(false),
    onMapLocal: setMapping,
  };

  return (
    <>
      <div className={`main-body${sidebarHidden ? ' no-sidebar' : ''}`} ref={bodyRef} style={widths}>
        {!sidebarHidden && (
          <div className="side-wrap" id="traffic-sidebar">
            <Sidebar
              counts={counts}
              hosts={hosts}
              encryptedHosts={encryptedHosts}
              clients={clients}
              onDecrypt={(host, choice) => setDecrypting({ host, choice })}
            />
          </div>
        )}
        <div className="traffic">
          <div className="filterbar">
            <button
              type="button"
              className="btn side-toggle"
              aria-expanded={!sidebarHidden}
              aria-controls={sidebarHidden ? undefined : 'traffic-sidebar'}
              aria-label={sidebarHidden ? 'Show the sidebar' : 'Hide the sidebar'}
              title={sidebarHidden ? 'Show the sidebar' : 'Hide the sidebar'}
              onClick={() => hideSidebar(!sidebarHidden)}
            >
              {sidebarHidden ? '»' : '«'}
            </button>
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
            <div className="seg layout-seg" role="group" aria-label="Traffic layout">
              {LAYOUTS.map((l) => (
                <button key={l.id} type="button" className={layout === l.id ? 'on' : ''} aria-pressed={layout === l.id} onClick={() => chooseLayout(l.id)}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          {filterError && (
            <div className="search-error" role="alert">
              {filterError}
            </div>
          )}
          {layout === 'tree' ? (
            <TrafficTree rows={rows} selectedId={ui.selectedFlowId} onSelect={select} {...menuActions} />
          ) : (
            <TrafficList
              rows={rows}
              selectedId={ui.selectedFlowId}
              onSelect={select}
              revealKey={ui.selectedFlowId}
              paused={ui.frozen !== null && !view}
              follow={follow}
              onFollowChange={setFollow}
              showDevice={appState?.mode === 'proxy' || appState?.mode === 'both'}
              {...menuActions}
            />
          )}
        </div>
        {selectedTunnel ? (
          <TunnelDetail tunnel={selectedTunnel} onDecrypt={(host) => setDecrypting({ host, choice: host })} />
        ) : (
          <DetailPanel flow={selected} onMapLocal={setMapping} />
        )}
        {!sidebarHidden && <Splitter label="Resize the sidebar" edge="start" pane={sidebar} />}
        <Splitter label="Resize the request details" edge="end" pane={detail} />
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
