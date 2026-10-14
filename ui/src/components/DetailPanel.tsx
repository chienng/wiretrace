import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import { copyText } from '../clipboard';
import { buildCurl, mockFilePath } from '../logic/curl';
import { flowUrl } from '../logic/filters';
import { formatDuration, formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import { matchesRequest } from '../logic/logs';
import { useDispatch, useStore } from '../store';
import type { FlowDetail, FlowSummary, Headers } from '../types';
import { BodyView } from './BodyView';
import { LogRow, LOG_ROW_HEIGHT } from './LogRow';
import { VirtualList } from './VirtualList';

type Tab = 'request' | 'response' | 'headers' | 'timing' | 'logs';
const TABS: { id: Tab; label: string }[] = [
  { id: 'request', label: 'Request' },
  { id: 'response', label: 'Response' },
  { id: 'headers', label: 'Headers' },
  { id: 'timing', label: 'Timing' },
  { id: 'logs', label: 'Logs' },
];

type Loaded = { id: string; detail: FlowDetail } | { id: string; error: string };

function HeaderTable({ title, headers }: { title: string; headers: Headers }) {
  return (
    <div className="hsec">
      <div className="sec-h">
        {title} ({headers.length})
      </div>
      <div className="kvtable">
        {headers.map(([k, v], i) => (
          <div key={i} className="kvrow">
            <span className="hk">{k}</span>
            <span className="hv">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ms(a: number | null, b: number | null): string {
  return a === null || b === null ? '—' : formatDuration((b - a) * 1000);
}

function Timing({ detail }: { detail: FlowDetail }) {
  const t = detail.timing;
  const rows: [string, string][] = [
    ['Request sent', ms(t.start, t.request_end)],
    ['Waiting for response', ms(t.request_end, t.response_start)],
    ['Response received', ms(t.response_start, t.response_end)],
    ['Total', ms(t.start, t.response_end ?? t.response_start ?? t.request_end)],
  ];
  return (
    <div className="hsec">
      <div className="sec-h">Timing</div>
      <div className="kvtable">
        {rows.map(([k, v]) => (
          <div key={k} className="kvrow">
            <span className="hk">{k}</span>
            <span className="hv">{v}</span>
          </div>
        ))}
        <div className="kvrow">
          <span className="hk">Started</span>
          <span className="hv">{formatTime(t.start)}</span>
        </div>
      </div>
    </div>
  );
}

function FlowLogs({ requestId }: { requestId: string | null }) {
  const { logs } = useStore();
  const lines = useMemo(() => {
    if (!requestId) return [];
    return [...logs.device, ...logs.app]
      .filter((l) => matchesRequest(l, requestId))
      .sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0) || a.seq - b.seq);
  }, [logs, requestId]);
  if (!requestId) return <div className="note">This request has no request ID.</div>;
  if (lines.length === 0) return <div className="note">No log lines carry this request ID.</div>;
  return (
    <VirtualList
      label="Request log lines"
      count={lines.length}
      rowHeight={LOG_ROW_HEIGHT}
      follow={false}
      className="grow"
      renderRow={(i) => {
        const line = lines[i]!;
        return <LogRow key={`${line.source}:${line.seq}`} line={line} compact />;
      }}
    />
  );
}

export function DetailPanel({ flow }: { flow: FlowSummary | null }) {
  const dispatch = useDispatch();
  const { logs, appState } = useStore();
  const [tab, setTab] = useState<Tab>('response');
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [mockNote, setMockNote] = useState<string | null>(null);

  const id = flow?.id ?? null;
  // Refetch when the flow gains a response, an error or a size.
  const version = flow ? `${flow.status}|${flow.error}|${flow.size}|${flow.duration_ms}` : '';

  useEffect(() => {
    setMockNote(null);
  }, [id]);

  useEffect(() => {
    if (id === null) {
      setLoaded(null);
      return;
    }
    const controller = new AbortController();
    api
      .flow(id, controller.signal)
      .then((detail) => setLoaded({ id, detail }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const message = e instanceof ApiError && e.status === 404 ? 'This request is no longer held in memory.' : 'Could not load the request.';
        setLoaded({ id, error: message });
      });
    return () => controller.abort();
  }, [id, version]);

  const requestId = flow?.request_id ?? null;
  const logCount = useMemo(() => {
    if (!requestId) return 0;
    let n = 0;
    for (const l of logs.device) if (matchesRequest(l, requestId)) n++;
    for (const l of logs.app) if (matchesRequest(l, requestId)) n++;
    return n;
  }, [logs, requestId]);

  if (!flow) return <div className="detail"><div className="empty">Select a request to see its details.</div></div>;

  const detail = loaded && 'detail' in loaded && loaded.id === flow.id ? loaded.detail : null;
  const error = loaded && 'error' in loaded && loaded.id === flow.id ? loaded.error : null;

  const copyCurl = async () => {
    if (!detail) return;
    const ok = await copyText(buildCurl(detail));
    dispatch({ type: 'toast', text: ok ? 'cURL copied' : 'Copy failed' });
  };

  const copyMock = async () => {
    if (!detail) return;
    const text = detail.response?.body.text ?? null;
    if (text === null) {
      dispatch({ type: 'toast', text: 'No text response body to copy' });
      return;
    }
    const ok = await copyText(text);
    const path = detail.mock_path || mockFilePath(appState?.mocks_dir ?? 'mocks', flow);
    setMockNote(path);
    dispatch({ type: 'toast', text: ok ? 'Response body copied' : 'Copy failed' });
  };

  const sc = statusClass(flow.status);

  return (
    <div className="detail">
      <div className="detail-head">
        <div className="line1">
          <span className={`m ${methodClass(flow.method)}`}>{methodLabel(flow.method)}</span>
          <span className="url" title={flowUrl(flow)}>
            {flow.path}
          </span>
          {flow.status !== null && <span className={`st ${sc}`}>{flow.status}</span>}
          {flow.status === null && flow.error !== null && <span className="st s5">ERR</span>}
        </div>
        <div className="meta">
          <span>
            Host <b>{flow.host}</b>
          </span>
          <span>
            Duration <b>{formatDuration(flow.duration_ms)}</b>
          </span>
          <span>
            Request ID <b className="mono">{flow.request_id ?? '—'}</b>
          </span>
        </div>
        {flow.error && <div className="errtext">{flow.error}</div>}
        <div className="actions">
          <button type="button" className="btn small" onClick={copyCurl} disabled={!detail}>
            Copy cURL
          </button>
          <button type="button" className="btn small" onClick={copyMock} disabled={!detail}>
            Copy as mock
          </button>
        </div>
        {mockNote && (
          <div className="mocknote">
            Copied. Save it as <span className="kbd">{mockNote}</span>
          </div>
        )}
      </div>
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab${tab === t.id ? ' on' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'logs' && logCount > 0 && <span className="c">{logCount}</span>}
          </button>
        ))}
      </div>
      <div className="detail-body">
        {error && <div className="note warn">{error}</div>}
        {!error && !detail && tab !== 'logs' && <div className="note">Loading…</div>}
        {detail && tab === 'request' && (
          <>
            <div className="codehead">
              {detail.request.http_version} · {flow.method} · {flowUrl(flow)}
            </div>
            <BodyView body={detail.request.body} label="Request" />
          </>
        )}
        {detail && tab === 'response' &&
          (detail.response ? (
            <>
              <div className="codehead">
                {detail.response.http_version} {detail.response.status} {detail.response.reason}
                {flow.mime ? ` · ${flow.mime}` : ''}
              </div>
              <BodyView body={detail.response.body} label="Response" />
            </>
          ) : (
            <div className="note">{flow.error ? 'No response: the request failed.' : 'No response yet.'}</div>
          ))}
        {detail && tab === 'headers' && (
          <div className="scroll">
            <HeaderTable title="Request headers" headers={detail.request.headers} />
            {detail.response && <HeaderTable title="Response headers" headers={detail.response.headers} />}
          </div>
        )}
        {detail && tab === 'timing' && <Timing detail={detail} />}
        {tab === 'logs' && <FlowLogs requestId={requestId} />}
      </div>
    </div>
  );
}
