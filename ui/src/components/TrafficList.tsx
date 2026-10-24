import { memo, useCallback, useMemo, useState } from 'react';
import { api, ApiError, ForbiddenError } from '../api';
import { copyText } from '../clipboard';
import { useNow } from '../hooks';
import { GIVE_UP, giveUpHint, waited } from '../logic/breakpoint';
import { buildCurl, mockFilePath } from '../logic/curl';
import { isError, isSlow } from '../logic/filters';
import { copyMockOff, newRuleOff, replayOff, SAFE_METHODS } from '../logic/flowMenu';
import { formatDuration, formatTime, methodClass, methodLabel, statusClass } from '../logic/format';
import { trafficSize } from '../logic/wsMessages';
import { decryptChoices, decryptMenuLabel, decryptOff, hostPort, isTunnel, openFor, tunnelTag } from '../logic/hosts';
import { mapLocalOff } from '../logic/mapLocal';
import { deviceText } from '../logic/proxyDevices';
import { breakpointRule, findBreakpoint, newRuleId, requestMatch, type RequestMatch } from '../logic/rules';
import { useData, useDispatch, useStore } from '../store';
import type { FlowDetail, FlowSummary, TrafficRow, TunnelRow } from '../types';
import { ContextMenu, type MenuAt, type MenuItem } from './ContextMenu';
import { Modal } from './Modal';
import { VirtualList } from './VirtualList';

export const TRAFFIC_ROW_HEIGHT = 28;
const NOT_API_HOST = "Rules apply only to the preset's API hosts";

interface RowProps {
  flow: FlowSummary;
  selected: boolean;
  onSelect: (id: string) => void;
  showDevice: boolean;
  onMenu: (flow: FlowSummary, at: MenuAt) => void;
}

function DeviceCell({ client }: { client: string | null }) {
  return <span className={`c-dev${client === 'mac' ? ' mac' : ''}`}>{deviceText(client)}</span>;
}

/** How long a paused flow has waited; after 20 s it says the app may give up. */
function PausedFor({ since }: { since: number | null }) {
  const now = useNow(1000);
  const hint = giveUpHint(since, now);
  return (
    <span className={`c-num c-dur${hint ? ' late' : ''}`} title={hint ?? undefined}>
      {hint && <span aria-label={GIVE_UP}>⚠ </span>}
      {waited(since, now)}
    </span>
  );
}

/** Classes a request row carries in List and Tree. */
export function flowRowClass(flow: FlowSummary, selected: boolean): string {
  return `frow${selected ? ' sel' : ''}${isError(flow) ? ' err' : ''}${flow.paused ? ' paused' : ''}${flow.replay_of ? ' replay' : ''}`;
}

export function FlowStatus({ flow }: { flow: FlowSummary }) {
  return (
    <span>
      {flow.status !== null ? (
        <span className={`st ${statusClass(flow.status)}`}>{flow.status}</span>
      ) : flow.error !== null ? (
        <span className="st s5" title={flow.error}>
          ERR
        </span>
      ) : (
        <span className="st s3">…</span>
      )}
    </span>
  );
}

export function FlowDuration({ flow }: { flow: FlowSummary }) {
  return flow.paused ? <PausedFor since={flow.paused_since} /> : <span className="c-num c-dur">{formatDuration(flow.duration_ms)}</span>;
}

export function FlowSize({ flow }: { flow: FlowSummary }) {
  return <span className="c-num c-size">{trafficSize(flow.websocket, flow.ws_messages, flow.size)}</span>;
}

export function FlowBadges({ flow }: { flow: FlowSummary }) {
  return (
    <span className="c-badges">
      {flow.paused && <span className="tag paused">Paused</span>}
      {!flow.paused && flow.edited && <span className="tag edited">Edited</span>}
      {flow.mapped && (
        <span className="tag mapped" title={flow.sent_to ? `Sent to ${flow.sent_to}` : undefined}>
          Mapped
        </span>
      )}
      {flow.rewritten && <span className="tag rewritten">Rewritten</span>}
      {flow.replay_of && <span className="tag replay">Replay</span>}
      {flow.mock && <span className="tag mock">Mock</span>}
      {flow.fault && (
        <span className="tag fault" title={flow.fault}>
          Fault
        </span>
      )}
      {isSlow(flow) && <span className="tag slow">Slow</span>}
    </span>
  );
}

