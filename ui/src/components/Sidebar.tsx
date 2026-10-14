import { QUICK_FILTERS, type HostCount, type QuickFilter } from '../logic/filters';
import { useDispatch, useStore } from '../store';

const HOST_COLORS = ['var(--blue)', 'var(--purple)', 'var(--green)', 'var(--orange)', 'var(--red)', 'var(--faint)'];

interface Props {
  counts: Record<QuickFilter, number>;
  hosts: HostCount[];
}

export function Sidebar({ counts, hosts }: Props) {
  const { ui, appState } = useStore();
  const dispatch = useDispatch();
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });

  return (
    <nav className="sidebar" aria-label="Filters">
      <div className="side-h">Session</div>
      <div className="side-i active" title={appState?.session ?? ''}>
        <span className="dot" style={{ background: 'var(--text)' }} />
        <span className="h">Current session</span>
      </div>

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
    </nav>
  );
}
