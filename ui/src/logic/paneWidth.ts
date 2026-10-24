/** Pane widths the tester drags, remembered in the browser's localStorage (spec 024). */
import { useLayoutEffect, useReducer, useState, type RefObject } from 'react';
import { browserStorage } from '../storage';

export interface PaneSpec {
  key: string;
  min: number;
  max: number;
  /** The width before the tester chooses one. */
  initial: (windowWidth: number) => number;
}

export interface PaneRange {
  min: number;
  max: number;
}

/** The request or log list keeps this much unless the tester drags a detail panel over it. */
export const LIST_MIN_DEFAULT = 480;
/** The narrowest list a detail panel the tester widened may leave (spec 026). */
export const LIST_MIN = 380;
export const KEY_STEP = 16;
export const KEY_STEP_BIG = 64;

const PREFIX = 'wiretrace.pane.';

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

const detailInitial = (low: number) => (windowWidth: number) => Math.round(clamp(windowWidth * 0.4, low, 720));

export const TRAFFIC_SIDEBAR: PaneSpec = { key: `${PREFIX}traffic.sidebar`, min: 160, max: 360, initial: () => 220 };
export const TRAFFIC_DETAIL: PaneSpec = { key: `${PREFIX}traffic.detail`, min: 360, max: Infinity, initial: detailInitial(470) };
export const LOGS_DETAIL: PaneSpec = { key: `${PREFIX}logs.detail`, min: 360, max: Infinity, initial: detailInitial(430) };

/** Where a handle may move when `room` is all the pane can take. Too little room pins it there. */
export function paneRange(spec: PaneSpec, room: number): PaneRange {
  const max = Math.max(0, Math.min(spec.max, room));
  return { min: Math.min(spec.min, max), max };
}

/**
 * The width a pane renders at: a chosen width within `room`, the default within `defaultRoom`.
 * The stored choice is not changed by a narrow window.
 */
export function fitWidth(spec: PaneSpec, stored: number | null, windowWidth: number, room: number, defaultRoom = room): number {
  const wanted = clamp(stored ?? spec.initial(windowWidth), spec.min, spec.max);
  return Math.max(0, Math.min(wanted, stored === null ? defaultRoom : room));
}

/** The remembered width; anything unreadable or out of range counts as none. */
export function loadWidth(storage: Pick<Storage, 'getItem'> | null, spec: PaneSpec): number | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(spec.key);
    if (raw === null || raw.trim() === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= spec.min && n <= spec.max ? Math.round(n) : null;
  } catch {
    return null;
  }
}

export function storeWidth(storage: Pick<Storage, 'setItem'> | null, spec: PaneSpec, width: number): void {
  try {
    storage?.setItem(spec.key, String(Math.round(width)));
  } catch {
    // Storage full or off: the width lasts until the window closes.
  }
}

export function clearWidth(storage: Pick<Storage, 'removeItem'> | null, spec: PaneSpec): void {
  try {
    storage?.removeItem(spec.key);
  } catch {
    // Nothing to clear.
  }
}

const STRIP_KEY = `${PREFIX}traffic.logs`;

/** Whether the tester collapsed the log strip under Traffic; shown unless stored as hidden. */
export function loadStripHidden(storage: Pick<Storage, 'getItem'> | null): boolean {
  try {
    return storage?.getItem(STRIP_KEY) === 'hidden';
  } catch {
    return false;
  }
}

export function storeStripHidden(storage: Pick<Storage, 'setItem' | 'removeItem'> | null, hidden: boolean): void {
  try {
    if (hidden) storage?.setItem(STRIP_KEY, 'hidden');
    else storage?.removeItem(STRIP_KEY);
  } catch {
    // Storage full or off: the choice lasts until the window closes.
  }
}

/**
 * `grow` is +1 when the pane widens as its handle moves right (the sidebar) and −1 when it
 * widens leftwards (a detail panel).
 */
export function dragWidth(startWidth: number, dx: number, grow: 1 | -1, range: PaneRange): number {
  return Math.round(clamp(startWidth + grow * dx, range.min, range.max));
}

/** The width a key asks for, 'reset' for the default, or null when the key is not ours. */
export function keyWidth(key: string, shift: boolean, width: number, grow: 1 | -1, range: PaneRange): number | 'reset' | null {
  const step = shift ? KEY_STEP_BIG : KEY_STEP;
  switch (key) {
    case 'ArrowLeft':
      return clamp(width - grow * step, range.min, range.max);
    case 'ArrowRight':
      return clamp(width + grow * step, range.min, range.max);
    case 'Home':
      return range.min;
    case 'End':
      return range.max;
    case 'Enter':
      return 'reset';
    default:
      return null;
  }
}

/** `stored` is the tester's choice; `live` is the width under a drag that has not ended yet. */
export interface PaneState {
  stored: number | null;
  live: number | null;
}

export type PaneAction = { type: 'preview'; width: number } | { type: 'choose'; width: number } | { type: 'release' } | { type: 'reset' };

export function paneState(state: PaneState, action: PaneAction): PaneState {
  switch (action.type) {
    case 'preview':
      return { ...state, live: action.width };
    case 'choose':
      return { stored: action.width, live: null };
    case 'release':
      return state.live === null ? state : { ...state, live: null };
    case 'reset':
      return { stored: null, live: null };
  }
}

export interface Pane extends PaneRange {
  width: number;
  /** While dragging: renders the width without remembering it. */
  preview: (width: number) => void;
  /** Renders and remembers the width. */
  choose: (width: number) => void;
  /** Ends a drag that changed nothing: back to the remembered width. */
  release: () => void;
  reset: () => void;
}

/** `room` bounds what the tester may choose; `defaultRoom` bounds the width before a choice. */
export function usePaneWidth(spec: PaneSpec, room: number, windowWidth: number, defaultRoom = room): Pane {
  const [state, dispatch] = useReducer(paneState, spec, (s): PaneState => ({ stored: loadWidth(browserStorage(), s), live: null }));
  const range = paneRange(spec, room);
  return {
    ...range,
    width: state.live === null ? fitWidth(spec, state.stored, windowWidth, room, defaultRoom) : clamp(state.live, range.min, range.max),
    preview: (width) => dispatch({ type: 'preview', width: Math.round(width) }),
    choose: (width) => {
      const kept = Math.round(clamp(clamp(width, range.min, range.max), spec.min, spec.max));
      dispatch({ type: 'choose', width: kept });
      storeWidth(browserStorage(), spec, kept);
    },
    release: () => dispatch({ type: 'release' }),
    reset: () => {
      dispatch({ type: 'reset' });
      clearWidth(browserStorage(), spec);
    },
  };
}

export interface BoxWidth {
  box: number;
  window: number;
}

/** The element's width and the window's, measured again whenever the element resizes. */
export function useBoxWidth(ref: RefObject<HTMLElement | null>): BoxWidth {
  const [size, setSize] = useState<BoxWidth>(() => {
    const w = typeof window === 'undefined' ? 0 : window.innerWidth;
    return { box: w, window: w };
  });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () =>
      setSize((s) => (s.box === el.clientWidth && s.window === window.innerWidth ? s : { box: el.clientWidth, window: window.innerWidth }));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
