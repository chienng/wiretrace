import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import { useDispatch, useStore } from '../store';
import type { SessionInfo } from '../types';
import { openSession } from '../viewing';

function when(ts: number | null): string {
  if (ts === null) return 'Unknown time';
  return new Date(ts * 1000).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function counts(s: SessionInfo): string {
  const parts = [s.requests === null ? 'requests —' : `${s.requests.toLocaleString('en-US')} requests`];
  if (s.device_lines !== null || s.app_lines !== null) {
    parts.push(`${((s.device_lines ?? 0) + (s.app_lines ?? 0)).toLocaleString('en-US')} log lines`);
  }
  return parts.join(' · ');
}

/** The previous sessions (not the live one), newest first; `reload` lists them again. */
export function usePreviousSessions() {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api
      .sessions()
      .then((all) => {
        setSessions(all.filter((s) => !s.live));
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Could not list the sessions'));
  }, []);
  useEffect(reload, [reload]);
  return { sessions, error, reload };
}

/** Opening one shows its traffic and logs read-only; the live capture goes on. */
export function SessionsList({ sessions, error }: { sessions: SessionInfo[] | null; error: string | null }) {
  const { view } = useStore();
  const dispatch = useDispatch();
  const [opening, setOpening] = useState<string | null>(null);

  if (error) return <div className="side-i muted">{error}</div>;
  if (sessions === null) return <div className="side-i muted">Loading…</div>;
  if (sessions.length === 0) return <div className="side-i muted">No previous session</div>;

  const open = async (name: string) => {
    setOpening(name);
    await openSession(dispatch, name);
    setOpening(null);
  };

  return (
    <div className="sessions">
      {sessions.map((s) => (
        <button
          key={s.name}
          type="button"
          className={`sess${view?.name === s.name ? ' active' : ''}`}
          disabled={opening !== null}
          aria-current={view?.name === s.name}
          onClick={() => void open(s.name)}
          title={s.name}
        >
          <span className="l1">
            {when(s.started_at)}
            {opening === s.name && <span className="busy">Opening…</span>}
          </span>
          <span className="l2">
            {s.preset || '—'} · {s.target || '—'}
          </span>
          <span className="l2">{counts(s)}</span>
        </button>
      ))}
    </div>
  );
}
