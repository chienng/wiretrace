import { describe, expect, it } from 'vitest';
import {
  KEY_STEP,
  KEY_STEP_BIG,
  LIST_MIN,
  LIST_MIN_DEFAULT,
  LOGS_DETAIL,
  TRAFFIC_DETAIL,
  TRAFFIC_SIDEBAR,
  clearWidth,
  dragWidth,
  fitWidth,
  keyWidth,
  loadStripHidden,
  loadWidth,
  paneRange,
  paneState,
  storeStripHidden,
  storeWidth,
  type PaneState,
} from './paneWidth';

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

const ROOMY = 10_000;

describe('pane width defaults', () => {
  it('give the detail panel 40 % of the window, within its default limits', () => {
    expect(fitWidth(TRAFFIC_DETAIL, null, 1440, ROOMY)).toBe(576);
    expect(fitWidth(TRAFFIC_DETAIL, null, 1024, ROOMY)).toBe(470);
    expect(fitWidth(TRAFFIC_DETAIL, null, 2560, ROOMY)).toBe(720);
    expect(fitWidth(LOGS_DETAIL, null, 1024, ROOMY)).toBe(430);
    expect(fitWidth(LOGS_DETAIL, null, 1440, ROOMY)).toBe(576);
    expect(fitWidth(TRAFFIC_SIDEBAR, null, 1440, ROOMY)).toBe(220);
  });
});

describe('pane width limits', () => {
  it('clamp a chosen width to the pane limits', () => {
    expect(fitWidth(TRAFFIC_SIDEBAR, 100, 1440, ROOMY)).toBe(160);
    expect(fitWidth(TRAFFIC_SIDEBAR, 500, 1440, ROOMY)).toBe(360);
    expect(fitWidth(TRAFFIC_DETAIL, 300, 1440, ROOMY)).toBe(360);
    expect(fitWidth(TRAFFIC_DETAIL, 900, 1440, ROOMY)).toBe(900);
  });

  it('let the default detail panel give way so the list keeps its default minimum', () => {
    const box = 1024;
    const sidebar = fitWidth(TRAFFIC_SIDEBAR, null, box, box - LIST_MIN_DEFAULT);
    const detail = fitWidth(TRAFFIC_DETAIL, null, box, box - LIST_MIN - sidebar, box - LIST_MIN_DEFAULT - sidebar);
    expect(sidebar).toBe(220);
    expect(detail).toBe(324);
    expect(box - sidebar - detail).toBe(LIST_MIN_DEFAULT);
  });

  it('let the sidebar give way only once the detail panel has nothing left', () => {
    expect(fitWidth(TRAFFIC_SIDEBAR, 360, 800, 800 - LIST_MIN_DEFAULT)).toBe(320);
  });

  it('keep the chosen width whenever it fits again: a narrow window does not overwrite it', () => {
    const stored = 700;
    expect(fitWidth(TRAFFIC_DETAIL, stored, 1100, 1100 - LIST_MIN - 220)).toBe(500);
    expect(fitWidth(TRAFFIC_DETAIL, stored, 1800, 1800 - LIST_MIN - 220)).toBe(700);
  });

  it('give a handle the range the room allows, pinned when the room is below the minimum', () => {
    expect(paneRange(TRAFFIC_DETAIL, ROOMY)).toEqual({ min: 360, max: ROOMY });
    expect(paneRange(TRAFFIC_DETAIL, 500)).toEqual({ min: 360, max: 500 });
    expect(paneRange(TRAFFIC_DETAIL, 300)).toEqual({ min: 300, max: 300 });
    expect(paneRange(TRAFFIC_SIDEBAR, -20)).toEqual({ min: 0, max: 0 });
  });
});

