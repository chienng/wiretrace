import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import type { Body } from '../types';
import { BodyView } from './BodyView';

const body = (text: string): Body => ({ text, size: text.length, binary: false, truncated: false });
const render = (b: Body) => renderToStaticMarkup(<BodyView body={b} label="Response" />);

describe('BodyView', () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it('offers JSON and JSON Text for a JSON body, JSON first', () => {
    const html = render(body('{"id":12345678901234567890}'));
    expect(html).toContain('aria-label="Response body view"');
    expect(html).toMatch(/<button type="button" class="on" aria-pressed="true">JSON<\/button>/);
    expect(html).toMatch(/<button type="button" class="" aria-pressed="false">JSON Text<\/button>/);
    expect(html).toContain('class="jline"');
    expect(html).not.toContain('<pre');
  });

  it('shows the indented text when the tester chose JSON Text', () => {
    const storage = { getItem: (k: string) => (k === 'wiretrace.body.view' ? 'text' : null) };
    (globalThis as { window?: unknown }).window = { localStorage: storage };
    const html = render(body('{"id":12345678901234567890,"a":[]}'));
    expect(html).toMatch(/aria-pressed="true">JSON Text</);
    expect(html).toContain('<pre class="plain">{\n  &quot;id&quot;: 12345678901234567890,\n  &quot;a&quot;: []\n}</pre>');
    expect(html).not.toContain('class="jline"');
  });

  it('shows a body that is not JSON as text, without the control', () => {
    const html = render(body('plain words'));
    expect(html).not.toContain('body view');
    expect(html).not.toContain('JSON Text');
    expect(html).toContain('<pre class="plain">plain words</pre>');
  });
});
