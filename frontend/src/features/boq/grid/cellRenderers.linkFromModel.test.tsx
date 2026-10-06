// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The narrow model column beside Qty showed nothing for a position without
// model links, so there was no visible way to start linking one. It now offers
// "pick elements in the 3D model" on such a row, and only when the host can
// act on it: a handler, a project model to open, and a bill that takes writes.

import type { ICellRendererParams } from 'ag-grid-community';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BimQtyPickerCellRenderer } from './cellRenderers';

const t = (k: string, o?: Record<string, string | number>) => (o?.defaultValue as string) ?? k;

function renderCell(data: Record<string, unknown>, context: Record<string, unknown>) {
  const params = { data, value: null, context: { t, ...context } } as unknown as ICellRendererParams;
  return render(<BimQtyPickerCellRenderer {...params} />);
}

const unlinked = { id: 'p1', ordinal: '01.010', quantity: 0, unit: 'm2', cad_element_ids: [] };

describe('the model cell on a position without links', () => {
  it('offers to pick elements in the model and calls the host with the position', () => {
    const onLinkFromModel = vi.fn();
    renderCell(unlinked, { onLinkFromModel, bimModelId: 'm-1' });
    fireEvent.click(screen.getByTestId('boq-link-from-model'));
    expect(onLinkFromModel).toHaveBeenCalledWith('p1');
  });

  it('offers nothing without a project model, without a handler, or on a locked bill', () => {
    const onLinkFromModel = vi.fn();
    const { unmount } = renderCell(unlinked, { onLinkFromModel, bimModelId: null });
    expect(screen.queryByTestId('boq-link-from-model')).toBeNull();
    unmount();
    const second = renderCell(unlinked, { bimModelId: 'm-1' });
    expect(screen.queryByTestId('boq-link-from-model')).toBeNull();
    second.unmount();
    renderCell(unlinked, { onLinkFromModel, bimModelId: 'm-1', readOnly: true });
    expect(screen.queryByTestId('boq-link-from-model')).toBeNull();
  });

  it('keeps the quantity picker, not the link action, on a linked position', () => {
    renderCell(
      { ...unlinked, cad_element_ids: ['e-1'] },
      { onLinkFromModel: vi.fn(), bimModelId: 'm-1', onUpdatePosition: vi.fn() },
    );
    expect(screen.queryByTestId('boq-link-from-model')).toBeNull();
    expect(screen.getByLabelText('Pick quantity from BIM')).toBeTruthy();
  });

  it('offers nothing on a section row', () => {
    renderCell({ ...unlinked, _isSection: true }, { onLinkFromModel: vi.fn(), bimModelId: 'm-1' });
    expect(screen.queryByTestId('boq-link-from-model')).toBeNull();
  });
});