const FlowRow = memo(function FlowRow({ flow, selected, onSelect, showDevice, onMenu }: RowProps) {
  return (
    <div
      className={flowRowClass(flow, selected)}
      style={{ height: TRAFFIC_ROW_HEIGHT }}
      role="option"
      aria-selected={selected}
      onClick={() => onSelect(flow.id)}
      onContextMenu={(e) => {
        e.preventDefault();
        onSelect(flow.id);
        onMenu(flow, { x: e.clientX, y: e.clientY });
      }}
    >
      <span className="c-time">{formatTime(flow.ts)}</span>
      {showDevice && <DeviceCell client={flow.client} />}
      <span className={`m ${methodClass(flow.method)}`}>{methodLabel(flow.method)}</span>
      <FlowStatus flow={flow} />
      <span className="c-path" title={flow.host + flow.path}>
        {flow.path}
      </span>
      <FlowDuration flow={flow} />
      <FlowSize flow={flow} />
      <FlowBadges flow={flow} />
    </div>
  );
});

interface TunnelProps {
  row: TunnelRow;
  selected: boolean;
  onSelect: (id: string) => void;
  showDevice: boolean;
  onMenu: (row: TunnelRow, at: MenuAt) => void;
}

/** A connection passed through without decrypting: no status, content or size (spec 022, slice C). */
const TunnelLine = memo(function TunnelLine({ row, selected, onSelect, showDevice, onMenu }: TunnelProps) {
  return (
    <div
      className={`frow enc${selected ? ' sel' : ''}`}
      style={{ height: TRAFFIC_ROW_HEIGHT }}
      role="option"
      aria-selected={selected}
      onClick={() => onSelect(row.id)}
      onContextMenu={(e) => {
        e.preventDefault();
        onSelect(row.id);
        onMenu(row, { x: e.clientX, y: e.clientY });
      }}
    >
      <span className="c-time">{formatTime(row.ts)}</span>
      {showDevice && <DeviceCell client={row.client} />}
      <span className="m conn">{row.method}</span>
      <span>
        <span className="st none" title="Not decrypted">
          🔒
        </span>
      </span>
      <span className="c-path" title={hostPort(row)}>
        {hostPort(row)}
      </span>
      <span className="c-num c-dur">{openFor(row)}</span>
      <span className="c-num c-size">—</span>
      <span className="c-badges">
        <span className="tag enc">{tunnelTag(row)}</span>
      </span>
    </div>
  );
});

export interface MenuActions {
  /** Decrypt `host`, offering `choice` first (the host or its parent domain). */
  onDecrypt: (host: string, choice: string) => void;
  onHideEncrypted: () => void;
  onMapLocal: (flow: FlowSummary) => void;
}

