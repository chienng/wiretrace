import type { AppState, ProxyWaiting } from '../types';

const KEY = 'wiretrace.proxyIgnored';
const MAX_IGNORED = 32;

/** The kinds a switch to a refused device offers: the ones that connect over Wi-Fi. */
export const CLIENT_TARGETS = ['ios', 'android', 'device'] as const;

export interface ProxyBanner {
  device: ProxyWaiting;
  accepted: string;
  /** Other waiting devices, not ignored. */
  more: number;
}

type BannerState = Pick<AppState, 'proxy_pin' | 'proxy_device' | 'proxy_waiting' | 'mode'>;

/** The live session pins a device and another one was refused: the most recent one not ignored. */
export function proxyBanner(state: BannerState | null, viewing: string | null, ignored: ReadonlySet<string>): ProxyBanner | null {
  if (!state || !state.proxy_pin || !state.proxy_device || viewing || state.mode === 'wireguard') return null;
  const shown = state.proxy_waiting
    .filter((w) => w.address !== state.proxy_device && !ignored.has(w.address))
    .sort((a, b) => b.last_at - a.last_at);
  const [device] = shown;
  if (!device) return null;
  return { device, accepted: state.proxy_device, more: shown.length - 1 };
}

/** Unix seconds → HH:MM in local time. */
export function clock(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function bannerText(banner: ProxyBanner): string {
  return (
    `Another device wants to use the Wi-Fi proxy: ${banner.device.address}, since ${clock(banner.device.first_at)}. ` +
    `Only ${banner.accepted} is accepted in this session.`
  );
}

export function moreText(more: number): string {
  return more > 0 ? `+${more} more` : '';
}

/** Setup's Connect step and the device menu's tooltip. */
export function acceptingLine(state: Pick<AppState, 'proxy_device'>): string | null {
  return state.proxy_device ? `Wi-Fi proxy: accepting ${state.proxy_device}` : null;
}

export function deviceMenuTitle(base: string, state: Pick<AppState, 'proxy_device'>, viewing: string | null): string {
  const line = viewing ? null : acceptingLine(state);
  return line ? `${base}\n${line}` : base;
}

export function switchTitle(address: string): string {
  return `Switch to the device at ${address}?`;
}

export function switchLead(accepted: string): string {
  return (
    'This session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy; ' +
    `the device at ${accepted} is refused until you switch back.`
  );
}

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
