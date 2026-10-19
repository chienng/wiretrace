import { useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { deviceLogsText } from '../logic/presets';
import { useDispatch } from '../store';
import type { PresetInfo } from '../types';
import { Modal } from './Modal';

interface Props {
  preset: PresetInfo;
  target: string;
  onClose: () => void;
}

/** Asked before switching: the server saves this session and the launcher starts the next one. */
export function SwitchPresetDialog({ preset, target, onClose }: Props) {
  const dispatch = useDispatch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    if (!busy) onClose();
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.switchPreset(preset.name);
      if (result) {
        dispatch({ type: 'switching', to: result.switching });
        return;
      }
      onClose();
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      setError(e instanceof ApiError ? e.message : 'Could not switch the preset');
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Switch to ${preset.name}?`}
      lead="The current session is saved first. Then a new session starts with this preset, the same target and mode. The phone stays connected."
      onClose={close}
    >
      <div className="kv2">
        <span>Decrypts</span>
        <span>{preset.api_hosts.length ? preset.api_hosts.join(', ') : 'None: this preset file does not load'}</span>
        <span>Device logs</span>
        <span>{deviceLogsText(preset, target)}</span>
      </div>
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
