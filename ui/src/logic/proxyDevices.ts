import type { AppState, ProxyWaiting } from '../types';

const KEY = 'wiretrace.proxyIgnored';
const MAX_IGNORED = 32;

/** The kinds a switch to a refused device offers: the ones that connect over Wi-Fi. */
export const CLIENT_TARGETS = ['ios', 'android', 'device'] as const;

export interface ProxyBanner {
  device: ProxyWaiting;
  /** The devices accepted in this session besides this Mac, in the order they were accepted. */
  accepted: string[];
  /** Other waiting devices, not ignored. */
  more: number;
}

type DeviceState = Pick<AppState, 'proxy_pin' | 'proxy_clients'>;
type BannerState = DeviceState & Pick<AppState, 'proxy_waiting' | 'mode'>;

/** The devices the Wi-Fi proxy accepts besides this Mac; empty without pinning. */
export function acceptedDevices(state: DeviceState): string[] {
  return state.proxy_pin ? state.proxy_clients.map((c) => c.address) : [];
}

/** The live session pins devices and another one was refused: the most recent one not ignored. */
export function proxyBanner(state: BannerState | null, viewing: string | null, ignored: ReadonlySet<string>): ProxyBanner | null {
  if (!state || !state.proxy_pin || viewing || state.mode === 'wireguard') return null;
  const accepted = acceptedDevices(state);
  const shown = state.proxy_waiting
    .filter((w) => !accepted.includes(w.address) && !ignored.has(w.address))
    .sort((a, b) => b.last_at - a.last_at);
  const [device] = shown;
  if (!device) return null;
  return { device, accepted, more: shown.length - 1 };
}

/** Unix seconds → HH:MM in local time. */
export function clock(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** "A", "A and B", "A, B and C". */
export function listText(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

export function bannerText(banner: ProxyBanner): string {
  const lead = `Another device wants to use the Wi-Fi proxy: ${banner.device.address}, since ${clock(banner.device.first_at)}. `;
  if (banner.accepted.length === 0) return `${lead}No other device is accepted in this session.`;
  if (banner.accepted.length === 1) return `${lead}Only ${banner.accepted[0]} is accepted in this session.`;
  return `${lead}Accepted in this session: ${banner.accepted.join(', ')}.`;
}

export function moreText(more: number): string {
  return more > 0 ? `+${more} more` : '';
}

/** The tab title: the number of devices waiting in front, so a background tab shows it too. */
export function tabTitle(waiting: number): string {
  return waiting > 0 ? `(${waiting}) Wiretrace` : 'Wiretrace';
}

/** The banner pulses again only when an address appears that was not waiting before. */
export function gainsAddress(before: ReadonlySet<string>, now: readonly string[]): boolean {
  return now.some((address) => !before.has(address));
}

export const AT_MOST_TITLE = (max: number) =>
  `This session accepts ${max} devices at most. Switch to it to start a session with only this device.`;

/** Allow… in the banner: disabled once the session accepts as many devices as it may. */
export function allowState(accepted: readonly string[], max: number): { disabled: boolean; title: string } {
  if (accepted.length >= max) return { disabled: true, title: AT_MOST_TITLE(max) };
  return { disabled: false, title: 'Let this device use the Wi-Fi proxy in this session' };
}

export function allowTitle(address: string): string {
  return `Allow the device at ${address}?`;
}

export function allowLead(accepted: readonly string[]): string {
  const like = accepted.length ? `, like ${listText(accepted)}` : '';
  return `It can use the Wi-Fi proxy until this session ends${like}.`;
}

export const ALLOW_WARNING =
  "Any device on this network can ask. Check the address in the phone's Wi-Fi settings before you allow it.";

/** Said when this device takes the last place. */
export function lastPlaceNote(accepted: readonly string[], max: number): string | null {
  return accepted.length === max - 1 ? `This session accepts ${max} devices besides this Mac. This one is the last.` : null;
}

export function removeTitle(address: string): string {
  return `Remove ${address} from this session?`;
}

export const REMOVE_LEAD =
  'The Wi-Fi proxy refuses it from now on: its next requests fail. The requests it already made stay in Traffic.';

export function removeNote(address: string, accepted: readonly string[]): string {
  const others = accepted.filter((a) => a !== address);
  const still = others.length
    ? `Still accepted: ${others.join(', ')}.`
    : 'No other device is accepted then: each one has to be allowed.';
  return `It can ask again: it then shows in the banner, where you can allow it. ${still}`;
}

/** Setup's Connect step and the device menu's tooltip. */
export function acceptingLine(state: DeviceState): string | null {
  const accepted = acceptedDevices(state);
  return accepted.length ? `Wi-Fi proxy: accepting ${accepted.join(', ')}` : null;
}

export function deviceMenuTitle(base: string, state: DeviceState, viewing: string | null): string {
  const line = viewing ? null : acceptingLine(state);
  return line ? `${base}\n${line}` : base;
}

export function switchTitle(address: string): string {
  return `Switch to the device at ${address}?`;
}

export function switchLead(accepted: readonly string[]): string {
  const lead = 'This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy';
  if (accepted.length === 0) return `${lead}.`;
  const who = accepted.length === 1 ? `the device at ${accepted[0]} is` : `the devices at ${listText(accepted)} are`;
  return `${lead}; ${who} refused until you switch back.`;
}

/** The Device column and the detail header: the address, or what a loopback or tunnel client is. */
export function deviceText(client: string | null | undefined): string {
  if (client === 'mac') return 'This Mac';
  if (client === 'wireguard') return 'WireGuard';
  return client ?? '';
}

export const TLS_FAILING_TITLE = 'Does not trust the certificate yet';

/** The kind chosen when the dialog opens: the one in use, when a phone can be it. */
export function preselectedKind(target: string): string | null {
  return (CLIENT_TARGETS as readonly string[]).includes(target) ? target : null;
}

/** Addresses ignored in this session, from this tab's storage; another session name reads as none. */
export function loadIgnored(storage: Pick<Storage, 'getItem'> | null, session: string): Set<string> {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return new Set();
    const data: unknown = JSON.parse(raw);
    if (!data || typeof data !== 'object') return new Set();
    const { session: saved, addresses } = data as { session?: unknown; addresses?: unknown };
    if (saved !== session || !Array.isArray(addresses)) return new Set();
    return new Set(addresses.filter((a): a is string => typeof a === 'string'));
  } catch {
    return new Set();
  }
}

/** Ignore adds the address for this session; the kept list replaces any other session's. */
export function storeIgnored(storage: Pick<Storage, 'setItem'> | null, session: string, ignored: ReadonlySet<string>): void {
  try {
    storage?.setItem(KEY, JSON.stringify({ session, addresses: [...ignored].slice(-MAX_IGNORED) }));
  } catch {
    // Storage full or off: the address stays ignored until the page reloads.
  }
}
