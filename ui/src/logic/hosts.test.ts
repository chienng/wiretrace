import { describe, expect, it } from 'vitest';
import {
  choiceNote,
  covered,
  decryptChoices,
  decryptOff,
  hostPort,
  hostsLine,
  isTunnel,
  loadShowEncrypted,
  MAX_API_HOSTS,
  notDecryptedText,
  openFor,
  storeShowEncrypted,
  tunnelTag,
} from './hosts';
import { flow, tunnel } from './testing';

describe('decrypt choices (the same as cli/preset.py)', () => {
  it.each([
    ['cdn.example.net', ['cdn.example.net', 'example.net']],
    ['cdn.example.co.uk', ['cdn.example.co.uk', 'example.co.uk']],
    ['example.co.uk', ['example.co.uk']],
    ['example.net', ['example.net']],
    ['a.b.example.com', ['a.b.example.com', 'b.example.com']],
    ['CDN.Example.NET.', ['cdn.example.net', 'example.net']],
    ['203.0.113.9', ['203.0.113.9']],
    ['2001:db8::1', ['2001:db8::1']],
  ])('%s', (host, choices) => {
    expect(decryptChoices(host)).toEqual(choices);
  });
  it('never offers a public suffix', () => {
    expect(decryptChoices('cdn.example.co.uk')).not.toContain('co.uk');
  });
});

describe('when Decrypt is off', () => {
  const state = { preset: 'staging', api_hosts: ['api.example.com'] };
  it('says why, in the order the server checks', () => {
    expect(decryptOff(state, 'cdn.example.net', 'old-session')).toMatch(/previous session/);
    expect(decryptOff(null, 'cdn.example.net', null)).toBe('Not connected');
    expect(decryptOff(state, '2001:db8::1', null)).toMatch(/IPv6/);
    expect(decryptOff({ ...state, preset: 'example' }, 'cdn.example.net', null)).toMatch(/template/);
    expect(decryptOff(state, 'v2.api.example.com', null)).toBe('v2.api.example.com is already decrypted in this session');
    const full = { ...state, api_hosts: Array.from({ length: MAX_API_HOSTS }, (_, i) => `h${i}.example.com`) };
    expect(decryptOff(full, 'cdn.example.net', null)).toBe('The preset already has 50 API hosts');
    expect(decryptOff(state, 'cdn.example.net', null)).toBeNull();
  });
  it('an API host covers itself and its subdomains only', () => {
    expect(covered(['example.net'], 'EXAMPLE.net')).toBe(true);
    expect(covered(['example.net'], 'cdn.example.net')).toBe(true);
    expect(covered(['example.net'], 'badexample.net')).toBe(false);
  });
});

describe('rows and texts', () => {
  it('tells a connection from a request', () => {
    expect(isTunnel(tunnel())).toBe(true);
    expect(isTunnel(flow())).toBe(false);
  });
  it('says open until the connection closes', () => {
    expect(openFor(tunnel({ ts: 10, closed_at: null }))).toBe('open');
    expect(openFor(tunnel({ ts: 10, closed_at: 22.4 }))).toBe('12.4 s');
    expect(openFor(tunnel({ ts: 10, closed_at: 10.25 }))).toBe('250 ms');
  });
  it('shows host and port, and tags a connection that is not TLS', () => {
    expect(hostPort(tunnel())).toBe('cdn.example.net:443');
    expect(hostPort(tunnel({ port: null }))).toBe('cdn.example.net');
    expect(tunnelTag(tunnel())).toBe('Encrypted');
    expect(tunnelTag(tunnel({ tls: false }))).toBe('Passed through');
  });
  it('words the detail and the dialog', () => {
    expect(notDecryptedText('cdn.example.net', 'default')).toBe(
      'cdn.example.net is not one of the API hosts of preset default, so Wiretrace passes this connection through without reading it. Decrypt the host to see its requests and responses.',
    );
    expect(choiceNote('cdn.example.net', 'cdn.example.net')).toBe('and its subdomains');
    expect(choiceNote('example.net', 'cdn.example.net')).toBe('and every subdomain, cdn.example.net included');
    expect(hostsLine('default', 3)).toBe('presets/default.yaml · 3 → 4 API hosts');
  });
});

describe('Show encrypted in this browser', () => {
  it('is on until turned off, and a refused storage reads as on', () => {
    const data = new Map<string, string>();
    const storage = {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => void data.set(k, v),
      removeItem: (k: string) => void data.delete(k),
    };
    expect(loadShowEncrypted(storage)).toBe(true);
    storeShowEncrypted(storage, false);
    expect(loadShowEncrypted(storage)).toBe(false);
    storeShowEncrypted(storage, true);
    expect(loadShowEncrypted(storage)).toBe(true);
    expect(loadShowEncrypted(null)).toBe(true);
    const refusing = {
      getItem: () => {
        throw new Error('off');
      },
    };
    expect(loadShowEncrypted(refusing)).toBe(true);
  });
});
