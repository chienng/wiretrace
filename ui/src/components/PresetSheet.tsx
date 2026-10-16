import { useEffect, useRef, useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import {
  addName,
  emptyFields,
  fieldsFromForm,
  fileChanged,
  formDirty,
  LAYOUT_NOTE,
  presetTag,
  RESTART_CONFIRM,
  savedButNotRestarted,
  sheetMode,
} from '../logic/presets';
import { useDispatch } from '../store';
import type { PresetDetail, PresetFieldName, PresetFields, PresetInfo } from '../types';
import { Modal } from './Modal';

interface Props {
  /** The preset in use. */
  current: string;
  /** The preset to open on; null opens a blank form for a new preset. */
  initial: string | null;
  onClose: () => void;
}

interface Refused {
  message: string;
  field: PresetFieldName | null;
}

const DISCARD = 'Discard your changes?';

function problem(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

/** A list of names with × to remove each and an input to add one (Enter, comma, or leaving the input). */
function ChipList({ id, label, items, onChange }: { id: string; label: string; items: string[]; onChange: (items: string[]) => void }) {
  const [text, setText] = useState('');
  const commit = () => {
    if (text.trim()) onChange(addName(items, text));
    setText('');
  };
  return (
    <div className="chips">
      {items.map((item) => (
        <span className="nchip" key={item}>
          {item}
          <button type="button" aria-label={`Remove ${item}`} onClick={() => onChange(items.filter((i) => i !== item))}>
            ×
          </button>
        </span>
      ))}
      <input
        id={id}
        className="chip-add"
        aria-label={`Add to ${label}`}
        placeholder="Add…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            commit();
          }
        }}
      />
    </div>
  );
}

