import { useCallback, useMemo, useState } from 'react';
import { LEVELS, LEVEL_NAMES, matchesLogText, matchesMinLevel, matchesRequest, logKey, type Level } from '../logic/logs';
import { loadStripHidden, storeStripHidden } from '../logic/paneWidth';
import { browserStorage } from '../storage';
import { useData, useDispatch, useStore } from '../store';
import type { LogLine, LogSource } from '../types';
import { LogRow, LOG_ROW_HEIGHT } from './LogRow';
import { VirtualList } from './VirtualList';

export function LogStrip({ requestId }: { requestId: string | null }) {
  const { ui } = useStore();
  const { logs, viewing } = useData();
  const dispatch = useDispatch();
  const patch = useCallback((p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p }), [dispatch]);
  const [hidden, setHidden] = useState(() => loadStripHidden(browserStorage()));
  const hide = (h: boolean) => {
    setHidden(h);
    storeStripHidden(browserStorage(), h);
  };

  const source = ui.stripSource;
  const visible = useMemo(() => {
    const cleared = viewing ? -Infinity : ui.clearedSeq[source];
    return logs[source].filter(
      (l) => l.seq > cleared && matchesMinLevel(l, ui.stripMinLevel) && matchesLogText(l, ui.stripText),
    );
  }, [logs, source, viewing, ui.clearedSeq, ui.stripMinLevel, ui.stripText]);

  const tabs: { id: LogSource; label: string }[] = [
    { id: 'device', label: 'Device logs' },
    { id: 'app', label: 'App logs' },
  ];

  return (
    <div className={`logs${hidden ? ' collapsed' : ''}`}>
      <div className="logs-bar">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab${source === t.id ? ' on' : ''}`}
            onClick={() => {
              patch({ stripSource: t.id });
              if (hidden) hide(false);
            }}
          >
            {t.label}
          </button>
        ))}
        <span className="spacer" />
        {!hidden && (
          <>
            <label className="select-wrap">
              <span className="sr">Level</span>
              <select
                value={ui.stripMinLevel}
                onChange={(e) => patch({ stripMinLevel: e.target.value as Level })}
                aria-label="Minimum level"
              >
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l === 'V' ? 'All levels' : `${LEVEL_NAMES[l]} and above`}
                  </option>
                ))}
              </select>
            </label>
            <input
              className="textin"
              type="search"
              placeholder="Filter logs…"
              value={ui.stripText}
              onChange={(e) => patch({ stripText: e.target.value })}
              aria-label="Filter logs"
            />
            <button
              type="button"
              className={`btn small${ui.stripAutoscroll ? ' toggled' : ''}`}
              aria-pressed={ui.stripAutoscroll}
              onClick={() => patch({ stripAutoscroll: !ui.stripAutoscroll })}
            >
              Auto-scroll
            </button>
          </>
        )}
        <button
          type="button"
          className="btn small"
          aria-expanded={!hidden}
          aria-controls={hidden ? undefined : 'log-strip-lines'}
          title={hidden ? 'Show the log strip' : "Hide the log strip; the Logs view and the detail panel's Logs tab still show the lines"}
          onClick={() => hide(!hidden)}
        >
          <svg width="10" height="10" viewBox="0 0 16 16" aria-hidden="true">
            <path d={hidden ? 'M3 10l5-5 5 5' : 'M3 6l5 5 5-5'} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {hidden ? 'Show logs' : 'Hide logs'}
        </button>
      </div>
      {!hidden && (
        <div className="loglist" id="log-strip-lines">
          {visible.length === 0 && <div className="empty">No log lines.</div>}
          <VirtualList
            label="Log lines"
            count={visible.length}
            rowHeight={LOG_ROW_HEIGHT}
            follow={ui.stripAutoscroll}
            onFollowChange={(f) => patch({ stripAutoscroll: f })}
            renderRow={(i) => {
              const line = visible[i] as LogLine;
              return (
                <LogRow
                  key={logKey(line)}
                  line={line}
                  linked={matchesRequest(line, requestId)}
                  selected={ui.selectedLog === logKey(line)}
                  onSelect={(l) => patch({ selectedLog: logKey(l) })}
                  onOpen={(l) => patch({ selectedLog: logKey(l), logsSource: l.source, view: 'logs' })}
                />
              );
            }}
          />
        </div>
      )}
    </div>
  );
}
