// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435, the navigation half. Every register in the change chain held
// the id of the record beside it and navigated to the bare module list. The
// helpers here are the destinations the pills now use; what is pinned is that
// each one carries the id, names the tab where the destination has tabs, and
// escapes an id that would otherwise rewrite the query string.

import { describe, it, expect } from 'vitest';
import {
  changeOrderDeepLink,
  contractDeepLink,
  linkedVariationDeepLink,
  variationBoqDeepLink,
  variationOrderDeepLink,
  variationRequestDeepLink,
} from './changeChainLinks';

describe('each link lands on the record, not the register', () => {
  it('carries the id into every destination', () => {
    expect(changeOrderDeepLink('co-42')).toBe('/changeorders?highlight=co-42');
    expect(contractDeepLink('ct-7')).toBe('/contracts?highlight=ct-7');
    expect(variationBoqDeepLink('boq-1')).toBe('/boq/boq-1');
  });

  it('names the tab on the variations workspace, which is five registers', () => {
    // A highlight with no tab would be an id the page has to guess the kind
    // of, and a request id and an order id look the same.
    expect(variationRequestDeepLink('vr-1')).toBe('/variations?tab=requests&highlight=vr-1');
    expect(variationOrderDeepLink('vo-1')).toBe('/variations?tab=orders&highlight=vo-1');
  });

  it('escapes an id that would otherwise break out of the query string', () => {
    expect(contractDeepLink('a b&highlight=evil')).toBe(
      '/contracts?highlight=a%20b%26highlight%3Devil',
    );
    expect(variationOrderDeepLink('x&tab=notices')).toBe(
      '/variations?tab=orders&highlight=x%26tab%3Dnotices',
    );
  });
});

describe('the variation a record links to', () => {
  it('prefers the order, which is the contractual record, over the request', () => {
    expect(
      linkedVariationDeepLink({ variation_order_id: 'vo-1', variation_request_id: 'vr-1' }),
    ).toBe('/variations?tab=orders&highlight=vo-1');
  });

  it('falls back to the request while no order exists yet', () => {
    expect(linkedVariationDeepLink({ variation_order_id: null, variation_request_id: 'vr-1' })).toBe(
      '/variations?tab=requests&highlight=vr-1',
    );
  });

  it('is null when the record links to no variation, so no pill is drawn', () => {
    // The alternative, a pill to the bare register, is the defect this file
    // exists for.
    expect(linkedVariationDeepLink({ variation_order_id: null, variation_request_id: null })).toBeNull();
    expect(linkedVariationDeepLink({})).toBeNull();
  });
});
