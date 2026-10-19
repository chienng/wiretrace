import { describe, expect, it } from 'vitest';
import type { AppState, DeviceInfo } from '../types';
import { OFF_WHILE_VIEWING } from './presets';
import {
  clearResume,
  RESUME_MAX_AGE_MS,
  storeResume,
  takeResume,
  wizardSwitch,
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
  loadChoice,
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
  storeChoice,
  trustChecklist,
  trustHint,
  tunnelSteps,
  wireguardSteps,
  type ConnectionChoice,
  type DeviceKind,
} from './setup';
import { flow } from './testing';

function state(over: Partial<AppState> = {}): AppState {
  return { mode: 'wireguard', preset: 'staging', device_seen_at: null, tls_failures: 0, device_logs: null, ...over } as AppState;
}

const T0 = 1_700_000_000_000;
const page = flow({ id: 'p', host: 'mitm.it', path: '/' });
const cert = flow({ id: 'c', host: 'mitm.it', path: '/cert/pem' });
const api = flow({ id: 'a', host: 'api.example.com' });
const HOSTS = ['api.example.com'];

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
    expect(firstApiFlow([flow({ host: 'mitm.it' })], HOSTS)).toBeNull();
    expect(firstApiFlow([flow({ id: 'a', host: 'mitm.it' }), flow({ id: 'b', host: 'api.example.com' })], HOSTS)?.id).toBe('b');
    expect(firstApiFlow([flow({ id: 's', host: 'eu.API.example.com.' })], HOSTS)?.id).toBe('s');
    expect(firstApiFlow([], HOSTS)).toBeNull();
  });

  it('does not count plain HTTP to another host as trusted', () => {
    // Regression: an iPhone's OCSP checks over plain HTTP were listed and ticked Trusted and
    // Check the app, though no request had reached an API host.
    const ocsp = flow({ id: 'o', scheme: 'http', host: 'ocsp.digicert.com', path: '/ME8wTTBLMEkw' });
    expect(firstApiFlow([page, ocsp], HOSTS)).toBeNull();
    expect(trustChecklist('iphone', [page, ocsp], HOSTS).map((i) => i.done)).toEqual([true, false, false]);
    expect(stepDone('check', state(), [ocsp], HOSTS)).toBe(false);
    expect(firstApiFlow([api], [])).toBeNull();
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
    expect(onboardingProgress([], HOSTS)).toEqual({ pageOpened: false, certDownloaded: false });
    expect(onboardingProgress([page], HOSTS)).toEqual({ pageOpened: true, certDownloaded: false });
    expect(onboardingProgress([page, cert], HOSTS)).toEqual({ pageOpened: true, certDownloaded: true });
    expect(onboardingProgress([flow({ host: 'MITM.IT.', path: '/cert/cer' })], HOSTS)).toEqual({ pageOpened: true, certDownloaded: true });
    expect(onboardingProgress([flow({ host: 'mitm.it', path: '/certificates' })], HOSTS).certDownloaded).toBe(false);
  });

  it('keeps the page and the download ticked by an API request when the cap dropped them', () => {
    expect(onboardingProgress([api], HOSTS)).toEqual({ pageOpened: true, certDownloaded: true });
    expect(trustChecklist('android', [api], HOSTS).every((i) => i.done)).toBe(true);
  });

  it('lists the page and the download only for a device that opens mitm.it', () => {
    expect(trustChecklist('iphone', [page], HOSTS).map((i) => [i.label, i.done])).toEqual([
      ['Page opened on the phone', true],
      ['Certificate downloaded', false],
      ['Trusted: the first request to an API host arrived', false],
    ]);
    expect(trustChecklist('ios-sim', [], HOSTS).map((i) => i.label)).toEqual(['Trusted: the first request to an API host arrived']);
    expect(trustChecklist('android-emu', [], HOSTS).length).toBe(1);
  });

  it('marks each step done from its live check', () => {
    expect(stepDone('connect', state(), [], HOSTS)).toBe(false);
    expect(stepDone('connect', state({ device_seen_at: 1 }), [], HOSTS)).toBe(true);
    expect(stepDone('trust', state(), [page, cert], HOSTS)).toBe(false);
    expect(stepDone('trust', state(), [api], HOSTS)).toBe(true);
    expect(stepDone('check', state(), [api], HOSTS)).toBe(true);
    expect(stepDone('logs', state(), [], HOSTS)).toBe(false);
    expect(stepDone('logs', state({ device_logs: 'Android' }), [], HOSTS)).toBe(true);
    expect(nextLabel(true, 'trust')).toBe('Done — Next: Trust Wiretrace');
    expect(nextLabel(false, 'check')).toBe('Next: Check the app');
  });

  it('hints at the address only after 60 s on the Trust step, connected, without a request to mitm.it', () => {
    const on = state({ device_seen_at: 1 });
    expect(trustHint('iphone', on, [], HOSTS, T0, T0 + 59_999)).toBeNull();
    expect(trustHint('iphone', on, [], HOSTS, T0, T0 + 60_000)).toBe('no-page');
    expect(trustHint('iphone', state(), [], HOSTS, T0, T0 + 120_000)).toBeNull();
    expect(trustHint('iphone', on, [page], HOSTS, T0, T0 + 120_000)).toBeNull();
    expect(trustHint('ios-sim', on, [], HOSTS, T0, T0 + 120_000)).toBeNull();
    expect(noPageHint('iphone', true)).toBe('Nothing from the page yet. On the phone, type http://mitm.it exactly (not https) in Safari, with the WireGuard tunnel on.');
    expect(noPageHint('android', false)).toContain('in Chrome, with the Wi-Fi proxy set');
  });

  it('shows the not-trusted message on the Trust step when TLS failures arrive', () => {
    expect(trustHint('android', state({ device_seen_at: 1, tls_failures: 2 }), [page, cert], HOSTS, T0, T0)).toBe('not-trusted');
    expect(trustHint('android', state({ device_seen_at: 1, tls_failures: 2 }), [api], HOSTS, T0, T0)).toBeNull();
  });

  it('hints what to check only after 30 s on the Check step, connected, with nothing from the app', () => {
    const on = state({ device_seen_at: 1 });
    expect(appHint(on, [page, cert], HOSTS, T0, T0 + 29_999)).toBeNull();
    expect(appHint(on, [page, cert], HOSTS, T0, T0 + 30_000)).toBe('no-traffic');
    expect(appHint(state(), [], HOSTS, T0, T0 + 60_000)).toBeNull();
    expect(appHint(on, [api], HOSTS, T0, T0 + 60_000)).toBeNull();
    expect(appHint(state({ device_seen_at: 1, tls_failures: 1 }), [], HOSTS, T0, T0)).toBe('not-trusted');
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
    const items = setupSummary('iphone', state({ device_seen_at: 1 }), [api], HOSTS);
    expect(items.map((i) => [i.label, i.done])).toEqual([
      ['iPhone connected to this Mac through WireGuard', true],
      ["Wiretrace trusted, and the app's requests arrive", true],
      ['Device logs off (optional)', false],
    ]);
    expect(nextTime('iphone', true)).toBe('Next time: switch the WireGuard tunnel on, then start Wiretrace. The certificate stays installed.');
    expect(nextTime('android', false)).toContain('set the Wi-Fi proxy again');
  });
});

