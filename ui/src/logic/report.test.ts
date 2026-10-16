import { describe, expect, it } from 'vitest';
import type { ReportDraft, Screenshot } from '../types';
import {
  canTakeScreenshot,
  countLabel,
  formatKey,
  formReducer,
  includedBoxes,
  initialForm,
  loadFormat,
  MAX_SCREENSHOTS,
  reportFlowId,
  storeFormat,
  titleError,
  type FormAction,
  type FormState,
} from './report';
import { flow } from './testing';

function draft(over: Partial<ReportDraft> = {}): ReportDraft {
  return {
    title: 'POST /api/v1/orders returns 500',
    description: '## Steps to reproduce\n1. \n',
    format: 'markdown',
    lead: { request: 'POST /api/v1/orders → 500', at: '19:41:18', device: null, session: 's1' },
    counts: { others: 3, device: 2, app: 1 },
    masked: { headers: ['Authorization'], fields: ['password'] },
    files: [{ kind: 'har', name: 's1-requests.har', size: 10 }],
    screenshots: { state: 'available', reason: null, items: [] },
    ...over,
  };
}

function shot(n: number): Screenshot {
  return { name: `20261016-1941${String(n).padStart(2, '0')}.png`, size: 100, time: `19:41:${String(n).padStart(2, '0')}` };
}

function run(state: FormState, ...actions: FormAction[]): FormState {
  return actions.reduce(formReducer, state);
}

function ready(over: Partial<ReportDraft> = {}): FormState {
  const s = initialForm('markdown');
  return run(s, { type: 'draft', seq: s.seq, draft: draft(over) });
}

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

