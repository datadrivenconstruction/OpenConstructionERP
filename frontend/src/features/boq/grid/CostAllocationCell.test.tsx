// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ICellRendererParams } from 'ag-grid-community';

import type { PositionAllocation } from '@/features/costmodel/structureApi';
import { CostAllocationCellRenderer, allocationCellView } from './CostAllocationCell';
import { CostAllocationCoverageBar, CostAllocationCoverageError } from '../CostAllocationCoverage';

const row = {
  cost_line_id: 'l1',
  cost_line_code: 'CL-1',
  cost_line_description: 'Walls',
  account_id: 'a1',
  account_code: '330',
  account_title: 'External walls',
  account_postable: true,
  share: '1',
  fraction: '1',
  amount: '10',
};

function alloc(over: Partial<PositionAllocation>): PositionAllocation {
  return {
    position_id: 'p1',
    boq_id: 'b1',
    ordinal: '1',
    description: '',
    unit: 'm',
    quantity: '1',
    total: '10',
    mode: 'single',
    rows: [row],
    valid: true,
    problem: null,
    share_total: '1',
    share_expected: '1',
    in_suspense: false,
    ...over,
  };
}

describe('allocationCellView', () => {
  it('reads single, split and none', () => {
    expect(allocationCellView(alloc({}))).toEqual({ kind: 'single', label: '330 · CL-1', valid: true, suspense: false });
    expect(allocationCellView(alloc({ mode: 'percent', rows: [row, { ...row, cost_line_id: 'l2' }], valid: false }))).toEqual({
      kind: 'split',
      parts: 2,
      valid: false,
      suspense: false,
    });
    expect(allocationCellView(alloc({ mode: 'none', rows: [] }))).toEqual({ kind: 'none' });
  });
});

describe('<CostAllocationCellRenderer>', () => {
  function cell(allocation: PositionAllocation | undefined, onOpen = vi.fn()) {
    const map = new Map<string, PositionAllocation>();
    if (allocation) map.set('p1', allocation);
    const params = { data: { id: 'p1' }, context: { costAllocations: map, onOpenCostAllocation: onOpen } } as unknown as ICellRendererParams;
    render(<CostAllocationCellRenderer {...params} />);
    return onOpen;
  }

  it('shows the split count and opens the drawer on click', () => {
    const onOpen = cell(alloc({ mode: 'quantity', rows: [row, { ...row, cost_line_id: 'l2' }, { ...row, cost_line_id: 'l3' }] }));
    fireEvent.click(screen.getByText('Split (3)'));
    expect(onOpen).toHaveBeenCalledWith('p1');
  });

  it('marks an unallocated position and draws nothing for a position not in the list', () => {
    cell(alloc({ mode: 'none', rows: [] }));
    expect(screen.getByText('Unallocated')).toBeInTheDocument();
  });

  it('flags a one-row quantity split that no longer adds up', () => {
    cell(alloc({ mode: 'quantity', valid: false, problem: 'shares_do_not_add_up' }));
    const button = screen.getByRole('button');
    expect(button).toHaveTextContent('330 · CL-1');
    expect(button).toHaveAttribute('title', expect.stringMatching(/no longer add up/));
  });

  it('says a position on a cost line without an account is in suspense, not allocated', () => {
    cell(alloc({ in_suspense: true, rows: [{ ...row, account_id: null, account_code: '', account_postable: false }] }));
    const button = screen.getByRole('button');
    expect(button).toHaveTextContent('No account');
    expect(button).toHaveTextContent('CL-1');
    expect(button).toHaveAttribute('title', expect.stringMatching(/sits in suspense/));
  });

  it('renders nothing without an allocation', () => {
    cell(undefined);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('<CostAllocationCoverageBar>', () => {
  it('shows the allocated share, the split count and the splits to fix', () => {
    const onToggle = vi.fn();
    render(
      <CostAllocationCoverageBar
        coverage={{
          boq_id: 'b1',
          positions_total: 10,
          positions_allocated: 7,
          positions_split: 2,
          positions_invalid: 1,
          value_total: '1000',
          value_allocated: '725.5',
          value_unallocated: '274.5',
          positions_in_suspense: 0,
          value_in_suspense: '0',
          share_pct: '72.55',
        }}
        currency="EUR"
        showColumn={false}
        onToggleColumn={onToggle}
      />,
    );
    expect(screen.getByTestId('cost-allocation-share')).toHaveTextContent(/72[.,]6 % of the value/);
    expect(screen.getByText('Split positions: 2')).toBeInTheDocument();
    expect(screen.getByText('Splits to fix: 1')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('cost-allocation-column-toggle'));
    expect(onToggle).toHaveBeenCalled();
  });
});

describe('<CostAllocationCoverageBar> with money in suspense', () => {
  it('shows the suspense next to the share and never reads as complete', () => {
    render(
      <CostAllocationCoverageBar
        coverage={{
          boq_id: 'b1',
          positions_total: 4,
          positions_allocated: 4,
          positions_split: 0,
          positions_invalid: 0,
          value_total: '1600',
          value_allocated: '1500',
          value_unallocated: '0',
          positions_in_suspense: 1,
          value_in_suspense: '100',
          share_pct: '93.75',
        }}
        currency="EUR"
        showColumn={false}
        onToggleColumn={vi.fn()}
      />,
    );
    expect(screen.getByTestId('cost-allocation-share')).toHaveTextContent(/93[.,]8 % of the value/);
    const suspense = screen.getByTestId('cost-allocation-suspense');
    expect(suspense).toHaveTextContent(/In suspense: .*100/);
    expect(suspense).toHaveAttribute('title', expect.stringMatching(/without an account: 1/));
  });
});

describe('<CostAllocationCoverageError>', () => {
  it('says the allocation failed to load and retries', () => {
    const onRetry = vi.fn();
    render(<CostAllocationCoverageError onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('The cost allocation of this bill could not be loaded.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });
});
