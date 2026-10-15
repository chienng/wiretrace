import { describe, expect, it } from 'vitest';
import {
  deviceFromTarget,
  DEVICES,
  emulatorConf,
  endpointOf,
  firstApiFlow,
  needsProxy,
  proxyCommand,
  proxySteps,
  tunnelSteps,
} from './setup';
import { flow } from './testing';

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
    expect(tunnelSteps('android-emu').map((s) => s.code).filter(Boolean)).toEqual(['adb push wiretrace.conf /sdcard/Download/']);
  });

  it('turns green only for a request to an API host, not the certificate page', () => {
    expect(firstApiFlow([flow({ host: 'mitm.it' })])).toBeNull();
    expect(firstApiFlow([flow({ id: 'a', host: 'mitm.it' }), flow({ id: 'b', host: 'api.example.com' })])?.id).toBe('b');
    expect(firstApiFlow([])).toBeNull();
  });
});
