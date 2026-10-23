import { describe, expect, it } from 'vitest';
import type { BreakpointInfo, FlowDetail } from '../types';
import {
  bodyNotEditableText,
  draftOf,
  draftProblem,
  editedParts,
  editsOf,
  giveUpHint,
  isFixed,
  TEXTS,
  waited,
  type Draft,
} from './breakpoint';
import { flow } from './testing';

const BODY = { text: '{"qty": 1}', size: 10, truncated: false, binary: false };

function held(over: Partial<BreakpointInfo> = {}): BreakpointInfo {
  return {
    phase: 'request',
    since: 1_700_000_000,
    revision: 3,
    body_not_editable: null,
    original: { method: 'POST', path: '/api/v1/orders', headers: [], body: BODY },
    ...over,
  };
}

function detail(breakpoint: BreakpointInfo | null): FlowDetail {
  return {
    summary: flow({ method: 'POST', path: '/api/v1/orders', status: null, paused: breakpoint?.phase ?? null }),
    request: {
      http_version: 'HTTP/1.1',
      headers: [
        ['Host', 'api.example.com'],
        ['Content-Length', '10'],
        ['X-Request-ID', 'req-1'],
      ],
      body: BODY,
    },
    response: breakpoint?.phase === 'response'
      ? { status: 200, reason: 'OK', http_version: 'HTTP/1.1', headers: [['content-type', 'application/json']], body: BODY }
      : null,
    timing: { start: null, request_end: null, response_start: null, response_end: null },
    comment: '',
    mock_path: '',
    breakpoint,
    changes: [],
  };
}

const initial = draftOf(detail(held())) as Draft;

describe('breakpoint', () => {
  it('drafts the held request, and nothing for a flow that is not paused', () => {
    expect(initial).toMatchObject({ phase: 'request', method: 'POST', path: '/api/v1/orders', body: '{"qty": 1}' });
    expect(draftOf(detail(null))).toBeNull();
    const response = draftOf(detail(held({ phase: 'response' })));
    expect(response).toMatchObject({ phase: 'response', status: '200', headers: [['content-type', 'application/json']] });
  });

  it('does not offer a binary body or one over 1 MiB', () => {
    expect(draftOf(detail(held({ body_not_editable: 'binary' })))?.body).toBeNull();
    expect(bodyNotEditableText('over 1 MiB')).toBe('Body not editable: over 1 MiB');
  });

  it('refuses what the server refuses, with its texts', () => {
    const cases: [Partial<Draft>, string][] = [
      [{ method: 'post' }, TEXTS.method],
      [{ method: 'A'.repeat(17) }, TEXTS.method],
      [{ path: 'api/v1' }, TEXTS.path],
      [{ path: '/a b' }, TEXTS.path],
      [{ headers: [...initial.headers, ['X-A', 'one\r\ntwo']] }, TEXTS.header],
      [{ headers: [...initial.headers, ['X A', 'one']] }, TEXTS.header],
      [{ headers: initial.headers.filter(([k]) => k !== 'Host') }, TEXTS.fixed],
      [{ headers: [...initial.headers, ['transfer-encoding', 'chunked']] }, TEXTS.fixed],
      [{ body: 'é'.repeat((1 << 19) + 1) }, TEXTS.bodySize],
    ];
    for (const [over, text] of cases) expect(draftProblem({ ...initial, ...over }, initial), JSON.stringify(over).slice(0, 60)).toBe(text);
    expect(draftProblem(initial, initial)).toBeNull();
    // A blank row the user added and left is not sent.
    expect(draftProblem({ ...initial, headers: [...initial.headers, ['', '']] }, initial)).toBeNull();
    const response = draftOf(detail(held({ phase: 'response' }))) as Draft;
    for (const status of ['99', '600', 'abc', '']) expect(draftProblem({ ...response, status }, response)).toBe(TEXTS.status);
    expect(draftProblem({ ...response, status: '503' }, response)).toBeNull();
  });

  it('sends every part, the body only when it changed, and names what changed', () => {
    expect(editsOf(initial, initial)).toEqual({ method: 'POST', path: '/api/v1/orders', headers: initial.headers, body: null });
    expect(editedParts(initial, initial)).toEqual([]);
    const draft = { ...initial, path: '/api/v1/orders?x=1', body: '{"qty": 2}', headers: [...initial.headers, [' X-New ', 'v'] as [string, string]] };
    expect(editsOf(draft, initial)).toMatchObject({ path: '/api/v1/orders?x=1', body: '{"qty": 2}' });
    expect(editsOf(draft, initial).headers.at(-1)).toEqual(['X-New', 'v']);
    expect(editedParts(draft, initial)).toEqual(['path', 'headers', 'body']);
    const response = draftOf(detail(held({ phase: 'response' }))) as Draft;
    expect(editsOf({ ...response, status: '503' }, response)).toEqual({ status: 503, headers: response.headers, body: null });
    expect(editedParts({ ...response, status: '503' }, response)).toEqual(['status']);
  });

  it('shows the waiting time, and after 20 s that apps give up', () => {
    const since = 1_700_000_000;
    expect(waited(since, (since + 14.9) * 1000)).toBe('0:14');
    expect(waited(since, (since + 75) * 1000)).toBe('1:15');
    expect(giveUpHint(since, (since + 19) * 1000)).toBeNull();
    expect(giveUpHint(since, (since + 21) * 1000)).toBe('Apps usually give up after 30–60 s. This one has waited 21 s.');
    expect(isFixed(' Content-Length')).toBe(true);
    expect(isFixed('content-type')).toBe(false);
  });
});