describe('a detail panel the tester widens (spec 026)', () => {
  const box = 1440;
  const sidebar = 220;
  const chosenRoom = box - LIST_MIN - sidebar;
  const defaultRoom = box - LIST_MIN_DEFAULT - sidebar;

  it('keeps the default layout: a 480 px list', () => {
    expect(fitWidth(TRAFFIC_DETAIL, null, box, chosenRoom, defaultRoom)).toBe(576);
    expect(fitWidth(LOGS_DETAIL, null, 1024, 1024 - LIST_MIN, 1024 - LIST_MIN_DEFAULT)).toBe(430);
    expect(fitWidth(TRAFFIC_DETAIL, null, 1024, 1024 - LIST_MIN - sidebar, 1024 - LIST_MIN_DEFAULT - sidebar)).toBe(324);
  });

  it('may leave a 380 px list, never less', () => {
    expect(paneRange(TRAFFIC_DETAIL, chosenRoom)).toEqual({ min: 360, max: 840 });
    expect(fitWidth(TRAFFIC_DETAIL, 840, box, chosenRoom, defaultRoom)).toBe(840);
    expect(fitWidth(TRAFFIC_DETAIL, 1200, box, chosenRoom, defaultRoom)).toBe(840);
    expect(paneRange(TRAFFIC_DETAIL, box - LIST_MIN - 160).max).toBe(900);
  });

  it('has no 720 px cap in a wide window', () => {
    expect(fitWidth(TRAFFIC_DETAIL, 1400, 2560, 2560 - LIST_MIN - sidebar, 2560 - LIST_MIN_DEFAULT - sidebar)).toBe(1400);
    expect(fitWidth(LOGS_DETAIL, 1400, 2560, 2560 - LIST_MIN, 2560 - LIST_MIN_DEFAULT)).toBe(1400);
  });

  it('loads a remembered width above 720 px, still not one below 360 px', () => {
    expect(loadWidth(memory({ [TRAFFIC_DETAIL.key]: '900' }), TRAFFIC_DETAIL)).toBe(900);
    expect(loadWidth(memory({ [LOGS_DETAIL.key]: '359' }), LOGS_DETAIL)).toBeNull();
  });

  it('leaves the sidebar range as it was', () => {
    expect(paneRange(TRAFFIC_SIDEBAR, box - LIST_MIN_DEFAULT)).toEqual({ min: 160, max: 360 });
  });
});

describe('the log strip choice', () => {
  const key = 'wiretrace.pane.traffic.logs';

  it('is hidden only when stored as hidden', () => {
    expect(loadStripHidden(memory({ [key]: 'hidden' }))).toBe(true);
    for (const raw of ['', 'shown', 'true', 'HIDDEN']) expect(loadStripHidden(memory({ [key]: raw }))).toBe(false);
    expect(loadStripHidden(memory())).toBe(false);
    expect(loadStripHidden(null)).toBe(false);
    expect(loadStripHidden({ getItem: () => { throw new Error('SecurityError'); } })).toBe(false);
  });

  it('removes the key when shown again', () => {
    const s = memory();
    storeStripHidden(s, true);
    expect([...s.data.entries()]).toEqual([[key, 'hidden']]);
    storeStripHidden(s, false);
    expect(s.data.size).toBe(0);
  });

  it('survives a browser that refuses to store', () => {
    const refusing = { setItem: () => { throw new Error('QuotaExceededError'); }, removeItem: () => { throw new Error('SecurityError'); } };
    expect(() => storeStripHidden(refusing, true)).not.toThrow();
    expect(() => storeStripHidden(refusing, false)).not.toThrow();
    expect(() => storeStripHidden(null, true)).not.toThrow();
  });
});

