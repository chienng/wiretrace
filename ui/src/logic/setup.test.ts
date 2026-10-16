import { describe, expect, it } from 'vitest';
import type { AppState } from '../types';
import {
  appChecks,
  appHint,
  beforeYouStart,
  confFileSteps,
  confOpen,
  confTitle,
  connectWhy,
  deviceFromTarget,
  DEVICES,
  emulatorConf,
  endpointOf,
  firstApiFlow,
  needsProxy,
  nextLabel,
  nextTime,
  noPageHint,
  onboardingProgress,
  proxyCommand,
  proxySteps,
  setupSummary,
  STEP_LABELS,
  stepDone,
  trustChecklist,
  trustHint,
  tunnelSteps,
} from './setup';
import { flow } from './testing';

function state(over: Partial<AppState> = {}): AppState {
  return { mode: 'wireguard', preset: 'staging', device_seen_at: null, tls_failures: 0, device_logs: null, ...over } as AppState;
}

const T0 = 1_700_000_000_000;
const page = flow({ id: 'p', host: 'mitm.it', path: '/' });
const cert = flow({ id: 'c', host: 'mitm.it', path: '/cert/pem' });
const api = flow({ id: 'a', host: 'api.example.com' });

const CONF = [
  '[Interface]',
  'PrivateKey = test-private-key-not-real=',
  'Address = 10.0.0.2/32',
  '',
  '[Peer]',
  'PublicKey = test-public-key-not-real=',
  'AllowedIPs = 0.0.0.0/0',
  'Endpoint = 192.168.1.24:51820',
  '',
].join('\n');

describe('setup wizard', () => {
  it('preselects the device from --target', () => {
    expect(deviceFromTarget('ios')).toBe('iphone');
    expect(deviceFromTarget('android')).toBe('android');
    expect(deviceFromTarget('ios-sim')).toBe('ios-sim');
    expect(deviceFromTarget('android-emu')).toBe('android-emu');
    expect(deviceFromTarget('device')).toBe('iphone');
    expect(DEVICES.map((d) => d.label)).toEqual(['iPhone', 'Android', 'iOS Simulator', 'Android emulator']);
  });

  it('reads the Mac address and the UDP port from the configuration', () => {
    expect(endpointOf(CONF)).toEqual({ host: '192.168.1.24', port: '51820' });
    expect(endpointOf('Endpoint = [fd00::1]:51821')).toEqual({ host: 'fd00::1', port: '51821' });
    expect(endpointOf(null)).toBeNull();
    expect(endpointOf('[Interface]\n')).toBeNull();
  });

  it('rewrites only the endpoint for the Android emulator', () => {
    const emu = emulatorConf(CONF);
    expect(emu).toContain('Endpoint = 10.0.2.2:51820');
    expect(emu).not.toContain('192.168.1.24');
    expect(emu.replace('10.0.2.2', '192.168.1.24')).toBe(CONF);
    expect(emulatorConf(CONF.replace(':51820', ':51999'))).toContain('Endpoint = 10.0.2.2:51999');
  });

  it('gives the exact command to restart in proxy mode', () => {
    expect(proxyCommand('staging', 'ios-sim')).toBe('./wiretrace start --preset staging --target ios-sim --mode proxy --ui wiretrace');
    expect(proxyCommand('staging', 'iphone')).toBe('./wiretrace start --preset staging --target ios --mode proxy --ui wiretrace');
    expect(needsProxy('ios-sim')).toBe(true);
    expect(needsProxy('android-emu')).toBe(false);
  });

  it('has steps for every device type and mode', () => {
    for (const d of DEVICES) {
      expect(proxySteps(d.id, '192.0.2.7', 8080).length).toBeGreaterThan(0);
      if (!needsProxy(d.id)) expect(tunnelSteps(d.id).length).toBeGreaterThan(0);
    }
    expect(proxySteps('iphone', '192.0.2.7', 8080).map((s) => s.text).join(' ')).toContain('Server 192.0.2.7, port 8080');
    expect(proxySteps('android-emu', '192.0.2.7', 8081)[0]?.code).toBe('adb shell settings put global http_proxy 10.0.2.2:8081');
    expect(tunnelSteps('android-emu').map((s) => s.code).filter(Boolean)).toEqual(['adb push ~/Downloads/wiretrace.conf /sdcard/Download/']);
  });

  it('keeps the configuration closed on phones until the QR code cannot be used', () => {
    expect(confOpen('iphone', false)).toBe(false);
    expect(confOpen('android', false)).toBe(false);
    expect(confOpen('iphone', true)).toBe(true);
    expect(confOpen('android-emu', false)).toBe(true);
    expect(confTitle('android-emu')).toBe('wiretrace.conf (for the emulator)');
    expect(confTitle('iphone')).toBe('Set up with wiretrace.conf instead');
  });

  it('sets a phone up from wiretrace.conf and says to delete it afterwards', () => {
    for (const kind of ['iphone', 'android'] as const) {
      const steps = confFileSteps(kind);
      expect(steps[0]?.text).toContain('Download wiretrace.conf');
      expect(steps.at(-1)?.text).toMatch(/delete wiretrace\.conf from the Mac/i);
    }
    expect(confFileSteps('android').map((s) => s.code).filter(Boolean)).toEqual(['adb push ~/Downloads/wiretrace.conf /sdcard/Download/']);
    expect(confFileSteps('android-emu')).toEqual([]);
  });

  it('turns green only for a request to an API host, not the certificate page', () => {
    expect(firstApiFlow([flow({ host: 'mitm.it' })])).toBeNull();
    expect(firstApiFlow([flow({ id: 'a', host: 'mitm.it' }), flow({ id: 'b', host: 'api.example.com' })])?.id).toBe('b');
    expect(firstApiFlow([])).toBeNull();
  });
});

