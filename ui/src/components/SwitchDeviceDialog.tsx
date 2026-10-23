import { useEffect, useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { deviceLabel, deviceLogsLine, phoneSteps } from '../logic/devices';
import { CLIENT_TARGETS, preselectedKind, switchLead, switchTitle } from '../logic/proxyDevices';
import { clearResume, storeResume } from '../logic/setup';
import { browserStorage } from '../storage';
import { useDispatch } from '../store';
import type { AppState, DeviceInfo } from '../types';
import { Modal } from './Modal';

interface Props {
  device: DeviceInfo;
  state: AppState;
  /** Opened from the Setup wizard: the new tab goes on with Setup at Connect. */
  fromWizard?: boolean;
  onClose: () => void;
}

/** Confirm and its saving state: the switch request, then this page waits for the next session's tab. */
function useSwitchConfirm(onClose: () => void, fromWizard: boolean) {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    if (!busy) onClose();
  };

  const confirm = async (send: () => Promise<unknown>, to: string) => {
    setBusy(true);
    setError(null);
    if (fromWizard) storeResume(browserStorage(), Date.now());
    try {
      const result = await send();
      if (result) {
        dispatch({ type: 'switching', to });
        return;
      }
      if (fromWizard) clearResume(browserStorage());
      onClose();
    } catch (e) {
      if (fromWizard) clearResume(browserStorage());
      if (e instanceof ForbiddenError) return;
      setError(e instanceof ApiError ? e.message : 'Could not switch the device');
      setBusy(false);
    }
  };

  return { busy, error, close, confirm };
}

function SwitchFoot({ busy, disabled = false, error, onCancel, onConfirm }: {
  busy: boolean;
  disabled?: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <>
      {error && (
        <div className="form-error switch-error" role="alert">
          {error}
        </div>
      )}
      <div className="sheet-foot switch-foot">
        <span className="tip">A new browser tab opens for the new session.</span>
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={busy || disabled} onClick={onConfirm}>
          {busy ? 'Saving…' : 'Save and switch'}
        </button>
      </div>
    </>
  );
}

/** Asked before switching: the server saves this session and the launcher starts one for the other device. */
export function SwitchDeviceDialog({ device, state, fromWizard = false, onClose }: Props) {
  const { busy, error, close, confirm } = useSwitchConfirm(onClose, fromWizard);
  const steps = phoneSteps(state.mode, state.proxy_pin, state.target, device.target);

  return (
    <Modal
      title={`Switch to ${device.label}?`}
      lead="The current session is saved first. Then a new session starts for this device, with the same preset and mode."
      onClose={close}
    >
      <div className="kv2">
        <span>Device logs</span>
        <span>{deviceLogsLine(device.device_logs)}</span>
      </div>
      {steps.length > 0 && (
        <ol className="instr gap-top">
          {steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      )}
      <SwitchFoot
        busy={busy}
        error={error}
        onCancel={close}
        onConfirm={() => void confirm(() => api.switchDevice(device.target), device.label)}
      />
    </Modal>
  );
}

/** Asked before switching to a device the Wi-Fi proxy refused: the next session accepts only its address. */
export function SwitchClientDialog({ address, accepted, state, onClose }: {
  address: string;
  /** Every device the current session accepts: the dialog names each one the next session refuses. */
  accepted: readonly string[];
  state: AppState;
  onClose: () => void;
}) {
  const { busy, error, close, confirm } = useSwitchConfirm(onClose, false);
  const [kind, setKind] = useState<string | null>(() => preselectedKind(state.target));
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .devices()
      .then((list) => live && setDevices(list))
      .catch((e: unknown) => live && setListError(e instanceof ApiError ? e.message : 'Could not list the devices'));
    return () => {
      live = false;
    };
  }, []);

  const logs = kind ? devices?.find((d) => d.target === kind)?.device_logs : undefined;
  const logsLine = !kind ? 'Choose the kind of device' : logs ? deviceLogsLine(logs) : (listError ?? 'Loading…');

  return (
    <Modal title={switchTitle(address)} lead={switchLead(accepted)} onClose={close}>
      <div className="seg sm switch-kind" role="radiogroup" aria-label="Kind of device">
        {CLIENT_TARGETS.map((target) => (
          <button
            type="button"
            role="radio"
            aria-checked={kind === target}
            className={kind === target ? 'on' : ''}
            key={target}
            disabled={busy}
            onClick={() => setKind(target)}
          >
            {deviceLabel(target)}
          </button>
        ))}
      </div>
      <div className="kv2 gap-top">
        <span>Device logs</span>
        <span>{logsLine}</span>
      </div>
      <SwitchFoot
        busy={busy}
        disabled={kind === null}
        error={error}
        onCancel={close}
        onConfirm={() => kind && void confirm(() => api.switchDevice(kind, address), `the device at ${address}`)}
      />
    </Modal>
  );
}
