import { describe, expect, it } from 'vitest';
import type { ChangeEntry, MapTarget, RewriteOp, Rule } from '../types';
import {
  MAP_HTTP_WARNING,
  MAP_TOKENS_WARNING,
  mapPreview,
  switchScheme,
  targetUrl,
  applySummary,
  breakpointRule,
  changeGroups,
  changeGroupTitle,
  changeParts,
  emptyRule,
  exportJson,
  filterRules,
  findBreakpoint,
  mergeImport,
  newOp,
  newRuleId,
  opOfKind,
  parseImport,
  parsePath,
  requestMatch,
  ruleFromFlow,
  ruleKind,
  ruleSummary,
  serverError,
  sideText,
  switchAction,
  validateRule,
} from './rules';

const HOSTS = ['api.example.com', 'auth.example.com'];

type RuleOverrides = Partial<Omit<Rule, 'match' | 'action' | 'apply'>> & {
  match?: Partial<Rule['match']>;
  action?: Partial<Rule['action']>;
  apply?: Partial<Rule['apply']>;
};

function rule(over: RuleOverrides = {}): Rule {
  const base = { ...emptyRule('orders500'), name: 'Orders fail' };
  return {
    ...base,
    ...over,
    match: { ...base.match, path: '/api/v1/orders', ...over.match },
    action: { ...base.action, ...over.action },
    apply: { ...base.apply, ...over.apply },
  };
}

