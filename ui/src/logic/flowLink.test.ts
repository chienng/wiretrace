import { describe, expect, it } from 'vitest';
import { flowLinkChoice } from './flowLink';

describe('#flow on first load', () => {
  it('selects a known id and asks to clear the fragment', () => {
    expect(flowLinkChoice('#flow=abc', ['abc', 'def'])).toEqual({ id: 'abc', clear: true });
  });

  it('decodes the id', () => {
    expect(flowLinkChoice('#flow=a%2Fb', ['a/b'])).toEqual({ id: 'a/b', clear: true });
  });

  it('ignores an unknown id but still clears the fragment', () => {
    expect(flowLinkChoice('#flow=missing', ['abc'])).toEqual({ id: null, clear: true });
  });

  it('leaves the page alone when there is no flow fragment', () => {
    expect(flowLinkChoice('', ['abc'])).toEqual({ id: null, clear: false });
    expect(flowLinkChoice('#other', ['abc'])).toEqual({ id: null, clear: false });
  });
});
