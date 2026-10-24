import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { methodClass, methodLabel } from '../logic/format';
import { hostPort, isTunnel, openFor, tunnelTag } from '../logic/hosts';
import { apiHostFor, type RequestMatch } from '../logic/rules';
import { ancestorsOf, branchKeys, buildTree, newHosts, pathTo, settleCursor, treeKey, visibleRows, type TreeBranch, type TreeMove, type VisibleRow } from '../logic/tree';
import { useDispatch, useStore } from '../store';
import { ContextMenu, type MenuAt, type MenuItem } from './ContextMenu';
import { FlowBadges, FlowDuration, FlowSize, FlowStatus, flowRowClass, TRAFFIC_ROW_HEIGHT, useTrafficMenus, type MenuActions } from './TrafficList';
import type { TrafficRow } from '../types';
import { VirtualList } from './VirtualList';

const PAD = 8;
const INDENT = 16;
/** A leaf's method lines up with its parent's name, past the fold triangle. */
const TOGGLE = 16;

interface RowProps {
  row: VisibleRow;
  cursor: boolean;
  selected: boolean;
  onClick: (row: VisibleRow) => void;
  onMenu: (row: VisibleRow, at: MenuAt) => void;
}

const TreeRow = memo(function TreeRow({ row, cursor, selected, onClick, onMenu }: RowProps) {
  const { node, depth } = row;
  const menu = (e: MouseEvent) => {
    e.preventDefault();
    onMenu(row, { x: e.clientX, y: e.clientY });
  };
  const common = { role: 'option', onClick: () => onClick(row), onContextMenu: menu } as const;
  const cur = cursor ? ' cur' : '';

  if (node.kind !== 'leaf') {
    return (
      <div className={`frow tnode${cur}`} style={{ height: TRAFFIC_ROW_HEIGHT, paddingLeft: PAD + depth * INDENT }} aria-selected={false} {...common}>
        <span className="tw" aria-hidden="true">
          {row.open ? '▾' : '▸'}
        </span>
        <span className="tn" title={node.name}>
          {node.name}
        </span>
        <span className="sr">{row.open ? ', open' : ', closed'}</span>
        <span className="tc">{node.count}</span>
      </div>
    );
  }

  const style = { height: TRAFFIC_ROW_HEIGHT, paddingLeft: PAD + depth * INDENT + TOGGLE };
  const r = node.row;
  if (isTunnel(r)) {
    return (
      <div className={`frow tleaf enc${selected ? ' sel' : ''}${cur}`} style={style} aria-selected={selected} {...common}>
        <span className="m conn">{r.method}</span>
        <span>
          <span className="st none" title="Not decrypted">
            🔒
          </span>
        </span>
        <span className="c-path" title={hostPort(r)}>
          {node.name}
        </span>
        <span className="c-num c-dur">{openFor(r)}</span>
        <span className="c-num c-size">—</span>
        <span className="c-badges">
          <span className="tag enc">{tunnelTag(r)}</span>
        </span>
      </div>
    );
  }
  return (
    <div className={`${flowRowClass(r, selected)} tleaf${cur}`} style={style} aria-selected={selected} {...common}>
      <span className={`m ${methodClass(r.method)}`}>{methodLabel(r.method)}</span>
      <FlowStatus flow={r} />
      <span className="c-path" title={r.host + r.path}>
        {node.name}
      </span>
      <FlowDuration flow={r} />
      <FlowSize flow={r} />
      <FlowBadges flow={r} />
    </div>
  );
});

