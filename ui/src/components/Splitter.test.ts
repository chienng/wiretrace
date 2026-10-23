import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { Pane } from '../logic/paneWidth';
import { Splitter } from './Splitter';

const pane: Pane = { width: 576, min: 360, max: 720, preview: () => {}, choose: () => {}, release: () => {}, reset: () => {} };

describe('Splitter', () => {
  it('is a focusable vertical separator carrying the pane width and its limits', () => {
    const html = renderToStaticMarkup(createElement(Splitter, { label: 'Resize the request details', edge: 'end', pane }));
    expect(html).toContain('role="separator"');
    expect(html).toContain('aria-orientation="vertical"');
    expect(html).toContain('aria-label="Resize the request details"');
    expect(html).toContain('aria-valuenow="576"');
    expect(html).toContain('aria-valuemin="360"');
    expect(html).toContain('aria-valuemax="720"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('class="splitter end"');
  });
});
