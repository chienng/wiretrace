import { api, ApiError } from '../api';
import markUrl from '../assets/mark.svg';
import { APP_STOP_TIP } from '../logic/appHint';
import { devicePill } from '../logic/device';
import { deviceLabel, deviceLogsLine, deviceMenuState, modeLabel } from '../logic/devices';
import { formatElapsed, formatVersion } from '../logic/format';
import { isCrash } from '../logic/logs';
import { deviceMenuTitle } from '../logic/proxyDevices';
import { PAUSED_LABEL, PAUSED_TIP, recordingPill } from '../logic/recording';
import { OFF_WHILE_VIEWING, presetMenuState, presetRowsState } from '../logic/presets';
import { useNow } from '../hooks';
import { useData, useDispatch, useStore } from '../store';
import type { AppState, DeviceInfo, PresetInfo } from '../types';
import { useEffect, useMemo, useRef, useState } from 'react';
import { PresetSheet } from './PresetSheet';
import { SwitchDeviceDialog } from './SwitchDeviceDialog';
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

/** The device label: a menu of the targets this session can switch to. Another device is confirmed in a dialog first. */
function DeviceMenu({ state, seen, viewing }: { state: AppState; seen: boolean; viewing: string | null }) {
  const [open, setOpen] = useState(false);
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<DeviceInfo | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const menu = deviceMenuState(viewing);

  useEffect(() => {
    if (viewing) {
      setOpen(false);
      setChosen(null);
    }
  }, [viewing]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setError(null);
    api
      .devices()
      .then((list) => live && setDevices(list))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Could not list the devices'));
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

  const choose = (device: DeviceInfo) => {
    setOpen(false);
    if (device.target !== state.target) setChosen(device);
  };

  return (
    <div className="picker" ref={box}>
      <button
        type="button"
        className={`pill ${seen ? 'ok' : 'wait'} picker-btn`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={menu.disabled}
        title={deviceMenuTitle(menu.title, state, viewing)}
        onClick={() => setOpen(!open)}
      >
        {deviceLabel(state.target)} · {modeLabel(state.mode)}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="pop" role="menu" aria-label="Devices">
          <div className="pop-h">Devices</div>
          {error && <div className="pop-foot plain">{error}</div>}
          {!error && !devices && <div className="pop-foot plain">Loading…</div>}
          {devices?.map((device) => {
            const current = device.target === state.target;
            return (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={current}
                className={`src pick${current ? ' on' : ''}`}
                key={device.target}
                disabled={!device.allowed && !current}
                onClick={() => choose(device)}
              >
                <span className="src-main">
                  <span className="name">{device.label}</span>
                  <span className="sub">{device.allowed || current ? deviceLogsLine(device.device_logs) : device.why_not}</span>
                </span>
                {current && <span className="state ok">In use</span>}
              </button>
            );
          })}
          <div className="pop-foot plain">Another device saves this session and starts a new one with the same preset.</div>
        </div>
      )}
      {chosen && <SwitchDeviceDialog device={chosen} state={state} onClose={() => setChosen(null)} />}
    </div>
  );
}

function Recording({ startedAt, reconnecting, paused, fromApp }: { startedAt: number; reconnecting: boolean; paused: boolean; fromApp: boolean }) {
  const now = useNow(1000);
  const pill = recordingPill(reconnecting, paused);
  if (pill === 'reconnecting') return <span className="pill wait">Reconnecting…</span>;
  if (pill === 'paused') {
    return (
      <span className="pill wait" title={PAUSED_TIP}>
        {PAUSED_LABEL}
      </span>
    );
  }
  return (
    <span className="rec" title={fromApp ? APP_STOP_TIP : undefined}>
      Recording · {formatElapsed(now / 1000 - startedAt)}
    </span>
  );
}

/** Requests held at a breakpoint now, live session only (spec 022, slice D). */
function PausedChip({ count }: { count: number }) {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const continueAll = async () => {
    setBusy(true);
    try {
      const { continued } = await api.continueAll();
      dispatch({ type: 'toast', text: `${continued} paused ${continued === 1 ? 'request' : 'requests'} sent unchanged` });
    } catch (e) {
      dispatch({ type: 'toast', text: e instanceof ApiError ? e.message : 'Could not reach Wiretrace' });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="paused-chip">
      <span>⏸ {count} paused</span>
      <button type="button" className="btn small" disabled={busy} onClick={() => void continueAll()} title="Every paused request goes on unchanged">
        Continue all
      </button>
    </span>
  );
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
      <div className="tb-group">
        <span className="title">
          <img className="mark" src={markUrl} alt="" width={36} height={36} />
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
        {appState && (
          <Recording
            startedAt={appState.started_at}
            reconnecting={phase === 'reconnecting'}
            paused={paused && !viewing}
            fromApp={appState.from_app}
          />
        )}
        {ui.view === 'traffic' && !viewing && (
          <>
            <button
              type="button"
              className={`btn small${paused ? ' toggled' : ''}`}
              onClick={() => dispatch({ type: paused ? 'resume' : 'pause' })}
              aria-pressed={paused}
            >
              {paused ? `Resume${newCount > 0 ? ` · ${newCount} new` : ''}` : 'Pause'}
            </button>
          </>
        )}
        {ui.view !== 'rules' && !viewing && (
          <button type="button" className="btn small" onClick={() => dispatch({ type: 'clear' })} title="Hide what is listed now">
            Clear
          </button>
        )}
        {(appState?.paused_count ?? 0) > 0 && <PausedChip count={appState?.paused_count ?? 0} />}
      </div>
      <div className="tb-group end">
        {appState && pill && (
          <>
            <PresetMenu current={appState.preset} target={appState.target} viewing={viewing} />
            <DeviceMenu state={appState} seen={seen} viewing={viewing} />
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
      </div>
    </header>
  );
}
