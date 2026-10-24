import { describe, expect, it } from 'vitest';
import { flow, tunnel } from './testing';
import {
  ancestorsOf,
  branchKeys,
  buildTree,
  ENCRYPTED_NAME,
  newHosts,
  settleCursor,
  splitPath,
  treeKey,
  visibleRows,
  type TreeBranch,
  type VisibleRow,
} from './tree';

const API = 'h:https://api.example.com';
const names = (rows: VisibleRow[]) => rows.map((r) => `${'  '.repeat(r.depth)}${r.node.name}`);
const keys = (rows: VisibleRow[]) => rows.map((r) => r.node.key);
const index = (rows: VisibleRow[]) => new Map(rows.map((r, i) => [r.node.key, i]));

describe('tree grouping', () => {
  it('names a host by scheme and host, with the port only when it is not the default', () => {
    const tree = buildTree([
      flow({ id: 'a' }),
      flow({ id: 'b', scheme: 'http', port: 80 }),
      flow({ id: 'c', port: 8443 }),
      flow({ id: 'd', scheme: 'http', port: 8080 }),
    ]);
    expect([...tree.roots.keys()]).toEqual([API, 'h:http://api.example.com', 'h:https://api.example.com:8443', 'h:http://api.example.com:8080']);
    expect(tree.roots.get(API)?.name).toBe('https://api.example.com');
    expect(tree.roots.get(API)?.host).toBe('api.example.com');
  });

  it('makes a folder of every segment but the last, never of the query', () => {
    expect(splitPath('/v1/users/42?expand=1&a=/b')).toEqual({ folders: ['v1', 'users'], leaf: '42?expand=1&a=/b' });
    expect(splitPath('/')).toEqual({ folders: [], leaf: '/' });
    expect(splitPath('/v1/users/')).toEqual({ folders: ['v1', 'users'], leaf: '/' });
    expect(splitPath('/?q=1')).toEqual({ folders: [], leaf: '/?q=1' });
  });

  it('puts /v1/users and /v1/users/42 both under v1', () => {
    const tree = buildTree([flow({ id: 'a', path: '/v1/users' }), flow({ id: 'b', path: '/v1/users/42' })]);
    const open = new Set([API, `${API}/v1`, `${API}/v1/users`]);
    expect(names(visibleRows(tree, open))).toEqual(['https://api.example.com', '  v1', '    users', '    users', '      42']);
    const v1 = tree.nodes.get(`${API}/v1`) as TreeBranch;
    expect([...v1.children.keys()]).toEqual(['f:a', `${API}/v1/users`]);
  });

  it('lists an encrypted connection directly under its host', () => {
    const tree = buildTree([tunnel({ id: 't1', host: 'cdn.example.net', port: 443, tls: true }), tunnel({ id: 't2', host: 'raw.example.net', port: 5222, tls: false })]);
    const rows = visibleRows(tree, new Set(tree.roots.keys()));
    expect(keys(rows)).toEqual(['h:https://cdn.example.net', 't:t1', 'h:http://raw.example.net:5222', 't:t2']);
    expect(rows[1]?.node.name).toBe(ENCRYPTED_NAME);
    expect(rows[1]?.depth).toBe(1);
  });

  it('keeps first-arrival order, so a new request never moves an existing row', () => {
    const first = [flow({ id: 'a', path: '/b/x' }), flow({ id: 'b', path: '/a/y' }), flow({ id: 'c', path: '/b/z' })];
    const open = new Set([API, `${API}/a`, `${API}/b`]);
    const before = keys(visibleRows(buildTree(first), open));
    expect(before).toEqual([API, `${API}/b`, 'f:a', 'f:c', `${API}/a`, 'f:b']);
    const after = keys(visibleRows(buildTree([...first, flow({ id: 'd', path: '/b/w' }), flow({ id: 'e', path: '/c/v' })]), new Set([...open, `${API}/c`])));
    expect(after).toEqual([API, `${API}/b`, 'f:a', 'f:c', 'f:d', `${API}/a`, 'f:b', `${API}/c`, 'f:e']);
  });

  it('counts the requests below each node', () => {
    const tree = buildTree([flow({ id: 'a', path: '/v1/users/1' }), flow({ id: 'b', path: '/v1/users/2' }), flow({ id: 'c', path: '/v1/me' }), tunnel({ id: 't', host: 'api.example.com', port: 443 })]);
    expect(tree.roots.get(API)?.count).toBe(4);
    expect((tree.nodes.get(`${API}/v1`) as TreeBranch).count).toBe(3);
    expect((tree.nodes.get(`${API}/v1/users`) as TreeBranch).count).toBe(2);
  });
});