describe('remembered pane widths', () => {
  it('are restored', () => {
    const s = memory();
    storeWidth(s, TRAFFIC_DETAIL, 612.4);
    expect([...s.data.entries()]).toEqual([['wiretrace.pane.traffic.detail', '612']]);
    expect(loadWidth(s, TRAFFIC_DETAIL)).toBe(612);
    expect(loadWidth(s, LOGS_DETAIL)).toBeNull();
  });

  it('count as absent when unreadable or out of range', () => {
    const key = TRAFFIC_SIDEBAR.key;
    for (const raw of ['', 'wide', 'NaN', 'Infinity', '120', '400']) expect(loadWidth(memory({ [key]: raw }), TRAFFIC_SIDEBAR)).toBeNull();
    expect(loadWidth(memory({ [key]: '160' }), TRAFFIC_SIDEBAR)).toBe(160);
    expect(loadWidth(null, TRAFFIC_SIDEBAR)).toBeNull();
    const refusing = { getItem: () => { throw new Error('SecurityError'); } };
    expect(loadWidth(refusing, TRAFFIC_SIDEBAR)).toBeNull();
  });

  it('are forgotten on reset', () => {
    const s = memory({ [LOGS_DETAIL.key]: '500', [TRAFFIC_DETAIL.key]: '600' });
    clearWidth(s, LOGS_DETAIL);
    expect(loadWidth(s, LOGS_DETAIL)).toBeNull();
    expect(loadWidth(s, TRAFFIC_DETAIL)).toBe(600);
  });

  it('survive a browser that refuses to store', () => {
    const full = { setItem: () => { throw new Error('QuotaExceededError'); } };
    expect(() => storeWidth(full, TRAFFIC_DETAIL, 500)).not.toThrow();
    expect(() => storeWidth(null, TRAFFIC_DETAIL, 500)).not.toThrow();
  });
});

describe('pane state while dragging', () => {
  it('leaves the remembered width alone during a drag, and after one that changed nothing', () => {
    const before: PaneState = { stored: 700, live: null };
    const dragging = paneState(before, { type: 'preview', width: 324 });
    expect(dragging).toEqual({ stored: 700, live: 324 });
    expect(paneState(dragging, { type: 'release' })).toEqual(before);
  });

  it('keeps following the window when a click on the handle changed nothing', () => {
    const before: PaneState = { stored: null, live: null };
    const clicked = paneState(paneState(before, { type: 'preview', width: 324 }), { type: 'release' });
    expect(clicked).toEqual(before);
    expect(fitWidth(TRAFFIC_DETAIL, clicked.stored, 1800, ROOMY)).toBe(720);
  });

  it('remembers the width a drag ends on, and forgets it on reset', () => {
    const chosen = paneState(paneState({ stored: null, live: null }, { type: 'preview', width: 610 }), { type: 'choose', width: 610 });
    expect(chosen).toEqual({ stored: 610, live: null });
    expect(paneState(chosen, { type: 'reset' })).toEqual({ stored: null, live: null });
  });
});

describe('handle movement', () => {
  const range = { min: 360, max: 720 };

  it('widens the sidebar rightwards and the detail panel leftwards while dragging', () => {
    expect(dragWidth(220, 40, 1, { min: 160, max: 360 })).toBe(260);
    expect(dragWidth(500, -40, -1, range)).toBe(540);
    expect(dragWidth(500, 40, -1, range)).toBe(460);
    expect(dragWidth(500, -1000, -1, range)).toBe(720);
    expect(dragWidth(220, -1000, 1, { min: 160, max: 360 })).toBe(160);
  });

  it('moves with the arrow keys, further with Shift, to the limits with Home and End', () => {
    expect(keyWidth('ArrowRight', false, 220, 1, { min: 160, max: 360 })).toBe(220 + KEY_STEP);
    expect(keyWidth('ArrowLeft', true, 300, 1, { min: 160, max: 360 })).toBe(300 - KEY_STEP_BIG);
    expect(keyWidth('ArrowLeft', true, 200, 1, { min: 160, max: 360 })).toBe(160);
    expect(keyWidth('ArrowLeft', false, 500, -1, range)).toBe(500 + KEY_STEP);
    expect(keyWidth('ArrowRight', true, 500, -1, range)).toBe(500 - KEY_STEP_BIG);
    expect(keyWidth('ArrowRight', true, 400, -1, range)).toBe(360);
    expect(keyWidth('Home', false, 500, -1, range)).toBe(360);
    expect(keyWidth('End', false, 500, -1, range)).toBe(720);
  });

  it('resets with Enter and leaves other keys alone', () => {
    expect(keyWidth('Enter', false, 500, -1, range)).toBe('reset');
    expect(keyWidth('ArrowUp', false, 500, -1, range)).toBeNull();
    expect(keyWidth('a', false, 500, -1, range)).toBeNull();
  });
});
