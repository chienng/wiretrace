import { useEffect, useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { bodyOff, bodyProblem, defaultMockName, editableBody, MAP_LOCAL_WARNING, mapLocalNote, mockNameProblem, ruleName } from '../logic/mapLocal';
import { apiHostFor } from '../logic/rules';
import { useDispatch, useStore } from '../store';
import type { FlowSummary } from '../types';
import { Modal } from './Modal';

type Loaded = { body: string; status: number; mime: string | null; revision: string } | { error: string };

/** Save a response as a mock file in the preset's mocks folder, and optionally answer with it (spec 022, slice F). */
export function MapLocalDialog({ flow, onClose }: { flow: FlowSummary; onClose: () => void }) {
  const dispatch = useDispatch();
  const { appState } = useStore();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [name, setName] = useState(() => defaultMockName(flow.method, flow.path));
  const [status, setStatus] = useState('');
  const [body, setBody] = useState('');
  const [rule, setRule] = useState(true);
  const [askReplace, setAskReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<{ field: string; message: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.flow(flow.id, controller.signal), api.rules()])
      .then(([detail, rules]) => {
        const response = detail.response;
        if (!response) return setLoaded({ error: 'This request has no response.' });
        const off = bodyOff(response.body);
        if (off) return setLoaded({ error: `${off}: it cannot be saved as a mock.` });
        const text = editableBody(response.body.text ?? '');
        setLoaded({ body: text, status: response.status, mime: flow.mime, revision: rules.revision });
        setBody(text);
        setStatus(String(response.status));
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted || e instanceof ForbiddenError) return;
        setLoaded({ error: e instanceof ApiError && e.status === 404 ? 'This request is no longer held in memory.' : 'Could not load the request.' });
      });
    return () => controller.abort();
  }, [flow.id, flow.mime]);

  const close = () => {
    if (!busy) onClose();
  };
  const ready = loaded !== null && 'body' in loaded;
  const statusNum = /^\d{3}$/.test(status.trim()) ? Number(status.trim()) : NaN;
  const nameProblem = mockNameProblem(name);
  const statusProblem = statusNum >= 100 && statusNum <= 599 ? null : '100 to 599';
  const sizeProblem = bodyProblem(body);
  const problemOf = (field: string, local: string | null) => local ?? (fieldError?.field === field ? fieldError.message : null);
  const host = apiHostFor(flow.host, appState?.api_hosts ?? []);
  const mocksDir = (appState?.mocks_dir ?? 'mocks').replace(/\/+$/, '');

  const save = async (replace: boolean) => {
    if (!loaded || !('body' in loaded) || nameProblem || statusProblem || sizeProblem) return;
    setBusy(true);
    setError(null);
    setFieldError(null);
    try {
      const saved = await api.mapLocal(flow.id, { file: name, status: statusNum, body, rule: rule && !!host, replace, revision: loaded.revision });
      dispatch({ type: 'toast', text: saved.rule_id ? `Saved ${saved.file}; the rule is first in Rules` : `Saved ${saved.file}` });
      onClose();
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      setBusy(false);
      if (!(e instanceof ApiError)) return setError('Could not save the file');
      const data = e.data && typeof e.data === 'object' ? (e.data as { exists?: unknown; saved?: unknown }) : {};
      if (e.status === 409 && data.exists === true) return setAskReplace(true);
      if (e.field && e.field !== 'rule') return setFieldError({ field: e.field, message: e.message });
      setError(e.message);
      if (data.saved === true) dispatch({ type: 'toast', text: `Saved ${name}; the rule was not added` });
    }
  };

  const nameShown = problemOf('file', nameProblem);
  const statusShown = problemOf('status', statusProblem);
  const bodyShown = problemOf('body', sizeProblem);

  return (
    <Modal title={`Map local: answer ${flow.method} ${flow.path.split('?', 1)[0]} from a file`} lead={`Saves this response into the mocks folder of preset ${appState?.preset ?? ''}.`} onClose={close} wide>
      {loaded === null && <div className="note">Loading…</div>}
      {loaded && 'error' in loaded && <div className="callout warn">{loaded.error}</div>}
      {loaded && 'body' in loaded && (
        <>
          <label className="field-l" htmlFor="ml-file">
            File
          </label>
          <div className="pathin">
            <span className="pre">{mocksDir}/</span>
            <input
              id="ml-file"
              className="textin mono"
              spellCheck={false}
              value={name}
              disabled={busy}
              aria-invalid={nameShown !== null}
              onChange={(e) => {
                setName(e.target.value);
                setAskReplace(false);
              }}
            />
          </div>
          {nameShown ? <div className="field-error">{nameShown}</div> : <div className="tip">Letters, digits, . _ - and / for folders; ends with .json.</div>}
          <div className="ml-row">
            <div>
              <label className="field-l" htmlFor="ml-status">
                Status
              </label>
              <input id="ml-status" className="textin mono w-status-in" inputMode="numeric" maxLength={3} value={status} disabled={busy} onChange={(e) => setStatus(e.target.value)} />
            </div>
            {loaded.mime && <div className="muted ml-type">Content-Type: {loaded.mime}</div>}
          </div>
          {statusShown && <div className="field-error">{statusShown}</div>}
          <label className="field-l" htmlFor="ml-body">
            Body
          </label>
          <textarea id="ml-body" className="bodyedit ml-body" spellCheck={false} value={body} disabled={busy} onChange={(e) => setBody(e.target.value)} />
          {bodyShown && <div className="field-error">{bodyShown}</div>}
          <label className="ml-check">
            <input type="checkbox" checked={rule} disabled={busy || !host} onChange={(e) => setRule(e.target.checked)} />
            <span>
              <span className="l">Answer with it now</span>
              <span className="s2">
                {host
                  ? `Adds the rule ${ruleName(flow.method, flow.path)} at the top of the rules: ${flow.method.toUpperCase()} ${host} ${flow.path.split('?', 1)[0]} · Mock ${Number.isNaN(statusNum) ? status : statusNum} from this file · always.`
                  : 'Rules apply only to the API hosts of the preset: only the file is written.'}
              </span>
            </span>
          </label>
          <div className="tip">{mapLocalNote(name, rule && !!host)}</div>
          <div className="callout warn gap-top">{MAP_LOCAL_WARNING}</div>
        </>
      )}
      {askReplace && (
        <div className="confirm" role="alertdialog" aria-label="Replace the file?">
          <span>
            <b>{name}</b> exists. Replace it?
          </span>
          <span className="spacer" />
          <button type="button" className="btn small" disabled={busy} onClick={() => setAskReplace(false)}>
            Keep it
          </button>
          <button type="button" className="btn small danger" disabled={busy} onClick={() => void save(true)}>
            Replace
          </button>
        </div>
      )}
      {error && (
        <div className="form-error switch-error" role="alert">
          {error}
        </div>
      )}
      <div className="sheet-foot">
        <span className="foot-note">
          {mocksDir}/{name.includes('/') ? `${name.slice(0, name.lastIndexOf('/'))}/` : ''}
        </span>
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={close}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={!ready || busy || askReplace || !!nameProblem || !!statusProblem || !!sizeProblem} onClick={() => void save(false)}>
          {busy ? 'Saving…' : rule && host ? 'Save and map' : 'Save file'}
        </button>
      </div>
    </Modal>
  );
}
