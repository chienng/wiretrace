import { createContext, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from 'react';
import type { InitialData } from './connection';
import type { QuickFilter } from './logic/filters';
import { LEVELS, type Level } from './logic/logs';
import { applyMessages, mergeFlows, mergeLogSets, type LogSets } from './logic/merge';
import type { AppState, FlowSummary, LogSource, Phase, RulesPayload, ServerMessage } from './types';

export type View = 'traffic' | 'logs' | 'rules';
export type Dialog = null | 'setup' | 'report' | 'compare';
export type LogsViewSource = LogSource | 'crashes';

export interface UiState {
  view: View;
  selectedFlowId: string | null;
  selectedLog: string | null;
  search: string;
  searchInit: boolean;
  quick: QuickFilter;
  host: string | null;
  /** Ids listed when Pause was pressed; null while live. */
  frozen: ReadonlySet<string> | null;
  /** Ids hidden by Clear. */
  hidden: ReadonlySet<string>;
  /** Log lines up to these seq values are hidden by Clear. */
  clearedSeq: Record<LogSource, number>;
  stripSource: LogSource;
  stripMinLevel: Level;
  stripText: string;
  stripAutoscroll: boolean;
  logsSource: LogsViewSource;
  logsLevels: ReadonlySet<Level>;
  logsText: string;
  logsAutoscroll: boolean;
  logsTag: string | null;
  logsLinkedOnly: boolean;
  /** The last seq listed per source when Pause logs was pressed; null while live. */
  logsFrozen: Record<LogSource, number> | null;
  /** Crash lines (by log key) whose stack trace is shown whole. */
  logsExpanded: ReadonlySet<string>;
  dialog: Dialog;
  toast: { id: number; text: string } | null;
  /** A request to pre-fill a new rule from (Traffic > New rule). */
  ruleSeed: FlowSummary | null;
}

export interface Store {
  phase: Phase;
  loaded: boolean;
  appState: AppState | null;
  flows: FlowSummary[];
  logs: LogSets;
  /** Loaded when the Rules view opens; counters then follow the socket. */
  rules: RulesPayload | null;
  /** The rules changed on the server since `rules` was loaded. */
  rulesStale: boolean;
  /** A previous session opened read-only; the live flows and logs above keep following the socket. */
  view: ViewedSession | null;
  ui: UiState;
}

export interface ViewedSession {
  name: string;
  flows: FlowSummary[];
  logs: LogSets;
  cutOff: boolean;
}

export type Action =
  | { type: 'phase'; phase: Phase }
  | { type: 'loaded'; data: InitialData; buffered: ServerMessage[] }
  | { type: 'message'; message: ServerMessage }
  | { type: 'ui'; patch: Partial<UiState> }
  | { type: 'rules'; rules: RulesPayload }
  | { type: 'newRuleFrom'; flow: FlowSummary }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'clear' }
  | { type: 'logsPause' }
  | { type: 'logsResume' }
  | { type: 'logsClear' }
  | { type: 'openFlow'; id: string }
  | { type: 'viewOpened'; view: ViewedSession }
  | { type: 'viewClosed' }
  | { type: 'toast'; text: string };

export const initialStore: Store = {
  phase: 'connecting',
  loaded: false,
  appState: null,
  flows: [],
  logs: { device: [], app: [] },
  rules: null,
  rulesStale: false,
  view: null,
  ui: {
    view: 'traffic',
    selectedFlowId: null,
    selectedLog: null,
    search: '',
    searchInit: false,
    quick: 'all',
    host: null,
    frozen: null,
    hidden: new Set(),
    clearedSeq: { device: -Infinity, app: -Infinity },
    stripSource: 'device',
    stripMinLevel: 'V',
    stripText: '',
    stripAutoscroll: true,
    logsSource: 'device',
    logsLevels: new Set(LEVELS),
    logsText: '',
    logsAutoscroll: true,
    logsTag: null,
    logsLinkedOnly: false,
    logsFrozen: null,
    logsExpanded: new Set(),
    dialog: null,
    toast: null,
    ruleSeed: null,
  },
};

let toastId = 0;

