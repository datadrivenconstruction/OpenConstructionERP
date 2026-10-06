// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A search result must not offer a click that does nothing.
//
// `unified_search` fans out to every collection in ALL_COLLECTIONS
// (backend/app/core/vector_index.py:112) when the caller sends no `types`
// filter, which is what the modal sends. `hitToHref` knew eleven of the
// fifteen, so a change order, a variation, an MoC record or a cost item got a
// row that looked exactly like a navigable one - same hover, same arrow - and
// swallowed the click, because the modal's handler skips `'#'` silently.
//
// The population is the assertion. A test that checked the four new cases by
// name would have passed just as happily before the backend grew from eleven
// collections to fifteen, which is the event that opened this hole in the
// first place; a test that walks the whole list fails the day it happens
// again.
import { describe, expect, it } from 'vitest';
import { hitToHref, type UnifiedSearchHit } from '../api';

const ID = '4015cdf0-9c2a-4f7e-9a1b-2f8e7d6c5b4a';

/** ALL_COLLECTIONS, in the order backend/app/core/vector_index.py declares it. */
const ALL_COLLECTIONS = [
  'oe_boq_positions',
  'oe_documents',
  'oe_tasks',
  'oe_risks',
  'oe_bim_elements',
  'oe_requirements',
  'oe_rfi_rfis',
  'oe_submittals_submittals',
  'oe_correspondence_correspondence',
  'oe_change_orders',
  'oe_variations',
  'oe_moc',
  'oe_validation',
  'oe_chat',
  'oe_cost_items',
];

function hit(overrides: Partial<UnifiedSearchHit> = {}): UnifiedSearchHit {
  return {
    id: ID,
    score: 0.5,
    title: 'Anything',
    snippet: '',
    text: '',
    module: 'boq',
    project_id: '',
    tenant_id: '',
    payload: {},
    collection: 'oe_boq_positions',
    ...overrides,
  };
}

describe('hitToHref', () => {
  it('routes every collection a search with no type filter can return', () => {
    expect(ALL_COLLECTIONS).toHaveLength(15);

    for (const collection of ALL_COLLECTIONS) {
      const href = hitToHref(hit({ collection }));

      expect(href).not.toBe('#');
      expect(href.startsWith('/')).toBe(true);
    }
  });

  it('carries the record id where the destination page can read one', () => {
    // `?highlight=` is the house convention for a list screen that selects a
    // row from the URL, and ChangeOrdersPage.tsx:2107 reads it.
    expect(hitToHref(hit({ collection: 'oe_change_orders' }))).toBe(
      `/changeorders?highlight=${ID}`,
    );
  });

  it('says which registers cannot select a record yet', () => {
    // VariationsPage, MoCPage and CostsPage read no id from the URL, so the
    // register is the honest destination and a parameter would be a link that
    // looks precise and is not. This assertion is the record of which three
    // are waiting for their other half - it is meant to be rewritten the day
    // one of those pages learns to read an id, not deleted.
    expect(hitToHref(hit({ collection: 'oe_variations' }))).toBe('/variations');
    expect(hitToHref(hit({ collection: 'oe_moc' }))).toBe('/moc');
    expect(hitToHref(hit({ collection: 'oe_cost_items' }))).toBe('/costs');
  });

  it('opens a requirement on the requirements tab, not on the quantity rules', () => {
    // The requirements (oe_requirements sets and items) are the Requirements
    // tab of /bim/rules. That page opens on the quantity rules unless the URL
    // names the tab, and it reads no requirement id, so the tab is the honest
    // destination and an `id=` would be a parameter nothing reads.
    expect(hitToHref(hit({ collection: 'oe_requirements' }))).toBe('/bim/rules?tab=requirements');
  });

  it('still refuses to invent a route for a collection it does not know', () => {
    // The modal renders this row non-navigable rather than letting the click
    // do nothing in silence.
    expect(hitToHref(hit({ collection: 'oe_future_module' }))).toBe('#');
  });
});
