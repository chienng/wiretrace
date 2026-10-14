import type { HostCount, QuickFilter } from '../logic/filters';
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
  const { ui } = useStore();
  const dispatch = useDispatch();
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });

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
                placeholder="Search URL, method, status…  or filter: ~m POST & ~c 500"
                aria-label="Search requests"
                aria-invalid={filterError !== null}
                spellCheck={false}
              />
            </div>
            {ui.host && (
              <button type="button" className="chip" onClick={() => patch({ host: null })} title="Remove host filter">
                host: {ui.host}
              </button>
            )}
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
            paused={ui.frozen !== null}
          />
        </div>
        <DetailPanel flow={selected} />
      </div>
      <LogStrip requestId={selected?.request_id ?? null} />
    </>
  );
}
