/** Saved searches, per preset, in the browser's localStorage (spec 008 decision 6): never on disk. */

export interface SavedFilter {
  id: string;
  name: string;
  search: string;
}

export const MAX_SAVED = 50;
export const MAX_NAME = 60;
export const MAX_SEARCH = 2000;
const PREFIX = 'wiretrace.savedFilters.';

export function storageKey(preset: string): string {
  return PREFIX + preset;
}

function valid(x: unknown): x is SavedFilter {
  if (!x || typeof x !== 'object') return false;
  const f = x as Record<string, unknown>;
  return typeof f.id === 'string' && typeof f.name === 'string' && typeof f.search === 'string' && f.name.trim() !== '';
}

/** The saved filters of a preset; anything unreadable is left out. */
export function loadSaved(storage: Pick<Storage, 'getItem'> | null, preset: string): SavedFilter[] {
  if (!storage) return [];
  try {
    const parsed: unknown = JSON.parse(storage.getItem(storageKey(preset)) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter(valid).slice(0, MAX_SAVED) : [];
  } catch {
    return [];
  }
}

/** False when the browser refused (storage full or off). */
export function storeSaved(storage: Pick<Storage, 'setItem'> | null, preset: string, list: readonly SavedFilter[]): boolean {
  if (!storage) return false;
  try {
    storage.setItem(storageKey(preset), JSON.stringify(list));
    return true;
  } catch {
    return false;
  }
}

export function cleanName(name: string): string {
  return name.replace(/\s+/g, ' ').trim().slice(0, MAX_NAME);
}

/** Save `search` under `name`; the same name (ignoring case) is replaced, in place. */
export function addSaved(list: readonly SavedFilter[], name: string, search: string, id: string): SavedFilter[] {
  const clean = cleanName(name);
  const text = search.trim().slice(0, MAX_SEARCH);
  if (!clean || !text) return [...list];
  const same = list.findIndex((f) => f.name.toLowerCase() === clean.toLowerCase());
  if (same >= 0) return list.map((f, i) => (i === same ? { ...f, name: clean, search: text } : f));
  return [...list, { id, name: clean, search: text }].slice(-MAX_SAVED);
}

export function renameSaved(list: readonly SavedFilter[], id: string, name: string): SavedFilter[] {
  const clean = cleanName(name);
  if (!clean) return [...list];
  return list.map((f) => (f.id === id ? { ...f, name: clean } : f));
}

export function removeSaved(list: readonly SavedFilter[], id: string): SavedFilter[] {
  return list.filter((f) => f.id !== id);
}
