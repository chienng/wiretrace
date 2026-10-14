import { useCallback, useMemo } from 'react';
import { copyText } from '../clipboard';
import { formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import {
  findLinkedFlow,
  isCrash,
  levelCounts,
  LEVELS,
  LEVEL_NAMES,
  logKey,
  matchesLevels,
  matchesLogText,
  normalizeLevel,
  type Level,
} from '../logic/logs';
import { useDispatch, useStore } from '../store';
import type { LogLine } from '../types';
import { LogRow, LOG_ROW_HEIGHT } from './LogRow';
import { VirtualList } from './VirtualList';

function LogDetail({ line }: { line: LogLine | null }) {
  const { flows } = useStore();
  const dispatch = useDispatch();
  const linked = useMemo(() => (line ? findLinkedFlow(line, flows) : null), [line, flows]);
  if (!line) return <div className="lg-detail"><div className="empty">Select a log line to see its details.</div></div>;
  const level = normalizeLevel(line.level);
  const copy = async () => {
    const ok = await copyText(line.raw ?? line.message);
    dispatch({ type: 'toast', text: ok ? 'Line copied' : 'Copy failed' });
  };
  return (
    <div className="lg-detail">
      <div className="hd">
        {level && <span className={`lv ${level}`}>{level}</span>}
        <span className="tgname">{line.tag ?? '(no tag)'}</span>
        <span className="spacer" />
        <button type="button" className="btn small" onClick={copy}>
          Copy line
        </button>
      </div>
      <div className="kv2">
        <span>Time</span>
        <span>{line.ts ? formatTime(line.ts) : '—'}</span>
        <span>Source</span>
        <span>{line.source}</span>
        <span>Level</span>
        <span>{level ? LEVEL_NAMES[level] : '—'}</span>
        <span>Request ID</span>
        <span>{line.request_id ?? '—'}</span>
        <span>Sequence</span>
        <span>{line.seq}</span>
      </div>
      <div className="sec-h">Message</div>
      <div className={`fullmsg${isCrash(line) || level === 'E' ? '' : ' plain'}`}>{line.message}</div>
      <div className="sec-h">Linked request</div>
      {linked ? (
        <div className="card">
          <div className="l1">
            <span className={`m ${methodClass(linked.method)}`}>{methodLabel(linked.method)}</span>
            {linked.status !== null && <span className={`st ${statusClass(linked.status)}`}>{linked.status}</span>}
            <span className="path">{linked.path}</span>
            <span className="spacer" />
            <button type="button" className="btn small" onClick={() => dispatch({ type: 'openFlow', id: linked.id })}>
              Open in Traffic →
            </button>
          </div>
          <div className="l2">
            {linked.host} · {linked.request_id}
          </div>
        </div>
      ) : (
        <div className="note">No request is linked to this line.</div>
      )}
    </div>
  );
}

export function LogsView() {
  const { logs, ui } = useStore();
  const dispatch = useDispatch();
  const patch = useCallback((p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p }), [dispatch]);

  const device = useMemo(() => logs.device.filter((l) => l.seq > ui.clearedSeq.device), [logs.device, ui.clearedSeq.device]);
  const app = useMemo(() => logs.app.filter((l) => l.seq > ui.clearedSeq.app), [logs.app, ui.clearedSeq.app]);
  const crashes = useMemo(
    () => [...device, ...app].filter(isCrash).sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0) || a.seq - b.seq),
    [device, app],
  );

  const sourceLines = ui.logsSource === 'device' ? device : ui.logsSource === 'app' ? app : crashes;
  const counts = useMemo(() => levelCounts(sourceLines), [sourceLines]);
  const visible = useMemo(
    () => sourceLines.filter((l) => matchesLevels(l, ui.logsLevels) && matchesLogText(l, ui.logsText)),
    [sourceLines, ui.logsLevels, ui.logsText],
  );
  const selected = useMemo(
    () => (ui.selectedLog ? sourceLines.find((l) => logKey(l) === ui.selectedLog) ?? null : null),
    [sourceLines, ui.selectedLog],
  );

  const toggleLevel = (level: Level) => {
    const next = new Set(ui.logsLevels);
    if (next.has(level)) next.delete(level);
    else next.add(level);
    patch({ logsLevels: next });
  };

  const sources = [
    { id: 'device' as const, label: 'Device', n: device.length },
    { id: 'app' as const, label: 'App', n: app.length },
    { id: 'crashes' as const, label: 'Crashes', n: crashes.length },
  ];

  const step = (delta: number) => {
    if (visible.length === 0) return;
    const at = visible.findIndex((l) => logKey(l) === ui.selectedLog);
    const next = Math.min(visible.length - 1, Math.max(0, (at < 0 ? (delta > 0 ? -1 : visible.length) : at) + delta));
    patch({ selectedLog: logKey(visible[next] as LogLine), logsAutoscroll: false });
  };
  const selectedIndex = visible.findIndex((l) => logKey(l) === ui.selectedLog);

  return (
    <div className="lg-wrap">
      <div className="lg-bar">
        <div className="lg-src">
          {sources.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`${ui.logsSource === s.id ? 'on' : ''}${s.id === 'crashes' && s.n > 0 ? ' crash' : ''}`}
              onClick={() => patch({ logsSource: s.id })}
            >
              {s.label}
              <b>{s.n.toLocaleString('en-US')}</b>
            </button>
          ))}
        </div>
        <div className="lvchips">
          {LEVELS.map((l) => (
            <button
              key={l}
              type="button"
              className={`lvchip ${l}${ui.logsLevels.has(l) ? ' on' : ''}`}
              aria-pressed={ui.logsLevels.has(l)}
              title={LEVEL_NAMES[l]}
              onClick={() => toggleLevel(l)}
            >
              {l}
              <b>{counts[l].toLocaleString('en-US')}</b>
            </button>
          ))}
        </div>
        <input
          className="textin grow"
          type="search"
          placeholder="Search tag and message…"
          value={ui.logsText}
          onChange={(e) => patch({ logsText: e.target.value })}
          aria-label="Search logs"
        />
        <button
          type="button"
          className={`btn small${ui.logsAutoscroll ? ' toggled' : ''}`}
          aria-pressed={ui.logsAutoscroll}
          onClick={() => patch({ logsAutoscroll: !ui.logsAutoscroll })}
        >
          Auto-scroll
        </button>
      </div>
      <div className="lg-body">
        <div className="lg-list">
          <div className="lhead">
            <span>Time</span>
            <span>Lvl</span>
            <span>Tag</span>
            <span>Message</span>
            <span />
          </div>
          <div className="lg-rows">
            {visible.length === 0 && <div className="empty">No log lines.</div>}
            <VirtualList
              label="Log lines"
              count={visible.length}
              rowHeight={LOG_ROW_HEIGHT}
              follow={ui.logsAutoscroll}
              onFollowChange={(f) => patch({ logsAutoscroll: f })}
              revealIndex={selectedIndex}
              revealKey={ui.selectedLog}
              onStep={step}
              renderRow={(i) => {
                const line = visible[i] as LogLine;
                return (
                  <LogRow
                    key={logKey(line)}
                    line={line}
                    selected={ui.selectedLog === logKey(line)}
                    onSelect={(l) => patch({ selectedLog: logKey(l) })}
                  />
                );
              }}
            />
          </div>
        </div>
        <LogDetail line={selected} />
      </div>
    </div>
  );
}
