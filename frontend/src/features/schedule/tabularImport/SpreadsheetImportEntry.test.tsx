// @ts-nocheck
/**
 * The two ways into the spreadsheet import from an open schedule: the
 * Interchange tab card and the empty schedule's quick-start tile.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/permissionGates', () => ({ useHasPermission: vi.fn() }));
vi.mock('./ScheduleSpreadsheetImportDialog', () => ({
  ScheduleSpreadsheetImportDialog: vi.fn(({ open, defaultTarget, schedule }) =>
    open ? <div data-testid="dialog" data-target={defaultTarget} data-schedule={schedule.id} /> : null,
  ),
}));

import { useHasPermission } from '@/shared/lib/permissionGates';
import { SpreadsheetImportEntry } from './SpreadsheetImportEntry';

const SCHEDULE = { id: 's1', name: 'Main', status: 'draft' };

function renderEntry(variant: 'card' | 'tile') {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <SpreadsheetImportEntry projectId="p1" schedule={SCHEDULE} variant={variant} />
    </QueryClientProvider>,
  );
}

describe('SpreadsheetImportEntry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useHasPermission.mockReturnValue(true);
  });

  it('opens the dialog from the empty schedule tile with "replace" proposed', () => {
    renderEntry('tile');
    expect(screen.queryByTestId('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Import from Excel or CSV/ }));
    const dialog = screen.getByTestId('dialog');
    expect(dialog).toHaveAttribute('data-target', 'replace');
    expect(dialog).toHaveAttribute('data-schedule', 's1');
  });

  it('opens the dialog from the Interchange card with a new schedule proposed', () => {
    renderEntry('card');
    fireEvent.click(screen.getByRole('button', { name: /Import spreadsheet/ }));
    expect(screen.getByTestId('dialog')).toHaveAttribute('data-target', 'new');
  });

  it('is disabled for a role that cannot write schedules', () => {
    useHasPermission.mockReturnValue(false);
    renderEntry('tile');
    expect(screen.getByRole('button', { name: /Import from Excel or CSV/ })).toBeDisabled();
  });
});
