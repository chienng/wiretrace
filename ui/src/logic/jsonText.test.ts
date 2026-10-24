import { describe, expect, it } from 'vitest';
import { formatJsonText } from './jsonText';

describe('JSON Text', () => {
  it('indents nested objects and arrays by 2 spaces, one value per line', () => {
    expect(formatJsonText('{"a":{"b":[1,2]},"c":true}')).toBe(
      ['{', '  "a": {', '    "b": [', '      1,', '      2', '    ]', '  },', '  "c": true', '}'].join('\n'),
    );
    expect(formatJsonText('[{"id":1},null]')).toBe(['[', '  {', '    "id": 1', '  },', '  null', ']'].join('\n'));
  });

  it('keeps empty objects and arrays on one line', () => {
    expect(formatJsonText('{}')).toBe('{}');
    expect(formatJsonText('[]')).toBe('[]');
    expect(formatJsonText('{"a":{ },"b":[\n]}')).toBe(['{', '  "a": {},', '  "b": []', '}'].join('\n'));
  });

  it('copies strings as sent, escapes and brackets inside them included', () => {
    const body = String.raw`{"q":"say \"hi\"","p":"C:\\dir\\","e":"caf\u00e9","x":"{a, b: [c]}","t":"\\"}`;
    expect(formatJsonText(body)).toBe(
      [
        '{',
        String.raw`  "q": "say \"hi\"",`,
        String.raw`  "p": "C:\\dir\\",`,
        String.raw`  "e": "caf\u00e9",`,
        '  "x": "{a, b: [c]}",',
        String.raw`  "t": "\\"`,
        '}',
      ].join('\n'),
    );
  });

  it('keeps number literals verbatim', () => {
    expect(formatJsonText('[12345678901234567890,1.50,-0,1e10,2E-3]')).toBe(
      ['[', '  12345678901234567890,', '  1.50,', '  -0,', '  1e10,', '  2E-3', ']'].join('\n'),
    );
  });

  it('gives the same text for minified and already-indented bodies', () => {
    const minified = '{"user":{"id":42,"tags":["a","b"]},"ok":false}';
    const indented = '{\n\t"user" : {\r\n    "id" : 42 ,\n "tags":[ "a" , "b" ]\n  },\n  "ok":false\n}';
    expect(formatJsonText(indented)).toBe(formatJsonText(minified));
  });

  it('ignores whitespace around the body', () => {
    expect(formatJsonText('  \n {"a":1} \n')).toBe('{\n  "a": 1\n}');
  });
});
