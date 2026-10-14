import { memo, useCallback, useMemo, useState } from 'react';
import { isError, isSlow } from '../logic/filters';
import { formatDuration, formatSize, formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import type { FlowSummary } from '../types';
import { VirtualList } from './VirtualList';

export const TRAFFIC_ROW_HEIGHT = 28;

interface RowProps {
  flow: FlowSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}

const FlowRow = memo(function FlowRow({ flow, selected, onSelect }: RowProps) {
  const sc = statusClass(flow.status);
  const err = isError(flow);
  return (
    <div
      className={`frow${selected ? ' sel' : ''}${err ? ' err' : ''}`}
      style={{ height: TRAFFIC_ROW_HEIGHT }}
      role="option"
      aria-selected={selected}
      onClick={() => onSelect(flow.id)}
    >
      <span className="c-time">{formatTime(flow.ts)}</span>
      <span className={`m ${methodClass(flow.method)}`}>{methodLabel(flow.method)}</span>
      <span>
        {flow.status !== null ? (
          <span className={`st ${sc}`}>{flow.status}</span>
        ) : flow.error !== null ? (
          <span className="st s5" title={flow.error}>
            ERR
          </span>
        ) : (
          <span className="st s3">…</span>
        )}
      </span>
      <span className="c-path" title={flow.host + flow.path}>
        {flow.path}
      </span>
      <span className="c-num">{formatDuration(flow.duration_ms)}</span>
      <span className="c-num">{formatSize(flow.size)}</span>
      <span className="c-badges">
        {flow.mock && <span className="tag mock">Mock</span>}
        {flow.fault && (
          <span className="tag fault" title={flow.fault}>
            Fault
          </span>
        )}
        {isSlow(flow) && <span className="tag slow">Slow</span>}
      </span>
    </div>
  );
});

interface Props {
  flows: FlowSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Changes when something outside the list selects a flow, so the row is scrolled into view. */
  revealKey: unknown;
  paused: boolean;
}

export function TrafficList({ flows, selectedId, onSelect, revealKey, paused }: Props) {
  const [follow, setFollow] = useState(true);
  const selectedIndex = useMemo(
    () => (selectedId === null ? -1 : flows.findIndex((f) => f.id === selectedId)),
    [flows, selectedId],
  );

  const step = useCallback(
    (delta: number) => {
      if (flows.length === 0) return;
      const from = selectedIndex < 0 ? (delta > 0 ? -1 : flows.length) : selectedIndex;
      const next = Math.min(flows.length - 1, Math.max(0, from + delta));
      onSelect((flows[next] as FlowSummary).id);
    },
    [flows, selectedIndex, onSelect],
  );

  return (
    <div className="flows-wrap">
      <div className="fhead">
        <span>Time</span>
        <span>Method</span>
        <span>Status</span>
        <span>Path</span>
        <span className="c-num">Duration</span>
        <span className="c-num">Size</span>
        <span />
      </div>
      <div className="flows-body">
        {flows.length === 0 && <div className="empty">No requests to show.</div>}
        <VirtualList
          label="Requests"
          count={flows.length}
          rowHeight={TRAFFIC_ROW_HEIGHT}
          follow={follow && !paused}
          onFollowChange={setFollow}
          revealIndex={selectedIndex}
          revealKey={revealKey}
          onStep={step}
          renderRow={(i) => {
            const f = flows[i] as FlowSummary;
            return <FlowRow key={f.id} flow={f} selected={f.id === selectedId} onSelect={onSelect} />;
          }}
        />
      </div>
    </div>
  );
}
