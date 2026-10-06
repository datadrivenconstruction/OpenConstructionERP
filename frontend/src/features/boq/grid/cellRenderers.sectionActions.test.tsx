// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The controls on a section header row.
 *
 * The delete control used to be a trash icon at opacity 0 that only hover
 * revealed, so on a touch screen a section could be added and never removed.
 * The tip above the grid also sent people to a "(...)" menu on sections that
 * only positions had. A section now carries both: the trash icon, always
 * drawn, and the same actions button the position rows have.
 */
import type { ICellRendererParams } from 'ag-grid-community';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SectionFullWidthRenderer } from './cellRenderers';

const SECTION = { id: 'sec-1', ordinal: '01', description: 'Walls', _isSection: true, _childCount: 3 };

function renderSection(ctx: Record<string, unknown> = {}) {
  const onShowContextMenu = vi.fn();
  const onDeleteSection = vi.fn();
  const params = {
    data: SECTION,
    context: {
      t: (k: string, o?: Record<string, unknown>) =>
        String(o?.defaultValue ?? k).replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name: string) => String(o?.[name] ?? '')),
      collapsedSections: new Set<string>(),
      onShowContextMenu,
      onDeleteSection,
      ...ctx,
    },
  } as unknown as ICellRendererParams;
  render(<SectionFullWidthRenderer {...params} />);
  return { onShowContextMenu, onDeleteSection };
}

describe('SectionFullWidthRenderer actions', () => {
  it('opens the section context menu from its (...) button', () => {
    const { onShowContextMenu } = renderSection();

    fireEvent.click(screen.getByRole('button', { name: 'Actions for section Walls' }));

    expect(onShowContextMenu).toHaveBeenCalledTimes(1);
    const [, type, data] = onShowContextMenu.mock.calls[0]!;
    expect(type).toBe('section');
    expect((data as { id: string }).id).toBe('sec-1');
  });

  it('draws the delete control without waiting for hover', () => {
    const { onDeleteSection } = renderSection();

    const trash = screen.getByRole('button', { name: 'Delete section with all positions' });
    // Not hidden at rest: no bare opacity-0, which is what made it invisible on touch.
    expect(trash.className.split(/\s+/)).not.toContain('opacity-0');

    fireEvent.click(trash);
    expect(onDeleteSection).toHaveBeenCalledWith('sec-1');
  });

  it('draws no delete control when the grid hands it nothing to call', () => {
    renderSection({ onDeleteSection: undefined });

    expect(screen.queryByRole('button', { name: 'Delete section with all positions' })).toBeNull();
    // The menu stays: collapse and the other read actions live there.
    expect(screen.getByRole('button', { name: 'Actions for section Walls' })).toBeTruthy();
  });

  it('draws no delete control on a locked bill', () => {
    renderSection({ readOnly: true });

    expect(screen.queryByRole('button', { name: 'Delete section with all positions' })).toBeNull();
  });
});