interface Props extends MenuActions {
  rows: TrafficRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/**
 * Traffic grouped by host and path (spec 028, slice C). The cursor is a row of the tree; on a
 * request it is the selected request, on a host or folder it leaves the selection alone.
 */
export function TrafficTree({ rows, selectedId, onSelect, ...actions }: Props) {
  const { ui, appState } = useStore();
  const dispatch = useDispatch();
  const { openFlowMenu, openTunnelMenu, menus, loadRules, breakpointItem } = useTrafficMenus(actions);
  const [nodeMenu, setNodeMenu] = useState<{ node: TreeBranch; at: MenuAt } | null>(null);

  const tree = useMemo(() => buildTree(rows), [rows]);
  const added = useMemo(() => newHosts(tree, ui.treeSeen), [tree, ui.treeSeen]);
  const open = useMemo(() => (added.length ? new Set([...ui.treeOpen, ...added]) : ui.treeOpen), [added, ui.treeOpen]);
  useLayoutEffect(() => {
    if (added.length) dispatch({ type: 'treeHostsSeen', keys: added });
  }, [added, dispatch]);
  const visible = useMemo(() => visibleRows(tree, open), [tree, open]);
  const index = useMemo(() => new Map(visible.map((r, i) => [r.node.key, i])), [visible]);

  /** From the host down to the cursor, so a cursor whose row went away falls back to the nearest one above. */
  const [path, setPath] = useState<string[]>([]);
  const cursor = settleCursor(index, path);
  const [reveal, setReveal] = useState(0);
  /** The id the tree itself just selected, so the effect below does not treat it as an outside selection. */
  const own = useRef<string | null>(null);

  const setOpen = useCallback((next: ReadonlySet<string>) => dispatch({ type: 'ui', patch: { treeOpen: next } }), [dispatch]);
  const select = useCallback(
    (id: string) => {
      if (id === selectedId) return;
      own.current = id;
      onSelect(id);
    },
    [selectedId, onSelect],
  );

  useEffect(() => {
    if (selectedId !== null && own.current === selectedId) {
      own.current = null;
      return;
    }
    own.current = null;
    const above = selectedId === null ? null : ancestorsOf(tree, selectedId);
    if (selectedId === null || above === null) {
      setPath([]);
      return;
    }
    const closed = above.filter((k) => !open.has(k));
    if (closed.length) setOpen(new Set([...open, ...closed]));
    setPath([...above, tree.leaves.get(selectedId) as string]);
    setReveal((n) => n + 1);
    // Only a change of selection from outside the tree opens and reveals it.
  }, [selectedId]);

  const apply = (move: TreeMove) => {
    if (move.open !== open) setOpen(move.open);
    if (move.cursor === null) return;
    setPath(pathTo(tree, move.cursor));
    const node = tree.nodes.get(move.cursor);
    if (node?.kind === 'leaf') select(node.row.id);
    setReveal((n) => n + 1);
  };

  const onRowClick = (row: VisibleRow) => {
    const { node } = row;
    setPath(pathTo(tree, node.key));
    if (node.kind === 'leaf') {
      select(node.row.id);
      return;
    }
    const next = new Set(open);
    if (row.open) next.delete(node.key);
    else next.add(node.key);
    setOpen(next);
  };

  const onRowMenu = (row: VisibleRow, at: MenuAt) => {
    const { node } = row;
    setPath(pathTo(tree, node.key));
    if (node.kind !== 'leaf') {
      setNodeMenu({ node, at });
      loadRules();
      return;
    }
    select(node.row.id);
    if (isTunnel(node.row)) openTunnelMenu(node.row, at);
    else openFlowMenu(node.row, at);
  };

  const onKey = (e: KeyboardEvent) => {
    const move = treeKey(visible, cursor, e.key, open);
    if (!move) return;
    e.preventDefault();
    apply(move);
  };

  /** Any method under the host (`/*`) or the folder (`/v1/users/*`). */
  const nodeMatch = (node: TreeBranch): RequestMatch => {
    const folders = pathTo(tree, node.key)
      .slice(1)
      .map((k) => tree.nodes.get(k)?.name ?? '');
    return { method: 'ANY', host: apiHostFor(node.host, appState?.api_hosts ?? []), path: `/${folders.map((f) => `${f}/`).join('')}*` };
  };

  const nodeItems = (node: TreeBranch): MenuItem[] => [
    breakpointItem(nodeMatch(node), node.kind === 'host' ? 'Breakpoint on this host' : 'Breakpoint on this folder'),
    { label: 'Expand all below', onSelect: () => setOpen(new Set([...open, ...branchKeys(node)])), divided: true },
    {
      label: 'Collapse all below',
      onSelect: () => {
        const below = new Set(branchKeys(node));
        setOpen(new Set([...open].filter((k) => !below.has(k))));
      },
    },
    ...(node.kind === 'host' ? [{ label: 'Show only this host', onSelect: () => dispatch({ type: 'ui', patch: { host: node.host } }), divided: true }] : []),
  ];

  return (
    <div className="flows-wrap tree">
      <div className="flows-body">
        {visible.length === 0 && <div className="empty">No requests to show.</div>}
        <VirtualList
          label="Requests by host and path"
          count={visible.length}
          rowHeight={TRAFFIC_ROW_HEIGHT}
          follow={false}
          revealIndex={cursor === null ? -1 : (index.get(cursor) ?? -1)}
          revealKey={reveal}
          onStep={(delta) => {
            const move = treeKey(visible, cursor, delta > 0 ? 'ArrowDown' : 'ArrowUp', open);
            if (move) apply(move);
          }}
          onKey={onKey}
          renderRow={(i) => {
            const row = visible[i] as VisibleRow;
            const { node } = row;
            return (
              <TreeRow
                key={node.key}
                row={row}
                cursor={node.key === cursor}
                selected={node.kind === 'leaf' && node.row.id === selectedId}
                onClick={onRowClick}
                onMenu={onRowMenu}
              />
            );
          }}
        />
      </div>
      {menus}
      {nodeMenu && <ContextMenu at={nodeMenu.at} label={nodeMenu.node.kind === 'host' ? 'Host' : 'Folder'} items={nodeItems(nodeMenu.node)} onClose={() => setNodeMenu(null)} />}
    </div>
  );
}
