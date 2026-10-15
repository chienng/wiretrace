import { useEffect, useRef, useState } from 'react';
import { devicePill, LOG_SOURCES, sourceInfo, STATE_LABELS } from '../logic/device';
import type { AppState } from '../types';

interface Props {
  state: AppState;
  appLines: number;
}

/** What the collector is doing, and how to collect another source: it does not switch the collector. */
export function DevicePicker({ state, appLines }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const pill = devicePill(state);
  const active = sourceInfo(state.device_logs);
  const status = state.device_status;
  const others = LOG_SOURCES.filter((s) => s.id !== active?.id);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const noDevice = !active || !status || status.state === 'waiting' || status.state === 'stopped' || status.state === 'error';

  return (
    <div className="picker" ref={box}>
      <button type="button" className={`btn small picker-btn ${pill.tone}`} aria-expanded={open} title={pill.title} onClick={() => setOpen(!open)}>
        <span className="dot" />
        {pill.text}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="pop" role="dialog" aria-label="Log sources">
          <div className="pop-h">Collecting now</div>
          {active ? (
            <div className="src on">
              <div className="src-main">
                <div className="name">{status?.model ? `${status.model}${status.os ? ` · ${status.os}` : ''}` : active.name}</div>
                <div className="sub">
                  {active.tool}
                  {status?.message ? ` · ${status.message}` : ''}
                </div>
              </div>
              <span className={`state ${pill.tone}`}>{status ? STATE_LABELS[status.state] : 'Starting'}</span>
            </div>
          ) : (
            <div className="src">
              <div className="src-main">
                <div className="name">No device log</div>
                <div className="sub">{state.device_logs_off ?? 'Device logs are off for this session.'}</div>
              </div>
            </div>
          )}
          <div className="pop-h">Other sources</div>
          {others.map((s) => (
            <div className="src" key={s.id}>
              <div className="src-main">
                <div className="name">{s.name}</div>
                <div className="sub">
                  {s.tool} · start with <code>--target {s.target}</code>
                </div>
              </div>
            </div>
          ))}
          <div className="pop-h">Over the network</div>
          <div className="src">
            <div className="src-main">
              <div className="name">App logs from the QA build</div>
              <div className="sub">POST qa-logs.internal · no cable needed</div>
            </div>
            <span className={`state ${appLines > 0 ? 'ok' : 'off'}`}>{appLines.toLocaleString('en-US')} lines</span>
          </div>
          {noDevice && (
            <div className="pop-foot">
              Device not listed? Check the USB cable, "Trust This Computer" on the iPhone, or USB debugging on Android. The
              Simulator must be booted.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
