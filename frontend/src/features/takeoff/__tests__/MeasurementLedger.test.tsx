/**
 * Render test for the MeasurementLedger component.  Exercises the
 * three user-facing behaviors the spec calls out:
 *   1. Subtotals per group are correct
 *   2. Sorting by Value toggles asc/desc
 *   3. Filtering by group hides non-matching rows
 */

// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MeasurementLedger } from '../components/MeasurementLedger';
import type { Measurement } from '../lib/takeoff-types';

function m(partial: Partial<Measurement> & { id: string }): Measurement {
  return {
    id: partial.id,
    type: partial.type ?? 'distance',
    points: partial.points ?? [],
    value: partial.value ?? 0,
    unit: partial.unit ?? 'm',
    label: partial.label ?? '',
    annotation: partial.annotation ?? partial.id,
    page: partial.page ?? 1,
    group: partial.group ?? 'General',
    ...partial,
  };
}

const FIXTURE: Measurement[] = [
  m({ id: 'a', value: 10, unit: 'm', group: 'Walls', annotation: 'Wall A' }),
  m({ id: 'b', value: 5, unit: 'm', group: 'Walls', annotation: 'Wall B' }),
  m({ id: 'c', type: 'area', value: 20, unit: 'm²', group: 'Floors', page: 2, annotation: 'Floor 1' }),
  m({ id: 'd', type: 'area', value: 15, unit: 'm²', group: 'Floors', page: 2, annotation: 'Floor 2' }),
  m({ id: 'e', type: 'count', value: 3, unit: 'pcs', group: 'Walls', annotation: 'Doors' }),
];

const COLORS = { Walls: '#EF4444', Floors: '#3B82F6' };

describe('MeasurementLedger', () => {
  it('renders the empty state when there are no measurements', () => {
    render(<MeasurementLedger measurements={[]} groupColorMap={COLORS} />);
    expect(screen.getByTestId('ledger-empty')).toBeInTheDocument();
  });

  it('renders a row per measurement', () => {
    render(<MeasurementLedger measurements={FIXTURE} groupColorMap={COLORS} />);
    const rows = screen.getAllByTestId('ledger-row');
    expect(rows).toHaveLength(5);
  });

  it('renders correct subtotal rows per group and unit', () => {
    render(<MeasurementLedger measurements={FIXTURE} groupColorMap={COLORS} />);
    const subtotals = screen.getAllByTestId('ledger-subtotal');
    // Walls has two unit buckets: m (distance) and pcs (count); Floors has m²
    const groupsSeen = subtotals.map((el) => el.getAttribute('data-group'));
    expect(groupsSeen).toContain('Walls');
    expect(groupsSeen).toContain('Floors');

    // Find the Walls/m subtotal row and assert its numeric cell reads 15.00.
    const wallsMetersRow = subtotals.find(
      (el) =>
        el.getAttribute('data-group') === 'Walls' &&
        el.getAttribute('data-unit') === 'm',
    )!;
    expect(wallsMetersRow).toBeTruthy();
    expect(wallsMetersRow.textContent).toContain('15'); // 10 + 5

    // Floors m² subtotal = 35.
    const floorsRow = subtotals.find(
      (el) =>
        el.getAttribute('data-group') === 'Floors' &&
        el.getAttribute('data-unit') === 'm²',
    )!;
    expect(floorsRow.textContent).toContain('35'); // 20 + 15
  });

  it('sorting by Value toggles asc → desc on repeat clicks', () => {
    render(<MeasurementLedger measurements={FIXTURE} groupColorMap={COLORS} />);

    // Click the Value header once → asc.  We pick up the data-sort
    // attribute on the header itself.
    const valueHeader = screen.getByTestId('ledger-header-value');
    fireEvent.click(valueHeader);
    expect(valueHeader.getAttribute('data-sort')).toBe('asc');

    fireEvent.click(valueHeader);
    expect(valueHeader.getAttribute('data-sort')).toBe('desc');

    fireEvent.click(valueHeader);
    expect(valueHeader.getAttribute('data-sort')).toBe('asc');
  });

  it('filtering by group hides non-matching rows', () => {
    render(<MeasurementLedger measurements={FIXTURE} groupColorMap={COLORS} />);

    // Open filters, then click the "Walls" chip.
    fireEvent.click(screen.getByTestId('ledger-filter-toggle'));
    const wallsChip = screen
      .getAllByTestId('filter-group')
      .find((el) => el.getAttribute('data-value') === 'Walls')!;
    fireEvent.click(wallsChip);

    // Only the three Walls rows remain.
    const rows = screen.getAllByTestId('ledger-row');
    expect(rows).toHaveLength(3);
    // Floors rows should not appear.
    const floorsRow = rows.find((r) => r.textContent?.includes('Floor 1'));
    expect(floorsRow).toBeUndefined();
  });

  it('click on a row calls onRowClick with the measurement', () => {
    let clicked: Measurement | null = null;
    render(
      <MeasurementLedger
        measurements={FIXTURE}
        groupColorMap={COLORS}
        onRowClick={(me) => (clicked = me)}
      />,
    );
    const rows = screen.getAllByTestId('ledger-row');
    fireEvent.click(rows[0]!);
    expect(clicked).not.toBeNull();
    expect(FIXTURE.some((me) => me.id === clicked!.id)).toBe(true);
  });

  it('renders grand-total rows for every measurement type present', () => {
    render(<MeasurementLedger measurements={FIXTURE} groupColorMap={COLORS} />);
    const grands = screen.getAllByTestId('ledger-grand-total');
    const types = grands.map((el) => el.getAttribute('data-type')).sort();
    expect(types).toEqual(['area', 'count', 'distance']);
  });
});
