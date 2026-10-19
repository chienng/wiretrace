import { useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { deviceLogsLine, phoneSteps } from '../logic/devices';
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

/** Asked before switching: the server saves this session and the launcher starts one for the other device. */
export function SwitchDeviceDialog({ device, state, fromWizard = false, onClose }: Props) {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const steps = phoneSteps(state.mode, state.proxy_pin, state.target, device.target);
  const close = () => {
    if (!busy) onClose();
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    if (fromWizard) storeResume(browserStorage(), Date.now());
    try {
      const result = await api.switchDevice(device.target);
      if (result) {
        dispatch({ type: 'switching', to: device.label });
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
      {error && (
        <div className="form-error switch-error" role="alert">
          {error}
        </div>
      )}
      <div className="sheet-foot switch-foot">
        <span className="tip">A new browser tab opens for the new session.</span>
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={close}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={() => void confirm()}>
          {busy ? 'Saving…' : 'Save and switch'}
        </button>
      </div>
    </Modal>
  );
}
