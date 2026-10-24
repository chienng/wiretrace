import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { emptyRule } from '../logic/rules';
import { RuleEditor } from './RuleEditor';

const render = (isNew: boolean) =>
  renderToStaticMarkup(
    <RuleEditor
      initial={emptyRule('r1')}
      isNew={isNew}
      savedEnabled={isNew ? null : true}
      apiHosts={['api.example.com']}
      mockFiles={null}
      others={[]}
      stats={null}
      busy={false}
      testTarget={null}
      testTargetLabel="Test on the last request"
      onSave={async () => null}
      onDelete={() => undefined}
      onRearm={() => undefined}
      onTest={async () => 'No request captured yet.'}
      onCancel={() => undefined}
      cancelHint="Discard this rule and go back to the request in Traffic"
    />,
  );

describe('RuleEditor', () => {
  it('lets a new rule be cancelled, back to where it came from', () => {
    const html = render(true);
    expect(html).toContain('title="Discard this rule and go back to the request in Traffic">Cancel</button>');
    expect(html).not.toContain('>Delete</button>');
  });

  it('offers Delete, not Cancel, for a saved rule', () => {
    const html = render(false);
    expect(html).toContain('>Delete</button>');
    expect(html).not.toContain('>Cancel</button>');
  });
});
