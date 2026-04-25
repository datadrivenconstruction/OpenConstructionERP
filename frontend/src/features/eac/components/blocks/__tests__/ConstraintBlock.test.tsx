/**
 * ConstraintBlock unit tests — operator → summary mapping.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';

import { ConstraintBlock, describeConstraint } from '../ConstraintBlock';

function renderWithDnd(ui: React.ReactElement) {
  return render(<DndContext>{ui}</DndContext>);
}

describe('describeConstraint', () => {
  it('formats binary operators with value and unit', () => {
    expect(
      describeConstraint({ operator: 'gte', value: 240, unit: 'mm' }),
    ).toBe('≥ 240 mm');
    expect(describeConstraint({ operator: 'eq', value: 'EXT' })).toBe('= EXT');
  });

  it('formats unary operators without a value', () => {
    expect(describeConstraint({ operator: 'exists' })).toBe('exists');
    expect(describeConstraint({ operator: 'is_null' })).toBe('is null');
  });

  it('formats range operators with min/max', () => {
    expect(
      describeConstraint({ operator: 'between', values: [100, 200], unit: 'mm' }),
    ).toBe('between 100 … 200 mm');
  });

  it('formats set operators with comma-separated values', () => {
    expect(describeConstraint({ operator: 'in', values: ['A', 'B', 'C'] })).toBe('in {A, B, C}');
  });

  it('handles missing values gracefully without throwing', () => {
    expect(describeConstraint({ operator: 'between' })).toBe('between ? … ?');
    expect(describeConstraint({ operator: 'eq' })).toBe('= ?');
  });
});

describe('ConstraintBlock', () => {
  it('renders summary text for the constraint', () => {
    renderWithDnd(<ConstraintBlock constraint={{ operator: 'gte', value: 240, unit: 'mm' }} />);
    expect(screen.getByText('Constraint')).toBeInTheDocument();
    expect(screen.getByText('≥ 240 mm')).toBeInTheDocument();
  });

  it('uses blue color via data attribute', () => {
    renderWithDnd(<ConstraintBlock constraint={{ operator: 'eq', value: 1 }} />);
    expect(screen.getByRole('group').getAttribute('data-block-color')).toBe('constraint');
  });
});
