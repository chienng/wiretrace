import { describe, expect, it } from 'vitest';
import { buildCurl, mockFilePath, shellQuote } from './curl';
import { flow } from './testing';

const body = (text: string | null) => ({ text, size: text?.length ?? 0, truncated: false, binary: text === null });

describe('shellQuote', () => {
  it('wraps in single quotes and escapes embedded ones', () => {
    expect(shellQuote('plain')).toBe(`'plain'`);
    expect(shellQuote(`it's`)).toBe(`'it'\\''s'`);
    expect(shellQuote('$HOME `id` "x"')).toBe(`'$HOME \`id\` "x"'`);
  });
});

describe('buildCurl', () => {
  it('includes method, URL, headers and body, and skips pseudo headers', () => {
    const detail = {
      summary: flow({ method: 'POST', path: '/api/v1/orders' }),
      request: {
        http_version: 'HTTP/2.0',
        headers: [
          [':authority', 'api.example.com'],
          ['content-type', 'application/json'],
          ['authorization', 'Bearer test-token'],
        ] as [string, string][],
        body: body(`{"note":"it's"}`),
      },
    };
    expect(buildCurl(detail)).toBe(
      `curl -X 'POST' 'https://api.example.com/api/v1/orders' -H 'content-type: application/json' ` +
        `-H 'authorization: Bearer test-token' --data-raw '{"note":"it'\\''s"}'`,
    );
  });

  it('leaves out the body when there is none or it is binary', () => {
    const request = { http_version: 'HTTP/1.1', headers: [], body: body('') };
    expect(buildCurl({ summary: flow(), request })).toBe(`curl -X 'GET' 'https://api.example.com/api/v1/profile'`);
    expect(buildCurl({ summary: flow(), request: { ...request, body: body(null) } })).not.toContain('--data-raw');
  });
});

describe('mockFilePath', () => {
  it('builds <mocks_dir>/<METHOD><path without query>.json', () => {
    expect(mockFilePath('mocks/staging', { method: 'get', path: '/api/v1/profile?x=1' })).toBe(
      'mocks/staging/GET/api/v1/profile.json',
    );
    expect(mockFilePath('mocks/staging/', { method: 'POST', path: '/a' })).toBe('mocks/staging/POST/a.json');
  });
});
