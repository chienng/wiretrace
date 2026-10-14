import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import { useDispatch, useStore } from '../store';
import type { Faults } from '../types';
import { Modal } from './Modal';

function parseInteger(label: string, raw: string): { value: number } | { error: string } {
  const t = raw.trim();
  if (t === '') return { value: 0 };
  if (!/^-?\d+$/.test(t)) return { error: `${label} must be a whole number` };
  return { value: Number(t) };
}

export function FaultsDialog() {
  const { appState } = useStore();
  const dispatch = useDispatch();
  const [filter, setFilter] = useState(appState?.faults.filter ?? '');
  const [status, setStatus] = useState(String(appState?.faults.status ?? 0));
  const [delay, setDelay] = useState(String(appState?.faults.delay_ms ?? 0));
  const [drop, setDrop] = useState(appState?.faults.drop ?? false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mocks, setMocks] = useState<string[] | null>(null);
  const [mocksFailed, setMocksFailed] = useState(false);
  const close = () => dispatch({ type: 'ui', patch: { dialog: null } });

  useEffect(() => {
    let cancelled = false;
    api
      .mocks()
      .then((files) => !cancelled && setMocks(files))
      .catch(() => !cancelled && setMocksFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (faults: Faults) => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.putFaults(faults);
      dispatch({ type: 'faults', faults: saved });
      dispatch({ type: 'toast', text: 'Faults saved' });
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save the faults.');
    } finally {
      setBusy(false);
    }
  };

  const onSave = () => {
    const s = parseInteger('Status', status);
    if ('error' in s) return setError(s.error);
    const d = parseInteger('Delay', delay);
    if ('error' in d) return setError(d.error);
    void save({ filter: filter.trim(), status: s.value, delay_ms: d.value, drop });
  };

  return (
    <Modal
      title="Faults"
      lead="Matching requests get the fault instead of reaching the server. A change applies to the next request."
      onClose={close}
    >
      <div className="form">
        <div className="field">
          <label htmlFor="f-filter">Filter</label>
          <input id="f-filter" className="textin mono" value={filter} placeholder="~u /api/v1/orders" onChange={(e) => setFilter(e.target.value)} spellCheck={false} />
        </div>
        <div className="row">
          <div className="field">
            <label htmlFor="f-status">Status (0 = off)</label>
            <input id="f-status" className="textin mono" inputMode="numeric" value={status} onChange={(e) => setStatus(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="f-delay">Delay (ms)</label>
            <input id="f-delay" className="textin mono" inputMode="numeric" value={delay} onChange={(e) => setDelay(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="f-drop">Drop connection</label>
            <label className="check-line">
              <input id="f-drop" type="checkbox" checked={drop} onChange={(e) => setDrop(e.target.checked)} />
              <span>{drop ? 'On' : 'Off'}</span>
            </label>
          </div>
        </div>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <div className="sec">
          <div className="sec-h">Mock files</div>
          {appState && <div className="mocksdir">{appState.mocks_dir}</div>}
          <div className="mocklist">
            {mocksFailed && <div className="note">Could not load the mock files.</div>}
            {!mocksFailed && mocks === null && <div className="note">Loading…</div>}
            {mocks?.length === 0 && <div className="note">No mock files.</div>}
            {mocks?.map((f) => (
              <div key={f} className="mockrow">
                {f}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="sheet-foot">
        <button type="button" className="btn danger" disabled={busy} onClick={() => void save({ filter: '', status: 0, delay_ms: 0, drop: false })}>
          Clear faults
        </button>
        <span className="spacer" />
        <button type="button" className="btn" onClick={close}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={onSave}>
          Save
        </button>
      </div>
    </Modal>
  );
}
