// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The right-click menu in the 3D viewer used to draw every item whether or not
// the host had wired a handler for it. "Create quantity rule" was one of them:
// the click closed the menu and nothing opened. These tests pin the guard that
// makes that class of dead item impossible: an item without a handler is not
// drawn, and an item with one calls it and closes the menu.

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown; count?: number }) => {
      const d = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return d.replace('{{count}}', String(opts?.count ?? ''));
    },
  }),
}));

vi.mock('@/shared/hooks/useDisplayQuantity', () => ({
  useDisplayQuantity: () => ({ convert: (value: number, unit: string) => ({ value, unit }) }),
}));

import { BIMContextMenu, type BIMContextMenuActions } from '../BIMContextMenu';
import type { BIMElementData } from '../ElementManager';

const wall = {
  id: 'el-1',
  name: 'Basic Wall 300',
  element_type: 'Walls',
  storey: 'Level 1',
  discipline: 'architectural',
  properties: {},
  quantities: { Area: 12.5 },
} as unknown as BIMElementData;

function renderMenu(actions: BIMContextMenuActions, selected: BIMElementData[] = [wall]) {
  const onClose = vi.fn();
  render(
    <BIMContextMenu
      menu={{ x: 10, y: 10, element: wall, selectedElements: selected }}
      actions={actions}
      onClose={onClose}
    />,
  );
  return { onClose };
}

describe('BIMContextMenu', () => {
  it('does not draw an item whose handler the host did not wire', () => {
    renderMenu({ onZoomToElement: vi.fn(), onCopyProperties: vi.fn() });
    expect(screen.queryByText('Create quantity rule')).toBeNull();
    expect(screen.queryByText('Add to BOQ')).toBeNull();
    expect(screen.queryByText('Show similar elements')).toBeNull();
    expect(screen.queryByText('Show in filter panel')).toBeNull();
    // The view group still renders: those handlers are wired.
    expect(screen.getByText('Zoom to element')).toBeTruthy();
  });

  it('calls the wired quantity-rule handler and closes the menu', () => {
    const onCreateQuantityRule = vi.fn();
    const { onClose } = renderMenu({ onCreateQuantityRule });
    fireEvent.click(screen.getByText('Create quantity rule'));
    expect(onCreateQuantityRule).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('hides the quantity-rule item for a multi-selection', () => {
    const other = { ...wall, id: 'el-2' } as BIMElementData;
    renderMenu({ onCreateQuantityRule: vi.fn(), onAddToBOQ: vi.fn() }, [wall, other]);
    expect(screen.queryByText('Create quantity rule')).toBeNull();
    expect(screen.getByText('Add 2 to BOQ')).toBeTruthy();
  });

  it('keeps a wired but disabled item drawn and disabled', () => {
    renderMenu({ onShowAll: vi.fn(), hasHidden: false });
    const showAll = screen.getByTestId('bim-ctx-show-all') as HTMLButtonElement;
    expect(showAll.disabled).toBe(true);
  });

  it('draws no group header and no divider for a group with no wired item', () => {
    const { container } = render(
      <BIMContextMenu
        menu={{ x: 10, y: 10, element: wall, selectedElements: [wall] }}
        actions={{ onZoomToElement: vi.fn() }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText('Solo Mode')).toBeNull();
    expect(container.querySelectorAll('[data-testid="bim-ctx-divider"]')).toHaveLength(0);
  });
});
