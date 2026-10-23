import { useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { choiceNote, DECRYPT_NOTES, decryptChoices, decryptedToast, decryptTitle, hostsLine } from '../logic/hosts';
import { useDispatch } from '../store';
import { Modal } from './Modal';

/** Add a passed-through host, or its parent domain, to the preset in use, applied without a restart (spec 022, slice C). */
export function DecryptHostDialog({ host, initial, preset, apiHosts, onClose }: {
  host: string;
  /** The choice the menu item named; the host when it named none. */
  initial?: string;
  preset: string;
  apiHosts: number;
  onClose: () => void;
}) {
  const dispatch = useDispatch();
  const choices = decryptChoices(host);
  const [chosen, setChosen] = useState(() => (initial && choices.includes(initial) ? initial : (choices[0] as string)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    if (!busy) onClose();
  };
  const decrypt = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.decryptHost(chosen);
      dispatch({ type: 'toast', text: result.applied ? decryptedToast(result.host) : (result.message ?? decryptedToast(result.host)) });
      onClose();
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      setError(e instanceof ApiError ? e.message : 'Could not decrypt the host');
      setBusy(false);
    }
  };

  return (
    <Modal title={decryptTitle(host)} lead={`Added to the API hosts of preset ${preset} and applied now. The session keeps running.`} onClose={close}>
      <div role="radiogroup" aria-label="What to decrypt">
        {choices.map((c) => (
          <label key={c} className={`choice${chosen === c ? ' on' : ''}`}>
            <input type="radio" name="decrypt-host" checked={chosen === c} disabled={busy} onChange={() => setChosen(c)} />
            <span>
              <span className="l">{c}</span>
              <span className="s2">{choiceNote(c, host)}</span>
            </span>
          </label>
        ))}
      </div>
      <ul className="plain">
        {DECRYPT_NOTES.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      {error && (
        <div className="form-error switch-error" role="alert">
          {error}
        </div>
      )}
      <div className="sheet-foot">
        <span className="foot-note">{hostsLine(preset, apiHosts)}</span>
        <span className="spacer" />
        <button type="button" className="btn" disabled={busy} onClick={close}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={() => void decrypt()}>
          {busy ? 'Saving…' : 'Decrypt'}
        </button>
      </div>
    </Modal>
  );
}