describe('setup wizard with the proxy and WireGuard together', () => {
  const KINDS: DeviceKind[] = ['iphone', 'android', 'ios-sim', 'android-emu'];
  const CHOICES: ConnectionChoice[] = ['proxy', 'wireguard'];

  it('follows the mode, and the choice only in both mode', () => {
    for (const kind of KINDS) {
      for (const choice of CHOICES) {
        expect(wireguardSteps('proxy', choice, kind)).toBe(false);
        expect(wireguardSteps('wireguard', choice, kind)).toBe(!needsProxy(kind));
        expect(wireguardSteps('both', choice, kind)).toBe(choice === 'wireguard' && !needsProxy(kind));
      }
    }
  });

  it('always gives the iOS Simulator the proxy steps', () => {
    for (const mode of ['both', 'wireguard', 'proxy']) {
      for (const choice of CHOICES) expect(wireguardSteps(mode, choice, 'ios-sim')).toBe(false);
    }
  });

  it('starts on the Wi-Fi proxy and remembers the choice', () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(loadChoice(storage)).toBe('proxy');
    storeChoice(storage, 'wireguard');
    expect(loadChoice(storage)).toBe('wireguard');
    storeChoice(storage, 'proxy');
    expect(loadChoice(storage)).toBe('proxy');
  });

  it('reads a missing, unknown or unreadable stored value as the Wi-Fi proxy', () => {
    expect(loadChoice(null)).toBe('proxy');
    for (const value of ['', 'WireGuard', 'both', 'tunnel']) {
      expect(loadChoice({ getItem: () => value })).toBe('proxy');
    }
    expect(
      loadChoice({
        getItem: () => {
          throw new Error('denied');
        },
      }),
    ).toBe('proxy');
    expect(() =>
      storeChoice(
        {
          setItem: () => {
            throw new Error('full');
          },
        },
        'wireguard',
      ),
    ).not.toThrow();
  });

  it('sums up the way the device connects in both mode', () => {
    const both = state({ mode: 'both', device_seen_at: 1 });
    expect(setupSummary('iphone', both, [api], HOSTS, 'proxy')[0]?.label).toBe('iPhone connected to this Mac through the proxy');
    expect(setupSummary('iphone', both, [api], HOSTS, 'wireguard')[0]?.label).toBe('iPhone connected to this Mac through WireGuard');
    expect(setupSummary('ios-sim', both, [api], HOSTS, 'wireguard')[0]?.label).toBe('iOS Simulator connected to this Mac through the proxy');
    expect(setupSummary('iphone', both, [api], HOSTS)[0]?.label).toContain('through the proxy');
  });
});

