import { describe, expect, it } from 'vitest';
import type { DeviceStatus } from '../types';
import { devicePill, linkName } from './device';

function status(over: Partial<DeviceStatus> = {}): DeviceStatus {
  return { state: 'streaming', message: 'streaming', source: 'adb logcat', app: 'com.example.app', model: 'Pixel 8', os: 'Android 15', updated_at: null, ...over };
}

describe('device pill', () => {
  it('shows the model, OS and link, green while streaming', () => {
    expect(devicePill({ device_logs: 'android', device_logs_off: null, device_status: status(), target: 'android' })).toMatchObject({
      text: 'Pixel 8 · Android 15 · USB',
      tone: 'ok',
    });
  });
  it('follows the collector state', () => {
    const base = { device_logs: 'ios', device_logs_off: null, target: 'ios' };
    expect(devicePill({ ...base, device_status: status({ state: 'waiting', model: '', os: '' }) })).toMatchObject({ text: 'iPhone · USB', tone: 'wait' });
    expect(devicePill({ ...base, device_status: status({ state: 'several' }) }).tone).toBe('wait');
    expect(devicePill({ ...base, device_status: status({ state: 'error', message: 'tool failed' }) })).toMatchObject({ tone: 'bad', title: 'Device logs: Error (tool failed)' });
    expect(devicePill({ ...base, device_status: status({ state: 'stopped' }) }).tone).toBe('off');
    expect(devicePill({ ...base, device_status: null })).toMatchObject({ text: 'iPhone · starting', tone: 'wait' });
  });
  it('says why device logs are off', () => {
    expect(devicePill({ device_logs: null, device_logs_off: 'adb is not installed', device_status: null, target: 'android' })).toEqual({
      text: 'Device logs off',
      tone: 'off',
      title: 'Device logs are off: adb is not installed',
    });
  });
  it('names the link by target', () => {
    expect(linkName('ios-sim')).toBe('Simulator');
    expect(linkName('android-emu')).toBe('Emulator');
    expect(linkName('android')).toBe('USB');
  });
});
