import { describe, expect, it } from 'vitest';
import { deviceLabel, deviceLogsLine, deviceMenuState, devicePhrase, modeLabel, phoneSteps, PIN_NOTE } from './devices';
import { OFF_WHILE_VIEWING } from './presets';

// The number is spec 018's test number.

describe('device menu (18)', () => {
  it('is off while a previous session is open, with the reason Setup and Rules give', () => {
    expect(deviceMenuState('2026-10-15_080000_myapp_android')).toEqual({ disabled: true, title: OFF_WHILE_VIEWING });
  });
  it('is on for the live session', () => {
    expect(deviceMenuState(null).disabled).toBe(false);
  });
});

describe('labels', () => {
  it('names every target as the server does, and an unknown one as itself', () => {
    expect(['ios', 'android', 'android-emu', 'ios-sim', 'device', 'pixel'].map(deviceLabel)).toEqual([
      'iPhone',
      'Android phone',
      'Android emulator',
      'iOS Simulator',
      'Another device',
      'pixel',
    ]);
  });
  it('reads in a sentence', () => {
    expect(devicePhrase('ios')).toBe('the iPhone');
    expect(devicePhrase('device')).toBe('the other device');
  });
  it('names each mode as the title bar does', () => {
    expect([modeLabel('wireguard'), modeLabel('both'), modeLabel('proxy')]).toEqual(['WireGuard', 'Proxy + WireGuard', 'Proxy']);
  });
});

describe('what to do on the phones (19)', () => {
  it('moves the tunnel in WireGuard mode, pinned or not', () => {
    const steps = ['Turn the WireGuard tunnel off on the iPhone, then on on the Android phone. First time on this phone: scan the QR code in Setup.'];
    expect(phoneSteps('wireguard', false, 'ios', 'android')).toEqual(steps);
    expect(phoneSteps('wireguard', true, 'ios', 'android')).toEqual(steps);
  });
  it('warns about the pin in proxy mode only when the proxy is pinned', () => {
    expect(phoneSteps('proxy', true, 'android', 'ios')).toEqual([`Remove the Wi-Fi proxy on the Android phone first: ${PIN_NOTE}`]);
    expect(phoneSteps('proxy', false, 'android', 'ios')).toEqual([]);
  });
  it('says disconnect and connect in both mode, and adds the pin when pinned', () => {
    const steps = phoneSteps('both', true, 'ios', 'android');
    expect(steps[0]).toBe(
      'Disconnect the iPhone (Wi-Fi proxy off, or tunnel off), then connect the Android phone the same way. First time on this phone: follow Setup.',
    );
    expect(steps[1]).toBe(`Remove the Wi-Fi proxy on the iPhone first: ${PIN_NOTE}`);
    expect(phoneSteps('both', false, 'ios', 'android')).toEqual([steps[0]]);
  });
});

describe('device log line', () => {
  it('names the app, or says why the logs are off', () => {
    expect(deviceLogsLine('com.example.app')).toBe('On · com.example.app');
    expect(deviceLogsLine('off (adb not found)')).toBe('Off: adb not found');
  });
});
