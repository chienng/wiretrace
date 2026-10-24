import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import { StoreProvider } from '../store';
import { LogStrip } from './LogStrip';

const render = () => renderToStaticMarkup(createElement(StoreProvider, null, createElement(LogStrip, { requestId: null })));

describe('LogStrip', () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it('shows its controls, the lines and Hide logs when open', () => {
    const html = render();
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('aria-controls="log-strip-lines"');
    expect(html).toContain('Hide logs');
    expect(html).toContain('id="log-strip-lines"');
    expect(html).toContain('aria-label="Filter logs"');
    expect(html).toContain('class="logs"');
  });

  it('collapses to its tabs and Show logs when the tester hid it', () => {
    const storage = { getItem: (k: string) => (k === 'wiretrace.pane.traffic.logs' ? 'hidden' : null) };
    (globalThis as { window?: unknown }).window = { localStorage: storage };
    const html = render();
    expect(html).toContain('class="logs collapsed"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('Show logs');
    expect(html).toContain('Device logs');
    expect(html).toContain('App logs');
    expect(html).not.toContain('id="log-strip-lines"');
    expect(html).not.toContain('aria-controls=');
    expect(html).not.toContain('aria-label="Filter logs"');
  });
});
