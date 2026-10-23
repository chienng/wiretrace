/** Spec 022, slice C: encrypted connections, and decrypting their host from the window. */
import type { AppState, TrafficRow, TunnelRow } from '../types';
import { formatDuration } from './format';

const KEY = 'wiretrace.showEncrypted';
const HIDDEN = 'hidden';
/** The server's preset/MAX_ENTRIES and TEMPLATE. */
export const MAX_API_HOSTS = 50;
export const TEMPLATE = 'example';

/** cli/preset.py SECOND_LEVEL_SUFFIXES: a two-label parent starting with one is a public suffix such as co.uk. */
const SECOND_LEVEL_SUFFIXES = new Set(['co', 'com', 'net', 'org', 'gov', 'edu', 'ac']);

function isIpAddress(host: string): boolean {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(':');
}

/** The same choices as cli/preset.py decrypt_choices: the host, then its parent when that is a domain. */
export function decryptChoices(host: string): string[] {
  const h = host.toLowerCase().replace(/\.$/, '');
  if (isIpAddress(h)) return [h];
  const parent = h.split('.').slice(1);
  if (parent.length < 2 || (parent.length === 2 && SECOND_LEVEL_SUFFIXES.has(parent[0] as string))) return [h];
  return [h, parent.join('.')];
}

/** An API host decrypts itself and its subdomains. */
export function covered(apiHosts: readonly string[], host: string): boolean {
  const h = host.toLowerCase();
  return apiHosts.some((a) => h === a.toLowerCase() || h.endsWith(`.${a.toLowerCase()}`));
}

/** Why Decrypt is off for this host, or null; the server checks the same. */
export function decryptOff(state: Pick<AppState, 'preset' | 'api_hosts'> | null, host: string, viewing: string | null): string | null {
  if (viewing) return 'Decrypting is off while a previous session is open';
  if (!state) return 'Not connected';
  if (host.includes(':')) return 'Only a host name can be decrypted, not an IPv6 address';
  if (state.preset === TEMPLATE) return 'The example preset is a template: start a session with another preset';
  if (covered(state.api_hosts, host)) return `${host} is already decrypted in this session`;
  if (state.api_hosts.length >= MAX_API_HOSTS) return `The preset already has ${MAX_API_HOSTS} API hosts`;
  return null;
}

export function isTunnel(row: TrafficRow): row is TunnelRow {
  return 'answer' in row;
}

/** "open" until it closes. */
export function openFor(row: Pick<TunnelRow, 'ts' | 'closed_at'>): string {
  if (row.closed_at === null) return 'open';
  const ms = Math.max(0, (row.closed_at - row.ts) * 1000);
  return ms < 1000 ? formatDuration(ms) : `${(ms / 1000).toFixed(1)} s`;
}

export function hostPort(row: Pick<TunnelRow, 'host' | 'port'>): string {
  return row.port === null ? row.host : `${row.host}:${row.port}`;
}

export function tunnelTag(row: Pick<TunnelRow, 'tls'>): string {
  return row.tls ? 'Encrypted' : 'Passed through';
}

export function notDecryptedText(host: string, preset: string): string {
  return `${host} is not one of the API hosts of preset ${preset}, so Wiretrace passes this connection through without reading it. Decrypt the host to see its requests and responses.`;
}

export const decryptTitle = (host: string) => `Decrypt ${host}?`;
export const decryptMenuLabel = (host: string) => `Decrypt ${host}… (and subdomains)`;

export function choiceNote(choice: string, host: string): string {
  return choice === host ? 'and its subdomains' : `and every subdomain, ${host} included`;
}

export const DECRYPT_NOTES = [
  'New connections to this host are decrypted. Connections already open stay encrypted until the app opens new ones; reopening the app is the sure way.',
  "The phone must trust Wiretrace's certificate. An app that pins its certificates fails these requests; the device's warning count shows it.",
];

export function hostsLine(preset: string, count: number): string {
  return `presets/${preset}.yaml · ${count} → ${count + 1} API hosts`;
}

export function decryptedToast(host: string): string {
  return `${host} is decrypted from its next connection`;
}

/** Show encrypted, in this browser; on unless the tester turned it off. */
export function loadShowEncrypted(storage: Pick<Storage, 'getItem'> | null): boolean {
  try {
    return storage?.getItem(KEY) !== HIDDEN;
  } catch {
    return true;
  }
}

export function storeShowEncrypted(storage: Pick<Storage, 'setItem' | 'removeItem'> | null, show: boolean): void {
  try {
    if (show) storage?.removeItem(KEY);
    else storage?.setItem(KEY, HIDDEN);
  } catch {
    // Storage full or off: the choice lasts until the window reloads.
  }
}
