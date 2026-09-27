// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A locked bill is read-only, and the toolbar offered Renumber and Paste from
 * Excel on it anyway: both rewrite positions. They are hidden when the editor
 * is read-only and stay on an open bill.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { BOQToolbar, type BOQToolbarProps } from '../BOQToolbar';

function stubT(key: string, options?: Record<string, string | number>): string {
  const fallback = options?.defaultValue;
  return typeof fallback === 'string' ? fallback : key;
}

function renderToolbar(readOnly: boolean) {
  const props: BOQToolbarProps = {
    t: stubT,
    projectId: 'proj-alpha',
    boqId: 'boq-17',
    canUndo: false,
    canRedo: false,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onShowVersionHistory: vi.fn(),
    onAddPosition: vi.fn(),
    onAddSection: vi.fn(),
    onOpenCostDb: vi.fn(),
    onOpenAssembly: vi.fn(),
    onImportClick: vi.fn(),
    isImporting: false,
    importInputRef: { current: null },
    onImportInputChange: vi.fn(),
    onExport: vi.fn(),
    onValidate: vi.fn(),
    onRecalculate: vi.fn(),
    isRecalculating: false,
    aiChatOpen: false,
    onToggleAiChat: vi.fn(),
    costFinderOpen: false,
    onToggleCostFinder: vi.fn(),
    smartPanelOpen: false,
    onToggleSmartPanel: vi.fn(),
    hasPositions: true,
    qualityScoreRing: null,
    summary: null,
    readOnly,
    onRenumber: vi.fn(),
    onPasteFromExcel: vi.fn(),
  };
  return render(
    <MemoryRouter>
      <BOQToolbar {...props} />
    </MemoryRouter>,
  );
}

describe('BOQ toolbar on a locked bill', () => {
  it('hides Renumber and Paste from Excel when read-only', () => {
    renderToolbar(true);

    expect(screen.queryByTestId('boq-renumber-button')).toBeNull();
    expect(screen.queryByTitle('Paste from Excel')).toBeNull();
  });

  it('offers both on an open bill', () => {
    renderToolbar(false);

    expect(screen.getByTestId('boq-renumber-button')).toBeTruthy();
    expect(screen.getByTitle('Paste from Excel')).toBeTruthy();
  });
});
