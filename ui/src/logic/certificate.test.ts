import { describe, expect, it } from 'vitest';
import { certificateSteps } from './certificate';

/** The first group's steps as one text. */
const firstSteps = (target: string, wireguard = true): string =>
  (certificateSteps(target, wireguard)[0]?.steps ?? []).map((s) => s.text).join('\n');

describe('certificate steps', () => {
  it('installs the iPhone profile before turning on its trust', () => {
    // Regression: the steps went from mitm.it straight to Certificate Trust Settings, where the
    // switch does not exist until the downloaded profile is installed.
    expect(certificateSteps('ios', true).map((g) => g.platform)).toEqual(['iPhone']);
    const steps = firstSteps('ios');
    const install = steps.indexOf('VPN & Device Management');
    const trust = steps.indexOf('Certificate Trust Settings');
    expect(install).toBeGreaterThan(steps.indexOf('http://mitm.it'));
    expect(trust).toBeGreaterThan(install);
    expect(steps).toContain('Safari');
  });

  it('names how the phone is connected', () => {
    expect(firstSteps('ios', true)).toMatch(/^With the WireGuard tunnel on/);
    expect(firstSteps('android', false)).toMatch(/^With the Wi-Fi proxy set/);
  });

  it('gives the Simulator and the emulator a command instead of mitm.it', () => {
    const sim = certificateSteps('ios-sim', false)[0]!;
    expect(sim.steps[0]!.code).toBe('xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem');
    expect(sim.steps.map((s) => s.text).join(' ')).not.toContain('mitm.it');
    const emu = certificateSteps('android-emu', true)[0]!;
    expect(emu.steps[0]!.code).toBe('adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /sdcard/Download/');
    expect(emu.steps.map((s) => s.text).join(' ')).toContain('Install a certificate');
  });

  it('shows both platforms when the target is not known', () => {
    expect(certificateSteps('device', true).map((g) => g.platform)).toEqual(['iPhone', 'Android']);
  });
});
