import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import type { InitialData } from './connection';
import { isFaultsOn } from './logic/faults';
import type { QuickFilter } from './logic/filters';
import { LEVELS, type Level } from './logic/logs';
import { applyMessages, mergeFlows, mergeLogSets, type LogSets } from './logic/merge';
import type { AppState, Faults, FlowSummary, LogSource, Phase, ServerMessage } from './types';

export type View = 'traffic' | 'logs';
export type Dialog = null | 'setup' | 'faults' | 'report';
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
  dialog: Dialog;
  toast: { id: number; text: string } | null;
}

export interface Store {
  phase: Phase;
  loaded: boolean;
  appState: AppState | null;
  flows: FlowSummary[];
  logs: LogSets;
  ui: UiState;
}

export type Action =
  | { type: 'phase'; phase: Phase }
  | { type: 'loaded'; data: InitialData; buffered: ServerMessage[] }
  | { type: 'message'; message: ServerMessage }
  | { type: 'ui'; patch: Partial<UiState> }
  | { type: 'faults'; faults: Faults }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'clear' }
  | { type: 'openFlow'; id: string }
  | { type: 'toast'; text: string };

export const initialStore: Store = {
  phase: 'connecting',
  loaded: false,
  appState: null,
  flows: [],
  logs: { device: [], app: [] },
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
    dialog: null,
    toast: null,
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
      return { ...store, loaded: true, appState, flows: merged.flows, logs: merged.logs, ui };
    }
    case 'message': {
      const m = action.message;
      if (m.type === 'flows') return { ...store, flows: mergeFlows(store.flows, m.flows) };
      if (m.type === 'logs') return { ...store, logs: mergeLogSets(store.logs, m.lines) };
      return { ...store, appState: m.state };
    }
    case 'ui':
      return { ...store, ui: { ...store.ui, ...action.patch } };
    case 'faults':
      return store.appState
        ? { ...store, appState: { ...store.appState, faults: action.faults, faults_on: isFaultsOn(action.faults) } }
        : store;
    case 'pause':
      return { ...store, ui: { ...store.ui, frozen: new Set(store.flows.map((f) => f.id)) } };
    case 'resume':
      return { ...store, ui: { ...store.ui, frozen: null } };
    case 'clear': {
      const hidden = new Set(store.ui.hidden);
      for (const f of store.flows) hidden.add(f.id);
      const last = (lines: { seq: number }[]) => (lines.length ? (lines[lines.length - 1] as { seq: number }).seq : -Infinity);
      return {
        ...store,
        ui: {
          ...store.ui,
          hidden,
          clearedSeq: {
            device: Math.max(store.ui.clearedSeq.device, last(store.logs.device)),
            app: Math.max(store.ui.clearedSeq.app, last(store.logs.app)),
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

function latestState(initial: AppState, buffered: ServerMessage[]): AppState {
  let state = initial;
  for (const m of buffered) if (m.type === 'state') state = m.state;
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
