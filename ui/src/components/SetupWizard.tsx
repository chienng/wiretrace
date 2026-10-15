import { useEffect, useRef, useState } from 'react';
import { copyText } from '../clipboard';
import { useNow } from '../hooks';
import { certificateSteps } from '../logic/certificate';
import { devicePill, STATE_LABELS } from '../logic/device';
import {
  deviceChoice,
  deviceFromTarget,
  deviceLogSteps,
  DEVICES,
  emulatorConf,
  endpointOf,
  firstApiFlow,
  needsProxy,
  NO_CONNECTION_HINT_S,
  proxyCommand,
  proxySteps,
  tunnelSteps,
  type DeviceKind,
  type Step,
} from '../logic/setup';
import { useDispatch, useStore } from '../store';
import type { AppState } from '../types';
import { Modal } from './Modal';

function Qr({ text }: { text: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    import('qrcode')
      .then((QR) => {
        const canvas = ref.current;
        if (cancelled || !canvas) return;
        return QR.toCanvas(canvas, text, { width: 202, margin: 0, errorCorrectionLevel: 'L' });
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [text]);
  if (failed) return <div className="qr note warn">The QR code could not be drawn. Copy the configuration text instead.</div>;
  return (
    <div className="qr">
      <canvas ref={ref} width={202} height={202} role="img" aria-label="WireGuard configuration QR code" />
    </div>
  );
}

type Copy = (text: string, what: string) => void;

function Code({ code, copy, what = 'Command' }: { code: string; copy: Copy; what?: string }) {
  return (
    <div className="addr">
      <span className="kbd">{code}</span>
      <button type="button" className="btn small" onClick={() => copy(code, what)}>
        Copy
      </button>
    </div>
  );
}

function Steps({ steps, copy }: { steps: Step[]; copy: Copy }) {
  return (
    <ol className="instr">
      {steps.map((s) => (
        <li key={s.text}>
          {s.text}
          {s.code && <Code code={s.code} copy={copy} />}
        </li>
      ))}
    </ol>
  );
}

function DeviceCards({ kind, onPick }: { kind: DeviceKind; onPick: (k: DeviceKind) => void }) {
  return (
    <div className="devcards" role="radiogroup" aria-label="Device type">
      {DEVICES.map((d) => (
        <button key={d.id} type="button" role="radio" aria-checked={kind === d.id} className={`devcard${kind === d.id ? ' on' : ''}`} onClick={() => onPick(d.id)}>
          <span className="lbl">{d.label}</span>
          <span className="sub">{d.sub}</span>
        </button>
      ))}
    </div>
  );
}

function Restart({ preset, kind, copy, why }: { preset: string; kind: DeviceKind; copy: Copy; why: string }) {
  return (
    <div className="hintbox">
      <p>{why}</p>
      <p>Stop Wiretrace with Ctrl+C in its Terminal and start it again in proxy mode:</p>
      <Code code={proxyCommand(preset, kind)} copy={copy} />
    </div>
  );
}

/** "Waiting for the device…" until the first connection, then "Connected"; the guest Wi-Fi hint after 30 s. */
function Connection({ state, since }: { state: AppState; since: number }) {
  const now = useNow(1000);
  if (state.device_seen_at !== null) {
    return (
      <div className="okbox">
        <b>Connected</b>
        <div>The device reached Wiretrace. Next, install the certificate.</div>
      </div>
    );
  }
  const late = now - since >= NO_CONNECTION_HINT_S * 1000;
  return (
    <>
      <div className="waiting">
        <span className="spinner" />
        <div>
          <b>Waiting for the device…</b>
          <div>This changes to "Connected" as soon as the first packet arrives.</div>
        </div>
      </div>
      {late && (
        <p className="tip">
          No connection after {NO_CONNECTION_HINT_S} seconds? Phone and Mac may be on a guest Wi-Fi that blocks
          device-to-device traffic. Try another Wi-Fi network or a hotspot, and check that the Mac's firewall lets
          mitmproxy accept connections.
        </p>
      )}
    </>
  );
}

function ConnectStep({ state, kind, setKind, copy }: { state: AppState; kind: DeviceKind; setKind: (k: DeviceKind) => void; copy: Copy }) {
  const [since] = useState(() => Date.now());
  const wg = state.mode === 'wireguard';
  const name = deviceChoice(kind).label;
  const macIp = state.mac_ip ?? '<Mac IP>';

  if (wg && needsProxy(kind)) {
    return (
      <>
        <h4>Connect the {name}</h4>
        <p className="lead">The Simulator cannot run the WireGuard app; it uses this Mac's proxy instead.</p>
        <DeviceCards kind={kind} onPick={setKind} />
        <Restart preset={state.preset} kind={kind} copy={copy} why="Wiretrace was started in WireGuard mode, which the Simulator cannot use." />
      </>
    );
  }

  if (!wg) {
    const address = `${macIp}:${state.proxy_port}`;
    const local = kind === 'ios-sim' || kind === 'android-emu';
    return (
      <>
        <h4>Connect the {name} through the Mac's proxy</h4>
        <p className="lead">{local ? 'The proxy listens on this Mac.' : 'Both devices must be on the same Wi-Fi network.'}</p>
        <DeviceCards kind={kind} onPick={setKind} />
        {!local && (
          <div className="addr">
            <span className="kbd big">{address}</span>
            <button type="button" className="btn small" onClick={() => copy(address, 'Address')}>
              Copy
            </button>
          </div>
        )}
        <Steps steps={proxySteps(kind, macIp, state.proxy_port)} copy={copy} />
        <Connection state={state} since={since} />
      </>
    );
  }

  const conf = state.wireguard_conf;
  const shown = conf && kind === 'android-emu' ? emulatorConf(conf) : conf;
  const endpoint = endpointOf(shown);
  return (
    <>
      <h4>Connect your {name} through WireGuard</h4>
      <p className="lead">Works on any Wi-Fi network and also captures apps that ignore the phone's proxy setting.</p>
      <DeviceCards kind={kind} onPick={setKind} />
      <div className="connect">
        <div>
          {shown ? <Qr text={shown} /> : <div className="qr note">The WireGuard configuration is not available yet.</div>}
          {endpoint && (
            <div className="qrcap">
              {kind === 'android-emu' ? 'Emulator address' : 'Mac address'} {endpoint.host} · UDP {endpoint.port}
            </div>
          )}
        </div>
        <div>
          <Steps steps={tunnelSteps(kind)} copy={copy} />
          <Connection state={state} since={since} />
        </div>
      </div>
      {shown && (
        <div className="confbox">
          <div className="confhead">
            <span className="sec-h">Configuration text</span>
            <button type="button" className="btn small" onClick={() => copy(shown, 'Configuration')}>
              Copy
            </button>
          </div>
          <pre className="conf">{shown}</pre>
          <div className="tip">This text contains the device's private key. Do not share it.</div>
        </div>
      )}
    </>
  );
}

function VerifyStep({ state, onCertificate }: { state: AppState; onCertificate: () => void }) {
  const { flows } = useStore();
  const first = firstApiFlow(flows);
  return (
    <>
      <h4>Verify traffic</h4>
      <p className="lead">Open the app on the device and use it. Requests to the preset's API hosts appear in the Traffic view.</p>
      {first ? (
        <div className="okbox">
          <b>Traffic received</b>
          <div>
            First request: {first.method} {first.host}
            {first.path}
          </div>
        </div>
      ) : state.tls_failures > 0 ? (
        <div className="hintbox bad" role="alert">
          <p>
            <b>The device does not trust the certificate yet.</b> Its HTTPS connections to the API hosts fail ({state.tls_failures}{' '}
            {state.tls_failures === 1 ? 'failure' : 'failures'} so far).
          </p>
          <button type="button" className="linkbtn" onClick={onCertificate}>
            Back to Install certificate →
          </button>
        </div>
      ) : (
        <div className="waiting">
          <span className="spinner" />
          <div>
            <b>Waiting for the first request…</b>
            <div>This turns green as soon as a request to an API host arrives.</div>
          </div>
        </div>
      )}
    </>
  );
}

function DeviceLogsStep({ state, kind }: { state: AppState; kind: DeviceKind }) {
  const target = deviceChoice(kind).target;
  const pill = devicePill(state);
  const status = state.device_status;
  return (
    <>
      <h4>Device logs</h4>
      <p className="lead">Optional. The device's own log, next to the traffic. App logs from a QA build need no cable.</p>
      {state.device_logs ? (
        <div className={pill.tone === 'ok' ? 'okbox' : pill.tone === 'bad' ? 'hintbox bad' : 'hintbox'}>
          <b>
            {pill.text}: {status ? STATE_LABELS[status.state] : 'starting'}
          </b>
          <div>
            {status?.message ? `${status.message}. ` : ''}
            The same state is shown in the title bar and in the Logs view.
          </div>
        </div>
      ) : (
        <div className="hintbox">
          <p>
            <b>Device logs are off</b>
            {state.device_logs_off ? `: ${state.device_logs_off}.` : '.'}
          </p>
          {state.target !== target && (
            <p>
              They are collected only when Wiretrace is started with <span className="kbd">--target {target}</span>.
            </p>
          )}
        </div>
      )}
      <ol className="instr gap-top">
        {deviceLogSteps(kind).map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
    </>
  );
}

const STEP_IDS = [1, 2, 3, 4, 5] as const;
type StepId = (typeof STEP_IDS)[number];

export function SetupWizard() {
  const { appState, flows } = useStore();
  const dispatch = useDispatch();
  const [step, setStep] = useState<StepId>(1);
  const [kind, setKind] = useState<DeviceKind>(() => deviceFromTarget(appState?.target ?? ''));
  const [alt, setAlt] = useState(false);
  const close = () => dispatch({ type: 'ui', patch: { dialog: null } });
  if (!appState) return null;

  const wg = appState.mode === 'wireguard';
  const proxyAlt = alt && wg && step === 2 && !needsProxy(kind);
  const copy: Copy = (text, what) => {
    void copyText(text).then((ok) => dispatch({ type: 'toast', text: ok ? `${what} copied` : 'Copy failed' }));
  };
  const rail: { id: StepId; label: string; sub: string; done: boolean }[] = [
    { id: 1, label: 'Choose device', sub: `${deviceChoice(kind).label}`, done: step > 1 },
    { id: 2, label: 'Connect tunnel', sub: wg && !needsProxy(kind) ? 'WireGuard' : 'Wi-Fi proxy', done: appState.device_seen_at !== null },
    { id: 3, label: 'Install certificate', sub: 'Once per device', done: firstApiFlow(flows) !== null },
    { id: 4, label: 'Verify traffic', sub: 'Open the app', done: firstApiFlow(flows) !== null },
    { id: 5, label: 'Device logs', sub: 'Optional, USB', done: appState.device_logs !== null },
  ];
  const stepClass = (s: (typeof rail)[number]) => (s.id === step ? 'cur' : s.done ? 'done' : 'todo');
  const next = rail[step]?.label;
  const certTarget = deviceChoice(kind).target;

  return (
    <Modal title="Connect a test device" onClose={close} wide>
      <div className="wizard">
        <div className="steps">
          {rail.map((s) => (
            <button key={s.id} type="button" className={`step ${stepClass(s)}`} aria-current={s.id === step ? 'step' : undefined} onClick={() => setStep(s.id)}>
              <span className="num">{stepClass(s) === 'done' ? '✓' : s.id}</span>
              <span>
                <span className="lbl">{s.label}</span>
                <br />
                <span className="sub">{s.sub}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="wiz-main">
          {step === 1 && (
            <>
              <h4>Which device do you test on?</h4>
              <p className="lead">The next steps are for this kind of device. Started with --target {appState.target}.</p>
              <DeviceCards kind={kind} onPick={setKind} />
            </>
          )}
          {step === 2 && <ConnectStep state={appState} kind={kind} setKind={setKind} copy={copy} />}
          {step === 3 && (
            <>
              <h4>Install the certificate</h4>
              <p className="lead">Needed once per device, so it trusts Wiretrace for HTTPS.</p>
              {certificateSteps(certTarget, wg).map((group) => (
                <Steps key={group.platform} steps={group.steps} copy={copy} />
              ))}
            </>
          )}
          {step === 4 && <VerifyStep state={appState} onCertificate={() => setStep(3)} />}
          {step === 5 && <DeviceLogsStep state={appState} kind={kind} />}
          {proxyAlt && (
            <Restart preset={appState.preset} kind={kind} copy={copy} why="Wiretrace cannot change from WireGuard to the Wi-Fi proxy while it runs." />
          )}
          <div className="wiz-foot">
            {wg && step === 2 && !needsProxy(kind) && (
              <button type="button" className="linkbtn" aria-expanded={alt} onClick={() => setAlt(!alt)}>
                Use Wi-Fi proxy instead
              </button>
            )}
            <span className="spacer" />
            {step > 1 && (
              <button type="button" className="btn" onClick={() => setStep((step - 1) as StepId)}>
                Back
              </button>
            )}
            {step < 5 ? (
              <button type="button" className="btn primary" onClick={() => setStep((step + 1) as StepId)}>
                Next: {next}
              </button>
            ) : (
              <button type="button" className="btn primary" onClick={close}>
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
