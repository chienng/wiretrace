import { describe, expect, it } from 'vitest';
import { loadDismissed, showAppHint, storeDismissed } from './appHint';

// The numbers are spec 019's test numbers.

describe('app hint strip (5)', () => {
  const app = { from_app: true };

  it('shows for an app session not dismissed', () => {
    expect(showAppHint(app, null, false)).toBe(true);
  });
  it('hides once dismissed, for a Terminal session, while viewing, and before the state loads', () => {
    expect(showAppHint(app, null, true)).toBe(false);
    expect(showAppHint({ from_app: false }, null, false)).toBe(false);
    expect(showAppHint(app, '2026-10-15_080000_myapp_android', false)).toBe(false);
    expect(showAppHint(null, null, false)).toBe(false);
  });
});

describe('dismissal (6)', () => {
  function memory(): Map<string, string> & Pick<Storage, 'getItem' | 'setItem'> {
    const items = new Map<string, string>() as Map<string, string> & Pick<Storage, 'getItem' | 'setItem'>;
    items.getItem = (k: string) => items.get(k) ?? null;
    items.setItem = (k: string, v: string) => void items.set(k, v);
    return items;
  }

  it('is kept, and holds only the word dismissed', () => {
    const s = memory();
    expect(loadDismissed(s)).toBe(false);
    storeDismissed(s);
    expect(loadDismissed(s)).toBe(true);
    expect([...s.entries()]).toEqual([['wiretrace.appHint', 'dismissed']]);
  });
  it('reads as not dismissed when the storage is missing or refuses', () => {
    const refusing = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    };
    expect(loadDismissed(null)).toBe(false);
    expect(loadDismissed(refusing)).toBe(false);
    expect(() => storeDismissed(refusing)).not.toThrow();
  });
});