/** The request and encrypted-connection menus, and Replay's confirmation, shared by List and Tree. */
export function useTrafficMenus({ onDecrypt, onHideEncrypted, onMapLocal }: MenuActions) {
  const { appState, rules, ui } = useStore();
  const { viewing } = useData();
  const dispatch = useDispatch();
  const [menu, setMenu] = useState<{ row: TunnelRow; at: MenuAt } | null>(null);
  const [flowMenu, setFlowMenu] = useState<{ flow: FlowSummary; at: MenuAt } | null>(null);
  const [confirmReplay, setConfirmReplay] = useState<FlowSummary | null>(null);
  const [rulesError, setRulesError] = useState<string | null>(null);

  /** Breakpoint items read the rules from the store; a menu refreshes them as it opens. */
  const loadRules = useCallback(() => {
    if (viewing) return;
    api
      .rules()
      .then((r) => {
        setRulesError(null);
        dispatch({ type: 'rules', rules: r });
      })
      .catch((e: unknown) => {
        if (!(e instanceof ForbiddenError)) setRulesError(e instanceof ApiError ? e.message : 'Could not load the rules');
      });
  }, [viewing, dispatch]);
  const openMenu = useCallback((row: TunnelRow, at: MenuAt) => setMenu({ row, at }), []);
  const closeMenu = useCallback(() => setMenu(null), []);
  const openFlowMenu = useCallback(
    (flow: FlowSummary, at: MenuAt) => {
      setFlowMenu({ flow, at });
      loadRules();
    },
    [loadRules],
  );
  const closeFlowMenu = useCallback(() => setFlowMenu(null), []);
  const toast = (text: string) => dispatch({ type: 'toast', text });

  const withDetail = async (flow: FlowSummary, use: (detail: FlowDetail) => Promise<void>) => {
    try {
      await use(await api.flow(flow.id, undefined, viewing));
    } catch (e) {
      if (!(e instanceof ForbiddenError)) toast(e instanceof ApiError && e.status === 404 ? 'This request is no longer held in memory' : 'Could not load the request');
    }
  };
  const copyCurl = (flow: FlowSummary) =>
    withDetail(flow, async (detail) => toast((await copyText(buildCurl(detail))) ? 'cURL copied' : 'Copy failed'));
  const copyMock = (flow: FlowSummary) =>
    withDetail(flow, async (detail) => {
      const text = detail.response?.body.text ?? null;
      if (text === null) return toast('No text response body to copy');
      const path = detail.mock_path || mockFilePath(appState?.mocks_dir ?? 'mocks', flow);
      toast((await copyText(text)) ? `Response body copied. Save it as ${path}` : 'Copy failed');
    });
  const replay = async (flow: FlowSummary) => {
    setConfirmReplay(null);
    const from = ui.selectedFlowId;
    try {
      const sent = await api.replay(flow.id);
      dispatch({ type: 'replaySent', id: sent.id, from });
      toast('Replay sent: it is listed as a new request marked REPLAY');
    } catch (e) {
      if (!(e instanceof ForbiddenError)) toast(e instanceof ApiError ? e.message : 'Replay failed');
    }
  };

  /** Adds a request-only pause rule at the top of the rules, or deletes the one already on `match`. */
  const toggleBreakpoint = async (match: RequestMatch) => {
    if (!rules) return;
    const existing = findBreakpoint(rules.rules, match);
    const rule = existing ?? breakpointRule(match, newRuleId());
    const next = existing ? rules.rules.filter((r) => r.id !== existing.id) : [rule, ...rules.rules];
    try {
      dispatch({ type: 'rules', rules: await api.putRules(rules.revision, next) });
      toast(existing ? `Removed the rule ${rule.name}` : `Added the rule ${rule.name} at the top of Rules: matching requests wait at the request`);
    } catch (e) {
      if (e instanceof ForbiddenError) return;
      if (e instanceof ApiError && e.status === 409) loadRules();
      toast(e instanceof ApiError ? e.message : 'Could not save the rules');
    }
  };

  /** Breakpoint, or Remove breakpoint when an enabled pause rule is on exactly `match` (spec 028, slice D). */
  const breakpointItem = (match: RequestMatch, label: string): MenuItem => {
    const reason = newRuleOff(viewing) ?? (match.host ? null : NOT_API_HOST) ?? (rules ? null : (rulesError ?? 'Loading the rules…'));
    return {
      label: rules && findBreakpoint(rules.rules, match) ? 'Remove breakpoint' : label,
      onSelect: () => void toggleBreakpoint(match),
      ...(reason ? { disabledReason: reason } : {}),
    };
  };

  const flowMenuItems = (flow: FlowSummary): MenuItem[] => {
    const off = (reason: string | null) => (reason ? { disabledReason: reason } : {});
    return [
      { label: 'Map local…', onSelect: () => onMapLocal(flow), ...off(mapLocalOff(flow, viewing)) },
      { label: 'Copy as mock', onSelect: () => void copyMock(flow), ...off(copyMockOff(flow)) },
      { label: 'New rule from this request', onSelect: () => dispatch({ type: 'newRuleFrom', flow }), ...off(newRuleOff(viewing)), divided: true },
      breakpointItem(requestMatch(flow, appState?.api_hosts ?? []), 'Breakpoint'),
      {
        label: 'Replay',
        onSelect: () => (SAFE_METHODS.has(flow.method.toUpperCase()) ? void replay(flow) : setConfirmReplay(flow)),
        ...off(replayOff(flow, viewing)),
      },
      { label: 'Copy cURL', onSelect: () => void copyCurl(flow), divided: true },
    ];
  };

  const menuItems = (row: TunnelRow): MenuItem[] => {
    const decrypts = decryptChoices(row.host).map((choice): MenuItem => {
      const off = decryptOff(appState, choice, viewing);
      return { label: decryptMenuLabel(choice), onSelect: () => onDecrypt(row.host, choice), ...(off ? { disabledReason: off } : {}) };
    });
    const copy = async () => {
      const ok = await copyText(row.host);
      dispatch({ type: 'toast', text: ok ? 'Host copied' : 'Copy failed' });
    };
    return [
      ...decrypts,
      { label: 'Copy host', onSelect: () => void copy(), divided: true },
      { label: `Show only ${row.host}`, onSelect: () => dispatch({ type: 'ui', patch: { host: row.host } }) },
      { label: 'Hide encrypted connections', onSelect: onHideEncrypted, divided: true },
    ];
  };

  const menus = (
    <>
      {menu && <ContextMenu at={menu.at} label="Encrypted connection" items={menuItems(menu.row)} onClose={closeMenu} />}
      {flowMenu && <ContextMenu at={flowMenu.at} label="Request" items={flowMenuItems(flowMenu.flow)} onClose={closeFlowMenu} />}
      {confirmReplay && (
        <Modal title={`Replay ${confirmReplay.method} ${confirmReplay.path}?`} lead="It repeats its effect on the backend." onClose={() => setConfirmReplay(null)}>
          <div className="sheet-foot">
            <span className="spacer" />
            <button type="button" className="btn" onClick={() => setConfirmReplay(null)}>
              Cancel
            </button>
            <button type="button" className="btn danger" onClick={() => void replay(confirmReplay)}>
              Replay
            </button>
          </div>
        </Modal>
      )}
    </>
  );
  return { openFlowMenu, openTunnelMenu: openMenu, menus, loadRules, breakpointItem };
}

