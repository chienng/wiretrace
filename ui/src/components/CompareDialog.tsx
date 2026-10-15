import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import {
  compareChoices,
  defaultOther,
  headerDiff,
  jsonDiff,
  lineDiff,
  parseJson,
  type HeaderRow,
  type JsonDiff,
  type LineDiff,
} from '../logic/diff';
import { formatTime, methodLabel } from '../logic/format';
import { useDispatch } from '../store';
import type { Body as BodyInfo, FlowDetail, FlowSummary } from '../types';
import { Modal } from './Modal';

type Side = { id: string; detail: FlowDetail } | { id: string; error: string };

function useDetail(id: string | null, session: string | null): Side | null {
  const [side, setSide] = useState<Side | null>(null);
  useEffect(() => {
    if (id === null) {
      setSide(null);
      return;
    }
    const controller = new AbortController();
    api
      .flow(id, controller.signal, session)
      .then((detail) => setSide({ id, detail }))
      .catch(() => !controller.signal.aborted && setSide({ id, error: 'Could not load this request: it may have been dropped from memory.' }));
    return () => controller.abort();
  }, [id, session]);
  return side && side.id === id ? side : null;
}

function label(f: FlowSummary): string {
  return `${formatTime(f.ts)} · ${methodLabel(f.method)} ${f.status ?? '—'} ${f.path}`;
}

function bodyText(body: BodyInfo | undefined): string | null {
  if (!body || body.binary) return null;
  return body.text;
}

function Headers({ rows }: { rows: HeaderRow[] }) {
  if (rows.length === 0) return <div className="note">No headers.</div>;
  return (
    <div className="cmp-grid">
      {rows.map((r) => (
        <div key={r.name} className={`cmp-row${r.changed ? ' changed' : ''}`}>
          <span className="k">{r.name}</span>
          <span className={r.left === null ? 'v none' : 'v'}>{r.left ?? '—'}</span>
          <span className={r.right === null ? 'v none' : 'v'}>{r.right ?? '—'}</span>
        </div>
      ))}
    </div>
  );
}

function BodyDiff({ left, right }: { left: BodyInfo | undefined; right: BodyInfo | undefined }) {
  const a = bodyText(left);
  const b = bodyText(right);
  const result = useMemo((): { kind: 'json'; json: JsonDiff } | { kind: 'lines'; lines: LineDiff } | null => {
    if (a === null || b === null) return null;
    const ja = parseJson(a);
    const jb = parseJson(b);
    if (ja.ok && jb.ok) return { kind: 'json', json: jsonDiff(ja.value, jb.value) };
    return { kind: 'lines', lines: lineDiff(a, b) };
  }, [a, b]);

  if (result === null) return <div className="note">{left?.binary || right?.binary ? 'A binary body is not compared.' : 'No body to compare.'}</div>;
  const truncated = left?.truncated || right?.truncated;
  if (result.kind === 'json') {
    const { changes, same, truncated: many } = result.json;
    return (
      <>
        {truncated && <div className="note warn">A body is larger than 2 MiB: only its start is compared.</div>}
        <div className="note">
          {changes.length === 0 ? 'The JSON bodies are the same.' : `${changes.length}${many ? '+' : ''} keys differ`}
          {same > 0 ? ` · ${same} values the same` : ''}
        </div>
        {changes.length > 0 && (
          <div className="cmp-grid">
            {changes.map((c) => (
              <div key={`${c.kind}:${c.path}`} className={`cmp-row ${c.kind}`}>
                <span className="k">{c.path}</span>
                <span className={c.left === undefined ? 'v none' : 'v'}>{c.left ?? '—'}</span>
                <span className={c.right === undefined ? 'v none' : 'v'}>{c.right ?? '—'}</span>
              </div>
            ))}
          </div>
        )}
      </>
    );
  }
  const { lines, cut } = result.lines;
  const changed = lines.some((l) => l.kind !== 'same');
  return (
    <>
      {(cut || truncated) && <div className="note warn">Only the start of the bodies is compared.</div>}
      {!changed ? (
        <div className="note">The bodies are the same.</div>
      ) : (
        <pre className="cmp-lines">
          {lines.map((l, i) => (
            <div key={i} className={l.kind}>
              {l.kind === 'added' ? '+ ' : l.kind === 'removed' ? '- ' : '  '}
              {l.text}
            </div>
          ))}
        </pre>
      )}
    </>
  );
}

/** Two requests side by side: status, headers, and the body as a JSON key diff or a line diff. */
export function CompareDialog({ flow, flows, session }: { flow: FlowSummary; flows: readonly FlowSummary[]; session: string | null }) {
  const dispatch = useDispatch();
  const close = () => dispatch({ type: 'ui', patch: { dialog: null } });
  const choices = useMemo(() => compareChoices(flow, flows), [flow, flows]);
  const [otherId, setOtherId] = useState<string | null>(() => defaultOther(flow, flows)?.id ?? choices[0]?.id ?? null);
  const [part, setPart] = useState<'response' | 'request'>('response');
  const left = useDetail(flow.id, session);
  const right = useDetail(otherId, session);
  const other = flows.find((f) => f.id === otherId) ?? null;

  const ld = left && 'detail' in left ? left.detail : null;
  const rd = right && 'detail' in right ? right.detail : null;
  const error = (left && 'error' in left && left.error) || (right && 'error' in right && right.error) || null;
  const lm = ld ? (part === 'response' ? ld.response : ld.request) : null;
  const rm = rd ? (part === 'response' ? rd.response : rd.request) : null;

  return (
    <Modal title="Compare requests" onClose={close} wide>
      <div className="cmp">
        <div className="cmp-head">
          <div className="cmp-side">
            <div className="sec-h">This request</div>
            <div className="mono">{label(flow)}</div>
          </div>
          <div className="cmp-side">
            <div className="sec-h">Compared with</div>
            {choices.length === 0 ? (
              <div className="note">There is no other request to compare with.</div>
            ) : (
              <select className="selectin wide" value={otherId ?? ''} onChange={(e) => setOtherId(e.target.value)} aria-label="Request to compare with">
                {choices.map((f) => (
                  <option key={f.id} value={f.id}>
                    {label(f)}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        {other && (
          <>
            <div className="seg sm cmp-tabs" role="tablist">
              {(['response', 'request'] as const).map((p) => (
                <button key={p} type="button" role="tab" aria-selected={part === p} className={part === p ? 'on' : ''} onClick={() => setPart(p)}>
                  {p === 'response' ? 'Response' : 'Request'}
                </button>
              ))}
            </div>
            {error && <div className="note warn">{error}</div>}
            {!error && (!ld || !rd) && <div className="note">Loading…</div>}
            {ld && rd && (
              <div className="cmp-body">
                <div className={`cmp-row status${flow.status !== other.status ? ' changed' : ''}`}>
                  <span className="k">Status</span>
                  <span className="v">{ld.response ? `${ld.response.status} ${ld.response.reason}` : (flow.error ?? '—')}</span>
                  <span className="v">{rd.response ? `${rd.response.status} ${rd.response.reason}` : (other.error ?? '—')}</span>
                </div>
                <div className="sec-h">Headers</div>
                {lm && rm ? <Headers rows={headerDiff(lm.headers, rm.headers)} /> : <div className="note">One of them has no response.</div>}
                <div className="sec-h">Body</div>
                {lm && rm ? <BodyDiff left={lm.body} right={rm.body} /> : <div className="note">One of them has no response.</div>}
              </div>
            )}
          </>
        )}
        <div className="sheet-foot">
          <span className="spacer" />
          <button type="button" className="btn" onClick={close}>
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
