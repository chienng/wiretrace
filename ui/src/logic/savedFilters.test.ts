import { describe, expect, it } from 'vitest';
import { MAX_NAME, MAX_SAVED, addSaved, cleanName, loadSaved, removeSaved, renameSaved, storageKey, storeSaved, type SavedFilter } from './savedFilters';

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe('saved filters', () => {
  it('are kept per preset', () => {
    const s = memory();
    const list = addSaved([], 'Checkout errors', '~u /checkout & ~c 500', 'id1');
    expect(storeSaved(s, 'myapp', list)).toBe(true);
    expect(loadSaved(s, 'myapp')).toEqual(list);
    expect(loadSaved(s, 'other')).toEqual([]);
    expect([...s.data.keys()]).toEqual([storageKey('myapp')]);
  });

  it('leave out anything unreadable', () => {
    expect(loadSaved(memory({ [storageKey('p')]: '{not json' }), 'p')).toEqual([]);
    expect(loadSaved(memory({ [storageKey('p')]: '{"a":1}' }), 'p')).toEqual([]);
    const mixed = JSON.stringify([{ id: 'a', name: 'ok', search: 'x' }, { id: 'b', name: ' ', search: 'x' }, { id: 1, name: 'n', search: 'x' }, null]);
    expect(loadSaved(memory({ [storageKey('p')]: mixed }), 'p')).toEqual([{ id: 'a', name: 'ok', search: 'x' }]);
    expect(loadSaved(null, 'p')).toEqual([]);
  });

  it('report a browser that refuses to store', () => {
    const full = { setItem: () => { throw new Error('QuotaExceededError'); } };
    expect(storeSaved(full, 'p', [])).toBe(false);
    expect(storeSaved(null, 'p', [])).toBe(false);
  });

  it('replace the same name, ignoring case, in place', () => {
    let list: SavedFilter[] = addSaved([], 'Errors', '~c 500', 'a');
    list = addSaved(list, 'Slow', '~u /slow', 'b');
    list = addSaved(list, 'errors', '~c 4', 'c');
    expect(list).toEqual([
      { id: 'a', name: 'errors', search: '~c 4' },
      { id: 'b', name: 'Slow', search: '~u /slow' },
    ]);
  });

  it('ignore an empty name or search, and tidy the name', () => {
    expect(addSaved([], '  ', 'x', 'a')).toEqual([]);
    expect(addSaved([], 'n', '   ', 'a')).toEqual([]);
    expect(cleanName('  two\n  words ')).toBe('two words');
    expect(cleanName('x'.repeat(100))).toHaveLength(MAX_NAME);
  });

  it('keep the newest when there are too many', () => {
    let list: SavedFilter[] = [];
    for (let i = 0; i < MAX_SAVED + 3; i++) list = addSaved(list, `f${i}`, 'x', `id${i}`);
    expect(list).toHaveLength(MAX_SAVED);
    expect(list[0]?.name).toBe('f3');
  });

  it('rename and delete by id', () => {
    const list = addSaved(addSaved([], 'A', 'a', '1'), 'B', 'b', '2');
    expect(renameSaved(list, '2', '  New  ').map((f) => f.name)).toEqual(['A', 'New']);
    expect(renameSaved(list, '2', ' ')).toEqual(list);
    expect(removeSaved(list, '1').map((f) => f.id)).toEqual(['2']);
  });
});
