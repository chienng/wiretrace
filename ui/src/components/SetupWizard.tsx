import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { api, ApiError } from '../api';
import { copyText } from '../clipboard';
import { download } from '../download';
import { useNow } from '../hooks';
import { certificateSteps } from '../logic/certificate';
import { devicePill, STATE_LABELS } from '../logic/device';
import {
  appChecks,
  appHint,
  beforeYouStart,
  CERTIFICATE_WHY,
  CONF_FILE,
  confFileSteps,
  confOpen,
  confTitle,
  connectWhy,
  deviceChoice,
  deviceFromTarget,
  deviceLogSteps,
  DEVICES,
  emulatorConf,
  endpointOf,
  firstApiFlow,
  loadChoice,
  needsProxy,
  nextLabel,
  nextTime,
  NO_CONNECTION_HINT_S,
  noPageHint,
  proxyCommand,
  proxySteps,
  setupSummary,
  STEP_LABELS,
  stepDone,
  storeChoice,
  STORE_BUILD_NOTE,
  trustChecklist,
  trustHint,
  tunnelSteps,
  usesTunnel,
  wireguardSteps,
  wizardSwitch,
  type ConnectionChoice,
  type DeviceKind,
  type Step,
  type StepKey,
  type WizardSwitch,
} from '../logic/setup';
import { browserStorage as storage } from '../storage';
import { useData, useDispatch, useStore } from '../store';
import type { AppState, DeviceInfo } from '../types';
import { Modal } from './Modal';
import { SwitchDeviceDialog } from './SwitchDeviceDialog';

const CHOICES: readonly { id: ConnectionChoice; label: string }[] = [
  { id: 'proxy', label: 'Wi-Fi proxy' },
  { id: 'wireguard', label: 'WireGuard' },
];

/** Offers to switch the session to the chosen card's device, through the title bar's confirm dialog. */
function SwitchBox({ box, onUse }: { box: WizardSwitch; onUse: (device: DeviceInfo) => void }) {
  const { device } = box;
  return (
    <div className="hintbox gap-top">
      <p>{box.note}</p>
      <button type="button" className="btn primary small" disabled={box.disabled} title={box.title} onClick={() => device && onUse(device)}>
        {box.button}
      </button>
      {box.disabled && box.title && <p className="tip">{box.title}</p>}
    </div>
  );
}

function Qr({ text, onFail }: { text: string; onFail: () => void }) {
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
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
        onFail();
      });
    return () => {
      cancelled = true;
    };
  }, [text, onFail]);
  if (failed) return <div className="qr note warn">The QR code could not be drawn. Use {CONF_FILE} below instead.</div>;
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

