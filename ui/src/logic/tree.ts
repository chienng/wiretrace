/**
 * Traffic as a tree (spec 028, slice C): a host, then a folder per path segment, then the
 * requests. Children keep the order their first request arrived in, so a new request never
 * moves a row above it. Keys are stable across rebuilds: host `h:<scheme>://<host>[:port]`,
 * folder `<parent>/<segment>`, request `f:<flow id>`, encrypted connection `t:<tunnel id>`.
 */
import type { TrafficRow } from '../types';
import { isTunnel } from './hosts';

export interface TreeBranch {
  kind: 'host' | 'folder';
  key: string;
  name: string;
  parent: string | null;
  /** The host filter that shows only this host's rows. */
  host: string;
  /** Requests below this node. */
  count: number;
  children: Map<string, TreeNode>;
}

export interface TreeLeaf {
  kind: 'leaf';
  key: string;
  name: string;
  parent: string;
  row: TrafficRow;
}

export type TreeNode = TreeBranch | TreeLeaf;

export interface Tree {
  roots: Map<string, TreeBranch>;
  nodes: Map<string, TreeNode>;
  /** Leaf key by row id. */
  leaves: Map<string, string>;
}

export interface VisibleRow {
  node: TreeNode;
  depth: number;
  open: boolean;
}

export const ENCRYPTED_NAME = 'Encrypted connection';

const DEFAULT_PORTS: Record<string, number> = { http: 80, https: 443, ws: 80, wss: 443 };

export function hostKey(scheme: string, host: string, port: number | null): string {
  const shown = port === null || DEFAULT_PORTS[scheme] === port ? '' : `:${port}`;
  return `h:${scheme}://${host}${shown}`;
}

export const leafKey = (row: TrafficRow): string => (isTunnel(row) ? `t:${row.id}` : `f:${row.id}`);

/** Every segment but the last is a folder; the last, with the query, names the request (`/` when empty). */
export function splitPath(path: string): { folders: string[]; leaf: string } {
  const q = path.indexOf('?');
  const pathname = q < 0 ? path : path.slice(0, q);
  const query = q < 0 ? '' : path.slice(q);
  const segments = (pathname.startsWith('/') ? pathname.slice(1) : pathname).split('/');
  const last = segments.pop() ?? '';
  return { folders: segments, leaf: (last || '/') + query };
}

function branch(kind: TreeBranch['kind'], key: string, name: string, parent: string | null, host: string): TreeBranch {
  return { kind, key, name, parent, host, count: 0, children: new Map() };
}

export function buildTree(rows: readonly TrafficRow[]): Tree {
  const tree: Tree = { roots: new Map(), nodes: new Map(), leaves: new Map() };
  for (const row of rows) {
    const tunnel = isTunnel(row);
    const hk = hostKey(tunnel ? (row.tls ? 'https' : 'http') : row.scheme, row.host, row.port);
    let parent = tree.roots.get(hk);
    if (!parent) {
      parent = branch('host', hk, hk.slice(2), null, row.host);
      tree.roots.set(hk, parent);
      tree.nodes.set(hk, parent);
    }
    parent.count++;
    const { folders, leaf } = tunnel ? { folders: [], leaf: ENCRYPTED_NAME } : splitPath(row.path);
    for (const segment of folders) {
      const key = `${parent.key}/${segment}`;
      let next = parent.children.get(key) as TreeBranch | undefined;
      if (!next) {
        next = branch('folder', key, segment, parent.key, parent.host);
        parent.children.set(key, next);
        tree.nodes.set(key, next);
      }
      next.count++;
      parent = next;
    }
    const key = leafKey(row);
    const node: TreeLeaf = { kind: 'leaf', key, name: leaf, parent: parent.key, row };
    parent.children.set(key, node);
    tree.nodes.set(key, node);
    tree.leaves.set(row.id, key);
  }
  return tree;
}

/** Hosts not seen before: they start open, folders start closed. */
export function newHosts(tree: Tree, seen: ReadonlySet<string>): string[] {
  return [...tree.roots.keys()].filter((k) => !seen.has(k));
}

/** The rows on screen: every root, and the children of open nodes. */
export function visibleRows(tree: Tree, open: ReadonlySet<string>): VisibleRow[] {
  const out: VisibleRow[] = [];
  const walk = (node: TreeNode, depth: number) => {
    const isOpen = node.kind !== 'leaf' && open.has(node.key);
    out.push({ node, depth, open: isOpen });
    if (isOpen) for (const child of (node as TreeBranch).children.values()) walk(child, depth + 1);
  };
  for (const root of tree.roots.values()) walk(root, 0);
  return out;
}

/** The keys from the host down to `key`, inclusive; empty when the node is not in the tree. */
export function pathTo(tree: Tree, key: string): string[] {
  const out: string[] = [];
  let at: string | null = key;
  while (at !== null) {
    const node = tree.nodes.get(at);
    if (!node) break;
    out.unshift(at);
    at = node.parent;
  }
  return out;
}

/** The host and folders above a request, top first; null when the row is not in the tree. */
export function ancestorsOf(tree: Tree, id: string): string[] | null {
  const key = tree.leaves.get(id);
  return key === undefined ? null : pathTo(tree, key).slice(0, -1);
}

/** A node's key and those of every host or folder below it. */
export function branchKeys(node: TreeBranch): string[] {
  const out = [node.key];
  for (const child of node.children.values()) if (child.kind !== 'leaf') out.push(...branchKeys(child));
  return out;
}

/** The cursor's row, or when it is gone the nearest visible one above it on `path` (host first); null if none. */
export function settleCursor(visible: ReadonlyMap<string, number>, path: readonly string[]): string | null {
  for (let i = path.length - 1; i >= 0; i--) {
    const key = path[i] as string;
    if (visible.has(key)) return key;
  }
  return null;
}

export interface TreeMove {
  cursor: string | null;
  open: ReadonlySet<string>;
}

/** What a key does with the tree focused; null for a key the tree does not use. */
export function treeKey(visible: readonly VisibleRow[], cursor: string | null, key: string, open: ReadonlySet<string>): TreeMove | null {
  const at = cursor === null ? -1 : visible.findIndex((r) => r.node.key === cursor);
  const row = visible[at];
  const stay: TreeMove = { cursor, open };
  const to = (i: number): TreeMove => ({ cursor: (visible[i] as VisibleRow).node.key, open });
  const set = (k: string, on: boolean): TreeMove => {
    const next = new Set(open);
    if (on) next.add(k);
    else next.delete(k);
    return { cursor: k, open: next };
  };
  switch (key) {
    case 'ArrowDown':
      if (visible.length === 0) return stay;
      return to(row ? Math.min(at + 1, visible.length - 1) : 0);
    case 'ArrowUp':
      if (visible.length === 0) return stay;
      return to(row ? Math.max(at - 1, 0) : visible.length - 1);
    case 'ArrowRight':
      if (!row || row.node.kind === 'leaf') return stay;
      return row.open ? to(at + 1) : set(row.node.key, true);
    case 'ArrowLeft':
      if (!row) return stay;
      if (row.node.kind !== 'leaf' && row.open) return set(row.node.key, false);
      return row.node.parent === null ? stay : { cursor: row.node.parent, open };
    case 'Enter':
    case ' ':
      if (!row || row.node.kind === 'leaf') return stay;
      return set(row.node.key, !row.open);
    default:
      return null;
  }
}
