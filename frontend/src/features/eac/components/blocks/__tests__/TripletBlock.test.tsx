/**
 * TripletBlock unit tests — render the inner attribute and constraint blocks
 * side-by-side with the divider.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';

import { TripletBlock } from '../TripletBlock';
import type { AttributeRef, Constraint } from '../../../types';

function renderWithDnd(ui: React.ReactElement) {
  return render(<DndContext>{ui}</DndContext>);
}

const ATTRIBUTE: AttributeRef = {
  kind: 'exact',
  pset_name: 'Pset_WallCommon',
  property_name: 'IsExternal',
};
const CONSTRAINT: Constraint = { operator: 'eq', value: true };

describe('TripletBlock', () => {
  it('renders both inner blocks and the parent heading', () => {
    renderWithDnd(<TripletBlock attribute={ATTRIBUTE} constraint={CONSTRAINT} />);
    expect(screen.getByText('Triplet')).toBeInTheDocument();
    expect(screen.getByTestId('eac-triplet-attribute')).toBeInTheDocument();
    expect(screen.getByTestId('eac-triplet-constraint')).toBeInTheDocument();
    // The inner attribute and constraint summaries should be visible
    expect(screen.getByText('Pset_WallCommon.IsExternal')).toBeInTheDocument();
    expect(screen.getByText('= true')).toBeInTheDocument();
  });

  it('uses the parent attribute color and exposes a triplet test id', () => {
    renderWithDnd(<TripletBlock attribute={ATTRIBUTE} constraint={CONSTRAINT} />);
    const triplet = screen.getByTestId('eac-block-triplet');
    expect(triplet).toBeInTheDocument();
    expect(triplet.getAttribute('data-block-color')).toBe('attribute');
  });

  it('forwards selection callbacks to the inner attribute and constraint', () => {
    const onAttr = vi.fn();
    const onConstraint = vi.fn();
    renderWithDnd(
      <TripletBlock
        attribute={ATTRIBUTE}
        constraint={CONSTRAINT}
        onAttributeSelect={onAttr}
        onConstraintSelect={onConstraint}
      />,
    );
    fireEvent.click(screen.getByTestId('eac-triplet-attribute'));
    fireEvent.click(screen.getByTestId('eac-triplet-constraint'));
    expect(onAttr).toHaveBeenCalledTimes(1);
    expect(onConstraint).toHaveBeenCalledTimes(1);
  });
});