export function reducer(store: Store, action: Action): Store {
  switch (action.type) {
    case 'phase':
      return store.phase === action.phase ? store : { ...store, phase: action.phase };
    case 'loaded': {
      const merged = applyMessages(
        { flows: mergeFlows([], action.data.flows), logs: mergeLogSets({ device: [], app: [] }, [...action.data.device, ...action.data.app]) },
        action.buffered,
      );
      const appState = latestState(action.data.state, action.buffered);
      const ui = store.ui.searchInit
        ? store.ui
        : { ...store.ui, search: appState.default_filter, searchInit: true };
      return { ...store, loaded: true, appState, flows: merged.flows, logs: merged.logs, ui, view: keptView(store.view, appState) };
    }
    case 'message': {
      const m = action.message;
      if (m.type === 'flows') return { ...store, flows: mergeFlows(store.flows, m.flows) };
      if (m.type === 'logs') return { ...store, logs: mergeLogSets(store.logs, m.lines) };
      if (m.type === 'rules') return applyRulesMessage(store, m);
      if (m.type === 'device') return store.appState ? { ...store, appState: { ...store.appState, device_status: m.status } } : store;
      return { ...store, appState: m.state, view: keptView(store.view, m.state) };
    }
    case 'viewOpened':
      return {
        ...store,
        view: action.view,
        ui: { ...store.ui, view: store.ui.view === 'rules' ? 'traffic' : store.ui.view, selectedFlowId: null, selectedLog: null, host: null, dialog: null },
      };
    case 'viewClosed':
      return store.view ? { ...store, view: null, ui: { ...store.ui, selectedFlowId: null, selectedLog: null, host: null } } : store;
    case 'ui':
      return { ...store, ui: { ...store.ui, ...action.patch } };
    case 'rules': {
      const rulesOn = action.rules.rules.filter((r) => r.enabled).length;
      const appState = store.appState ? { ...store.appState, rules_on: rulesOn } : store.appState;
      return { ...store, rules: action.rules, rulesStale: false, appState };
    }
    case 'newRuleFrom':
      return { ...store, ui: { ...store.ui, view: 'rules', ruleSeed: action.flow } };
    case 'pause':
      return { ...store, ui: { ...store.ui, frozen: new Set(store.flows.map((f) => f.id)) } };
    case 'resume':
      return { ...store, ui: { ...store.ui, frozen: null } };
    case 'logsPause':
      return { ...store, ui: { ...store.ui, logsFrozen: { device: lastSeq(store.logs.device), app: lastSeq(store.logs.app) } } };
    case 'logsResume':
      return { ...store, ui: { ...store.ui, logsFrozen: null } };
    case 'logsClear':
      return {
        ...store,
        ui: {
          ...store.ui,
          clearedSeq: {
            device: Math.max(store.ui.clearedSeq.device, lastSeq(store.logs.device)),
            app: Math.max(store.ui.clearedSeq.app, lastSeq(store.logs.app)),
          },
          selectedLog: null,
        },
      };
    case 'clear': {
      const hidden = new Set(store.ui.hidden);
      for (const f of store.flows) hidden.add(f.id);
      return {
        ...store,
        ui: {
          ...store.ui,
          hidden,
          clearedSeq: {
            device: Math.max(store.ui.clearedSeq.device, lastSeq(store.logs.device)),
            app: Math.max(store.ui.clearedSeq.app, lastSeq(store.logs.app)),
          },
          selectedFlowId: null,
          selectedLog: null,
        },
      };
    }
    case 'openFlow': {
      const hidden = new Set(store.ui.hidden);
      hidden.delete(action.id);
      const frozen = store.ui.frozen ? new Set(store.ui.frozen).add(action.id) : null;
      return {
        ...store,
        ui: { ...store.ui, view: 'traffic', selectedFlowId: action.id, quick: 'all', host: null, search: '', hidden, frozen },
      };
    }
    case 'toast':
      return { ...store, ui: { ...store.ui, toast: { id: ++toastId, text: action.text } } };
  }
}

/** Counters always follow; a new revision or file error means the list must be reloaded. */
export function applyRulesMessage(store: Store, m: Extract<ServerMessage, { type: 'rules' }>): Store {
  if (!store.rules) return store;
  const stale = m.revision !== store.rules.revision || m.error !== store.rules.error;
  return { ...store, rules: { ...store.rules, stats: m.stats }, rulesStale: store.rulesStale || stale };
}

/** The server holds one opened session for every page: when another page changed it, this one goes back to live. */
function keptView(view: ViewedSession | null, state: AppState): ViewedSession | null {
  return view && state.viewing === view.name ? view : null;
}

function lastSeq(lines: readonly { seq: number }[]): number {
  return lines.length ? (lines[lines.length - 1] as { seq: number }).seq : -Infinity;
}

/** The state after the messages that arrived while loading: a state message replaces it, a device message updates it. */
export function latestState(initial: AppState, buffered: ServerMessage[]): AppState {
  let state = initial;
  for (const m of buffered) {
    if (m.type === 'state') state = m.state;
    else if (m.type === 'device') state = { ...state, device_status: m.status };
  }
  return state;
}

const StoreContext = createContext<Store>(initialStore);
const DispatchContext = createContext<Dispatch<Action>>(() => undefined);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [store, dispatch] = useReducer(reducer, initialStore);
  return (
    <DispatchContext.Provider value={dispatch}>
      <StoreContext.Provider value={store}>{children}</StoreContext.Provider>
    </DispatchContext.Provider>
  );
}

export const useStore = () => useContext(StoreContext);
export const useDispatch = () => useContext(DispatchContext);

export interface ShownData {
  flows: FlowSummary[];
  logs: LogSets;
  /** The previous session shown, or null for the live one. */
  viewing: string | null;
}

/** The flows and logs the window shows: the opened previous session, else the live one. */
export function useData(): ShownData {
  const { view, flows, logs } = useStore();
  return useMemo(
    () => (view ? { flows: view.flows, logs: view.logs, viewing: view.name } : { flows, logs, viewing: null }),
    [view, flows, logs],
  );
}
