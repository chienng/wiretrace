import { useEffect, useRef, useState } from 'react';
import { copyText } from '../clipboard';
import { useDispatch, useStore } from '../store';
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

const STEPS = [
  { id: 1, label: 'Connect', sub: 'Phone to this Mac' },
  { id: 2, label: 'Install certificate', sub: 'Once per device' },
  { id: 3, label: 'Verify traffic', sub: 'Open the app' },
] as const;

export function SetupDialog() {
  const { appState, flows } = useStore();
  const dispatch = useDispatch();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const close = () => dispatch({ type: 'ui', patch: { dialog: null } });
  if (!appState) return null;

  const wg = appState.mode === 'wireguard';
  const received = appState.flow_count > 0 || flows.length > 0;
  const address = `${appState.mac_ip ?? '<Mac IP>'}:${appState.proxy_port}`;

  const copy = async (text: string, what: string) => {
    const ok = await copyText(text);
    dispatch({ type: 'toast', text: ok ? `${what} copied` : 'Copy failed' });
  };

  const stepState = (id: number) => (id < step || (id === 3 && received) ? 'done' : id === step ? 'cur' : 'todo');

  return (
    <Modal title="Connect a test device" onClose={close} wide>
      <div className="wizard">
        <div className="steps">
          {STEPS.map((s) => (
            <button key={s.id} type="button" className={`step ${stepState(s.id)}`} onClick={() => setStep(s.id)}>
              <span className="num">{stepState(s.id) === 'done' ? '✓' : s.id}</span>
              <span>
                <span className="lbl">{s.label}</span>
                <br />
                <span className="sub">{s.sub}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="wiz-main">
          {step === 1 && wg && (
            <>
              <h4>Connect your {appState.target} through WireGuard</h4>
              <p className="lead">Works on any Wi-Fi network and also captures apps that ignore the phone's proxy setting.</p>
              <div className="connect">
                {appState.wireguard_conf ? <Qr text={appState.wireguard_conf} /> : <div className="qr note">The WireGuard configuration is not available yet.</div>}
                <ol className="instr">
                  <li>
                    Install <b>WireGuard</b> from the App Store or Google Play.
                  </li>
                  <li>
                    Open WireGuard → <b>Add a tunnel</b> → <b>Create from QR code</b>, and scan this code.
                  </li>
                  <li>
                    Name the tunnel <span className="kbd">Wiretrace</span> and allow adding the VPN configuration.
                  </li>
                  <li>
                    Switch the tunnel <b>on</b>.
                  </li>
                </ol>
              </div>
              {appState.wireguard_conf && (
                <div className="confbox">
                  <div className="confhead">
                    <span className="sec-h">Configuration text</span>
                    <button type="button" className="btn small" onClick={() => copy(appState.wireguard_conf ?? '', 'Configuration')}>
                      Copy
                    </button>
                  </div>
                  <pre className="conf">{appState.wireguard_conf}</pre>
                  <div className="tip">This text contains the phone's private key. Do not share it.</div>
                </div>
              )}
            </>
          )}
          {step === 1 && !wg && (
            <>
              <h4>Connect your {appState.target} through the Mac's proxy</h4>
              <p className="lead">Both devices must be on the same Wi-Fi network.</p>
              <div className="addr">
                <span className="kbd big">{address}</span>
                <button type="button" className="btn small" onClick={() => copy(address, 'Address')}>
                  Copy
                </button>
              </div>
              <ol className="instr">
                <li>
                  On the phone open the Wi-Fi network's settings and set <b>HTTP proxy</b> to <b>Manual</b>.
                </li>
                <li>
                  Server <span className="kbd">{appState.mac_ip ?? '<Mac IP>'}</span>, port <span className="kbd">{appState.proxy_port}</span>.
                </li>
                <li>Save. Apps that ignore the proxy setting are not captured in this mode.</li>
              </ol>
            </>
          )}
          {step === 2 && (
            <>
              <h4>Install the certificate</h4>
              <p className="lead">Needed once per device, so the phone trusts Wiretrace for HTTPS.</p>
              <ol className="instr">
                <li>
                  While connected, open <span className="kbd">http://mitm.it</span> in the phone's browser.
                </li>
                <li>Pick the phone's platform and follow the instructions shown there.</li>
                <li>On iOS also turn the certificate on in Settings → General → About → Certificate Trust Settings.</li>
              </ol>
            </>
          )}
          {step === 3 && (
            <>
              <h4>Verify traffic</h4>
              <p className="lead">Open the app on the phone and use it. Requests appear in the Traffic view.</p>
              {received ? (
                <div className="pill ok big">Traffic received</div>
              ) : (
                <div className="waiting">
                  <span className="spinner" />
                  <div>
                    <b>Waiting for the device…</b>
                    <div>This turns green as soon as the first request arrives.</div>
                  </div>
                </div>
              )}
            </>
          )}
          <div className="wiz-foot">
            {step > 1 && (
              <button type="button" className="btn" onClick={() => setStep((step - 1) as 1 | 2)}>
                Back
              </button>
            )}
            {step < 3 ? (
              <button type="button" className="btn primary" onClick={() => setStep((step + 1) as 2 | 3)}>
                Next: {STEPS[Math.min(step, 2)]?.label}
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
