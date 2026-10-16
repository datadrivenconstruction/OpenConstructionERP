// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A viewer can start an estimate (issue #101) but `boq.delete` needs an editor,
// so the bin was offered to everybody and a viewer's click on their own bill
// was refused. The backend now lets the author delete their own bill; the bin
// follows the same rule.

import { describe, it, expect } from 'vitest';
import { canDeleteBoq } from '../canDeleteBoq';

const ME = '11111111-1111-1111-1111-111111111111';
const OTHER = '22222222-2222-2222-2222-222222222222';

describe('canDeleteBoq', () => {
  it('lets a viewer delete the bill they started', () => {
    expect(canDeleteBoq('viewer', ME, { created_by: ME })).toBe(true);
    expect(canDeleteBoq('viewer', ME.toUpperCase(), { created_by: ME })).toBe(true);
  });

  it("keeps a viewer off someone else's bill and off bills with no recorded author", () => {
    expect(canDeleteBoq('viewer', ME, { created_by: OTHER })).toBe(false);
    expect(canDeleteBoq('viewer', ME, { created_by: null })).toBe(false);
    expect(canDeleteBoq('viewer', null, { created_by: null })).toBe(false);
    expect(canDeleteBoq(null, '', { created_by: '' })).toBe(false);
  });

  it('leaves editors and above deleting any bill', () => {
    for (const role of ['editor', 'manager', 'admin']) {
      expect(canDeleteBoq(role, ME, { created_by: OTHER })).toBe(true);
      expect(canDeleteBoq(role, ME, {})).toBe(true);
    }
  });
});
