import { devicePill } from '../logic/device';
import { formatElapsed } from '../logic/format';
import { isCrash } from '../logic/logs';
import { useNow } from '../hooks';
import { useData, useDispatch, useStore } from '../store';
import { useMemo } from 'react';

interface Props {
  newCount: number;
}

function Recording({ startedAt, reconnecting }: { startedAt: number; reconnecting: boolean }) {
  const now = useNow(1000);
  if (reconnecting) return <span className="pill wait">Reconnecting…</span>;
  return <span className="rec">Recording · {formatElapsed(now / 1000 - startedAt)}</span>;
}

export function TitleBar({ newCount }: Props) {
  const { appState, ui, phase, flows } = useStore();
  const { logs, viewing } = useData();
  const dispatch = useDispatch();
  const patch = (p: Partial<typeof ui>) => dispatch({ type: 'ui', patch: p });
  const crashes = useMemo(() => {
    const shown = (source: 'device' | 'app') => (viewing ? -Infinity : ui.clearedSeq[source]);
    return (
      logs.device.filter((l) => l.seq > shown('device') && isCrash(l)).length +
      logs.app.filter((l) => l.seq > shown('app') && isCrash(l)).length
    );
  }, [logs, ui.clearedSeq, viewing]);
  const offWhileViewing = viewing ? 'Off while a previous session is open' : undefined;
  const paused = ui.frozen !== null;
  const rulesOn = appState?.rules_on ?? 0;
  const seen = !!appState && (appState.flow_count > 0 || flows.length > 0);
  const pill = appState ? devicePill(appState) : null;

  return (
    <header className="titlebar">
      <span className="title">Wiretrace</span>
      <div className="seg sm" role="tablist" aria-label="View">
        <button type="button" role="tab" aria-selected={ui.view === 'traffic'} className={ui.view === 'traffic' ? 'on' : ''} onClick={() => patch({ view: 'traffic' })}>
          Traffic
        </button>
        <button type="button" role="tab" aria-selected={ui.view === 'logs'} className={ui.view === 'logs' ? 'on' : ''} onClick={() => patch({ view: 'logs' })}>
          Logs{crashes > 0 && <span className="c">{crashes} {crashes === 1 ? 'crash' : 'crashes'}</span>}
        </button>
      </div>
      {appState && <Recording startedAt={appState.started_at} reconnecting={phase === 'reconnecting'} />}
      {ui.view === 'traffic' && !viewing && (
        <>
          <button type="button" className="btn small" onClick={() => dispatch({ type: paused ? 'resume' : 'pause' })} aria-pressed={paused}>
            {paused ? `Resume${newCount > 0 ? ` · ${newCount} new` : ''}` : 'Pause'}
          </button>
        </>
      )}
      {ui.view !== 'rules' && !viewing && (
        <button type="button" className="btn small" onClick={() => dispatch({ type: 'clear' })} title="Hide what is listed now">
          Clear
        </button>
      )}
      <span className="spacer" />
      {appState && pill && (
        <>
          <span className="static-select" title="Preset">Preset: {appState.preset}</span>
          <span className={`pill ${seen ? 'ok' : 'wait'}`} title="Target and mode">
            {appState.target} · {appState.mode === 'wireguard' ? 'WireGuard' : 'Proxy'}
          </span>
          <span className={`pill ${pill.tone}`} title={pill.title}>
            {pill.text}
          </span>
        </>
      )}
      <button
        type="button"
        className={`btn${ui.view === 'rules' ? ' toggled' : ''}`}
        aria-pressed={ui.view === 'rules'}
        disabled={!!viewing}
        title={offWhileViewing}
        onClick={() => patch({ view: ui.view === 'rules' ? 'traffic' : 'rules' })}
      >
        Rules{rulesOn > 0 && <span className="count">{rulesOn} active</span>}
      </button>
      <button type="button" className="btn" disabled={!!viewing} title={offWhileViewing} onClick={() => patch({ dialog: 'setup' })}>
        Setup
      </button>
      <button type="button" className="btn primary" onClick={() => dispatch({ type: 'openReport' })}>
        Report bug
      </button>
    </header>
  );
}
