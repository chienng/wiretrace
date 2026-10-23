import { describe, expect, it } from 'vitest';
import {
  acceptedDevices,
  acceptingLine,
  allowLead,
  allowState,
  allowTitle,
  ALLOW_WARNING,
  bannerText,
  clock,
  deviceMenuTitle,
  deviceText,
  gainsAddress,
  lastPlaceNote,
  listText,
  loadIgnored,
  moreText,
  preselectedKind,
  proxyBanner,
  REMOVE_LEAD,
  removeNote,
  removeTitle,
  storeIgnored,
  switchLead,
  switchTitle,
  tabTitle,
} from './proxyDevices';
import type { ProxyClient, ProxyWaiting } from '../types';

// Specs 021 and 022.

const A = '192.168.2.71';
const B = '192.168.2.72';
const C = '192.168.2.73';
const D = '192.168.2.74';

function waiting(address: string, last_at: number, first_at = last_at): ProxyWaiting {
  return { address, first_at, last_at, count: 1 };
}

function client(address: string): ProxyClient {
  return { address, seen_at: 100, requests: 0, tls_failures: 0 };
}

function state(
  over: Partial<{ proxy_pin: boolean; proxy_clients: ProxyClient[]; proxy_waiting: ProxyWaiting[]; mode: string }> = {},
) {
  return { proxy_pin: true, proxy_clients: [client(A)], proxy_waiting: [waiting(B, 200)], mode: 'both', ...over };
}

describe('which device the banner shows', () => {
  it('shows the waiting device and the accepted ones', () => {
    expect(proxyBanner(state(), null, new Set())).toEqual({ device: waiting(B, 200), accepted: [A], more: 0 });
    const two = state({ proxy_clients: [client(A), client(C)] });
    expect(proxyBanner(two, null, new Set())).toEqual({ device: waiting(B, 200), accepted: [A, C], more: 0 });
  });
  it('shows the most recent one not ignored, and how many more', () => {
    const list = [waiting(C, 100), waiting(B, 300), waiting(D, 200)];
    expect(proxyBanner(state({ proxy_waiting: list }), null, new Set())).toMatchObject({ device: { address: B }, more: 2 });
    expect(proxyBanner(state({ proxy_waiting: list }), null, new Set([B]))).toMatchObject({ device: { address: D }, more: 1 });
  });
  it('hides when every waiting device is ignored, and comes back for another address', () => {
    expect(proxyBanner(state(), null, new Set([B]))).toBeNull();
    const again = state({ proxy_waiting: [waiting(C, 400), waiting(B, 300)] });
    expect(proxyBanner(again, null, new Set([B]))).toMatchObject({ device: { address: C }, more: 0 });
  });
  it('shows with no device accepted, after every one was removed', () => {
    expect(proxyBanner(state({ proxy_clients: [] }), null, new Set())).toEqual({ device: waiting(B, 200), accepted: [], more: 0 });
  });
  it('hides without pinning, in WireGuard mode, while viewing, and before the state loads', () => {
    expect(proxyBanner(state({ proxy_pin: false }), null, new Set())).toBeNull();
    expect(proxyBanner(state({ mode: 'wireguard' }), null, new Set())).toBeNull();
    expect(proxyBanner(state(), '2026-10-19_080000_myapp_ios', new Set())).toBeNull();
    expect(proxyBanner(null, null, new Set())).toBeNull();
    expect(proxyBanner(state({ proxy_waiting: [] }), null, new Set())).toBeNull();
  });
  it('never offers an accepted device', () => {
    expect(proxyBanner(state({ proxy_waiting: [waiting(A, 500)] }), null, new Set())).toBeNull();
  });
  it('takes no accepted list without pinning: the --client devices are not accepted by Allow', () => {
    expect(acceptedDevices(state({ proxy_pin: false }))).toEqual([]);
    expect(acceptedDevices(state({ proxy_clients: [client(A), client(B)] }))).toEqual([A, B]);
  });
});

