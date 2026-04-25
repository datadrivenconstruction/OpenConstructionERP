/**
 * SelectorBlock unit tests — describe() output for every selector kind +
 * render contract.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';

import { SelectorBlock, describeSelector } from '../SelectorBlock';
import type { EntitySelector } from '../../../types';

function renderWithDnd(ui: React.ReactElement) {
  return render(<DndContext>{ui}</DndContext>);
}

describe('describeSelector', () => {
  it('formats every selector kind compactly', () => {
    expect(describeSelector({ type: 'ifc_class', ifc_class: 'IfcWall' })).toBe('IFC: IfcWall');
    expect(
      describeSelector({ type: 'ifc_class', ifc_class: 'IfcWall', include_subtypes: true }),
    ).toBe('IFC: IfcWall (+ subtypes)');
    expect(describeSelector({ type: 'category', category: 'Walls' })).toBe('Category: Walls');
    expect(
      describeSelector({
        type: 'classification',
        classifier_id: 'uniformat',
        codes: ['B2010', 'B2020'],
      }),
    ).toBe('Classification: B2010, B2020');
    expect(
      describeSelector({ type: 'spatial', scope: 'level', ref_id: 'L1' }),
    ).toBe('level: L1');
    expect(describeSelector({ type: 'attribute', predicate: { type: 'and', children: [] } })).toBe(
      'Attribute predicate',
    );
    expect(describeSelector({ type: 'and', children: [] })).toBe('AND 0 children');
    expect(
      describeSelector({
        type: 'or',
        children: [
          { type: 'category', category: 'Walls' },
          { type: 'category', category: 'Doors' },
        ],
      }),
    ).toBe('OR 2 children');
    expect(
      describeSelector({ type: 'not', child: { type: 'category', category: 'Walls' } }),
    ).toBe('NOT');
  });
});

describe('SelectorBlock', () => {
  it('renders the heading with the selector kind', () => {
    const selector: EntitySelector = { type: 'category', category: 'Walls' };
    renderWithDnd(<SelectorBlock selector={selector} />);
    expect(screen.getByText('Selector · category')).toBeInTheDocument();
    expect(screen.getByText('Category: Walls')).toBeInTheDocument();
  });

  it('uses the selector color (gray) via data attribute', () => {
    renderWithDnd(<SelectorBlock selector={{ type: 'category', category: 'Walls' }} />);
    expect(screen.getByRole('group').getAttribute('data-block-color')).toBe('selector');
  });
});
