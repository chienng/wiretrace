import { describe, expect, it } from 'vitest';
import { answersAlone, bodyOff, bodyProblem, defaultMockName, editableBody, mapLocalNote, mapLocalOff, mockNameProblem, NAME_PROBLEM, ruleName } from './mapLocal';
import { flow } from './testing';

describe('map local (spec 022, slice F)', () => {
  it('names the file from the method and path, query dropped, long paths cut', () => {
    expect(defaultMockName('get', '/api/v1/profile?x=1')).toBe('saved/GET_api_v1_profile.json');
    expect(defaultMockName('POST', '/')).toBe('saved/POST_index.json');
    expect(defaultMockName('GET', '/a b/ü:c')).toBe('saved/GET_a_b___c.json');
    const long = defaultMockName('GET', `/${'x'.repeat(300)}`);
    expect(long.split('/')[1]).toHaveLength(80);
    expect(mockNameProblem(long)).toBeNull();
    expect(mockNameProblem(defaultMockName('GET', '/.hidden'))).toBeNull();
  });

  it('refuses the names the server refuses', () => {
    for (const bad of ['../x.json', 'saved/../x.json', '.x.json', 'saved/.x.json', '/abs.json', 'x.txt', 'a//b.json', 'a b.json', `${'x'.repeat(81)}.json`, 'a\\b.json', '']) {
      expect(mockNameProblem(bad), bad).toBe(NAME_PROBLEM);
    }
    expect(mockNameProblem('GET/api/v1/profile.json')).toBeNull();
  });

  it('says when a file answers on its own', () => {
    expect(answersAlone('GET/api/v1/profile.json')).toBe(true);
    expect(answersAlone('saved/GET_api.json')).toBe(false);
    expect(answersAlone('GET.json')).toBe(false);
    expect(mapLocalNote('GET/x.json', false)).toContain('on its own');
    expect(mapLocalNote('saved/x.json', false)).toContain('Only the file');
  });

  it('gives the reason it is off', () => {
    expect(mapLocalOff(flow(), null)).toBeNull();
    expect(mapLocalOff(flow(), 'old')).toBe('Map local is off while a previous session is open');
    expect(mapLocalOff(flow({ status: null }), null)).toBe('This request is still in progress');
    expect(mapLocalOff(flow({ status: null, error: 'reset' }), null)).toBe('This request has no response');
    expect(mapLocalOff(flow({ mime: 'image/png' }), null)).toBe('The response is binary');
    expect(mapLocalOff(flow({ size: (1 << 20) + 1 }), null)).toBe('The response is over 1 MiB');
    expect(bodyOff({ text: null, size: 3, truncated: false, binary: true })).toBe('The response is binary');
    expect(bodyOff({ text: 'x', size: 3 << 20, truncated: true, binary: false })).toBe('The response is over 1 MiB');
    expect(bodyOff({ text: '{}', size: 2, truncated: false, binary: false })).toBeNull();
  });

  it('pretty-prints a JSON body and checks its size', () => {
    expect(editableBody('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(editableBody('not json')).toBe('not json');
    expect(bodyProblem('x'.repeat((1 << 20) + 1))).toBe('At most 1 MiB');
    expect(ruleName('get', '/api/v1/profile?x=1')).toBe('Map local GET /api/v1/profile');
  });
});
