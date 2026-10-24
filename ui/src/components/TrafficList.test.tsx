import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { flow } from '../logic/testing';
import { StoreProvider } from '../store';
import { TrafficList } from './TrafficList';

const noop = () => undefined;

describe('TrafficList', () => {
  it('marks a replay row, selected or not, and no other row', () => {
    const html = renderToStaticMarkup(
      <StoreProvider>
        <TrafficList
          rows={[flow({ id: 'f1' }), flow({ id: 'f2', replay_of: 'f1' }), flow({ id: 'f3', replay_of: 'f1' })]}
          selectedId="f3"
          onSelect={noop}
          revealKey={null}
          paused={false}
          follow
          onFollowChange={noop}
          showDevice={false}
          onDecrypt={noop}
          onHideEncrypted={noop}
          onMapLocal={noop}
        />
      </StoreProvider>,
    );
    const classes = [...html.matchAll(/class="(frow[^"]*)"/g)].map((m) => m[1]);
    expect(classes).toEqual(['frow', 'frow replay', 'frow sel replay']);
  });
});
