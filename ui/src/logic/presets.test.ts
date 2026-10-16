import { describe, expect, it } from 'vitest';
import type { PresetFields, PresetInfo } from '../types';
import {
  addName,
  deviceLogsText,
  emptyFields,
  fieldsFromForm,
  fileChanged,
  formDirty,
  OFF_WHILE_VIEWING,
  presetMenuState,
  presetRowsState,
  presetTag,
  READ_ONLY_NOTE,
  savedButNotRestarted,
  sheetMode,
} from './presets';

function preset(over: Partial<PresetInfo> = {}): PresetInfo {
  return { name: 'other', api_hosts: ['other.example.com'], device_logs: false, app: null, ...over };
}

describe('preset menu', () => {
  it('is off while a previous session is open, with the reason Setup and Rules give', () => {
    expect(presetMenuState('2026-10-15_080000_myapp_android')).toEqual({ disabled: true, title: OFF_WHILE_VIEWING });
  });
  it('is on for the live session', () => {
    expect(presetMenuState(null).disabled).toBe(false);
  });
});

describe('device log line', () => {
  it('names the app when this target collects it', () => {
    expect(deviceLogsText(preset({ device_logs: true, app: 'com.example.app' }), 'android')).toBe('On · com.example.app');
  });
  it('says which app key the preset lacks for this target', () => {
    expect(deviceLogsText(preset(), 'android-emu')).toBe('Off: the preset has no app.android_package');
    expect(deviceLogsText(preset(), 'ios-sim')).toBe('Off: the preset has no app.ios_process');
  });
  it('is off for --target device whatever the preset says', () => {
    expect(deviceLogsText(preset(), 'device')).toBe('Off: --target device has no device log');
  });
});

function fields(over: Partial<PresetFields> = {}): PresetFields {
  return { ...emptyFields(), api_hosts: ['api.example.com'], ...over };
}

describe('form to fields', () => {
  it('starts empty, with all seven keys', () => {
    expect(Object.keys(emptyFields()).sort()).toEqual(
      ['android_package', 'api_hosts', 'default_filter', 'ios_process', 'redact_fields', 'redact_headers', 'request_id_header'],
    );
  });
  it('trims every host and name, drops empty lines, and trims the strings', () => {
    const form = fields({
      api_hosts: ['  api.example.com ', '', '   '],
      android_package: ' com.example.app ',
      ios_process: '\tMyApp',
      request_id_header: ' X-Request-ID ',
      default_filter: ' !~t image ',
      redact_headers: [' X-Otp', ''],
      redact_fields: ['', ' otp '],
    });
    expect(fieldsFromForm(form)).toEqual({
      api_hosts: ['api.example.com'],
      android_package: 'com.example.app',
      ios_process: 'MyApp',
      request_id_header: 'X-Request-ID',
      default_filter: '!~t image',
      redact_headers: ['X-Otp'],
      redact_fields: ['otp'],
    });
  });
  it('does not change the form it is given', () => {
    const form = fields({ api_hosts: [' a '] });
    fieldsFromForm(form);
    expect(form.api_hosts).toEqual([' a ']);
  });
});

describe('dirty check', () => {
  it('is clean for the loaded values and for edits that trim away', () => {
    const saved = fields();
    expect(formDirty(saved, fields())).toBe(false);
    expect(formDirty(saved, fields({ api_hosts: ['api.example.com', '  '] }))).toBe(false);
    expect(formDirty(saved, fields({ android_package: '  ' }))).toBe(false);
  });
  it('is dirty after a real change', () => {
    expect(formDirty(fields(), fields({ api_hosts: ['api.example.org'] }))).toBe(true);
    expect(formDirty(fields(), fields({ api_hosts: [] }))).toBe(true);
    expect(formDirty(fields(), fields({ redact_fields: ['otp'] }))).toBe(true);
  });
  it('is dirty for a new preset once a name is typed', () => {
    expect(formDirty(emptyFields(), emptyFields())).toBe(false);
    expect(formDirty(emptyFields(), emptyFields(), 'qa2')).toBe(true);
    expect(formDirty(emptyFields(), emptyFields(), '  ')).toBe(false);
  });
});

describe('primary button', () => {
  const base = { isNew: false, name: 'local', inUse: false, readOnly: false };
  it('reads Create preset for a new preset', () => {
    expect(sheetMode({ ...base, isNew: true, name: '' }).label).toBe('Create preset');
  });
  it('reads Save for a preset that is not in use, and does not restart', () => {
    expect(sheetMode(base)).toMatchObject({ label: 'Save', restarts: false, readOnly: false });
  });
  it('reads Save and restart for the preset in use, which asks first', () => {
    expect(sheetMode({ ...base, name: 'staging', inUse: true })).toMatchObject({ label: 'Save and restart', restarts: true });
  });
  it('has no save button for example, and says to use New preset', () => {
    const mode = sheetMode({ ...base, name: 'example', readOnly: true });
    expect(mode).toMatchObject({ label: null, readOnly: true, note: READ_ONLY_NOTE });
    expect(READ_ONLY_NOTE).toContain('New preset');
  });
  it('keeps example read-only even when it is in use or the server did not say', () => {
    expect(sheetMode({ ...base, name: 'example', inUse: true }).label).toBeNull();
  });
});

describe('menu rows and list tags', () => {
  it('are off while a previous session is open, for the menu reason', () => {
    expect(presetRowsState('2026-10-15_080000_myapp_android')).toEqual({ disabled: true, title: OFF_WHILE_VIEWING });
    expect(presetRowsState(null)).toEqual({ disabled: false, title: undefined });
  });
  it('mark the preset in use and the template', () => {
    expect(presetTag('staging', 'staging')).toBe('In use');
    expect(presetTag('example', 'staging')).toBe('Template');
    expect(presetTag('local', 'staging')).toBeNull();
  });
});

describe('add a name to hide', () => {
  it('trims, ignores empty text and repeats', () => {
    expect(addName(['otp'], ' pin ')).toEqual(['otp', 'pin']);
    expect(addName(['otp'], '  ')).toEqual(['otp']);
    expect(addName(['otp'], 'otp ')).toEqual(['otp']);
  });
});

describe('save answers', () => {
  it('knows the 409 for a changed file, and no other 409', () => {
    expect(fileChanged(409, 'The file changed')).toBe(true);
    expect(fileChanged(409, 'Editing presets is off while a previous session is open')).toBe(false);
    expect(fileChanged(400, 'The file changed')).toBe(false);
  });
  it('knows a save whose restart did not start', () => {
    expect(savedButNotRestarted('Saved, but the session could not restart: stop and start again')).toBe(true);
    expect(savedButNotRestarted('Could not save the preset: the file on disk is unchanged')).toBe(false);
  });
});
