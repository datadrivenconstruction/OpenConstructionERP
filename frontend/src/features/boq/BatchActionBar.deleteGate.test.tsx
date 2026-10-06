// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Delete selected" in the batch bar is a `boq.delete` call (EDITOR and up on
 * the server), like the grid's own delete controls. A viewer can still select
 * rows and change their unit or classification (`boq.update` is VIEWER), so the
 * bar stays; only Delete goes.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen } from '@testing-library/react';

import { BatchActionBar } from './BatchActionBar';
import { useAuthStore } from '@/stores/useAuthStore';

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null });
});

function renderBar() {
  render(
    <BatchActionBar
      selectedIds={['pos-1', 'pos-2']}
      onBatchDelete={vi.fn()}
      onBatchChangeUnit={vi.fn()}
      onClearSelection={vi.fn()}
    />,
  );
}

describe('BatchActionBar delete gate', () => {
  it('offers Delete selected to an editor', () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderBar();
    expect(screen.getByRole('button', { name: 'Delete selected' })).toBeTruthy();
  });

  it('offers no Delete selected to a viewer, but keeps the rest of the bar', () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderBar();
    expect(screen.queryByRole('button', { name: 'Delete selected' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Change unit' })).toBeTruthy();
  });
});
