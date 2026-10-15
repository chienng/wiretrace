import { describe, expect, it } from 'vitest';
import type { Rule } from '../types';
import {
  applySummary,
  emptyRule,
  exportJson,
  filterRules,
  mergeImport,
  newRuleId,
  parseImport,
  ruleFromFlow,
  ruleSummary,
  serverError,
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
