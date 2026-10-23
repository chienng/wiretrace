import { useEffect, useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { DEFAULT_PORT, freeLine, parsePort, PORT_HINT, portProblem, restartNote } from '../logic/port';
import { useDispatch } from '../store';
import { Modal } from './Modal';

const CHECK_DELAY_MS = 250;

type Check = { port: number; free: boolean } | { port: number; error: string };

/** Restart the session on another Wi-Fi proxy port (spec 022, slice B). */
export function ChangePortDialog({ current, macIp, onClose }: { current: number; macIp: string | null; onClose: () => void }) {
  const dispatch = useDispatch();
  const [text, setText] = useState('');
  const [check, setCheck] = useState<Check | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = text.trim() ? portProblem(text, current) : null;
  const port = problem === null ? parsePort(text) : null;

  useEffect(() => {
    setCheck(null);
    if (port === null) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .portCheck(String(port), abort.signal)
        .then((result) => setCheck({ port, free: result.free }))
        .catch((e: unknown) => {
          if (abort.signal.aborted || e instanceof ForbiddenError) return;
          setCheck({ port, error: e instanceof ApiError ? e.message : 'Could not check the port' });
        });
    }, CHECK_DELAY_MS);
    return () => {
      abort.abort();
      window.clearTimeout(timer);
    };
  }, [port]);

  const close = () => {
    if (!busy) onClose();
  };
  const checked = check && check.port === port ? check : null;
  const ready = port !== null && checked !== null && 'free' in checked && checked.free;

  const confirm = async () => {
    if (!ready || port === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.changePort(port);
      if (result) {
        dispatch({ type: 'switching', to: `port ${port}` });
        return;
      }
      onClose();
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      setError(e instanceof ApiError ? e.message : 'Could not change the port');
      setBusy(false);
    }
  };

  return (
    <Modal title="Wi-Fi proxy port" lead="The port phones use for the Wi-Fi proxy on this Mac. WireGuard is not affected." onClose={close}>
      <label className="field-l" htmlFor="proxy-port">
        Port
      </label>
      <input
        id="proxy-port"
        className="textin mono port-in"
        inputMode="numeric"
        autoFocus
        value={text}
        maxLength={5}
        placeholder={String(current)}
        aria-invalid={problem !== null}
        disabled={busy}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void confirm();
        }}
      />
      <div className="tip">{PORT_HINT}</div>
      {problem && (
        <div className="callout warn gap-top" role="status">
          {problem}
        </div>
      )}
      {port !== null && !checked && <div className="callout info gap-top">Checking port {port}…</div>}
      {checked && 'free' in checked && (
        <div className={`callout ${checked.free ? 'ok' : 'warn'} gap-top`} role="status">
          {freeLine(checked.port, checked.free)}
        </div>
      )}
      {checked && 'error' in checked && <div className="callout warn gap-top">{checked.error}</div>}
      {port !== null && <div className="callout info">{restartNote(port, macIp)}</div>}
      {error && (
        <div className="form-error switch-error" role="alert">
          {error}
        </div>
      )}
      <div className="sheet-foot">
        {current !== DEFAULT_PORT && (
          <button type="button" className="linkbtn" disabled={busy} onClick={() => setText(String(DEFAULT_PORT))}>
            Back to {DEFAULT_PORT}
          </button>
        )}
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={close}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={!ready || busy} onClick={() => void confirm()}>
          {busy ? 'Saving…' : 'Change port and restart'}
        </button>
      </div>
    </Modal>
  );
}
