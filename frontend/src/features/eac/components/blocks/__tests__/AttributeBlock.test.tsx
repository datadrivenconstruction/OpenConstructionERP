/**
 * AttributeBlock unit tests — exact / alias / regex display.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';

import { AttributeBlock, describeAttribute } from '../AttributeBlock';
import type { AttributeRef } from '../../../types';

function renderWithDnd(ui: React.ReactElement) {
  return render(<DndContext>{ui}</DndContext>);
}

describe('describeAttribute', () => {
  it('formats exact references with and without pset', () => {
    expect(
      describeAttribute({ kind: 'exact', pset_name: 'Pset_WallCommon', property_name: 'IsExternal' }),
    ).toBe('Pset_WallCommon.IsExternal');
    expect(
      describeAttribute({ kind: 'exact', pset_name: null, property_name: 'GlobalId' }),
    ).toBe('GlobalId');
  });

  it('formats alias references with canonical name when available', () => {
    expect(
      describeAttribute({ kind: 'alias', alias_id: 'a1', canonical_name: 'Thickness' }),
    ).toBe('Thickness (alias)');
    expect(describeAttribute({ kind: 'alias', alias_id: 'a1' })).toBe('alias:a1');
  });

  it('formats regex references with pattern and scope', () => {
    expect(
      describeAttribute({ kind: 'regex', pattern: '^Pset_', scope: 'pset_name' }),
    ).toBe('/^Pset_/ (pset_name)');
  });
});

describe('AttributeBlock', () => {
  it('renders kind-specific label for each kind', () => {
    const exact: AttributeRef = { kind: 'exact', property_name: 'Length', pset_name: 'Pset_Wall' };
    const { unmount } = renderWithDnd(<AttributeBlock attribute={exact} />);
    expect(screen.getByText('Property')).toBeInTheDocument();
    expect(screen.getByText('Pset_Wall.Length')).toBeInTheDocument();
    unmount();

    renderWithDnd(<AttributeBlock attribute={{ kind: 'alias', alias_id: 'a1' }} />);
    expect(screen.getByText('Alias')).toBeInTheDocument();
  });

  it('uses purple color via data attribute', () => {
    renderWithDnd(<AttributeBlock attribute={{ kind: 'alias', alias_id: 'a1' }} />);
    expect(screen.getByRole('group').getAttribute('data-block-color')).toBe('attribute');
  });
});
