import { describe, it, expect } from 'vitest';
import { changeOrderSource } from './changeOrderSource';

describe('a change order raised from a design revision', () => {
  it('links to the revision on the acceptance page', () => {
    const src = changeOrderSource({ source: 'design_revision', design_revision_id: 'rev 1' });
    expect(src?.kind).toBe('design_revision');
    expect(src?.to).toBe('/design/acceptance?revision=rev%201');
  });

  it('draws nothing without a revision id', () => {
    expect(changeOrderSource({ source: 'design_revision' })).toBeNull();
  });
});
