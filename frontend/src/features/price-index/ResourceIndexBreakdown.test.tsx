// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// The breakdown has to show each multiplication with the server's own figures,
// say when sample data was used, and never present a partial bill as the
// estimate total. The fixture is position 1 of the backend's hand-computed
// example (2 x 12.5 x 400.00 = 10 000.00, x 1.25 = 12 500.00, ...).
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { EstimateBreakdown } from './ResourceIndexPage';
import type { OverheadNorm, ResourceIndexEstimate } from './resourceIndexApi';

// formatAmount groups with a thin space (U+2009); Testing Library's default
// normaliser folds any whitespace run into a plain space before matching.
const S = ' ';

function fixture(overrides: Partial<ResourceIndexEstimate> = {}): ResourceIndexEstimate {
  return {
    region_code: 'RU-MOW',
    quarter: '2026-Q1',
    on_date: '2026-02-15',
    currency: 'RUB',
    vat_rate_pct: '22.0',
    vat_tax_name: 'VAT Standard (NDS)',
    indices_used: [
      { resource_group: 'labor', index_value: '1.250000', source: 'Letter', is_sample: false },
      { resource_group: 'machine', index_value: '1.100000', source: 'Letter', is_sample: false },
      { resource_group: 'operator_wages', index_value: '1.300000', source: 'Letter', is_sample: false },
      { resource_group: 'material', index_value: '1.050000', source: 'Letter', is_sample: false },
    ],
    norms_used: [
      { work_type_code: 'concrete', label: 'Concrete', nr_pct: '103.0000', sp_pct: '65.0000', source: '', is_sample: false },
    ],
    uses_sample_data: false,
    positions: [
      {
        ref: 'pos-1',
        ordinal: '1.1',
        description: 'Concrete blinding',
        unit: '100 m3',
        quantity: '2',
        work_type: 'concrete',
        work_type_source: 'chosen',
        lines: [
          {
            code: 'L1', name: 'Workers', unit: 'man-h', kind: 'labor', quantity: '12.5', base_unit_price: '400.00',
            position_quantity: '2', base_amount: '10000.00', index_group: 'labor', index: '1.250000',
            current_amount: '12500.00', operator_wage_index: null, operator_wage_current: null,
          },
          {
            code: 'O1', name: 'Pump operator', unit: 'man-h', kind: 'operator', quantity: '3', base_unit_price: '500.00',
            position_quantity: '2', base_amount: '3000.00', index_group: 'machine', index: '1.100000',
            current_amount: '3300.00', operator_wage_index: '1.300000', operator_wage_current: '3900.00',
          },
        ],
        base_ot: '10000.00', base_em: '9000.00', base_otm: '3000.00', base_m: '5000.00', base_direct: '24000.00',
        ot: '12500.00', em: '9900.00', otm: '3900.00', m: '5250.00', direct: '27650.00', fot: '16400.00',
        nr_pct: '103.0000', nr: '16892.00', sp_pct: '65.0000', sp: '10660.00', total: '55202.00',
      },
    ],
    by_work_type: [
      { work_type: 'concrete', label: 'Concrete', nr_pct: '103.0000', sp_pct: '65.0000', fot: '16400.00', nr: '16892.00', sp: '10660.00' },
    ],
    totals: {
      base_ot: '10000.00', base_em: '9000.00', base_otm: '3000.00', base_m: '5000.00', base_direct: '24000.00',
      ot: '12500.00', em: '9900.00', otm: '3900.00', m: '5250.00', direct: '27650.00', fot: '16400.00',
      nr: '16892.00', sp: '10660.00', total: '55202.00', vat_rate_pct: '22.0', vat: '12144.44', total_with_vat: '67346.44',
    },
    excluded: [],
    priced_count: 1,
    excluded_count: 0,
    is_complete: true,
    boq_id: 'boq-1',
    boq_name: 'Smeta',
    project_id: 'proj-1',
    ...overrides,
  };
}

