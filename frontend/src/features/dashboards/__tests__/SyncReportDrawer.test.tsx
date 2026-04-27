// @ts-nocheck
/**
 * Tests for SyncReportDrawer (T09 / task #192).
 *
 * Covers:
 *   - "in sync" report renders the success banner, no issue groups
 *   - dropped columns render with error styling and the column name
 *   - clicking Auto-heal calls applySyncHeal
 *   - Auto-heal is disabled when no auto-fixable issues exist
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    applySyncHeal: vi.fn(),
  };
});

import { applySyncHeal } from '../api';
import { SyncReportDrawer } from '../SyncReportDrawer';

const inSyncReport = {
  preset_id: 'p-1',
  snapshot_id: 'snap-1',
  status: 'synced',
  is_in_sync: true,
  column_renames: [],
  dropped_columns: [],
  dropped_filter_values: [],
  dtype_changes: [],
};

const droppedColumnReport = {
  preset_id: 'p-1',
  snapshot_id: 'snap-1',
  status: 'needs_review',
  is_in_sync: false,
  column_renames: [],
  dropped_columns: [
    {
      kind: 'dropped_column',
      severity: 'error',
      suggested_fix: 'manual',
      column: 'ghost_col',
      new_column: null,
      dropped_values: [],
      old_dtype: null,
      new_dtype: null,
      message_key: 'preset.sync.dropped_column',
      message: 'Column ghost_col was dropped.',
    },
  ],
  dropped_filter_values: [],
  dtype_changes: [],
};

const renameReport = {
  preset_id: 'p-1',
  snapshot_id: 'snap-1',
  status: 'stale',
  is_in_sync: false,
  column_renames: [
    {
      kind: 'column_rename',
      severity: 'warning',
      suggested_fix: 'auto_rename',
      column: 'qty',
      new_column: 'quantity',
      dropped_values: [],
      old_dtype: 'numeric',
      new_dtype: 'numeric',
      message_key: 'preset.sync.column_rename',
      message: "Column 'qty' renamed to 'quantity'.",
    },
  ],
  dropped_columns: [],
  dropped_filter_values: [],
  dtype_changes: [],
};

function withQueryClient(child: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{child}</QueryClientProvider>;
}

beforeEach(() => {
  (applySyncHeal as ReturnType<typeof vi.fn>).mockReset();
  (applySyncHeal as ReturnType<typeof vi.fn>).mockResolvedValue({
    preset: {},
    report: inSyncReport,
  });
});

afterEach(() => {
  cleanup();
});

describe('SyncReportDrawer', () => {
  it('renders the in-sync success banner when report is in sync', () => {
    render(
      withQueryClient(
        <SyncReportDrawer
          presetId="p-1"
          report={inSyncReport}
          isLoading={false}
          onClose={() => {}}
        />,
      ),
    );
    expect(screen.getByTestId('sync-report-in-sync')).toBeInTheDocument();
    expect(
      screen.queryByTestId('sync-issue-group-dropped-columns'),
    ).not.toBeInTheDocument();
  });

  it('renders dropped column issues with the column name', () => {
    render(
      withQueryClient(
        <SyncReportDrawer
          presetId="p-1"
          report={droppedColumnReport}
          isLoading={false}
          onClose={() => {}}
        />,
      ),
    );
    expect(
      screen.getByTestId('sync-issue-group-dropped-columns'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('sync-issue-dropped_column-ghost_col'),
    ).toHaveTextContent('ghost_col');
  });

  it('clicking Auto-heal calls applySyncHeal', async () => {
    render(
      withQueryClient(
        <SyncReportDrawer
          presetId="p-1"
          report={renameReport}
          isLoading={false}
          onClose={() => {}}
        />,
      ),
    );

    const button = screen.getByTestId('sync-report-auto-heal');
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(applySyncHeal).toHaveBeenCalledWith('p-1');
    });
  });

  it('Auto-heal is disabled when only manual issues remain', () => {
    render(
      withQueryClient(
        <SyncReportDrawer
          presetId="p-1"
          report={droppedColumnReport}
          isLoading={false}
          onClose={() => {}}
        />,
      ),
    );

    const button = screen.getByTestId('sync-report-auto-heal');
    expect(button).toBeDisabled();
  });
});
