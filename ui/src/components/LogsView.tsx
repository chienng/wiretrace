import { useCallback, useMemo, useRef, useState, type CSSProperties } from 'react';
import { copyText } from '../clipboard';
import { download } from '../download';
import { formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import {
  contextText,
  crashLines,
  exportText,
  findLinkedFlow,
  foldCrashes,
  foldMessage,
  isCrash,
  isLinked,
  itemAtTime,
  levelCounts,
  LEVELS,
  LEVEL_NAMES,
  logKey,
  matchesLevels,
  matchesLogText,
  matchesTag,
  normalizeLevel,
  requestIds,
  requestsAround,
  tagCounts,
  AROUND_S,
  CONTEXT_LINES,
  type Level,
  type LogItem,
} from '../logic/logs';
import { LIST_MIN, LIST_MIN_DEFAULT, LOGS_DETAIL, useBoxWidth, usePaneWidth } from '../logic/paneWidth';
import type { Range } from '../logic/timeline';
import { useData, useDispatch, useStore } from '../store';
import type { FlowSummary, LogLine } from '../types';
import { DevicePicker } from './DevicePicker';
import { LogRow, LOG_ROW_HEIGHT } from './LogRow';
import { Toggle } from './RuleEditor';
import { Splitter } from './Splitter';
import { Timeline } from './Timeline';
import { VirtualList } from './VirtualList';

function FlowCard({ flow, onOpen }: { flow: FlowSummary; onOpen: () => void }) {
  return (
    <div className="card">
      <div className="l1">
        <span className={`m ${methodClass(flow.method)}`}>{methodLabel(flow.method)}</span>
        {flow.status !== null && <span className={`st ${statusClass(flow.status)}`}>{flow.status}</span>}
        <span className="path">{flow.path}</span>
        <span className="spacer" />
        <button type="button" className="btn small" onClick={onOpen}>
          Open in Traffic →
        </button>
      </div>
      <div className="l2">
        {formatTime(flow.ts)} · {flow.host}
        {flow.request_id ? ` · ${flow.request_id}` : ''}
      </div>
    </div>
  );
}

function LogDetail({ line, context, flows }: { line: LogLine | null; context: readonly LogLine[]; flows: readonly FlowSummary[] }) {
  const dispatch = useDispatch();
  const [whole, setWhole] = useState<string | null>(null);
  const linked = useMemo(() => (line ? findLinkedFlow(line, flows) : null), [line, flows]);
  const around = useMemo(() => (line ? requestsAround(line, flows) : []), [line, flows]);
  if (!line) return <div className="lg-detail"><div className="empty">Select a log line to see its details.</div></div>;
  const level = normalizeLevel(line.level);
  const key = logKey(line);
  const message = foldMessage(line.message, whole === key);
  const copy = async (text: string, what: string) => {
    const ok = await copyText(text);
    dispatch({ type: 'toast', text: ok ? `${what} copied` : 'Copy failed' });
  };
  const open = (id: string) => dispatch({ type: 'openFlow', id });
  return (
    <div className="lg-detail">
      <div className="hd">
        {level && <span className={`lv ${level}`}>{level}</span>}
        <span className="tgname">{line.tag ?? '(no tag)'}</span>
        <span className="spacer" />
        <button type="button" className="btn small" onClick={() => copy(line.raw ?? line.message, 'Line')}>
          Copy line
        </button>
        <button type="button" className="btn small" onClick={() => copy(contextText(context, line, formatTime), 'Lines')} title={`This line and ${CONTEXT_LINES} lines before and after it`}>
          Copy ±{CONTEXT_LINES} lines
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
      <div className={`fullmsg${isCrash(line) || level === 'E' ? '' : ' plain'}`}>
        {message.text}
        {message.hidden > 0 && (
          <button type="button" className="linkbtn more" onClick={() => setWhole(key)}>
            Show {message.hidden} more {message.hidden === 1 ? 'line' : 'lines'}
          </button>
        )}
      </div>
      <div className="sec-h">Linked request</div>
      {linked ? <FlowCard flow={linked} onOpen={() => open(linked.id)} /> : <div className="note">No request is linked to this line.</div>}
      <div className="sec-h">Requests around this line (±{AROUND_S} s)</div>
      {around.length === 0 ? (
        <div className="note">{line.ts == null ? 'This line has no time.' : 'No request within that time.'}</div>
      ) : (
        <div className="around">
          {around.map((f) => (
            <button type="button" key={f.id} className={`arow${f.id === linked?.id ? ' on' : ''}`} onClick={() => open(f.id)} title="Open in Traffic">
              <span className="t">{formatTime(f.ts)}</span>
              <span className={`m ${methodClass(f.method)}`}>{methodLabel(f.method)}</span>
              <span className={`st ${statusClass(f.status)}`}>{f.status ?? '—'}</span>
              <span className="path">{f.path}</span>
            </button>
          ))}
        </div>
      )}
      <div>
        <button type="button" className="btn small" onClick={() => dispatch({ type: 'ui', patch: { logsTag: line.tag ?? '' } })}>
          Show only this tag
        </button>
      </div>
    </div>
  );
}

function MoreRow({ hidden, onShow }: { hidden: number; onShow: () => void }) {
  return (
    <div className="lrow more" style={{ height: LOG_ROW_HEIGHT }}>
      <span className="t" />
      <span />
      <span />
      <button type="button" className="linkbtn" onClick={onShow}>
        Show {hidden} more {hidden === 1 ? 'line' : 'lines'}
      </button>
      <span />
    </div>
  );
}

const NO_TAG = '\u0000';
const EVERYTHING = { device: -Infinity, app: -Infinity };

export function LogsView() {
  const { appState, ui } = useStore();
  const { flows, logs, viewing } = useData();
  const dispatch = useDispatch();
  const patch = useCallback((p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p }), [dispatch]);
  const [rows, setRows] = useState<[number, number]>([-1, -1]);
  const onRange = useCallback((first: number, last: number) => setRows([first, last]), []);
  const bodyRef = useRef<HTMLDivElement>(null);
  const size = useBoxWidth(bodyRef);
  const detail = usePaneWidth(LOGS_DETAIL, size.box - LIST_MIN, size.window, size.box - LIST_MIN_DEFAULT);

  // Pause and Clear act on the live session only.
  const frozen = viewing ? null : ui.logsFrozen;
  const cleared = viewing ? EVERYTHING : ui.clearedSeq;
  const device = useMemo(
    () => logs.device.filter((l) => l.seq > cleared.device && (!frozen || l.seq <= frozen.device)),
    [logs.device, cleared.device, frozen],
  );
  const app = useMemo(() => logs.app.filter((l) => l.seq > cleared.app && (!frozen || l.seq <= frozen.app)), [logs.app, cleared.app, frozen]);
  const newLines = frozen
    ? logs.device.filter((l) => l.seq > Math.max(frozen.device, cleared.device)).length +
      logs.app.filter((l) => l.seq > Math.max(frozen.app, cleared.app)).length
    : 0;
  const crashes = useMemo(() => crashLines(device, app), [device, app]);
  const shownFlows = useMemo(() => (viewing ? flows : flows.filter((f) => !ui.hidden.has(f.id))), [viewing, flows, ui.hidden]);
  const ids = useMemo(() => requestIds(shownFlows), [shownFlows]);

  const sourceLines = ui.logsSource === 'device' ? device : ui.logsSource === 'app' ? app : crashes;
  const counts = useMemo(() => levelCounts(sourceLines), [sourceLines]);
  const tags = useMemo(() => tagCounts(sourceLines), [sourceLines]);
  const visible = useMemo(
    () =>
      sourceLines.filter(
        (l) =>
          matchesLevels(l, ui.logsLevels) &&
          matchesLogText(l, ui.logsText) &&
          matchesTag(l, ui.logsTag) &&
          (!ui.logsLinkedOnly || isLinked(l, ids)),
      ),
    [sourceLines, ui.logsLevels, ui.logsText, ui.logsTag, ui.logsLinkedOnly, ids],
  );
  const items = useMemo(() => foldCrashes(visible, ui.logsExpanded), [visible, ui.logsExpanded]);
  const selected = useMemo(
    () => (ui.selectedLog ? sourceLines.find((l) => logKey(l) === ui.selectedLog) ?? null : null),
    [sourceLines, ui.selectedLog],
  );
  const context = selected?.source === 'app' ? app : device;
  const selectedIndex = items.findIndex((it) => it.kind === 'line' && logKey(it.line) === ui.selectedLog);

  const shown = useMemo<Range | null>(() => {
    const [first, last] = rows;
    if (first < 0) return null;
    let start: number | null = null;
    let end: number | null = null;
    for (let i = first; i <= last && i < items.length; i++) {
      const it = items[i] as LogItem;
      if (it.kind !== 'line' || it.line.ts == null) continue;
      if (start === null) start = it.line.ts;
      end = it.line.ts;
    }
    return start !== null && end !== null ? { start, end } : null;
  }, [rows, items]);

  const toggleLevel = (level: Level) => {
    const next = new Set(ui.logsLevels);
    if (next.has(level)) next.delete(level);
    else next.add(level);
    patch({ logsLevels: next });
  };
  const expand = (crash: string) => patch({ logsExpanded: new Set(ui.logsExpanded).add(crash) });

  const sources = [
    { id: 'device' as const, label: 'Device logs', n: device.length },
    { id: 'app' as const, label: 'App logs', n: app.length },
    { id: 'crashes' as const, label: 'Crashes', n: crashes.filter(isCrash).length },
  ];

  const step = (delta: number) => {
    const lines = items.flatMap((it, i) => (it.kind === 'line' ? [i] : []));
    if (lines.length === 0) return;
    const at = lines.indexOf(selectedIndex);
    const next = Math.min(lines.length - 1, Math.max(0, (at < 0 ? (delta > 0 ? -1 : lines.length) : at) + delta));
    const item = items[lines[next] as number] as LogItem;
    if (item.kind === 'line') patch({ selectedLog: logKey(item.line), logsAutoscroll: false });
  };

  const pick = (ts: number) => {
    const at = itemAtTime(items, ts);
    const item = at < 0 ? null : (items[at] as LogItem);
    if (item?.kind === 'line') patch({ selectedLog: logKey(item.line), logsAutoscroll: false });
  };

  const exportLines = () => {
    const title = sources.find((s) => s.id === ui.logsSource)?.label ?? 'Logs';
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    download(`wiretrace-${ui.logsSource}-${stamp}.txt`, exportText(visible, title, formatTime), 'text/plain');
    dispatch({ type: 'toast', text: `Exported ${visible.length.toLocaleString('en-US')} lines, not masked` });
  };

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
        {appState && !viewing && <DevicePicker state={appState} appLines={app.length} />}
        <span className="spacer" />
        {!viewing && (
          <>
            <button
              type="button"
              className={`btn small${frozen ? ' toggled' : ''}`}
              aria-pressed={!!frozen}
              onClick={() => dispatch({ type: frozen ? 'logsResume' : 'logsPause' })}
            >
              {frozen ? `Resume logs${newLines > 0 ? ` · ${newLines.toLocaleString('en-US')} new` : ''}` : 'Pause logs'}
            </button>
            <button type="button" className="btn small" onClick={() => dispatch({ type: 'logsClear' })} title="Hide the lines listed now; the log files keep them">
              Clear
            </button>
          </>
        )}
        <button type="button" className="btn small" onClick={exportLines} disabled={visible.length === 0} title="The lines listed now, as text. Not masked: may contain tokens and personal data.">
          Export .txt
        </button>
        <button
          type="button"
          className={`btn small${ui.logsAutoscroll ? ' toggled' : ''}`}
          aria-pressed={ui.logsAutoscroll}
          onClick={() => patch({ logsAutoscroll: !ui.logsAutoscroll })}
        >
          Auto-scroll
        </button>
      </div>
      <div className="lg-bar">
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
        <span className="select-wrap">
          <select
            aria-label="Tag"
            value={ui.logsTag === null ? '' : ui.logsTag === '' ? NO_TAG : ui.logsTag}
            onChange={(e) => patch({ logsTag: e.target.value === '' ? null : e.target.value === NO_TAG ? '' : e.target.value })}
          >
            <option value="">Tag: any</option>
            {ui.logsTag !== null && !tags.some((t) => t.tag === ui.logsTag) && (
              <option value={ui.logsTag === '' ? NO_TAG : ui.logsTag}>{ui.logsTag || '(no tag)'} · 0</option>
            )}
            {tags.map((t) => (
              <option key={t.tag} value={t.tag === '' ? NO_TAG : t.tag}>
                {t.tag || '(no tag)'} · {t.count.toLocaleString('en-US')}
              </option>
            ))}
          </select>
        </span>
        <label className="toggle-label">
          <Toggle on={ui.logsLinkedOnly} label="Only lines linked to requests" onChange={(on) => patch({ logsLinkedOnly: on })} />
          Only lines linked to requests
        </label>
      </div>
      <Timeline flows={shownFlows} lines={sourceLines} shown={shown} selected={selected?.ts ?? null} onPick={pick} />
      <div className="lg-body" ref={bodyRef} style={{ '--detail-w': `${detail.width}px` } as CSSProperties}>
        <div className="lg-list">
          <div className="lhead">
            <span className="h-time">Time</span>
            <span>Lvl</span>
            <span>Tag</span>
            <span>Message</span>
            <span />
          </div>
          <div className="lg-rows">
            {items.length === 0 && <div className="empty">No log lines.</div>}
            <VirtualList
              label="Log lines"
              count={items.length}
              rowHeight={LOG_ROW_HEIGHT}
              follow={ui.logsAutoscroll}
              onFollowChange={(f) => patch({ logsAutoscroll: f })}
              revealIndex={selectedIndex}
              revealKey={ui.selectedLog}
              onStep={step}
              onRange={onRange}
              renderRow={(i) => {
                const item = items[i] as LogItem;
                if (item.kind === 'more') return <MoreRow key={`more:${item.crash}`} hidden={item.hidden} onShow={() => expand(item.crash)} />;
                const line = item.line;
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
        <LogDetail line={selected} context={context} flows={shownFlows} />
        <Splitter label="Resize the log line details" edge="end" pane={detail} />
      </div>
    </div>
  );
}