const NORMS: OverheadNorm[] = [
  { id: 'n1', work_type_code: 'concrete', label: 'Concrete', nr_pct: '103', sp_pct: '65', source: '', is_sample: false, created_at: '', updated_at: '' },
  { id: 'n2', work_type_code: 'masonry', label: 'Masonry', nr_pct: '120', sp_pct: '70', source: '', is_sample: false, created_at: '', updated_at: '' },
];

function renderIt(result: ResourceIndexEstimate, onWorkTypeChange?: (ref: string, code: string) => void) {
  return render(
    <EstimateBreakdown
      result={result}
      norms={NORMS}
      normLabel={new Map(NORMS.map((n) => [n.work_type_code, n.label]))}
      onWorkTypeChange={onWorkTypeChange}
      chosen={{ 'pos-1': 'concrete' }}
    />,
  );
}

describe('EstimateBreakdown', () => {
  it('shows every multiplication with the server figures', () => {
    renderIt(fixture());
    // Line: Q x consumption x base price = base, x index = current.
    expect(screen.getByText(`2 × 12.5 × 400.00 =`, { exact: false })).toBeTruthy();
    expect(screen.getAllByText(`12${S}500.00`).length).toBeGreaterThan(0);
    // The operator line also shows its wage share at the wage index.
    expect(screen.getByText('× 1.3 =', { exact: false })).toBeTruthy();
    expect(screen.getAllByText(`3${S}900.00`).length).toBeGreaterThan(0);
    // NR and SP on the wage fund.
    expect(screen.getByText(`16${S}400.00 × 103%`)).toBeTruthy();
    expect(screen.getByText(`16${S}400.00 × 65%`)).toBeTruthy();
    // FOT = OT + OTm.
    expect(screen.getAllByText(`12${S}500.00 + 3${S}900.00`).length).toBeGreaterThan(0);
    // VAT from the rate the server read for the date.
    expect(screen.getByText(`55${S}202.00 × 22%`)).toBeTruthy();
    expect(screen.getByText(`67${S}346.44`)).toBeTruthy();
    expect(screen.getByText('Estimate totals')).toBeTruthy();
    expect(screen.queryByText(/sample indices or norms/)).toBeNull();
  });

  it('warns when sample data was used', () => {
    renderIt(fixture({ uses_sample_data: true }));
    expect(screen.getByText(/sample indices or norms shipped for demonstration/)).toBeTruthy();
  });

  it('labels a partial bill and lists what was left out', () => {
    renderIt(
      fixture({
        is_complete: false,
        excluded_count: 2,
        excluded: [
          { position_id: 'p2', ordinal: '1.2', description: 'Facade', reason: 'no_resources', detail: '' },
          { position_id: 'p3', ordinal: '1.3', description: 'Lift', reason: 'unmapped_resource_type', detail: 'subcontractor' },
        ],
      }),
    );
    expect(screen.getByText(/Partial: 1 positions priced, 2 not priced/)).toBeTruthy();
    expect(screen.getByText('Totals of the priced positions')).toBeTruthy();
    expect(screen.queryByText('Estimate totals')).toBeNull();
    expect(screen.getByText(/no resource breakdown on the position/)).toBeTruthy();
    expect(screen.getByText(/resource type subcontractor has no group/)).toBeTruthy();
  });

  it('lets a person change the work type of a position', () => {
    const onChange = vi.fn();
    renderIt(fixture(), onChange);
    const select = screen.getByRole('combobox', { name: 'Work type' });
    fireEvent.change(select, { target: { value: 'masonry' } });
    expect(onChange).toHaveBeenCalledWith('pos-1', 'masonry');
  });

  it('offers a work type for a position left out for lacking one', () => {
    const onChange = vi.fn();
    renderIt(
      fixture({
        is_complete: false,
        excluded_count: 1,
        excluded: [{ position_id: 'p9', ordinal: '2.1', description: 'Walls', reason: 'no_work_type', detail: '' }],
      }),
      onChange,
    );
    const selects = screen.getAllByRole('combobox', { name: 'Work type' });
    expect(selects.length).toBe(2);
    fireEvent.change(selects[0]!, { target: { value: 'concrete' } });
    expect(onChange).toHaveBeenCalledWith('p9', 'concrete');
  });
});