function Steps({ steps, copy, className = '' }: { steps: Step[]; copy: Copy; className?: string }) {
  return (
    <ol className={`instr ${className}`.trim()}>
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

function ConnectionSwitch({ choice, onChoose }: { choice: ConnectionChoice; onChoose: (c: ConnectionChoice) => void }) {
  return (
    <div className="addr">
      <div className="seg" role="radiogroup" aria-label="How the device connects">
        {CHOICES.map((c) => (
          <button key={c.id} type="button" role="radio" aria-checked={choice === c.id} className={choice === c.id ? 'on' : ''} onClick={() => onChoose(c.id)}>
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Checklist({ items }: { items: { label: string; done: boolean }[] }) {
  return (
    <ul className="checklist">
      {items.map((i) => (
        <li key={i.label} className={i.done ? 'done' : undefined}>
          <span className="tick" aria-hidden="true">
            {i.done ? '✓' : ''}
          </span>
          {i.label}
          <span className="sr">{i.done ? ' (done)' : ' (not yet)'}</span>
        </li>
      ))}
    </ul>
  );
}

function NotTrusted({ failures, note, onBack }: { failures: number; note?: string; onBack?: () => void }) {
  return (
    <div className="hintbox bad" role="alert">
      <p>
        <b>The device does not trust the certificate yet.</b> Its HTTPS connections to the API hosts fail ({failures}{' '}
        {failures === 1 ? 'failure' : 'failures'} so far).
      </p>
      {note && <p>{note}</p>}
      {onBack && (
        <button type="button" className="linkbtn" onClick={onBack}>
          Back to {STEP_LABELS.trust} →
        </button>
      )}
    </div>
  );
}

function BeforeYouStart({ kind, wireguard }: { kind: DeviceKind; wireguard: boolean }) {
  const { needs, once } = beforeYouStart(kind, wireguard);
  return (
    <div className="hintbox">
      <p>
        <b>Before you start</b>, you need:
      </p>
      <ul className="needs">
        {needs.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      <p>{once}</p>
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
        <div>The device reached Wiretrace. Next, make it trust Wiretrace.</div>
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

function ConnectStep({
  state,
  kind,
  setKind,
  choice,
  onChoose,
  copy,
}: {
  state: AppState;
  kind: DeviceKind;
  setKind: (k: DeviceKind) => void;
  choice: ConnectionChoice;
  onChoose: (c: ConnectionChoice) => void;
  copy: Copy;
}) {
  const [since] = useState(() => Date.now());
  const [confShown, setConfShown] = useState(false);
  const [qrFailed, setQrFailed] = useState(false);
  const onQrFail = useCallback(() => setQrFailed(true), []);
  const wg = wireguardSteps(state.mode, choice, kind);
  const choosable = state.mode === 'both' && !needsProxy(kind);
  const name = deviceChoice(kind).label;
  const macIp = state.mac_ip ?? '<Mac IP>';

  if (state.mode === 'wireguard' && needsProxy(kind)) {
    return (
      <>
        <h4>Connect the {name} to this Mac</h4>
        <p className="lead">{connectWhy(kind, true)}</p>
        <DeviceCards kind={kind} onPick={setKind} />
        <Restart preset={state.preset} kind={kind} copy={copy} why="Wiretrace was started for the WireGuard VPN app, which the Simulator cannot use." />
      </>
    );
  }

  if (!wg) {
    const address = `${macIp}:${state.proxy_port}`;
    const local = kind === 'ios-sim' || kind === 'android-emu';
    return (
      <>
        <h4>Connect the {name} to this Mac</h4>
        <p className="lead">{connectWhy(kind, wg)}</p>
        <DeviceCards kind={kind} onPick={setKind} />
        {choosable && <ConnectionSwitch choice={choice} onChoose={onChoose} />}
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
  const forced = confOpen(kind, qrFailed);
  const steps = confFileSteps(kind);
  return (
    <>
      <h4>Connect your {name} to this Mac</h4>
      <p className="lead">{connectWhy(kind, wg)}</p>
      <DeviceCards kind={kind} onPick={setKind} />
      {choosable && <ConnectionSwitch choice={choice} onChoose={onChoose} />}
      <div className="connect">
        <div>
          {shown ? <Qr text={shown} onFail={onQrFail} /> : <div className="qr note">The WireGuard configuration is not available yet.</div>}
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
      {shown &&
        (forced || confShown ? (
          <div className="confbox">
            <div className="confhead">
              <span className="sec-h">{confTitle(kind)}</span>
              <span className="confacts">
                {!forced && (
                  <button type="button" className="linkbtn" onClick={() => setConfShown(false)}>
                    Hide
                  </button>
                )}
                <button type="button" className="btn small" onClick={() => download(CONF_FILE, shown, 'application/octet-stream')}>
                  Download {CONF_FILE}
                </button>
                <button type="button" className="btn small" onClick={() => copy(shown, 'Configuration')}>
                  Copy text
                </button>
              </span>
            </div>
            {steps.length > 0 && <Steps steps={steps} copy={copy} />}
            <pre className="conf">{shown}</pre>
            <div className="tip">This holds the device's private key. Do not share it or show it in a screenshot.</div>
          </div>
        ) : (
          <p className="tip">
            <button type="button" className="linkbtn" onClick={() => setConfShown(true)}>
              Can't scan the QR code?
            </button>{' '}
            Set the tunnel up from a file instead.
          </p>
        ))}
    </>
  );
}

function TrustStep({ state, kind, choice, copy }: { state: AppState; kind: DeviceKind; choice: ConnectionChoice; copy: Copy }) {
  const { flows } = useStore();
  const [since] = useState(() => Date.now());
  const now = useNow(1000);
  const wg = wireguardSteps(state.mode, choice, kind);
  const hint = trustHint(kind, state, flows, since, now);
  return (
    <>
      <h4>Trust Wiretrace</h4>
      <p className="lead">{CERTIFICATE_WHY} Needed once per device.</p>
      <Checklist items={trustChecklist(kind, flows)} />
      {hint === 'not-trusted' && <NotTrusted failures={state.tls_failures} />}
      {hint === 'no-page' && (
        <div className="hintbox" role="status">
          {noPageHint(kind, wg)}
        </div>
      )}
      {certificateSteps(deviceChoice(kind).target, wg).map((group) => (
        <Steps key={group.platform} steps={group.steps} copy={copy} className="gap-top" />
      ))}
    </>
  );
}

function CheckAppStep({ state, kind, choice, onTrust }: { state: AppState; kind: DeviceKind; choice: ConnectionChoice; onTrust: () => void }) {
  const { flows, rules } = useStore();
  const dispatch = useDispatch();
  const [since] = useState(() => Date.now());
  const now = useNow(1000);
  const missing = rules === null;
  useEffect(() => {
    if (!missing) return;
    let cancelled = false;
    api
      .rules()
      .then((r) => !cancelled && dispatch({ type: 'rules', rules: r }))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [missing, dispatch]);
  const first = firstApiFlow(flows);
  const hint = appHint(state, flows, since, now);
  const android = kind === 'android' || kind === 'android-emu';
  return (
    <>
      <h4>Check the app</h4>
      <p className="lead">Open the app on the device and go to a screen that loads data. Its requests appear in Traffic.</p>
      {first ? (
        <div className="okbox">
          <b>Traffic received</b>
          <div>
            First request: {first.method} {first.host}
            {first.path}
          </div>
        </div>
      ) : hint === 'not-trusted' ? (
        <NotTrusted failures={state.tls_failures} note={android ? STORE_BUILD_NOTE : undefined} onBack={onTrust} />
      ) : (
        <>
          <div className="waiting">
            <span className="spinner" />
            <div>
              <b>Waiting for the first request…</b>
              <div>This turns green as soon as a request to an API host arrives.</div>
            </div>
          </div>
          {hint === 'no-traffic' && (
            <div className="hintbox" role="status">
              <p>Nothing from the app yet. Check that:</p>
              <ul className="needs">
                {appChecks(kind, wireguardSteps(state.mode, choice, kind), state.preset, rules?.api_hosts ?? []).map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Summary({ state, kind, choice }: { state: AppState; kind: DeviceKind; choice: ConnectionChoice }) {
  const { flows } = useStore();
  return (
    <div className="summary">
      <h5>What is set up</h5>
      <Checklist items={setupSummary(kind, state, flows, choice)} />
      <p className="tip">{nextTime(kind, wireguardSteps(state.mode, choice, kind))}</p>
    </div>
  );
}

function DeviceLogsStep({ state, kind, switchBox }: { state: AppState; kind: DeviceKind; switchBox: ReactNode }) {
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
        </div>
      )}
      {switchBox}
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
const STEP_KEYS: Record<StepId, StepKey> = { 1: 'device', 2: 'connect', 3: 'trust', 4: 'check', 5: 'logs' };

/** `startAtConnect`: the tab was opened by a switch started from this wizard. */
export function SetupWizard({ startAtConnect = false }: { startAtConnect?: boolean }) {
  const { appState, flows } = useStore();
  const { viewing } = useData();
  const dispatch = useDispatch();
  const [step, setStep] = useState<StepId>(startAtConnect ? 2 : 1);
  const [kind, setKind] = useState<DeviceKind>(() => deviceFromTarget(appState?.target ?? ''));
  const [alt, setAlt] = useState(false);
  const [choice, setChoice] = useState<ConnectionChoice>(() => loadChoice(storage()));
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  const [devicesError, setDevicesError] = useState<string | null>(null);
  const [switchTo, setSwitchTo] = useState<DeviceInfo | null>(null);
  useEffect(() => {
    let live = true;
    api
      .devices()
      .then((list) => live && setDevices(list))
      .catch((e: unknown) => live && setDevicesError(e instanceof ApiError ? e.message : 'Could not list the devices'));
    return () => {
      live = false;
    };
  }, []);
  // The confirm dialog handles Escape and its backdrop itself: the wizard stays open under it.
  const close = () => {
    if (!switchTo) dispatch({ type: 'ui', patch: { dialog: null } });
  };
  if (!appState) return null;

  const choose = (c: ConnectionChoice) => {
    setChoice(c);
    storeChoice(storage(), c);
  };
  // Only a WireGuard-only session needs a restart for the Wi-Fi proxy.
  const wireguardOnly = appState.mode === 'wireguard';
  const wg = wireguardSteps(appState.mode, choice, kind);
  const proxyAlt = alt && wireguardOnly && step === 2 && !needsProxy(kind);
  const copy: Copy = (text, what) => {
    void copyText(text).then((ok) => dispatch({ type: 'toast', text: ok ? `${what} copied` : 'Copy failed' }));
  };
  const done = (id: StepId) => {
    const key = STEP_KEYS[id];
    return key === 'device' ? step > 1 : stepDone(key, appState, flows);
  };
  const subs: Record<StepId, string> = {
    1: deviceChoice(kind).label,
    2: usesTunnel(kind, wg) ? 'WireGuard' : 'Wi-Fi proxy',
    3: 'Once per device',
    4: 'Open the app',
    5: 'Optional, USB',
  };
  const stepClass = (id: StepId) => (id === step ? 'cur' : done(id) ? 'done' : 'todo');
  const box = wizardSwitch(kind, appState.target, devices, devicesError, viewing);
  const switchBox = box && <SwitchBox box={box} onUse={setSwitchTo} />;

  return (
    <Modal title="Connect a test device" onClose={close} wide>
      <div className="wizard">
        <div className="steps">
          {STEP_IDS.map((id) => (
            <button
              key={id}
              type="button"
              className={`step ${stepClass(id)}${done(id) ? ' passed' : ''}`}
              aria-current={id === step ? 'step' : undefined}
              onClick={() => setStep(id)}
            >
              <span className="num">{done(id) ? '✓' : id}</span>
              <span>
                <span className="lbl">{STEP_LABELS[STEP_KEYS[id]]}</span>
                <br />
                <span className="sub">{subs[id]}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="wiz-main">
          {step === 1 && (
            <>
              <h4>Which device do you test on?</h4>
              <p className="lead">The next steps are written for this kind of device.</p>
              <DeviceCards kind={kind} onPick={setKind} />
              {switchBox}
              <BeforeYouStart kind={kind} wireguard={wg} />
            </>
          )}
          {step === 2 && <ConnectStep state={appState} kind={kind} setKind={setKind} choice={choice} onChoose={choose} copy={copy} />}
          {step === 3 && <TrustStep state={appState} kind={kind} choice={choice} copy={copy} />}
          {step === 4 && <CheckAppStep state={appState} kind={kind} choice={choice} onTrust={() => setStep(3)} />}
          {step === 5 && <DeviceLogsStep state={appState} kind={kind} switchBox={switchBox} />}
          {proxyAlt && (
            <Restart
              preset={appState.preset}
              kind={kind}
              copy={copy}
              why="A Wi-Fi proxy is a setting on the phone, used instead of the VPN app. Wiretrace cannot switch to it while it runs."
            />
          )}
          {step === 5 && <Summary state={appState} kind={kind} choice={choice} />}
          <div className="wiz-foot">
            {wireguardOnly && step === 2 && !needsProxy(kind) && (
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
                {nextLabel(done(step), STEP_KEYS[(step + 1) as StepId])}
              </button>
            ) : (
              <button type="button" className="btn primary" onClick={() => dispatch({ type: 'ui', patch: { dialog: null, view: 'traffic' } })}>
                Done — open Traffic
              </button>
            )}
          </div>
        </div>
      </div>
      {switchTo && <SwitchDeviceDialog device={switchTo} state={appState} fromWizard onClose={() => setSwitchTo(null)} />}
    </Modal>
  );
}