function device(over: Partial<DeviceInfo> = {}): DeviceInfo {
  return { target: 'android', label: 'Android phone', allowed: true, why_not: null, device_logs: 'com.example.app', ...over };
}

describe('switching from the wizard (spec 018, A-10)', () => {
  const android = device();
  const sim = device({ target: 'ios-sim', label: 'iOS Simulator', allowed: false, why_not: 'The iOS Simulator needs the Wi-Fi proxy' });

  it('shows no box when the chosen card is the session device', () => {
    expect(wizardSwitch('iphone', 'ios', [android], null, null)).toBeNull();
    expect(wizardSwitch('android', 'android', [android], null, null)).toBeNull();
  });
  it('names the session device and offers the chosen one', () => {
    expect(wizardSwitch('android', 'ios', [android], null, null)).toEqual({
      note: 'This session collects iPhone logs.',
      button: 'Use Android for this session',
      device: android,
      disabled: false,
    });
  });
  it('is disabled with why_not when /api/devices does not allow that device', () => {
    expect(wizardSwitch('ios-sim', 'ios', [android, sim], null, null)).toMatchObject({ disabled: true, title: sim.why_not });
  });
  it('is disabled while a previous session is open', () => {
    expect(wizardSwitch('android', 'ios', [android], null, '2026-10-15_080000_myapp_android')).toMatchObject({ disabled: true, title: OFF_WHILE_VIEWING });
  });
  it('waits for the list, and says why when it failed', () => {
    expect(wizardSwitch('android', 'ios', null, null, null)).toMatchObject({ disabled: true, title: 'Loading the devices…' });
    expect(wizardSwitch('android', 'ios', null, 'Forbidden', null)).toMatchObject({ disabled: true, title: 'Forbidden' });
  });
  it('says there are no device logs for --target device', () => {
    expect(wizardSwitch('android', 'device', [android], null, null)?.note).toBe('This session collects no device logs.');
  });
});

function memory(): Storage {
  const items = new Map<string, string>();
  return {
    getItem: (k: string) => items.get(k) ?? null,
    setItem: (k: string, v: string) => void items.set(k, v),
    removeItem: (k: string) => void items.delete(k),
    clear: () => items.clear(),
    key: () => null,
    get length() {
      return items.size;
    },
  };
}

describe('resume entry (spec 018, A-11)', () => {
  const now = 1_760_000_000_000;

  it('opens Setup at Connect when fresh, and is removed', () => {
    const s = memory();
    storeResume(s, now - 5_000);
    expect(takeResume(s, now)).toBe(true);
    expect(s.getItem('wiretrace.resume')).toBeNull();
    expect(takeResume(s, now)).toBe(false);
  });
  it('holds only the step and the time', () => {
    const s = memory();
    storeResume(s, now);
    expect(JSON.parse(s.getItem('wiretrace.resume') as string)).toEqual({ step: 'connect', at: now });
  });
  it('is ignored when older than two minutes, and removed', () => {
    const s = memory();
    storeResume(s, now - RESUME_MAX_AGE_MS - 1);
    expect(takeResume(s, now)).toBe(false);
    expect(s.getItem('wiretrace.resume')).toBeNull();
  });
  it('is ignored when malformed or absent', () => {
    const s = memory();
    for (const raw of ['not json', 'null', '"connect"', '{"step":"trust","at":0}', `{"step":"connect","at":"${now}"}`]) {
      s.setItem('wiretrace.resume', raw);
      expect(takeResume(s, now)).toBe(false);
    }
    expect(takeResume(s, now)).toBe(false);
    expect(takeResume(null, now)).toBe(false);
  });
  it('can be withdrawn when the switch does not happen', () => {
    const s = memory();
    storeResume(s, now);
    clearResume(s);
    expect(takeResume(s, now)).toBe(false);
  });
});
