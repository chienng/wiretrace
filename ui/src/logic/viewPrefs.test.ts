import { describe, expect, it } from 'vitest';
import { loadBodyView, loadSidebarHidden, storeBodyView, storeSidebarHidden } from './viewPrefs';

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

const refusing = {
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('QuotaExceededError');
  },
  removeItem: () => {
    throw new Error('SecurityError');
  },
};

describe('sidebar choice', () => {
  const key = 'wiretrace.pane.traffic.sidebar.state';

  it('is hidden only when stored as hidden', () => {
    expect(loadSidebarHidden(memory({ [key]: 'hidden' }))).toBe(true);
    for (const raw of ['', 'shown', 'HIDDEN', '1']) expect(loadSidebarHidden(memory({ [key]: raw }))).toBe(false);
    expect(loadSidebarHidden(memory())).toBe(false);
    expect(loadSidebarHidden(null)).toBe(false);
    expect(loadSidebarHidden(refusing)).toBe(false);
  });

  it('removes the key when shown again, and leaves the width alone', () => {
    const s = memory({ 'wiretrace.pane.traffic.sidebar': '300' });
    storeSidebarHidden(s, true);
    expect(s.data.get(key)).toBe('hidden');
    storeSidebarHidden(s, false);
    expect(s.data.has(key)).toBe(false);
    expect(s.data.get('wiretrace.pane.traffic.sidebar')).toBe('300');
  });

  it('survives a browser that refuses to store', () => {
    expect(() => storeSidebarHidden(refusing, true)).not.toThrow();
    expect(() => storeSidebarHidden(null, true)).not.toThrow();
  });
});

describe('body view choice', () => {
  const key = 'wiretrace.body.view';

  it('is JSON Text only when stored as text', () => {
    expect(loadBodyView(memory({ [key]: 'text' }))).toBe('text');
    for (const raw of ['', 'json', 'TEXT', 'raw']) expect(loadBodyView(memory({ [key]: raw }))).toBe('json');
    expect(loadBodyView(memory())).toBe('json');
    expect(loadBodyView(null)).toBe('json');
    expect(loadBodyView(refusing)).toBe('json');
  });

  it('removes the key when set back to JSON', () => {
    const s = memory();
    storeBodyView(s, 'text');
    expect(s.data.get(key)).toBe('text');
    storeBodyView(s, 'json');
    expect(s.data.has(key)).toBe(false);
  });

  it('survives a browser that refuses to store', () => {
    expect(() => storeBodyView(refusing, 'text')).not.toThrow();
    expect(() => storeBodyView(null, 'text')).not.toThrow();
  });
});
