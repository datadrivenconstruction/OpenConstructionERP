/**
 * The unit picker follows the project's units system, keeps every unit the bill
 * already uses, and remembers "More units..." picks per project.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/react';

import { UnitCellEditor } from './cellEditors';
import type { FormulaCellEditorParams } from './cellEditors';
import { loadProjectExtraUnits, rememberProjectExtraUnit } from '../boqHelpers';

function renderUnit(context: Record<string, unknown>) {
  const params = {
    value: 'm2',
    data: { unit: 'm2' },
    node: { id: 'row-1', data: { unit: 'm2' }, setDataValue: vi.fn() },
    api: { stopEditing: vi.fn(), tabToNextCell: vi.fn(), tabToPreviousCell: vi.fn() },
    column: { getColId: () => 'unit' },
    context,
  } as unknown as FormulaCellEditorParams;
  render(<UnitCellEditor {...params} />);
}

const offered = () => screen.getAllByRole('option').map((o) => o.getAttribute('data-unit-value'));

describe('unit picker market scope', () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('narrows to the project units system', () => {
    renderUnit({ projectId: 'p1', unitsSystem: 'metric', positions: [] });
    expect(offered()).not.toContain('cuyd');
    expect(offered()).toContain('m3');
  });

  it('keeps units already used in the bill', () => {
    renderUnit({ projectId: 'p1', unitsSystem: 'metric', positions: [{ unit: 'sqft' }, { unit: '' }] });
    expect(offered()).toContain('sqft');
    expect(offered()).not.toContain('cuyd');
  });

  it('remembers a More units pick for that project only', async () => {
    renderUnit({ projectId: 'p1', unitsSystem: 'metric', positions: [] });
    const more = document.querySelector('[data-unit-more]') as HTMLElement;
    fireEvent.mouseDown(more);
    const cuyd = (await screen.findAllByRole('option')).find((o) => o.getAttribute('data-unit-value') === 'cuyd') as HTMLElement;
    fireEvent.mouseDown(cuyd);
    expect(loadProjectExtraUnits('p1')).toEqual(['cuyd']);
    expect(loadProjectExtraUnits('p2')).toEqual([]);
    cleanup();
    renderUnit({ projectId: 'p1', unitsSystem: 'metric', positions: [] });
    expect(offered()).toContain('cuyd');
  });

  it('ignores a missing project id when remembering', () => {
    rememberProjectExtraUnit(null, 'cuyd');
    expect(loadProjectExtraUnits('null')).toEqual([]);
    expect(loadProjectExtraUnits(null)).toEqual([]);
  });
});