describe('rules', () => {
  it('makes ids the server accepts', () => {
    expect(newRuleId()).toMatch(/^[a-z0-9]{10}$/);
    expect(newRuleId(() => 0)).toBe('aaaaaaaaaa');
  });

  it('seeds a rule from a request without its query', () => {
    const seeded = ruleFromFlow({ method: 'post', host: 'v2.api.example.com', path: '/api/v1/orders?page=2' }, HOSTS, 'seeded1');
    expect(seeded.name).toBe('POST /api/v1/orders');
    expect(seeded.match).toEqual({ method: 'POST', host: 'api.example.com', path: '/api/v1/orders', body_contains: '' });
    expect(ruleFromFlow({ method: 'BREW', host: 'other.org', path: '' }, HOSTS, 'seeded2').match)
      .toMatchObject({ method: 'ANY', host: '', path: '/' });
  });

  it('accepts a valid rule', () => {
    expect(validateRule(rule(), HOSTS, [])).toEqual({});
    expect(validateRule(rule({ action: { type: 'delay', delay_ms: 3000 } }), HOSTS, [])).toEqual({});
    expect(validateRule(rule({ action: { type: 'mock', status: 200, mock_file: 'GET/a.json' } }), HOSTS, ['GET/a.json'])).toEqual({});
  });

  it('reports each field with the server key', () => {
    const cases: [Rule, string][] = [
      [rule({ id: 'abc' }), 'id'],
      [rule({ name: ' ' }), 'name'],
      [rule({ name: 'x'.repeat(81) }), 'name'],
      [rule({ match: { method: 'post' } }), 'match.method'],
      [rule({ match: { host: 'other.example.com' } }), 'match.host'],
      [rule({ match: { path: '' } }), 'match.path'],
      [rule({ match: { path: 'api' } }), 'match.path'],
      [rule({ match: { path: `/${'x'.repeat(512)}` } }), 'match.path'],
      [rule({ match: { body_contains: 'x'.repeat(257) } }), 'match.body_contains'],
      [rule({ action: { status: 99 } }), 'action.status'],
      [rule({ action: { status: 600 } }), 'action.status'],
      [rule({ action: { body: 'é'.repeat((1 << 19) + 1) } }), 'action.body'],
      [rule({ action: { type: 'mock', mock_file: 'GET/gone.json' } }), 'action.mock_file'],
      [rule({ action: { delay_ms: 120_001 } }), 'action.delay_ms'],
      [rule({ action: { type: 'delay', delay_ms: 0 } }), 'action.delay_ms'],
      [rule({ apply: { mode: 'every_nth', n: 1 } }), 'apply.n'],
      [rule({ apply: { mode: 'every_nth', n: 1001 } }), 'apply.n'],
    ];
    for (const [bad, field] of cases) {
      expect(Object.keys(validateRule(bad, HOSTS, ['GET/a.json'])), field).toEqual([field]);
    }
    expect(validateRule(rule(), HOSTS, [], [rule()]).id).toBe('Used by another rule');
  });

  it('summarizes rules for the list', () => {
    expect(ruleSummary(rule({ apply: { mode: 'once' } }))).toBe('Return 500 · once');
    expect(ruleSummary(rule({ action: { type: 'delay', delay_ms: 3000 } }))).toBe('3,000 ms then forward · always');
    expect(ruleSummary(rule({ action: { type: 'mock', status: 200, mock_file: 'POST/api/cart.json' } }))).toBe('cart.json · always');
    expect(ruleSummary(rule({ action: { type: 'drop', delay_ms: 500 } }))).toBe('Close connection (simulate network loss) after 500 ms · always');
    expect(applySummary(rule({ apply: { mode: 'every_nth', n: 3 } }))).toBe('every 3rd call');
    expect(applySummary(rule({ apply: { mode: 'every_nth', n: 12 } }))).toBe('every 12th call');
  });

  it('pauses at a breakpoint: the phase is its own key, and a pause has no delay', () => {
    const pause = rule({ action: switchAction(rule().action, 'pause', 500) });
    expect(pause.action).toMatchObject({ type: 'pause', pause_at: 'request', delay_ms: 0 });
    expect(validateRule(pause, HOSTS, [])).toEqual({});
    expect(Object.keys(validateRule({ ...pause, action: { ...pause.action, delay_ms: 10 } }, HOSTS, []))).toEqual(['action.delay_ms']);
    expect(Object.keys(validateRule({ ...pause, action: { ...pause.action, pause_at: undefined } }, HOSTS, []))).toEqual(['action.pause_at']);
    const back = switchAction({ ...pause.action, pause_at: 'both' }, 'status', 500);
    expect('pause_at' in back).toBe(false);
    expect(switchAction(back, 'pause', 500).pause_at).toBe('request');
    expect(ruleSummary({ ...pause, action: { ...pause.action, pause_at: 'both' } })).toBe('request and response · always');
    expect(ruleSummary({ ...pause, action: { ...pause.action, pause_at: 'response' } })).toBe('response · always');
  });

  it('filters by text and type', () => {
    const rules = [rule(), rule({ id: 'slowpay1', name: 'Slow pay', match: { path: '/api/v1/pay' }, action: { type: 'delay', delay_ms: 10 } })];
    expect(filterRules(rules, 'ORDERS', 'all').map((r) => r.id)).toEqual(['orders500']);
    expect(filterRules(rules, '', 'delay').map((r) => r.id)).toEqual(['slowpay1']);
    expect(filterRules(rules, 'orders', 'delay')).toEqual([]);
  });

  it('round-trips an export through import', () => {
    const rules = [rule()];
    expect(parseImport(exportJson(rules))).toEqual(rules);
    expect(parseImport('{nope')).toEqual({ error: 'The file is not JSON.' });
    expect(parseImport('{"version": 2, "rules": []}')).toHaveProperty('error');
    expect(parseImport('{"version": 1, "rules": [{"id": "x"}]}')).toHaveProperty('error');
  });

  it('adds imported rules after the current ones with new ids on collision, or replaces them all', () => {
    const current = [rule()];
    const incoming = [rule({ name: 'Imported' }), rule({ id: 'fresh01', name: 'Fresh' })];
    const ids = ['newid01', 'newid02'];
    const added = mergeImport(current, incoming, 'add', () => ids.shift()!);
    expect(added.map((r) => [r.id, r.name])).toEqual([
      ['orders500', 'Orders fail'],
      ['newid01', 'Imported'],
      ['fresh01', 'Fresh'],
    ]);
    expect(mergeImport(current, incoming, 'replace')).toEqual(incoming);
  });

  it('maps a server 400 to a field of this rule or a general message', () => {
    expect(serverError({ error: 'must not be empty', index: 0, field: 'match.path' }, 0)).toEqual({ field: 'match.path', message: 'must not be empty' });
    expect(serverError({ error: 'is missing', index: 2, field: 'action' }, 0)).toEqual({ field: null, message: 'Rule 3: action is missing' });
    expect(serverError('nope', 0)).toBeNull();
  });
});

