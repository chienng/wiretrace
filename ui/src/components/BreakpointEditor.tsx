import { useState } from 'react';
import { api, ApiError } from '../api';
import {
  bodyNotEditableText,
  draftProblem,
  editedParts,
  editsOf,
  giveUpHint,
  isFixed,
  type Draft,
} from '../logic/breakpoint';
import { METHODS } from '../logic/rules';
import { useNow } from '../hooks';
import { useDispatch } from '../store';
import type { BreakpointInfo, Headers } from '../types';
import { BodyView } from './BodyView';

const EDIT_METHODS = METHODS.filter((m) => m !== 'ANY');

/** A paused request or response: edit it, then Continue (Send to app) or Abort (spec 022, slice D). */
export function BreakpointEditor({ flowId, held, initial, onGone }: { flowId: string; held: BreakpointInfo; initial: Draft; onGone: () => void }) {
  const dispatch = useDispatch();
  const now = useNow(1000);
  const [draft, setDraft] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const edited = editedParts(draft, initial);
  const hint = giveUpHint(held.since, now);
  const request = draft.phase === 'request';
  const set = (patch: Partial<Draft>) => {
    setDraft({ ...draft, ...patch });
    setError(null);
  };
  const setHeader = (i: number, at: 0 | 1, value: string) =>
    set({ headers: draft.headers.map((h, j) => (j === i ? ((at === 0 ? [value, h[1]] : [h[0], value]) as [string, string]) : h)) });

  const act = async (action: 'continue' | 'abort') => {
    if (action === 'continue') {
      const problem = draftProblem(draft, initial);
      if (problem) {
        setError(problem);
        return;
      }
    }
    setBusy(true);
    try {
      const sent = action === 'continue' && edited.length > 0 ? editsOf(draft, initial) : null;
      const result = await api.breakpoint(flowId, action, held.revision, sent);
      const text = action === 'abort' ? 'Aborted: the app sees a network error' : result.edited ? 'Sent with your edits' : 'Sent unchanged';
      dispatch({ type: 'toast', text });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach Wiretrace');
      if (e instanceof ApiError && e.status === 409) onGone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bp">
      <div className="bp-body scroll">
        {request ? (
          <div className="row">
            <select className="selectin w-method" aria-label="Method" value={draft.method} onChange={(e) => set({ method: e.target.value })}>
              {!(EDIT_METHODS as readonly string[]).includes(draft.method) && <option value={draft.method}>{draft.method}</option>}
              {EDIT_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <input className="textin mono grow" aria-label="Path and query" spellCheck={false} value={draft.path} onChange={(e) => set({ path: e.target.value })} />
          </div>
        ) : (
          <div className="row center">
            <label className="sec-h" htmlFor="bp-status">
              Status
            </label>
            <input id="bp-status" className="textin mono w-status-in" inputMode="numeric" value={draft.status} onChange={(e) => set({ status: e.target.value })} />
            {draft.status.trim() !== initial.status && <span className="muted">was {initial.status}</span>}
          </div>
        )}

        <div className="sec-h">Headers</div>
        <div className="bp-headers">
          {draft.headers.map(([k, v], i) =>
            isFixed(k) && initial.headers.some(([ik, iv]) => ik === k && iv === v) ? (
              <div key={i} className="bp-h fixed" title="Wiretrace sets this header">
                <input className="textin mono" aria-label="Header name" value={k} readOnly />
                <input className="textin mono" aria-label={`${k} value`} value={v} readOnly />
                <span />
              </div>
            ) : (
              <div key={i} className="bp-h">
                <input className="textin mono" aria-label="Header name" spellCheck={false} value={k} onChange={(e) => setHeader(i, 0, e.target.value)} />
                <input className="textin mono" aria-label={`${k || 'Header'} value`} spellCheck={false} value={v} onChange={(e) => setHeader(i, 1, e.target.value)} />
                <button type="button" className="iconbtn" aria-label={`Remove ${k || 'header'}`} onClick={() => set({ headers: draft.headers.filter((_, j) => j !== i) })}>
                  ×
                </button>
              </div>
            ),
          )}
          <button type="button" className="linkbtn" onClick={() => set({ headers: [...draft.headers, ['', ''] as [string, string]] })}>
            + Add header
          </button>
        </div>

        <div className="sec-h">Body</div>
        {draft.body === null ? (
          <div className="note">{bodyNotEditableText(held.body_not_editable ?? 'binary')}</div>
        ) : (
          <textarea className="bodyedit bp-text" aria-label={request ? 'Request body' : 'Response body'} spellCheck={false} value={draft.body} onChange={(e) => set({ body: e.target.value })} />
        )}
        {hint && <div className="bp-hint">{hint}</div>}
      </div>
      {error && (
        <div className="form-error bp-error" role="alert">
          {error}
        </div>
      )}
      <div className="bp-foot">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void act('continue')}>
          {request ? 'Continue' : 'Send to app'}
        </button>
        <button type="button" className="btn danger" disabled={busy} onClick={() => void act('abort')} title="Closes the request: the app sees a network error">
          Abort
        </button>
        <button type="button" className="linkbtn" disabled={busy || edited.length === 0} onClick={() => set(initial)}>
          Undo edits
        </button>
        <span className="spacer" />
        {edited.length > 0 && <span className="muted">Edited: {edited.join(', ')}</span>}
      </div>
    </div>
  );
}

/** The held message as it arrived, before any edit. */
export function BreakpointOriginal({ held }: { held: BreakpointInfo }) {
  const o = held.original;
  const headers: Headers = o.headers;
  return (
    <div className="scroll">
      <div className="codehead">{held.phase === 'request' ? `${o.method ?? ''} ${o.path ?? ''}` : `Status ${o.status ?? ''}`}</div>
      <div className="hsec">
        <div className="sec-h">Headers ({headers.length})</div>
        <div className="kvtable">
          {headers.map(([k, v], i) => (
            <div key={i} className="kvrow">
              <span className="hk">{k}</span>
              <span className="hv">{v}</span>
            </div>
          ))}
        </div>
      </div>
      <BodyView body={o.body} label={held.phase === 'request' ? 'Original request' : 'Original response'} />
    </div>
  );
}
