// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project hub counted every row of the estimate, section headers included,
// while the BOQ list counts positions only, so one project showed two numbers.

import { describe, it, expect } from 'vitest';
import { countLeafPositions } from '../ProjectDetailPage';

describe('the position count on the project hub', () => {
  it('leaves section headers out', () => {
    const details = [
      {
        positions: [
          { unit: '', quantity: '0', unit_rate: '0' },
          { unit: 'm3', quantity: '120', unit_rate: '85.50' },
          { unit: 'section', quantity: 0, unit_rate: 0 },
          { unit: 'm2', quantity: '40', unit_rate: '0' },
        ],
      },
      { positions: [{ unit: 'pcs', quantity: '3', unit_rate: '1200' }] },
    ];
    expect(countLeafPositions(details)).toBe(3);
  });

  it('is zero without estimates', () => {
    expect(countLeafPositions([])).toBe(0);
  });
});