describe('rewrite rules (spec 022, slice E)', () => {
  const rewrite = (ops: RewriteOp[], over: Partial<Rule['action']> = {}) => rule({ action: { type: 'rewrite', ops, delay_ms: 0, ...over } });
  const errors = (ops: RewriteOp[]) => validateRule(rewrite(ops), HOSTS, null);

  it('switches to Rewrite with one empty change and no delay, and drops ops when leaving it', () => {
    const r = switchAction({ ...rule().action, delay_ms: 300 }, 'rewrite', 500);
    expect(r).toMatchObject({ type: 'rewrite', delay_ms: 0, ops: [newOp()] });
    expect('ops' in switchAction(r, 'status', 500)).toBe(false);
    expect(switchAction({ ...r, ops: [{ on: 'response', op: 'remove_json', path: 'a' }] }, 'rewrite', 500).ops).toHaveLength(1);
  });

  it('keeps exactly the keys of a change kind', () => {
    const header: RewriteOp = { on: 'response', op: 'set_header', name: 'x-a', value: '1' };
    expect(opOfKind(header, 'remove_header')).toEqual({ on: 'response', op: 'remove_header', name: 'x-a' });
    expect(opOfKind(header, 'set_json')).toEqual({ on: 'response', op: 'set_json', path: 'x-a', value: '1' });
    expect(opOfKind({ on: 'request', op: 'remove_json', path: 'data.a' }, 'add_header')).toEqual({ on: 'request', op: 'add_header', name: 'data.a', value: '' });
  });

  it('parses paths as the server does', () => {
    expect(parsePath('data.user.isPremium')).toEqual(['data', 'user', 'isPremium']);
    expect(parsePath('items[0].price')).toEqual(['items', 0, 'price']);
    expect(parsePath('[2]')).toEqual([2]);
    expect(parsePath('["a.b"].c')).toEqual(['a.b', 'c']);
    expect(parsePath('a["x\\"y"]')).toEqual(['a', 'x"y']);
    for (const bad of ['', 'a.', '.a', 'a..b', 'a[01]', 'a[-1]', 'a[x]', 'a"b', '["a"', 'a]', `${'a.'.repeat(20)}a`, 'k'.repeat(257)]) {
      expect(parsePath(bad), bad).toBeNull();
    }
  });

  it('refuses what the server refuses, with the field named', () => {
    expect(errors([])).toEqual({ 'action.ops': 'Add 1 to 20 changes' });
    expect(Object.keys(errors(Array.from({ length: 21 }, newOp)))).toEqual(['action.ops']);
    expect(errors([{ on: 'request', op: 'set_header', name: 'X Bad', value: 'v' }])).toEqual({
      'action.ops.0.name': "A header name: letters, digits and - _ . ! # $ % & ' * + ^ ` | ~",
    });
    for (const name of ['Host', 'content-length', 'Transfer-Encoding', 'Connection', 'keep-alive', 'TE', 'Trailer', 'Upgrade', 'Proxy-Authorization', ':path']) {
      expect(errors([{ on: 'request', op: 'remove_header', name }])['action.ops.0.name'], name).toBeTruthy();
    }
    expect(errors([{ on: 'request', op: 'add_header', name: 'x-a', value: 'a\nb' }])).toEqual({
      'action.ops.0.value': 'At most 4,096 characters, without a line break',
    });
    expect(errors([{ on: 'request', op: 'add_header', name: 'x-a', value: 'v'.repeat(4097) }])['action.ops.0.value']).toBeTruthy();
    expect(errors([{ on: 'response', op: 'set_json', path: 'a..b', value: '1' }])['action.ops.0.path']).toBe(
      'Keys joined by . with [n] for items; at most 20 parts and 256 characters',
    );
    expect(errors([{ on: 'response', op: 'set_json', path: 'a', value: 'yes' }])).toEqual({ 'action.ops.0.value': 'JSON: true, 12, "text", null or {"a": 1}' });
    expect(errors([{ on: 'response', op: 'set_json', path: 'a', value: 'NaN' }])['action.ops.0.value']).toBeTruthy();
    expect(errors([{ on: 'response', op: 'set_json', path: 'a', value: `"${'x'.repeat(64 << 10)}"` }])).toEqual({ 'action.ops.0.value': 'At most 64 KiB' });
    expect(validateRule(rewrite([newOp()].map((o) => ({ ...o, name: 'x-a' })), { delay_ms: 100 }), HOSTS, null)).toEqual({
      'action.delay_ms': 'A Rewrite rule has no delay',
    });
    expect(
      errors([
        { on: 'request', op: 'set_header', name: 'x-feature-flags', value: 'checkout-v2' },
        { on: 'response', op: 'set_json', path: 'data.user.isPremium', value: 'true' },
        { on: 'response', op: 'remove_json', path: 'data.user.trialEndsAt' },
        { on: 'response', op: 'remove_header', name: 'cache-control' },
      ]),
    ).toEqual({});
  });

  it('labels change rules and summarises them', () => {
    const r = rewrite([newOp(), newOp()]);
    expect(ruleKind(r)).toBe('Changes');
    expect(ruleKind(rule())).toBe('Answers');
    expect(ruleSummary(r)).toBe('Rewrite, 2 changes · always');
    expect(ruleSummary(rewrite([newOp()]))).toBe('Rewrite, 1 change · always');
  });

  it('groups the Changes tab by rule and says why a change was skipped', () => {
    const c = (over: Partial<ChangeEntry>): ChangeEntry => ({ rule: 'Premium user', on: 'response', op: 'set_json', target: 'a', value: 'true', applied: true, reason: '', ...over });
    const groups = changeGroups([c({ on: 'request', op: 'set_header', target: 'Authorization', value: '•••• (masked)' }), c({}), c({ op: 'remove_json', value: null, applied: false, reason: 'not found' }), c({ rule: 'Other' })]);
    expect(groups.map(changeGroupTitle)).toEqual(['Rewrite · rule Premium user · 2 of 3 applied', 'Rewrite · rule Other · 1 of 1 applied']);
    const [first, , skipped] = groups[0]?.entries ?? [];
    expect(first && changeParts(first)).toEqual({ label: 'Set header', target: 'Authorization', value: '•••• (masked)' });
    expect(skipped && changeParts(skipped)).toEqual({ label: 'Remove JSON field', target: 'a', value: null });
    expect(sideText('request')).toBe('Request');
  });
});

