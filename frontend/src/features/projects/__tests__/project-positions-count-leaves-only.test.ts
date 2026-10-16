// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project hub counted every row of the estimate, section headers included,
// while the BOQ list counts positions only, so one project showed two numbers.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

  it('is the count every estimate row on the hub shows too', () => {
    // The KPI card was fixed first; the estimate list below it still printed the raw row count.
    const src = readFileSync(resolve(__dirname, '../ProjectDetailPage.tsx'), 'utf8');
    expect(src).toMatch(/const posCount = detail \? countLeafPositions\(\[detail\]\) : 0;/);
  });
});