describe('setup wizard for first-time testers', () => {
  it('uses plain words for the steps and the device cards', () => {
    expect(Object.values(STEP_LABELS)).toEqual(['Choose device', 'Connect to this Mac', 'Trust Wiretrace', 'Check the app', 'Device logs']);
    expect(DEVICES.map((d) => `${d.label} — ${d.sub}`)).toEqual([
      'iPhone — a real iPhone',
      'Android — a real Android phone',
      'iOS Simulator — on this Mac',
      'Android emulator — on this Mac',
    ]);
    expect(connectWhy('iphone', true)).toContain('WireGuard is a free VPN app');
    expect(connectWhy('android', false)).toContain('A Wi-Fi proxy is a setting');
    expect(connectWhy('ios-sim', true)).toContain('proxy setting');
  });

  it('says what is needed before starting, and that it is once per phone', () => {
    const b = beforeYouStart('iphone', true);
    expect(b.needs.join(' ')).toContain('A QA build of the app. A store build hides its traffic');
    expect(b.needs.join(' ')).toContain('About five minutes');
    expect(b.once).toBe('You do this once per phone. Next time, you only switch the tunnel on (step 2 shows how).');
    expect(beforeYouStart('android', false).once).toContain('set the proxy again');
    expect(beforeYouStart('ios-sim', true).once).toContain('once per Simulator');
  });

  it('ticks the page and the download from requests to mitm.it', () => {
    expect(onboardingProgress([])).toEqual({ pageOpened: false, certDownloaded: false });
    expect(onboardingProgress([page])).toEqual({ pageOpened: true, certDownloaded: false });
    expect(onboardingProgress([page, cert])).toEqual({ pageOpened: true, certDownloaded: true });
    expect(onboardingProgress([flow({ host: 'MITM.IT.', path: '/cert/cer' })])).toEqual({ pageOpened: true, certDownloaded: true });
    expect(onboardingProgress([flow({ host: 'mitm.it', path: '/certificates' })]).certDownloaded).toBe(false);
  });

  it('keeps the page and the download ticked by an API request when the cap dropped them', () => {
    expect(onboardingProgress([api])).toEqual({ pageOpened: true, certDownloaded: true });
    expect(trustChecklist('android', [api]).every((i) => i.done)).toBe(true);
  });

  it('lists the page and the download only for a device that opens mitm.it', () => {
    expect(trustChecklist('iphone', [page]).map((i) => [i.label, i.done])).toEqual([
      ['Page opened on the phone', true],
      ['Certificate downloaded', false],
      ['Trusted: the first request to an API host arrived', false],
    ]);
    expect(trustChecklist('ios-sim', []).map((i) => i.label)).toEqual(['Trusted: the first request to an API host arrived']);
    expect(trustChecklist('android-emu', []).length).toBe(1);
  });

  it('marks each step done from its live check', () => {
    expect(stepDone('connect', state(), [])).toBe(false);
    expect(stepDone('connect', state({ device_seen_at: 1 }), [])).toBe(true);
    expect(stepDone('trust', state(), [page, cert])).toBe(false);
    expect(stepDone('trust', state(), [api])).toBe(true);
    expect(stepDone('check', state(), [api])).toBe(true);
    expect(stepDone('logs', state(), [])).toBe(false);
    expect(stepDone('logs', state({ device_logs: 'Android' }), [])).toBe(true);
    expect(nextLabel(true, 'trust')).toBe('Done — Next: Trust Wiretrace');
    expect(nextLabel(false, 'check')).toBe('Next: Check the app');
  });

  it('hints at the address only after 60 s on the Trust step, connected, without a request to mitm.it', () => {
    const on = state({ device_seen_at: 1 });
    expect(trustHint('iphone', on, [], T0, T0 + 59_999)).toBeNull();
    expect(trustHint('iphone', on, [], T0, T0 + 60_000)).toBe('no-page');
    expect(trustHint('iphone', state(), [], T0, T0 + 120_000)).toBeNull();
    expect(trustHint('iphone', on, [page], T0, T0 + 120_000)).toBeNull();
    expect(trustHint('ios-sim', on, [], T0, T0 + 120_000)).toBeNull();
    expect(noPageHint('iphone', true)).toBe('Nothing from the page yet. On the phone, type http://mitm.it exactly (not https) in Safari, with the WireGuard tunnel on.');
    expect(noPageHint('android', false)).toContain('in Chrome, with the Wi-Fi proxy set');
  });

  it('shows the not-trusted message on the Trust step when TLS failures arrive', () => {
    expect(trustHint('android', state({ device_seen_at: 1, tls_failures: 2 }), [page, cert], T0, T0)).toBe('not-trusted');
    expect(trustHint('android', state({ device_seen_at: 1, tls_failures: 2 }), [api], T0, T0)).toBeNull();
  });

  it('hints what to check only after 30 s on the Check step, connected, with nothing from the app', () => {
    const on = state({ device_seen_at: 1 });
    expect(appHint(on, [page, cert], T0, T0 + 29_999)).toBeNull();
    expect(appHint(on, [page, cert], T0, T0 + 30_000)).toBe('no-traffic');
    expect(appHint(state(), [], T0, T0 + 60_000)).toBeNull();
    expect(appHint(on, [api], T0, T0 + 60_000)).toBeNull();
    expect(appHint(state({ device_seen_at: 1, tls_failures: 1 }), [], T0, T0)).toBe('not-trusted');
  });

  it('lists the checks with the preset and its API hosts', () => {
    const checks = appChecks('android', true, 'staging', ['api.example.com', 'auth.example.com']);
    expect(checks[0]).toBe('The app is a QA build for the environment of the preset staging.');
    expect(checks[1]).toBe("It talks to the preset's API hosts: api.example.com, auth.example.com.");
    expect(checks[3]).toBe('The WireGuard tunnel is still on.');
    expect(appChecks('iphone', false, 'staging', [])[1]).toContain('the API hosts in your preset file');
  });

  it('gives the Samsung path and a search fallback for the Android Wi-Fi proxy', () => {
    const text = proxySteps('android', '192.0.2.7', 8080).map((s) => s.text).join(' ');
    expect(text).toContain('Advanced options → Proxy → Manual');
    expect(text).toContain('Samsung: Settings → Connections → Wi-Fi → the gear next to the network → View more → Proxy → Manual');
    expect(text).toContain('Search Settings for "Proxy"');
  });

  it('sums up what is set up and what to do next time', () => {
    const items = setupSummary('iphone', state({ device_seen_at: 1 }), [api]);
    expect(items.map((i) => [i.label, i.done])).toEqual([
      ['iPhone connected to this Mac through WireGuard', true],
      ["Wiretrace trusted, and the app's requests arrive", true],
      ['Device logs off (optional)', false],
    ]);
    expect(nextTime('iphone', true)).toBe('Next time: switch the WireGuard tunnel on, then start Wiretrace. The certificate stays installed.');
    expect(nextTime('android', false)).toContain('set the Wi-Fi proxy again');
  });
});
