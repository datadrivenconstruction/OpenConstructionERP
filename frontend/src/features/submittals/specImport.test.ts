import { describe, expect, it } from 'vitest';
import { defaultSelection, groupBySection, type SpecProposalItem } from './specImportApi';

const item = (over: Partial<SpecProposalItem>): SpecProposalItem => ({
  id: 'a',
  spec_section: '03 30 00',
  section_title: 'Concrete',
  kind: 'product_data',
  submittal_type: 'product_data',
  title: 'Product data - Concrete',
  source_page: 3,
  source_excerpt: '',
  confidence: 0.9,
  decision: 'pending',
  submittal_id: null,
  duplicate: false,
  ...over,
});

describe('spec import review', () => {
  it('groups proposals by section in order of appearance', () => {
    const groups = groupBySection([item({ id: '1' }), item({ id: '2', spec_section: '09 91 23' }), item({ id: '3' })]);
    expect(groups.map(([s, l]) => [s, l.length])).toEqual([
      ['03 30 00', 2],
      ['09 91 23', 1],
    ]);
  });

  it('ticks only confident, new proposals by default', () => {
    const sel = defaultSelection([
      item({ id: 'ok' }),
      item({ id: 'low', confidence: 0.6 }),
      item({ id: 'dup', duplicate: true }),
      item({ id: 'done', submittal_id: 's1' }),
    ]);
    expect([...sel]).toEqual(['ok']);
  });
});
