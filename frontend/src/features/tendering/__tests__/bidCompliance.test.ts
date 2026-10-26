// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Bid​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ compliance chips: stale revision, missing addenda, compliant, and silence without data.

import { describe, it, expect } from 'vitest';
import { bidComplianceChips } from '../bidCompliance';

describe('bidComplianceChips', () => {
  it('says nothing when the backend reports no compliance data', () => {
    expect(bidComplianceChips({})).toEqual([]);
  });

  it('marks a bid on an older bill revision as a warning', () => {
    const chips = bidComplianceChips({ boq_revision_no: 1, current_boq_revision: 2, revision_current: false, missing_addenda: [], compliant: false });
    expect(chips).toEqual([{ kind: 'revision_stale', tone: 'warning', revision: 1 }]);
  });

  it('lists missing addenda in red alongside a stale revision', () => {
    const chips = bidComplianceChips({ boq_revision_no: 1, revision_current: false, missing_addenda: [2, 3], compliant: false });
    expect(chips.map((c) => c.kind)).toEqual(['revision_stale', 'missing_addenda']);
    expect(chips[1]).toMatchObject({ tone: 'error', missing: [2, 3] });
  });

  it('shows compliant in green only when nothing is wrong', () => {
    const chips = bidComplianceChips({ revision_current: true, missing_addenda: [], compliant: true });
    expect(chips).toEqual([{ kind: 'compliant', tone: 'success' }]);
  });
});