describe('visible rows', () => {
  const tree = buildTree([flow({ id: 'a', path: '/v1/users/1' }), flow({ id: 'b', path: '/health' })]);

  it('hides the children of closed nodes and gives depths', () => {
    expect(names(visibleRows(tree, new Set()))).toEqual(['https://api.example.com']);
    const rows = visibleRows(tree, new Set([API, `${API}/v1/users`]));
    expect(names(rows)).toEqual(['https://api.example.com', '  v1', '  health']);
    expect(rows.map((r) => r.open)).toEqual([true, false, false]);
  });

  it('opens new hosts only', () => {
    expect(newHosts(tree, new Set())).toEqual([API]);
    expect(newHosts(tree, new Set([API]))).toEqual([]);
  });

  it('finds the host and folders above a request, and nothing for a missing one', () => {
    expect(ancestorsOf(tree, 'a')).toEqual([API, `${API}/v1`, `${API}/v1/users`]);
    expect(ancestorsOf(tree, 'b')).toEqual([API]);
    expect(ancestorsOf(tree, 'nope')).toBeNull();
  });

  it('lists a node and every branch below it for Expand and Collapse all below', () => {
    expect(branchKeys(tree.roots.get(API) as TreeBranch)).toEqual([API, `${API}/v1`, `${API}/v1/users`]);
  });
});

describe('tree keyboard', () => {
  const tree = buildTree([flow({ id: 'a', path: '/v1/x' }), flow({ id: 'b', path: '/health' }), flow({ id: 'c', host: 'cdn.example.com', path: '/img' })]);
  const CDN = 'h:https://cdn.example.com';
  const open = new Set([API, CDN]);
  const rows = visibleRows(tree, open);
  // https://api.example.com, v1, health, https://cdn.example.com, img
  const key = (cursor: string | null, k: string, o: ReadonlySet<string> = open) => treeKey(visibleRows(tree, o), cursor, k, o);

  it('moves through the visible rows with ↓ and ↑, staying put at the ends', () => {
    expect(keys(rows)).toEqual([API, `${API}/v1`, 'f:b', CDN, 'f:c']);
    expect(key(API, 'ArrowDown')?.cursor).toBe(`${API}/v1`);
    expect(key('f:b', 'ArrowUp')?.cursor).toBe(`${API}/v1`);
    expect(key('f:c', 'ArrowDown')?.cursor).toBe('f:c');
    expect(key(API, 'ArrowUp')?.cursor).toBe(API);
    expect(key(null, 'ArrowDown')?.cursor).toBe(API);
    expect(key(null, 'ArrowUp')?.cursor).toBe('f:c');
  });

  it('opens a closed node with →, then moves to its first child; a leaf stays', () => {
    const opened = key(`${API}/v1`, 'ArrowRight');
    expect(opened?.cursor).toBe(`${API}/v1`);
    expect(opened?.open.has(`${API}/v1`)).toBe(true);
    expect(key(`${API}/v1`, 'ArrowRight', opened?.open)?.cursor).toBe('f:a');
    expect(key('f:b', 'ArrowRight')).toEqual({ cursor: 'f:b', open });
  });

  it('closes an open node with ←, goes to the parent from a leaf or closed node, and leaves a closed host alone', () => {
    const closed = key(API, 'ArrowLeft');
    expect(closed?.cursor).toBe(API);
    expect(closed?.open.has(API)).toBe(false);
    expect(key('f:b', 'ArrowLeft')?.cursor).toBe(API);
    expect(key(`${API}/v1`, 'ArrowLeft')?.cursor).toBe(API);
    expect(key(API, 'ArrowLeft', closed?.open)).toEqual({ cursor: API, open: closed?.open });
  });

  it('toggles a node with Enter or Space and does nothing on a leaf', () => {
    expect(key(CDN, 'Enter')?.open.has(CDN)).toBe(false);
    expect(key(`${API}/v1`, ' ')?.open.has(`${API}/v1`)).toBe(true);
    expect(key('f:c', 'Enter')).toEqual({ cursor: 'f:c', open });
  });

  it('ignores other keys', () => {
    expect(key(API, 'a')).toBeNull();
    expect(key(API, 'Tab')).toBeNull();
  });

  it('moves a vanished cursor to the nearest visible ancestor, or none', () => {
    const path = [API, `${API}/v1`, 'f:a'];
    expect(settleCursor(index(rows), path)).toBe(`${API}/v1`);
    expect(settleCursor(index(visibleRows(tree, new Set([CDN]))), path)).toBe(API);
    expect(settleCursor(index(visibleRows(buildTree([flow({ id: 'c', host: 'cdn.example.com', path: '/img' })]), new Set())), path)).toBeNull();
    expect(settleCursor(index(rows), [])).toBeNull();
  });
});
