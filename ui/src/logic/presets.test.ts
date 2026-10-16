import { describe, expect, it } from 'vitest';
import type { PresetInfo } from '../types';
import { deviceLogsText, OFF_WHILE_VIEWING, presetMenuState } from './presets';

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
