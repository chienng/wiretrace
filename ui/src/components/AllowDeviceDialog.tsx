import { useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { ALLOW_WARNING, allowLead, allowTitle, lastPlaceNote } from '../logic/proxyDevices';
import { useDispatch } from '../store';
import { Modal } from './Modal';

/** Send a device change; the pushed state then shows it. Shared by Allow and Remove. */
export function useDeviceChange(onClose: () => void, failure: string) {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    if (!busy) onClose();
  };
  const send = async (call: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      dispatch({ type: 'toast', text: done });
      onClose();
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      setError(e instanceof ApiError ? e.message : failure);
      setBusy(false);
    }
  };
  return { busy, error, close, send };
}

export function DeviceChangeFoot({ busy, error, label, danger = false, onCancel, onConfirm }: {
  busy: boolean;
  error: string | null;
  label: string;
  danger?: boolean;
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
      <div className="sheet-foot">
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className={`btn ${danger ? 'destructive' : 'primary'}`} disabled={busy} onClick={onConfirm}>
          {busy ? 'Saving…' : label}
        </button>
      </div>
    </>
  );
}

/** Asked before a refused device may use the Wi-Fi proxy alongside the accepted ones (spec 022). */
export function AllowDeviceDialog({ address, accepted, max, onClose }: {
  address: string;
  accepted: readonly string[];
  max: number;
  onClose: () => void;
}) {
  const { busy, error, close, send } = useDeviceChange(onClose, 'Could not allow the device');
  const last = lastPlaceNote(accepted, max);
  return (
    <Modal title={allowTitle(address)} lead={allowLead(accepted)} onClose={close}>
      <div className="callout warn">{ALLOW_WARNING}</div>
      {last && <div className="callout info">{last}</div>}
      <DeviceChangeFoot
        busy={busy}
        error={error}
        label="Allow"
        onCancel={close}
        onConfirm={() => void send(() => api.allowDevice(address), `${address} can use the Wi-Fi proxy`)}
      />
    </Modal>
  );
}
