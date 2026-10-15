import { activeChips, type ChipKind, type HostCount, type QuickFilter } from '../logic/filters';
import { useDispatch, useStore } from '../store';
import type { FlowSummary } from '../types';
import { DetailPanel } from './DetailPanel';
import { LogStrip } from './LogStrip';
import { Sidebar } from './Sidebar';
import { TrafficList } from './TrafficList';

interface Props {
  flows: FlowSummary[];
  selected: FlowSummary | null;
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
  filterError: string | null;
}

export function TrafficView({ flows, selected, counts, hosts, filterError }: Props) {
  const { ui, appState, view } = useStore();
  const dispatch = useDispatch();
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });
  const chips = activeChips({ quick: ui.quick, host: ui.host, text: ui.search }, appState?.default_filter ?? '');
  const remove = (kind: ChipKind) => {
    if (kind === 'host') patch({ host: null });
    else if (kind === 'quick') patch({ quick: 'all' });
    else patch({ search: '' });
  };

  return (
    <>
      <div className="main-body">
        <Sidebar counts={counts} hosts={hosts} />
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
          </div>
          {filterError && (
            <div className="search-error" role="alert">
              {filterError}
            </div>
          )}
          <TrafficList
            flows={flows}
            selectedId={ui.selectedFlowId}
            onSelect={(id) => patch({ selectedFlowId: id })}
            revealKey={ui.selectedFlowId}
            paused={ui.frozen !== null && !view}
          />
        </div>
        <DetailPanel flow={selected} />
      </div>
      <LogStrip requestId={selected?.request_id ?? null} />
    </>
  );
}
