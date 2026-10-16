import type { PresetFields, PresetInfo } from '../types';

/** Why Setup, Rules and the preset menu are off while a previous session is open. */
export const OFF_WHILE_VIEWING = 'Off while a previous session is open';

/** The title bar's preset menu: off while a previous session is open, like Setup and Rules. */
export function presetMenuState(viewing: string | null): { disabled: boolean; title: string } {
  return viewing ? { disabled: true, title: OFF_WHILE_VIEWING } : { disabled: false, title: 'Switch the preset' };
}

/** The switch dialog's device log line for this preset and the session's target. */
export function deviceLogsText(preset: PresetInfo, target: string): string {
  if (preset.device_logs && preset.app) return `On · ${preset.app}`;
  if (target === 'device') return 'Off: --target device has no device log';
  const key = target.startsWith('android') ? 'android_package' : 'ios_process';
  return `Off: the preset has no app.${key}`;
}

/** The two rows under the preset menu's list: off while a previous session is open, with the menu's reason. */
export function presetRowsState(viewing: string | null): { disabled: boolean; title: string | undefined } {
  return viewing ? { disabled: true, title: OFF_WHILE_VIEWING } : { disabled: false, title: undefined };
}

/** What the sheet shows beside a preset in its list. */
export function presetTag(name: string, current: string): 'In use' | 'Template' | null {
  if (name === current) return 'In use';
  return name === TEMPLATE ? 'Template' : null;
}

/** The shipped template: the release replaces it, so the sheet only shows it. */
export const TEMPLATE = 'example';

/** Said in the sheet before **Save and restart** writes anything. */
export const RESTART_CONFIRM = 'This session is saved and a new one starts with these settings. The phone stays connected.';

export const READ_ONLY_NOTE = 'This is the template that every release replaces, so it cannot be saved. Use New preset to make your own.';

export const LAYOUT_NOTE = "Saving rewrites the file in Wiretrace's layout; comments in it are not kept.";

export function emptyFields(): PresetFields {
  return {
    api_hosts: [],
    android_package: '',
    ios_process: '',
    request_id_header: '',
    default_filter: '',
    redact_headers: [],
    redact_fields: [],
  };
}

function cleanList(list: readonly string[]): string[] {
  return list.map((item) => item.trim()).filter((item) => item !== '');
}

/** The form as the server gets it: every host and name trimmed, empty lines dropped, strings trimmed. */
export function fieldsFromForm(form: PresetFields): PresetFields {
  return {
    api_hosts: cleanList(form.api_hosts),
    android_package: form.android_package.trim(),
    ios_process: form.ios_process.trim(),
    request_id_header: form.request_id_header.trim(),
    default_filter: form.default_filter.trim(),
    redact_headers: cleanList(form.redact_headers),
    redact_fields: cleanList(form.redact_fields),
  };
}

/** True when the form, as it would be sent, differs from the fields it started from (or the new name is typed). */
export function formDirty(saved: PresetFields, form: PresetFields, newName = ''): boolean {
  return newName.trim() !== '' || JSON.stringify(fieldsFromForm(saved)) !== JSON.stringify(fieldsFromForm(form));
}

/** A name added to a chip list: trimmed, and not added twice or empty. */
export function addName(list: readonly string[], text: string): string[] {
  const name = text.trim();
  if (!name || list.includes(name)) return [...list];
  return [...list, name];
}

export interface SheetMode {
  /** The primary button; null when the preset cannot be saved. */
  label: 'Create preset' | 'Save' | 'Save and restart' | null;
  /** Saving the preset in use asks first and restarts the session. */
  restarts: boolean;
  readOnly: boolean;
  note: string | null;
}

/** The primary button and read-only state for the form: a new preset, one that is not in use, or the one in use. */
export function sheetMode(selected: { isNew: boolean; name: string; inUse: boolean; readOnly: boolean }): SheetMode {
  if (selected.isNew) return { label: 'Create preset', restarts: false, readOnly: false, note: null };
  if (selected.readOnly || selected.name === TEMPLATE) return { label: null, restarts: false, readOnly: true, note: READ_ONLY_NOTE };
  if (selected.inUse) return { label: 'Save and restart', restarts: true, readOnly: false, note: null };
  return { label: 'Save', restarts: false, readOnly: false, note: null };
}

/** The server's 409 for a file that changed after the sheet loaded it: the sheet reloads it. */
export function fileChanged(status: number, message: string): boolean {
  return status === 409 && message.startsWith('The file changed');
}

/** The server's 500 once the file is written but the restart could not start. */
export function savedButNotRestarted(message: string): boolean {
  return message.startsWith('Saved, but');
}
