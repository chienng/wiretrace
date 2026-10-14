import { useState } from 'react';
import { api, ApiError } from '../api';
import { useDispatch } from '../store';
import type { ReportResult } from '../types';
import { Modal } from './Modal';

export function ReportDialog() {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const close = () => dispatch({ type: 'ui', patch: { dialog: null } });

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    setRevealError(null);
    try {
      setResult(await api.report());
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setError('A report is already being written');
      else setError(e instanceof ApiError ? e.message : 'The report could not be created.');
    } finally {
      setBusy(false);
    }
  };

  const reveal = async () => {
    setRevealError(null);
    try {
      await api.reveal();
    } catch (e) {
      setRevealError(e instanceof ApiError ? e.message : 'Could not open Finder.');
    }
  };

  return (
    <Modal
      title="Report bug"
      lead="Writes a zip with the requests saved so far in this session, plus the device and app logs."
      onClose={close}
    >
      {!result && (
        <p className="note-block">Sensitive headers and fields are masked in the report. Nothing is sent anywhere.</p>
      )}
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      {result && (
        <div className="report-result">
          <div className={result.ok ? 'report-ok' : 'form-error'}>{result.message}</div>
          {result.zip && (
            <div className="kv2 wide">
              <span>Report</span>
              <span>{result.zip}</span>
              <span>Requests</span>
              <span>
                {result.requests}
                {result.failed > 0 ? ` (${result.failed} failed)` : ''}
              </span>
              <span>Device log lines</span>
              <span>{result.device_lines}</span>
              <span>App log lines</span>
              <span>{result.app_lines}</span>
            </div>
          )}
          <div className="tip">Log lines are masked by pattern only; check them before sharing.</div>
          {revealError && (
            <div className="form-error" role="alert">
              {revealError}
            </div>
          )}
        </div>
      )}
      <div className="sheet-foot">
        <span className="spacer" />
        <button type="button" className="btn" onClick={close}>
          Close
        </button>
        {result?.zip && (
          <button type="button" className="btn" onClick={() => void reveal()}>
            Show in Finder
          </button>
        )}
        <button type="button" className="btn primary" disabled={busy} onClick={() => void run()}>
          {busy ? 'Creating…' : result ? 'Create again' : 'Create report'}
        </button>
      </div>
    </Modal>
  );
}