describe('report form', () => {
  it('fills the title and description from the draft', () => {
    const s = ready();
    expect(s.phase).toBe('ready');
    expect(s.title).toBe('POST /api/v1/orders returns 500');
    expect(s.description).toBe('## Steps to reproduce\n1. \n');
    expect(s.edited).toBe(false);
  });

  it('regenerates at once while the text is unedited', () => {
    const s = run(ready(), { type: 'change', change: { kind: 'box', box: 'device', on: false } });
    expect(s.phase).toBe('loading');
    expect(s.include.device).toBe(false);
    expect(s.pending).toBeNull();
  });

  it('asks before replacing edits, and No keeps the text and the old choice', () => {
    const edited = run(ready(), { type: 'description', text: 'my steps' });
    const asked = run(edited, { type: 'change', change: { kind: 'format', format: 'jira' } });
    expect(asked.pending).toEqual({ kind: 'format', format: 'jira' });
    expect(asked.format).toBe('markdown');
    expect(asked.seq).toBe(edited.seq);

    const kept = run(asked, { type: 'cancel' });
    expect(kept.description).toBe('my steps');
    expect(kept.format).toBe('markdown');
    expect(kept.phase).toBe('ready');

    const replaced = run(asked, { type: 'confirm' });
    expect(replaced.format).toBe('jira');
    expect(replaced.phase).toBe('loading');
    const answered = run(replaced, { type: 'draft', seq: replaced.seq, draft: draft({ description: 'h2. Steps', format: 'jira' }) });
    expect(answered.description).toBe('h2. Steps');
    expect(answered.edited).toBe(false);
  });

  it('ignores a stale draft', () => {
    let s = ready();
    s = run(s, { type: 'change', change: { kind: 'box', box: 'app', on: false } });
    const older = s.seq;
    s = run(s, { type: 'change', change: { kind: 'box', box: 'others', on: false } });
    s = run(s, { type: 'draft', seq: older, draft: draft({ description: 'old' }) });
    expect(s.phase).toBe('loading');
    expect(s.description).not.toBe('old');
    s = run(s, { type: 'failed', seq: older, error: 'boom' });
    expect(s.error).toBeNull();
    s = run(s, { type: 'draft', seq: s.seq, draft: draft({ description: 'new' }) });
    expect(s.description).toBe('new');
  });

  it('keeps the description read-only while a draft is loading', () => {
    const s = run(ready(), { type: 'change', change: { kind: 'box', box: 'app', on: false } }, { type: 'description', text: 'lost' });
    expect(s.description).not.toBe('lost');
    expect(s.edited).toBe(false);
  });

  it('copies the current text, edits included', () => {
    const s = run(ready(), { type: 'title', text: 'Order fails' }, { type: 'description', text: 'edited body' });
    expect(s.title).toBe('Order fails');
    expect(s.description).toBe('edited body');
  });

  it('keeps an edited title across regenerations', () => {
    let s = run(ready(), { type: 'title', text: 'Mine' }, { type: 'change', change: { kind: 'format', format: 'jira' } });
    s = run(s, { type: 'draft', seq: s.seq, draft: draft({ title: 'Other' }) });
    expect(s.title).toBe('Mine');
  });

  it('checks the title length', () => {
    expect(titleError('x')).toBeNull();
    expect(titleError('   ')).not.toBeNull();
    expect(titleError('x'.repeat(200))).toBeNull();
    expect(titleError('x'.repeat(201))).not.toBeNull();
  });

  it('holds the 5 screenshot limit', () => {
    const four = ready({ screenshots: { state: 'available', reason: null, items: [1, 2, 3, 4].map(shot) } });
    expect(canTakeScreenshot(four)).toBe(true);
    const capturing = run(four, { type: 'capturing' });
    expect(canTakeScreenshot(capturing)).toBe(false);
    const five = run(capturing, { type: 'captured', screenshots: [1, 2, 3, 4, 5].map(shot) });
    expect(five.screenshots).toHaveLength(MAX_SCREENSHOTS);
    expect(canTakeScreenshot(five)).toBe(false);
    const fewer = run(five, { type: 'removed', screenshots: [1, 2, 3, 4].map(shot) });
    expect(canTakeScreenshot(fewer)).toBe(true);
  });

  it('shows a failed screenshot and keeps working', () => {
    const s = run(ready(), { type: 'capturing' }, { type: 'captureFailed', error: 'adb: device unauthorized' });
    expect(s.capturing).toBe(false);
    expect(s.shotError).toBe('adb: device unauthorized');
    expect(canTakeScreenshot(s)).toBe(true);
    expect(run(s, { type: 'capturing' }).shotError).toBeNull();
  });

  it('takes no screenshot when the state is off or manual', () => {
    expect(canTakeScreenshot(ready({ screenshots: { state: 'off', reason: 'No Android device connected', items: [] } }))).toBe(false);
    expect(canTakeScreenshot(ready({ screenshots: { state: 'manual', reason: 'Take it on the iPhone', items: [] } }))).toBe(false);
  });

  it('lists the boxes ticked, in order', () => {
    expect(includedBoxes({ others: true, device: false, app: true })).toEqual(['others', 'app']);
    expect(countLabel('others', 1)).toBe('1 request');
    expect(countLabel('device', 42)).toBe('42 lines');
  });
});

describe('report request', () => {
  it('is the selected request, else the most recent failed one, else none', () => {
    const flows = [
      flow({ id: 'a', ts: 1, status: 500 }),
      flow({ id: 'b', ts: 3, status: null, error: 'Connection reset' }),
      flow({ id: 'c', ts: 4, status: 200 }),
      flow({ id: 'd', ts: 2, status: 404 }),
    ];
    expect(reportFlowId('c', flows)).toBe('c');
    expect(reportFlowId(null, flows)).toBe('b');
    expect(reportFlowId('gone', flows)).toBe('b');
    expect(reportFlowId(null, [flow({ id: 'ok', status: 200 })])).toBeNull();
  });
});

describe('report format', () => {
  it('is remembered per preset, Markdown by default', () => {
    const s = memory();
    expect(loadFormat(s, 'staging')).toBe('markdown');
    storeFormat(s, 'staging', 'jira');
    expect(loadFormat(s, 'staging')).toBe('jira');
    expect(loadFormat(s, 'other')).toBe('markdown');
    expect([...s.data.keys()]).toEqual([formatKey('staging')]);
    expect(loadFormat(memory({ [formatKey('p')]: 'html' }), 'p')).toBe('markdown');
    expect(loadFormat(null, 'p')).toBe('markdown');
  });
});