interface Props extends MenuActions {
  rows: TrafficRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Changes when something outside the list selects a flow, so the row is scrolled into view. */
  revealKey: unknown;
  paused: boolean;
  /** Keep the newest row in view; kept by the Traffic view so it survives a switch to Tree. */
  follow: boolean;
  onFollowChange: (follow: boolean) => void;
  /** Modes that take Wi-Fi devices show who sent each request. */
  showDevice: boolean;
}

export function TrafficList({ rows, selectedId, onSelect, revealKey, paused, follow, onFollowChange, showDevice, ...actions }: Props) {
  const { openFlowMenu, openTunnelMenu, menus } = useTrafficMenus(actions);
  const selectedIndex = useMemo(
    () => (selectedId === null ? -1 : rows.findIndex((f) => f.id === selectedId)),
    [rows, selectedId],
  );

  const step = useCallback(
    (delta: number) => {
      if (rows.length === 0) return;
      const from = selectedIndex < 0 ? (delta > 0 ? -1 : rows.length) : selectedIndex;
      const next = Math.min(rows.length - 1, Math.max(0, from + delta));
      onSelect((rows[next] as TrafficRow).id);
    },
    [rows, selectedIndex, onSelect],
  );

  return (
    <div className={`flows-wrap${showDevice ? ' dev' : ''}`}>
      <div className="fhead">
        <span className="h-time">Time</span>
        {showDevice && <span className="h-dev">Device</span>}
        <span>Method</span>
        <span>Status</span>
        <span>Path</span>
        <span className="c-num c-dur">Duration</span>
        <span className="c-num c-size">Size</span>
        <span />
      </div>
      <div className="flows-body">
        {rows.length === 0 && <div className="empty">No requests to show.</div>}
        <VirtualList
          label="Requests"
          count={rows.length}
          rowHeight={TRAFFIC_ROW_HEIGHT}
          follow={follow && !paused}
          onFollowChange={onFollowChange}
          revealIndex={selectedIndex}
          revealKey={revealKey}
          onStep={step}
          renderRow={(i) => {
            const r = rows[i] as TrafficRow;
            return isTunnel(r) ? (
              <TunnelLine key={r.id} row={r} selected={r.id === selectedId} onSelect={onSelect} showDevice={showDevice} onMenu={openTunnelMenu} />
            ) : (
              <FlowRow key={r.id} flow={r} selected={r.id === selectedId} onSelect={onSelect} showDevice={showDevice} onMenu={openFlowMenu} />
            );
          }}
        />
      </div>
      {menus}
    </div>
  );
}