/** The Presets sheet: the preset files on the left, one preset's form on the right (spec 013, extension A). */
export function PresetSheet({ current, initial, onClose }: Props) {
  const dispatch = useDispatch();
  const [list, setList] = useState<PresetInfo[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  /** The preset name on the form; null is a new preset. */
  const [selected, setSelected] = useState<string | null>(initial);
  const [detail, setDetail] = useState<PresetDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<PresetFields>(emptyFields);
  const [newName, setNewName] = useState('');
  const [refused, setRefused] = useState<Refused | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const latest = useRef(0);

  const isNew = selected === null;
  const loading = !isNew && !detail && !loadError;
  const saved = detail?.fields ?? emptyFields();
  const dirty = formDirty(saved, form, isNew ? newName : '');
  const mode = sheetMode({ isNew, name: selected ?? '', inUse: detail?.in_use ?? false, readOnly: detail?.read_only ?? false });

  const refreshList = async () => {
    try {
      setList(await api.presets());
      setListError(null);
    } catch (e) {
      if (!(e instanceof ForbiddenError)) setListError(problem(e, 'Could not list the presets'));
    }
  };

  const reset = (name: string | null) => {
    latest.current += 1;
    setSelected(name);
    setDetail(null);
    setLoadError(null);
    setForm(emptyFields());
    setNewName('');
    setRefused(null);
    setNotice(null);
    setConfirming(false);
  };

  /** Fills the form from the file on disk. */
  const load = async (name: string): Promise<boolean> => {
    reset(name);
    const mine = latest.current;
    try {
      const found = await api.presetDetail(name);
      if (mine !== latest.current) return false;
      setDetail(found);
      setForm(found.fields);
      return true;
    } catch (e) {
      if (mine !== latest.current || e instanceof ForbiddenError) return false;
      setLoadError(problem(e, 'Could not load the preset'));
      return false;
    }
  };

  useEffect(() => {
    void refreshList();
    if (initial) void load(initial);
    // Runs once: later selections go through `choose`.
  }, []);

  const choose = (name: string | null) => {
    if (busy || name === selected) return;
    if (dirty && !window.confirm(DISCARD)) return;
    if (name === null) reset(null);
    else void load(name);
  };

  const close = () => {
    if (busy) return;
    if (dirty && !window.confirm(DISCARD)) return;
    onClose();
  };

  const edit = <K extends keyof PresetFields>(key: K, value: PresetFields[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (refused?.field === key) setRefused(null);
  };

  const submit = async (restart: boolean) => {
    setBusy(true);
    setRefused(null);
    setNotice(null);
    setConfirming(false);
    const fields = fieldsFromForm(form);
    try {
      if (selected === null) {
        const made = await api.createPreset(newName.trim(), fields);
        await refreshList();
        if (await load(made.name)) {
          setNotice(
            `Created presets/${made.name}.yaml. This session is still on ${current}: choose ${made.name} from the Preset menu to switch to it.`,
          );
        }
      } else {
        const result = await api.savePreset(selected, detail?.revision ?? '', fields, restart);
        if (result.switching) {
          dispatch({ type: 'switching', preset: result.switching });
          return;
        }
        await refreshList();
        if (await load(selected)) setNotice(`Saved presets/${selected}.yaml. This session keeps running.`);
      }
    } catch (e) {
      if (e instanceof ForbiddenError) {
        setBusy(false);
        return;
      }
      const message = problem(e, 'Could not save the preset');
      if (selected !== null && e instanceof ApiError && (fileChanged(e.status, message) || savedButNotRestarted(message))) {
        // The file on disk is not what the form was loaded from: show it as it is now.
        await refreshList();
        const again = await load(selected);
        if (again && fileChanged(e.status, message)) setNotice(`${message} on disk after this sheet loaded it. It is shown again as it is now, and nothing was written.`);
        else setRefused({ message, field: null });
      } else {
        const field = e instanceof ApiError ? e.field : null;
        setRefused({ message, field: field as PresetFieldName | null });
      }
    }
    setBusy(false);
  };

  const bad = (field: PresetFieldName) => refused?.field === field;
  const mark = (field: PresetFieldName) => (bad(field) ? { 'aria-invalid': true as const } : {});
  const refusedLine = (field: PresetFieldName) =>
    bad(field) && (
      <div className="field-error" role="alert">
        This value was refused: see the message below.
      </div>
    );

  const hosts = form.api_hosts;

  return (
    <Modal title="Presets" onClose={close} wide>
      <div className="preset-sheet">
        <p className="lead">One file per project and environment. Only the listed hosts are decrypted.</p>
        <div className="preset-grid">
          <div>
            <nav className="plist" aria-label="Preset files">
              {list?.map((preset) => {
                const tag = presetTag(preset.name, current);
                return (
                  <button
                    type="button"
                    className={`pi${selected === preset.name ? ' sel' : ''}`}
                    key={preset.name}
                    aria-current={selected === preset.name ? 'true' : undefined}
                    onClick={() => choose(preset.name)}
                  >
                    <span className="pn">{preset.name}</span>
                    {tag && <span className={`here${tag === 'Template' ? ' tpl' : ''}`}>{tag}</span>}
                  </button>
                );
              })}
              <button type="button" className={`pi add${isNew ? ' sel' : ''}`} aria-current={isNew ? 'true' : undefined} onClick={() => choose(null)}>
                + New preset
              </button>
            </nav>
            {!list && !listError && <p className="hint">Loading…</p>}
            {listError && <p className="hint bad">{listError}</p>}
            <p className="hint">Select a name to edit it. Saving the one in use starts a new session.</p>
          </div>

          <fieldset className="preset-form" disabled={busy || confirming || mode.readOnly || loading || !!loadError}>
            {loadError && (
              <div className="form-error" role="alert">
                {loadError}
              </div>
            )}
            {detail?.error && (
              <div className="form-error" role="alert">
                {detail.error}
              </div>
            )}
            {loading && <p className="hint">Loading…</p>}

            <div className="field">
              <label htmlFor="preset-name">Name</label>
              <input
                id="preset-name"
                className="textin mono"
                value={isNew ? newName : (selected ?? '')}
                readOnly={!isNew}
                disabled={!isNew}
                maxLength={64}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => {
                  setNewName(e.target.value);
                  if (bad('name')) setRefused(null);
                }}
                {...mark('name')}
              />
              {refusedLine('name')}
              <div className="hint">
                Saved as presets/{isNew ? newName.trim() || '<name>' : selected}.yaml. Letters, digits, _ and -. The name cannot be changed later.
              </div>
            </div>

            <div className="field">
              <label htmlFor="preset-host-0">API hosts</label>
              {[...hosts, ''].map((host, i) => (
                <div className="hostline" key={i}>
                  <input
                    id={`preset-host-${i}`}
                    className="textin mono"
                    aria-label={i < hosts.length ? `API host ${i + 1}` : 'Add a host'}
                    placeholder="Add a host…"
                    value={host}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(e) => {
                      const next = [...hosts];
                      next[i] = e.target.value;
                      edit('api_hosts', next);
                    }}
                    {...mark('api_hosts')}
                  />
                  {i < hosts.length && (
                    <button type="button" className="x" aria-label={`Remove host ${i + 1}`} onClick={() => edit('api_hosts', hosts.filter((_, j) => j !== i))}>
                      ×
                    </button>
                  )}
                </div>
              ))}
              {refusedLine('api_hosts')}
              <div className="hint">Host names only. Each host includes its subdomains, on any port.</div>
            </div>

            <div className="row">
              <div className="field">
                <label htmlFor="preset-android">Android package</label>
                <input
                  id="preset-android"
                  className="textin mono"
                  value={form.android_package}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => edit('android_package', e.target.value)}
                  {...mark('android_package')}
                />
                {refusedLine('android_package')}
              </div>
              <div className="field">
                <label htmlFor="preset-ios">iOS process</label>
                <input
                  id="preset-ios"
                  className="textin mono"
                  value={form.ios_process}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => edit('ios_process', e.target.value)}
                  {...mark('ios_process')}
                />
                {refusedLine('ios_process')}
              </div>
            </div>

            <div className="row">
              <div className="field">
                <label htmlFor="preset-request-id">Request ID header</label>
                <input
                  id="preset-request-id"
                  className="textin mono"
                  placeholder="X-Request-ID"
                  value={form.request_id_header}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => edit('request_id_header', e.target.value)}
                  {...mark('request_id_header')}
                />
                {refusedLine('request_id_header')}
              </div>
              <div className="field">
                <label htmlFor="preset-filter">Starting filter</label>
                <input
                  id="preset-filter"
                  className="textin mono"
                  placeholder="optional, e.g. !~t image"
                  value={form.default_filter}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => edit('default_filter', e.target.value)}
                  {...mark('default_filter')}
                />
                {refusedLine('default_filter')}
              </div>
            </div>

            <div className="field">
              <label htmlFor="preset-hide-headers">Extra headers to hide</label>
              <ChipList id="preset-hide-headers" label="Extra headers to hide" items={form.redact_headers} onChange={(items) => edit('redact_headers', items)} />
              {refusedLine('redact_headers')}
              <div className="hint">Added to the built-in list. Passwords, tokens and cookies stay hidden either way.</div>
            </div>

            <div className="field">
              <label htmlFor="preset-hide-fields">Extra fields to hide</label>
              <ChipList id="preset-hide-fields" label="Extra fields to hide" items={form.redact_fields} onChange={(items) => edit('redact_fields', items)} />
              {refusedLine('redact_fields')}
              <div className="hint">Added to the built-in list. Passwords, tokens and cookies stay hidden either way.</div>
            </div>
          </fieldset>
        </div>

        {refused && (
          <div className="form-error preset-refused" role="alert">
            {refused.message}
          </div>
        )}
        {mode.note && <div className="callout">{mode.note}</div>}
        {confirming && <div className="callout" role="alertdialog" aria-label="Save and restart">{RESTART_CONFIRM}</div>}
        {isNew && !notice && (
          <div className="callout">
            Create writes the file and leaves this session on <b>{current}</b>. Choose the new preset from the Preset menu afterwards to switch: traffic so far is saved, and the phone stays connected.
          </div>
        )}
        {notice && (
          <div className="callout" role="status">
            {notice}
          </div>
        )}

        <div className="sheet-foot">
          <span className="spacer" />
          {confirming ? (
            <>
              <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button type="button" className="btn primary" disabled={busy} onClick={() => void submit(true)}>
                Save and restart
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn" disabled={busy} onClick={close}>
                {mode.readOnly ? 'Close' : 'Cancel'}
              </button>
              {mode.label && (
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy || loading || !!loadError || (isNew && !newName.trim())}
                  onClick={() => (mode.restarts ? setConfirming(true) : void submit(false))}
                >
                  {busy ? 'Saving…' : mode.label}
                </button>
              )}
            </>
          )}
        </div>
        {!isNew && !mode.readOnly && <p className="tip preset-layout">{LAYOUT_NOTE}</p>}
      </div>
    </Modal>
  );
}