describe('texts', () => {
  const first = new Date(2026, 9, 19, 19, 21, 30).getTime() / 1000;
  const lead = 'Another device wants to use the Wi-Fi proxy: 192.168.2.72, since 19:21. ';
  it('banner, with the time of the first refusal and every accepted device', () => {
    const banner = (accepted: string[]) => ({ device: waiting(B, first + 600, first), accepted, more: 0 });
    expect(clock(first)).toBe('19:21');
    expect(bannerText(banner([A]))).toBe(`${lead}Only 192.168.2.71 is accepted in this session.`);
    expect(bannerText(banner([A, C]))).toBe(`${lead}Accepted in this session: 192.168.2.71, 192.168.2.73.`);
    expect(bannerText(banner([]))).toBe(`${lead}No other device is accepted in this session.`);
    expect(moreText(0)).toBe('');
    expect(moreText(2)).toBe('+2 more');
  });
  it('lists', () => {
    expect(listText([])).toBe('');
    expect(listText([A])).toBe(A);
    expect(listText([A, B])).toBe(`${A} and ${B}`);
    expect(listText([A, B, C])).toBe(`${A}, ${B} and ${C}`);
  });
  it('switch dialog names every device the next session refuses', () => {
    expect(switchTitle(B)).toBe('Switch to the device at 192.168.2.72?');
    expect(switchLead([A])).toBe(
      'This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy; the device at 192.168.2.71 is refused until you switch back.',
    );
    expect(switchLead([A, C, D])).toBe(
      'This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy; the devices at 192.168.2.71, 192.168.2.73 and 192.168.2.74 are refused until you switch back.',
    );
    expect(switchLead([])).toBe('This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy.');
  });
  it('allow dialog, and the last place', () => {
    expect(allowTitle(D)).toBe('Allow the device at 192.168.2.74?');
    expect(allowLead([A, B, C])).toBe(
      'It can use the Wi-Fi proxy until this session ends, like 192.168.2.71, 192.168.2.72 and 192.168.2.73.',
    );
    expect(allowLead([])).toBe('It can use the Wi-Fi proxy until this session ends.');
    expect(ALLOW_WARNING).toBe(
      "Any device on this network can ask. Check the address in the phone's Wi-Fi settings before you allow it.",
    );
    expect(lastPlaceNote([A, B, C], 4)).toBe('This session accepts 4 devices besides this Mac. This one is the last.');
    expect(lastPlaceNote([A, B], 4)).toBeNull();
  });
  it('Allow… is off once the session accepts as many devices as it may', () => {
    expect(allowState([A, B, C], 4).disabled).toBe(false);
    expect(allowState([A, B, C, D], 4)).toEqual({
      disabled: true,
      title: 'This session accepts 4 devices at most. Switch to it to start a session with only this device.',
    });
  });
  it('remove dialog says who stays accepted', () => {
    expect(removeTitle(C)).toBe('Remove 192.168.2.73 from this session?');
    expect(REMOVE_LEAD).toBe(
      'The Wi-Fi proxy refuses it from now on: its next requests fail. The requests it already made stay in Traffic.',
    );
    expect(removeNote(C, [A, B, C])).toBe(
      'It can ask again: it then shows in the banner, where you can allow it. Still accepted: 192.168.2.71, 192.168.2.72.',
    );
    expect(removeNote(A, [A])).toBe(
      'It can ask again: it then shows in the banner, where you can allow it. No other device is accepted then: each one has to be allowed.',
    );
  });
  it('Setup line and device menu tooltip', () => {
    expect(acceptingLine(state({ proxy_clients: [client(A), client(B)] }))).toBe('Wi-Fi proxy: accepting 192.168.2.71, 192.168.2.72');
    expect(acceptingLine(state({ proxy_clients: [] }))).toBeNull();
    expect(acceptingLine(state({ proxy_pin: false }))).toBeNull();
    expect(deviceMenuTitle('Switch the device', state(), null)).toBe('Switch the device\nWi-Fi proxy: accepting 192.168.2.71');
    expect(deviceMenuTitle('Off', state(), '2026-10-19_080000_myapp_ios')).toBe('Off');
    expect(deviceMenuTitle('Switch the device', state({ proxy_clients: [] }), null)).toBe('Switch the device');
  });
  it('tab title counts the waiting devices', () => {
    expect(tabTitle(0)).toBe('Wiretrace');
    expect(tabTitle(2)).toBe('(2) Wiretrace');
  });
  it('the banner pulses again only for an address that was not waiting', () => {
    expect(gainsAddress(new Set(), [B])).toBe(true);
    expect(gainsAddress(new Set([B]), [B])).toBe(false);
    expect(gainsAddress(new Set([B, C]), [B])).toBe(false);
    expect(gainsAddress(new Set([B]), [C, B])).toBe(true);
  });
  it('Device column', () => {
    expect(deviceText('mac')).toBe('This Mac');
    expect(deviceText('wireguard')).toBe('WireGuard');
    expect(deviceText(A)).toBe(A);
    expect(deviceText(null)).toBe('');
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
