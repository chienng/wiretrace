import { api, ApiError } from '../api';
import markUrl from '../assets/mark.svg';
import { devicePill } from '../logic/device';
import { formatElapsed, formatVersion } from '../logic/format';
import { isCrash } from '../logic/logs';
import { OFF_WHILE_VIEWING, presetMenuState, presetRowsState } from '../logic/presets';
import { useNow } from '../hooks';
import { useData, useDispatch, useStore } from '../store';
import type { PresetInfo } from '../types';
import { useEffect, useMemo, useRef, useState } from 'react';
import { PresetSheet } from './PresetSheet';
import { SwitchPresetDialog } from './SwitchPresetDialog';

interface Props {
  newCount: number;
}

/** The preset label: a menu of `presets/*.yaml`. Another preset is confirmed in a dialog first; the sheet edits them. */
function PresetMenu({ current, target, viewing }: { current: string; target: string; viewing: string | null }) {
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState<PresetInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<PresetInfo | null>(null);
  /** The sheet is open: on this preset, or on a blank form for null. */
  const [sheet, setSheet] = useState<{ initial: string | null } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const menu = presetMenuState(viewing);
  const rows = presetRowsState(viewing);

  useEffect(() => {
    if (viewing) {
      setOpen(false);
      setChosen(null);
      setSheet(null);
    }
  }, [viewing]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setError(null);
    api
      .presets()
      .then((list) => live && setPresets(list))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Could not list the presets'));
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => {
      live = false;
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const choose = (preset: PresetInfo) => {
    setOpen(false);
    if (preset.name !== current) setChosen(preset);
  };

  const openSheet = (initial: string | null) => {
    setOpen(false);
    setSheet({ initial });
  };

  return (
    <div className="picker" ref={box}>
      <button
        type="button"
        className="static-select picker-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={menu.disabled}
        title={menu.title}
        onClick={() => setOpen(!open)}
      >
        Preset: {current}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="pop" role="menu" aria-label="Presets">
          <div className="pop-h">Presets</div>
          {error && <div className="pop-foot plain">{error}</div>}
          {!error && !presets && <div className="pop-foot plain">Loading…</div>}
          {presets?.map((preset) => (
            <button
              type="button"
              role="menuitemradio"
              aria-checked={preset.name === current}
              className={`src pick${preset.name === current ? ' on' : ''}`}
              key={preset.name}
              onClick={() => choose(preset)}
            >
              <span className="src-main">
                <span className="name">{preset.name}</span>
                <span className="sub">{preset.api_hosts.length ? preset.api_hosts.join(', ') : 'Does not load'}</span>
              </span>
              {preset.name === current && <span className="state ok">In use</span>}
            </button>
          ))}
          <div className="pop-rows">
            <button type="button" role="menuitem" className="pop-row" disabled={rows.disabled} title={rows.title} onClick={() => openSheet(current)}>
              Edit presets…
            </button>
            <button type="button" role="menuitem" className="pop-row" disabled={rows.disabled} title={rows.title} onClick={() => openSheet(null)}>
              New preset…
            </button>
          </div>
          <div className="pop-foot plain">Another preset saves this session and starts a new one. The phone stays connected.</div>
        </div>
      )}
      {chosen && <SwitchPresetDialog preset={chosen} target={target} onClose={() => setChosen(null)} />}
      {sheet && <PresetSheet current={current} initial={sheet.initial} onClose={() => setSheet(null)} />}
    </div>
  );
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
  const offWhileViewing = viewing ? OFF_WHILE_VIEWING : undefined;
  const paused = ui.frozen !== null;
  const rulesOn = appState?.rules_on ?? 0;
  const seen = !!appState && (appState.flow_count > 0 || flows.length > 0);
  const pill = appState ? devicePill(appState) : null;
  const version = formatVersion(appState?.version);

  return (
    <header className="titlebar">
      <span className="title">
        <img className="mark" src={markUrl} alt="" width={24} height={24} />
        <span className="name">
          Wiretrace
          {/* Always rendered, so the name does not move up once /api/state arrives. */}
          <span className="version" title={version ? 'Wiretrace version' : undefined}>
            {version}
          </span>
        </span>
      </span>
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
          <PresetMenu current={appState.preset} target={appState.target} viewing={viewing} />
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
