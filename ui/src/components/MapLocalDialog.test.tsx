import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { flow } from '../logic/testing';
import { StoreProvider } from '../store';
import { MapLocalDialog } from './MapLocalDialog';

describe('MapLocalDialog', () => {
  it('keeps its content and footer inside the padded form of the wide sheet', () => {
    const html = renderToStaticMarkup(
      <StoreProvider>
        <MapLocalDialog flow={flow()} onClose={() => undefined} />
      </StoreProvider>,
    );
    expect(html).toContain('class="sheet wide"');
    expect(html).toMatch(/<p class="lead">Saves this response/);
    expect(html).toMatch(/<div class="ml-form"><div class="note">Loading…<\/div>.*<div class="sheet-foot">.*<\/div><\/div><\/div><\/div>$/);
  });
});