describe('Map remote rules (spec 022, slice G)', () => {
  const remote = (target: Partial<MapTarget> = {}, over: RuleOverrides = {}) =>
    rule({ ...over, action: { type: 'map_remote', status: 200, delay_ms: 0, target: { scheme: 'https', host: 'staging-api.example.com', port: 443, ...target }, ...over.action } });
  const hostError = (host: string) => validateRule(remote({ host }), HOSTS, null)['action.target.host'];

  it('refuses this Mac and its network, as the server does on save', () => {
    for (const host of ['localhost', 'dev.localhost', 'printer.local', '127.0.0.1', '10.0.0.5', '172.16.0.1', '172.31.255.255', '192.168.1.20',
      '100.64.0.1', '100.127.0.1', '169.254.1.1', '0.0.0.0', '224.0.0.1', '::1', '[::1]', '::', 'fe80::1', 'fd00::1', 'fc00::1', 'ff02::1',
      '::ffff:10.0.0.1', '::ffff:7f00:1']) {
      expect(hostError(host), host).toBe('Not this Mac or addresses on your network.');
    }
    for (const host of ['staging-api.example.com', 'STAGING-API.example.com.', '203.0.113.10', '172.32.0.1', '100.128.0.1', '2001:db8::1', '[2001:db8::1]']) {
      expect(hostError(host), host).toBeUndefined();
    }
  });

  it('wants a DNS name or an IP address, a port 1 to 65535 and no delay', () => {
    for (const host of ['staging', 'bad_host.example.com', '-a.example.com', 'host.123', 'a::b::c', 'fe80::1%en0']) {
      expect(hostError(host), host).toBe('A DNS name or an IP address, e.g. staging-api.example.com');
    }
    expect(hostError('')).toBe('Enter the server to send requests to');
    expect(validateRule(remote({ port: 0 }), HOSTS, null)['action.target.port']).toBe('1 to 65535');
    expect(validateRule(remote({ port: 65536 }), HOSTS, null)['action.target.port']).toBe('1 to 65535');
    expect(validateRule(remote({}, { action: { delay_ms: 100 } }), HOSTS, null)['action.delay_ms']).toBe('A Map remote rule has no delay');
    expect(validateRule(remote(), HOSTS, null)).toEqual({});
  });

  it('refuses the matched host on its default port, but not on another port', () => {
    const same = (port: number) => validateRule(remote({ host: 'api.example.com', port }, { match: { host: 'api.example.com' } }), HOSTS, null)['action.target.host'];
    expect(same(443)).toBe('Must differ from the host the rule matches');
    expect(same(8443)).toBeUndefined();
  });

  it('previews the URL with path and query kept, and warns about tokens and plain HTTP', () => {
    expect(mapPreview(remote({}, { match: { host: 'api.example.com' } }), HOSTS)).toEqual({
      from: 'https://api.example.com/api/v1/orders', to: 'https://staging-api.example.com', path: '/api/v1/orders' });
    expect(mapPreview(remote({ scheme: 'http', port: 8080 }), HOSTS)?.to).toBe('http://staging-api.example.com:8080');
    expect(targetUrl({ scheme: 'https', host: '2001:db8::1', port: 443 })).toBe('https://[2001:db8::1]');
    expect(mapPreview(remote({ host: '' }), HOSTS)).toBeNull();
    expect(MAP_TOKENS_WARNING).toBe("The app's tokens and cookies go to this server too.");
    expect(MAP_HTTP_WARNING).toBe('Plain HTTP: anyone on the network path can read it.');
  });

  it('defaults the target, follows the default port when the scheme changes, and keeps only its own keys', () => {
    const a = switchAction(rule().action, 'map_remote', 500);
    expect(a.target).toEqual({ scheme: 'https', host: '', port: 443 });
    expect(switchScheme({ scheme: 'https', host: 'x.example.com', port: 443 }, 'http').port).toBe(80);
    expect(switchScheme({ scheme: 'https', host: 'x.example.com', port: 8443 }, 'http').port).toBe(8443);
    expect('target' in switchAction(remote().action, 'status', 500)).toBe(false);
    expect(ruleKind(remote())).toBe('Changes');
    expect(ruleSummary(remote())).toBe('Map remote → staging-api.example.com · always');
  });
});

