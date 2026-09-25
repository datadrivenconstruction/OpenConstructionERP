/**
 * Enter in the unit cell saves what the estimator typed.
 *
 * The suggestion list opens with its first entry highlighted, and Enter used to
 * commit that highlighted entry whether or not anyone had chosen it. The list
 * filters by prefix and the metric units start with ``mm``, so typing ``m`` and
 * pressing Enter saved ``mm``, and opening a cell holding ``m3`` and pressing
 * Enter replaced it with ``mm`` as well. A suggestion is a choice only once the
 * estimator moves the highlight onto it with the arrow keys.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/react';

import { UnitCellEditor } from './cellEditors';
import type { FormulaCellEditorParams } from './cellEditors';

function renderUnit(value: string) {
  const setDataValue = vi.fn();
  const params = {
    value,
    data: { unit: value },
    node: { id: `row-${value}`, data: { unit: value }, setDataValue },
    api: { stopEditing: vi.fn(), tabToNextCell: vi.fn(), tabToPreviousCell: vi.fn() },
    column: { getColId: () => 'unit' },
  } as unknown as FormulaCellEditorParams;
  render(<UnitCellEditor {...params} />);
  return { input: screen.getByRole('combobox') as HTMLInputElement, setDataValue };
}

describe('Enter in the unit cell', () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
    // jsdom has no layout, so the list's scroll-into-view on navigation is a no-op here.
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('saves the typed unit, not the first suggestion that starts with it', () => {
    const { input, setDataValue } = renderUnit('m3');
    fireEvent.change(input, { target: { value: 'm' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(setDataValue).toHaveBeenCalledWith('unit', 'm');
    expect(setDataValue).not.toHaveBeenCalledWith('unit', 'mm');
  });

  it('keeps the stored unit when the cell is opened and closed with Enter', () => {
    const { input, setDataValue } = renderUnit('m3');
    fireEvent.keyDown(input, { key: 'Enter' });
    // Nothing changed, so nothing is written.
    expect(setDataValue).not.toHaveBeenCalled();
  });

  it('saves the suggestion the estimator moved onto with the arrow keys', () => {
    const { input, setDataValue } = renderUnit('m3');
    fireEvent.change(input, { target: { value: 'm' } });
    // Two steps down from the first entry is the third one, whatever the
    // locale's list holds; read it off the list before Enter closes it.
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    const third = screen.getAllByRole('option')[2]?.getAttribute('data-unit-value');
    expect(third).toBeTruthy();
    expect(third).not.toBe('m');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(setDataValue).toHaveBeenCalledTimes(1);
    expect(setDataValue).toHaveBeenCalledWith('unit', third);
  });

  it('goes back to the typed text once the estimator types after moving', () => {
    const { input, setDataValue } = renderUnit('m3');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.change(input, { target: { value: 'm2' } });
    fireEvent.change(input, { target: { value: 'm' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(setDataValue).toHaveBeenCalledWith('unit', 'm');
  });
});
