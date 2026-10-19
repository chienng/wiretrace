import { describe, expect, it } from 'vitest';
import {
  acceptingLine,
  bannerText,
  clock,
  deviceMenuTitle,
  loadIgnored,
  moreText,
  preselectedKind,
  proxyBanner,
  storeIgnored,
  switchLead,
  switchTitle,
} from './proxyDevices';
import type { ProxyWaiting } from '../types';

// Spec 021.

const A = '192.168.2.71';
const B = '192.168.2.72';
const C = '192.168.2.73';

function waiting(address: string, last_at: number, first_at = last_at): ProxyWaiting {
  return { address, first_at, last_at, count: 1 };
}

function state(over: Partial<{ proxy_pin: boolean; proxy_device: string | null; proxy_waiting: ProxyWaiting[]; mode: string }> = {}) {
  return { proxy_pin: true, proxy_device: A, proxy_waiting: [waiting(B, 200)], mode: 'both', ...over };
}

describe('which device the banner shows', () => {
  it('shows the waiting device and the accepted one', () => {
    expect(proxyBanner(state(), null, new Set())).toEqual({ device: waiting(B, 200), accepted: A, more: 0 });
  });
  it('shows the most recent one not ignored, and how many more', () => {
    const list = [waiting(C, 100), waiting(B, 300), waiting('192.168.2.74', 200)];
    expect(proxyBanner(state({ proxy_waiting: list }), null, new Set())).toMatchObject({ device: { address: B }, more: 2 });
    expect(proxyBanner(state({ proxy_waiting: list }), null, new Set([B]))).toMatchObject({
      device: { address: '192.168.2.74' },
      more: 1,
    });
  });
  it('hides when every waiting device is ignored, and comes back for another address', () => {
    expect(proxyBanner(state(), null, new Set([B]))).toBeNull();
    const again = state({ proxy_waiting: [waiting(C, 400), waiting(B, 300)] });
    expect(proxyBanner(again, null, new Set([B]))).toMatchObject({ device: { address: C }, more: 0 });
  });
  it('hides without pinning, before a device is pinned, in WireGuard mode, while viewing, and before the state loads', () => {
    expect(proxyBanner(state({ proxy_pin: false }), null, new Set())).toBeNull();
    expect(proxyBanner(state({ proxy_device: null }), null, new Set())).toBeNull();
    expect(proxyBanner(state({ mode: 'wireguard' }), null, new Set())).toBeNull();
    expect(proxyBanner(state(), '2026-10-19_080000_myapp_ios', new Set())).toBeNull();
    expect(proxyBanner(null, null, new Set())).toBeNull();
    expect(proxyBanner(state({ proxy_waiting: [] }), null, new Set())).toBeNull();
  });
  it('never offers the accepted device', () => {
    expect(proxyBanner(state({ proxy_waiting: [waiting(A, 500)] }), null, new Set())).toBeNull();
  });
});

describe('texts', () => {
  it('banner, with the time of the first refusal', () => {
    const first = new Date(2026, 9, 19, 19, 21, 30).getTime() / 1000;
    const banner = { device: waiting(B, first + 600, first), accepted: A, more: 0 };
    expect(clock(first)).toBe('19:21');
    expect(bannerText(banner)).toBe(
      'Another device wants to use the Wi-Fi proxy: 192.168.2.72, since 19:21. Only 192.168.2.71 is accepted in this session.',
    );
    expect(moreText(0)).toBe('');
    expect(moreText(2)).toBe('+2 more');
  });
  it('dialog', () => {
    expect(switchTitle(B)).toBe('Switch to the device at 192.168.2.72?');
    expect(switchLead(A)).toBe(
      'This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy; the device at 192.168.2.71 is refused until you switch back.',
    );
  });
  it('Setup line and device menu tooltip', () => {
    expect(acceptingLine({ proxy_device: A })).toBe('Wi-Fi proxy: accepting 192.168.2.71');
    expect(acceptingLine({ proxy_device: null })).toBeNull();
    expect(deviceMenuTitle('Switch the device', { proxy_device: A }, null)).toBe(
      'Switch the device\nWi-Fi proxy: accepting 192.168.2.71',
    );
    expect(deviceMenuTitle('Off', { proxy_device: A }, '2026-10-19_080000_myapp_ios')).toBe('Off');
    expect(deviceMenuTitle('Switch the device', { proxy_device: null }, null)).toBe('Switch the device');
  });
  it('preselects the kind in use when a phone can be it', () => {
    expect(preselectedKind('ios')).toBe('ios');
    expect(preselectedKind('android')).toBe('android');
    expect(preselectedKind('device')).toBe('device');
    expect(preselectedKind('ios-sim')).toBeNull();
    expect(preselectedKind('android-emu')).toBeNull();
  });
});

describe('ignored addresses', () => {
  function memory(): Map<string, string> & Pick<Storage, 'getItem' | 'setItem'> {
    const items = new Map<string, string>() as Map<string, string> & Pick<Storage, 'getItem' | 'setItem'>;
    items.getItem = (k: string) => items.get(k) ?? null;
    items.setItem = (k: string, v: string) => void items.set(k, v);
    return items;
  }
  const session = '2026-10-19_192100_myapp_ios';

  it('survive a reload of the same session', () => {
    const s = memory();
    expect(loadIgnored(s, session)).toEqual(new Set());
    storeIgnored(s, session, new Set([B]));
    expect(loadIgnored(s, session)).toEqual(new Set([B]));
    expect([...s.keys()]).toEqual(['wiretrace.proxyIgnored']);
  });
  it('reset with a new session name', () => {
    const s = memory();
    storeIgnored(s, session, new Set([B]));
    expect(loadIgnored(s, '2026-10-19_193000_myapp_ios')).toEqual(new Set());
  });
  it('read as none when the storage is missing, refuses, or holds something else', () => {
    const refusing = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    };
    expect(loadIgnored(null, session)).toEqual(new Set());
    expect(loadIgnored(refusing, session)).toEqual(new Set());
    expect(() => storeIgnored(refusing, session, new Set([B]))).not.toThrow();
    const s = memory();
    for (const raw of ['not json', 'null', '[]', JSON.stringify({ session, addresses: 'x' })]) {
      s.setItem('wiretrace.proxyIgnored', raw);
      expect(loadIgnored(s, session)).toEqual(new Set());
    }
    s.setItem('wiretrace.proxyIgnored', JSON.stringify({ session, addresses: [B, 3, null] }));
    expect(loadIgnored(s, session)).toEqual(new Set([B]));
  });
  it('keep at most 32 addresses', () => {
    const s = memory();
    const many = new Set(Array.from({ length: 40 }, (_, i) => `10.0.0.${i}`));
    storeIgnored(s, session, many);
    const kept = loadIgnored(s, session);
    expect(kept.size).toBe(32);
    expect(kept.has('10.0.0.39')).toBe(true);
    expect(kept.has('10.0.0.0')).toBe(false);
  });
});
