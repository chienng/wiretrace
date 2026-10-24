import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { flow } from '../logic/testing';
import { StoreProvider } from '../store';
import { TrafficTree } from './TrafficTree';

const noop = () => undefined;

function rowsOf(selectedId: string | null): string[] {
  const html = renderToStaticMarkup(
    <StoreProvider>
      <TrafficTree
        rows={[
          flow({ id: 'f1', path: '/api/v1/profile' }),
          flow({ id: 'f2', path: '/api/v1/users' }),
          flow({ id: 'f3', path: '/health' }),
          flow({ id: 'f5', path: '/ready', replay_of: 'f3' }),
          flow({ id: 'f4', host: 'cdn.example.com', path: '/logo.png' }),
        ]}
        selectedId={selectedId}
        onSelect={noop}
        onDecrypt={noop}
        onHideEncrypted={noop}
        onMapLocal={noop}
      />
    </StoreProvider>,
  );
  return html.split('<div class="frow').slice(1);
}

describe('TrafficTree', () => {
  it('shows new hosts open, their folders closed, and the counts', () => {
    const rows = rowsOf(null);
    expect(rows).toHaveLength(6);
    expect(rows[0]).toMatch(/^ tnode".*>https:\/\/api\.example\.com<.*, open.*<span class="tc">4<\/span>/);
    expect(rows[1]).toMatch(/^ tnode".*>api<.*, closed.*<span class="tc">2<\/span>/);
    expect(rows[2]).toMatch(/^[^"]* tleaf".*>health</);
    expect(rows[3]).toMatch(/^[^"]* tleaf".*>ready</);
    expect(rows[4]).toMatch(/^ tnode".*>https:\/\/cdn\.example\.com<.*<span class="tc">1<\/span>/);
    expect(rows[5]).toMatch(/^[^"]* tleaf".*>logo\.png</);
  });

  it('draws the fold arrow as a 12 px chevron, down when open and right when closed', () => {
    const rows = rowsOf(null);
    expect(rows[0]).toMatch(/<span class="tw"[^>]*><svg width="12" height="12"[^>]*><path d="M3 6l5 5 5-5"/);
    expect(rows[1]).toMatch(/<span class="tw"[^>]*><svg width="12" height="12"[^>]*><path d="M6 3l5 5-5 5"/);
    expect(rows.join('')).not.toMatch(/[▸▾]/);
  });

  it('lines a leaf up with the name of its parent, past the fold arrow', () => {
    const rows = rowsOf(null);
    expect(rows[0]).toContain('padding-left:8px');
    expect(rows[2]).toContain('padding-left:46px');
  });

  it('marks a replay leaf, and no other row', () => {
    const marked = rowsOf(null).filter((r) => /^[^"]*\breplay\b/.test(r));
    expect(marked).toHaveLength(1);
    expect(marked[0]).toMatch(/>ready</);
  });

  it('marks the selected request, and only it, as selected', () => {
    const rows = rowsOf('f3');
    const selected = rows.filter((r) => r.includes('aria-selected="true"'));
    expect(selected).toHaveLength(1);
    expect(selected[0]).toMatch(/^ sel[^"]* tleaf".*>health</);
  });
});