describe('breakpoints (spec 028, slice D)', () => {
  const request = requestMatch({ method: 'get', host: 'v2.api.example.com', path: '/api/v1/users/42?expand=1' }, HOSTS);

  it('matches a request like New rule from this request does, query left out', () => {
    expect(request).toEqual({ method: 'GET', host: 'api.example.com', path: '/api/v1/users/42' });
    expect(requestMatch({ method: 'GET', host: 'other.org', path: '/x' }, HOSTS).host).toBe('');
  });

  it('pauses at the request only, and names what it holds', () => {
    const r = breakpointRule(request, 'bp00001');
    expect(r).toMatchObject({ id: 'bp00001', name: 'Breakpoint: GET /api/v1/users/42', enabled: true, apply: { mode: 'always', n: 0 } });
    expect(r.match).toEqual({ ...request, body_contains: '' });
    expect(r.action).toMatchObject({ type: 'pause', pause_at: 'request', delay_ms: 0 });
    expect(validateRule(r, HOSTS, null)).toEqual({});
    expect(breakpointRule({ method: 'ANY', host: 'api.example.com', path: '/*' }, 'bp00002').name).toBe('Breakpoint: api.example.com');
    expect(breakpointRule({ method: 'ANY', host: 'api.example.com', path: '/api/v1/*' }, 'bp00003').name).toBe('Breakpoint: /api/v1/*');
  });

  it('finds only an enabled pause rule on exactly that method, host and path, without body text', () => {
    const bp = breakpointRule(request, 'bp00001');
    expect(findBreakpoint([rule(), bp], request)).toBe(bp);
    expect(findBreakpoint([{ ...bp, match: { ...bp.match, host: 'API.example.com' } }], request)).toBeDefined();
    expect(findBreakpoint([{ ...bp, enabled: false }], request)).toBeUndefined();
    expect(findBreakpoint([{ ...bp, match: { ...bp.match, body_contains: 'x' } }], request)).toBeUndefined();
    expect(findBreakpoint([{ ...bp, match: { ...bp.match, method: 'ANY' } }], request)).toBeUndefined();
    expect(findBreakpoint([{ ...bp, match: { ...bp.match, path: '/api/v1/users/*' } }], request)).toBeUndefined();
    expect(findBreakpoint([{ ...bp, action: { ...bp.action, type: 'delay', delay_ms: 100 } }], request)).toBeUndefined();
  });
});
