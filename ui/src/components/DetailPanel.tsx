import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import { copyText } from '../clipboard';
import { draftOf, phaseText, waited } from '../logic/breakpoint';
import { buildCurl, mockFilePath } from '../logic/curl';
import { flowUrl } from '../logic/filters';
import { formatDuration, formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import { decryptOff, hostPort, notDecryptedText, openFor, tunnelTag } from '../logic/hosts';
import { matchesRequest } from '../logic/logs';
import { newRuleOff, replayOff, SAFE_METHODS } from '../logic/flowMenu';
import { mapLocalOff } from '../logic/mapLocal';
import { detailTabs } from '../logic/wsMessages';
import { deviceText } from '../logic/proxyDevices';
import { changeGroups, changeGroupTitle, changeParts, sideText } from '../logic/rules';
import { useData, useDispatch, useStore } from '../store';
import type { FlowDetail, FlowSummary, Headers, TunnelRow } from '../types';
import { useNow } from '../hooks';
import { BodyView } from './BodyView';
import { WsMessages } from './WsMessages';
import { BreakpointEditor, BreakpointOriginal } from './BreakpointEditor';
import { LogRow, LOG_ROW_HEIGHT } from './LogRow';
import { VirtualList } from './VirtualList';

type Tab = 'edit' | 'original' | 'messages' | 'request' | 'response' | 'headers' | 'changes' | 'timing' | 'logs';

function Changes({ detail }: { detail: FlowDetail }) {
  return (
    <div className="scroll">
      <div className="hsec">
        {detail.changes.length === 0 && !detail.map_remote && <div className="note">No change recorded for this request.</div>}
        {detail.map_remote && (
          <div className="chg-group">
            <div className="sec-h">Map remote{detail.map_remote.rule && ` · rule ${detail.map_remote.rule}`}</div>
            <div className="chg-row">
              <span className="ok" aria-label="Applied">
                ✓
              </span>
              <span className="on">{sideText('request')}</span>
              <span>
                {detail.map_remote.from} → <code>{detail.map_remote.to}</code>
              </span>
            </div>
          </div>
        )}
        {changeGroups(detail.changes).map((g, i) => (
          <div key={i} className="chg-group">
            <div className="sec-h">{changeGroupTitle(g)}</div>
            {g.entries.map((c, j) => {
              const { label, target, value } = changeParts(c);
              return (
                <div key={j} className="chg-row">
                  <span className={c.applied ? 'ok' : 'skip'} aria-label={c.applied ? 'Applied' : 'Skipped'}>
                    {c.applied ? '✓' : '–'}
                  </span>
                  <span className="on">{sideText(c.on)}</span>
                  <span>
                    {label} <code>{target}</code>
                    {value !== null && (
                      <>
                        {' '}
                        = <code>{value}</code>
                      </>
                    )}
                    {!c.applied && c.reason && <span className="why"> · skipped: {c.reason}</span>}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
        {detail.comment && (
          <>
            <div className="sec-h chg-comment">Comment</div>
            <div className="hv">{detail.comment}</div>
          </>
        )}
      </div>
    </div>
  );
}

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
  const { logs } = useData();
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

/** A connection passed through without decrypting: what is known about it, and how to decrypt its host. */
export function TunnelDetail({ tunnel, onDecrypt }: { tunnel: TunnelRow; onDecrypt: (host: string) => void }) {
  const { appState } = useStore();
  const { viewing } = useData();
  const off = decryptOff(appState, tunnel.host, viewing);
  return (
    <div className="detail">
      <div className="detail-head">
        <div className="line1">
          <span className="m conn">{tunnel.method}</span>
          <span className="url" title={hostPort(tunnel)}>
            {hostPort(tunnel)}
          </span>
          <span className="tag enc">{tunnelTag(tunnel)}</span>
        </div>
        <div className="meta">
          {tunnel.client && (
            <span>
              Device <b className={tunnel.client === 'mac' || tunnel.client === 'wireguard' ? undefined : 'mono'}>{deviceText(tunnel.client)}</b>
            </span>
          )}
          <span>
            Opened <b>{formatTime(tunnel.ts)}</b>
          </span>
          <span>
            {tunnel.closed_at === null ? 'Still open' : <>Open for <b>{openFor(tunnel)}</b></>}
          </span>
        </div>
      </div>
      <div className="detail-body">
        <div className="scroll">
          <div className="infobox">
            <span className="t">Not decrypted</span>
            <span>{notDecryptedText(tunnel.host, appState?.preset ?? '')}</span>
            <button type="button" className="btn primary small" disabled={off !== null} title={off ?? undefined} onClick={() => onDecrypt(tunnel.host)}>
              Decrypt this host…
            </button>
          </div>
          {tunnel.headers && <HeaderTable title="CONNECT request from the phone" headers={tunnel.headers} />}
          {tunnel.answer && (
            <div className="hsec">
              <div className="sec-h">Answer</div>
              <div className="kvtable">
                <div className="kvrow">
                  <span className="hk">Status</span>
                  <span className="hv">{tunnel.answer.replace(/^HTTP\/1\.1 /, '')} (sent by Wiretrace)</span>
                </div>
                <div className="kvrow">
                  <span className="hk">Then</span>
                  <span className="hv">{tunnel.tls ? 'TLS straight to the server, not read' : 'Bytes straight to the server, not read'}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function Waited({ since }: { since: number | null }) {
  return <b className="mono">{waited(since, useNow(1000))}</b>;
}

export function DetailPanel({ flow, onMapLocal }: { flow: FlowSummary | null; onMapLocal: (flow: FlowSummary) => void }) {
  const dispatch = useDispatch();
  const { appState } = useStore();
  const { logs, viewing } = useData();
  const [tab, setTab] = useState<Tab>('response');
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [mockNote, setMockNote] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [refetch, setRefetch] = useState(0);

  const id = flow?.id ?? null;
  const paused = flow?.paused ?? null;
  // Refetch when the flow gains a response, an error or a size, or pauses or goes on.
  const version = flow ? `${flow.status}|${flow.error}|${flow.size}|${flow.duration_ms}|${paused}|${refetch}` : '';

  useEffect(() => {
    setMockNote(null);
    setConfirming(false);
  }, [id]);

  const changed = (flow?.rewritten ?? false) || (flow?.mapped ?? false);
  const socket = flow?.websocket ?? false;
  useEffect(() => {
    if (!changed) setTab((t) => (t === 'changes' ? (socket ? 'messages' : 'response') : t));
  }, [id, changed, socket]);

  useEffect(() => {
    if (paused) setTab('edit');
    else if (socket) setTab('messages');
    else setTab((t) => (t === 'edit' || t === 'original' || t === 'messages' ? 'response' : t));
  }, [id, paused, socket]);

  useEffect(() => {
    if (id === null) {
      setLoaded(null);
      return;
    }
    const controller = new AbortController();
    api
      .flow(id, controller.signal, viewing)
      .then((detail) => setLoaded({ id, detail }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const message = e instanceof ApiError && e.status === 404 ? 'This request is no longer held in memory.' : 'Could not load the request.';
        setLoaded({ id, error: message });
      });
    return () => controller.abort();
  }, [id, version, viewing]);

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
  const held = flow.paused ? (detail?.breakpoint ?? null) : null;
  const draft = held && detail ? draftOf(detail) : null;
  const shown = detailTabs(socket, changed);
  const tabs: { id: Tab; label: string }[] = held
    ? [{ id: 'edit', label: held.phase === 'request' ? 'Edit request' : 'Edit response' }, { id: 'original', label: 'Original' }, ...shown]
    : shown;

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

  const replay = async () => {
    setConfirming(false);
    setReplaying(true);
    try {
      await api.replay(flow.id);
      dispatch({ type: 'toast', text: 'Replay sent: it is listed as a new request marked REPLAY' });
    } catch (e) {
      dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : 'Replay failed' });
    } finally {
      setReplaying(false);
    }
  };
  const askReplay = () => (SAFE_METHODS.has(flow.method.toUpperCase()) ? void replay() : setConfirming(true));
  const replayOffText = replayOff(flow, viewing);
  const mapOff = mapLocalOff(flow, viewing);

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
          {flow.replay_of && <span className="tag replay">Replay</span>}
          {flow.paused && <span className="tag paused">Paused</span>}
          {!flow.paused && flow.edited && <span className="tag edited">Edited</span>}
          {flow.mapped && <span className="tag mapped">Mapped</span>}
          {flow.rewritten && <span className="tag rewritten">Rewritten</span>}
        </div>
        <div className="meta">
          {flow.paused && (
            <span>
              {phaseText(flow.paused)} · <Waited since={flow.paused_since} />
            </span>
          )}
          <span>
            Host <b>{flow.host}</b>
          </span>
          {flow.mapped && flow.sent_to && (
            <span className="sent-to">
              Sent to <b>{flow.sent_to}</b>
            </span>
          )}
          <span>
            Duration <b>{formatDuration(flow.duration_ms)}</b>
          </span>
          <span>
            Request ID <b className="mono">{flow.request_id ?? '—'}</b>
          </span>
          {flow.client && (
            <span>
              Device <b className={flow.client === 'mac' || flow.client === 'wireguard' ? undefined : 'mono'}>{deviceText(flow.client)}</b>
            </span>
          )}
          {flow.replay_of && (
            <span>
              Replay of{' '}
              <button type="button" className="linkbtn" onClick={() => dispatch({ type: 'ui', patch: { selectedFlowId: flow.replay_of } })}>
                the original request
              </button>
            </span>
          )}
        </div>
        {flow.error && <div className="errtext">{flow.error}</div>}
        <div className="actions">
          <button type="button" className="btn small" onClick={copyCurl} disabled={!detail}>
            Copy cURL
          </button>
          <button type="button" className="btn small" onClick={copyMock} disabled={!detail}>
            Copy as mock
          </button>
          <button type="button" className="btn small" onClick={() => onMapLocal(flow)} disabled={mapOff !== null} title={mapOff ?? 'Save the response as a mock file and answer with it'}>
            Map local…
          </button>
          <button type="button" className="btn small" onClick={askReplay} disabled={replayOffText !== null || replaying} title={replayOffText ?? 'Send this request again'}>
            {replaying ? 'Replaying…' : 'Replay'}
          </button>
          <button type="button" className="btn small" onClick={() => dispatch({ type: 'ui', patch: { dialog: 'compare' } })}>
            Compare…
          </button>
          <button
            type="button"
            className="btn small"
            onClick={() => dispatch({ type: 'newRuleFrom', flow })}
            disabled={!!viewing}
            title={newRuleOff(viewing) ?? 'A rule for this method, host and path'}
          >
            New rule
          </button>
          <button type="button" className="btn small primary" onClick={() => dispatch({ type: 'openReport', flowId: flow.id })}>
            Report
          </button>
        </div>
        {confirming && (
          <div className="confirm" role="alertdialog" aria-label="Replay this request?">
            <span>
              Replay <b>{flow.method}</b> {flow.path}? It repeats its effect on the backend.
            </span>
            <span className="spacer" />
            <button type="button" className="btn small" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button type="button" className="btn small danger" onClick={() => void replay()}>
              Replay
            </button>
          </div>
        )}
        {mockNote && (
          <div className="mocknote">
            Copied. Save it as <span className="kbd">{mockNote}</span>
          </div>
        )}
      </div>
      <div className="tabs">
        {tabs.map((t) => (
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
        {!error && !detail && tab !== 'logs' && tab !== 'messages' && <div className="note">Loading…</div>}
        {tab === 'messages' && socket && <WsMessages flow={flow} session={viewing} />}
        {detail && tab === 'edit' && held && draft && (
          <BreakpointEditor key={`${flow.id}:${held.revision}`} flowId={flow.id} held={held} initial={draft} onGone={() => setRefetch((n) => n + 1)} />
        )}
        {detail && tab === 'edit' && !held && <div className="note">Loading…</div>}
        {detail && tab === 'original' && held && <BreakpointOriginal held={held} />}
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
        {detail && tab === 'changes' && changed && <Changes detail={detail} />}
        {detail && tab === 'timing' && <Timing detail={detail} />}
        {tab === 'logs' && <FlowLogs requestId={requestId} />}
      </div>
    </div>
  );
}
