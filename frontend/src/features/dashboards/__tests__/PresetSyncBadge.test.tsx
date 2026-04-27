// @ts-nocheck
/**
 * Tests for PresetSyncBadge (T09 / task #192).
 *
 * Covers:
 *   - renders with the variant matching the supplied initialStatus
 *   - clicking the badge opens the SyncReportDrawer
 *   - non-interactive mode swallows the click (drawer never opens)
 *   - falls back to the fetched report's status when initialStatus
 *     is omitted
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
    getSyncReport: vi.fn(),
    applySyncHeal: vi.fn(),
  };
});

import { getSyncReport } from '../api';
import { PresetSyncBadge } from '../PresetSyncBadge';

const sampleReport = {
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
      column: 'ghost_column',
      new_column: null,
      dropped_values: [],
      old_dtype: null,
      new_dtype: null,
      message_key: 'preset.sync.dropped_column',
      message: "Column 'ghost_column' is no longer present.",
    },
  ],
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
  (getSyncReport as ReturnType<typeof vi.fn>).mockReset();
  (getSyncReport as ReturnType<typeof vi.fn>).mockResolvedValue(sampleReport);
});

afterEach(() => {
  cleanup();
});

describe('PresetSyncBadge', () => {
  it('renders with the supplied initialStatus', () => {
    render(
      withQueryClient(
        <PresetSyncBadge presetId="p-1" initialStatus="stale" />,
      ),
    );
    const badge = screen.getByTestId('preset-sync-badge-p-1');
    expect(badge).toHaveAttribute('data-status', 'stale');
  });

  it('clicking the badge opens the SyncReportDrawer', async () => {
    render(
      withQueryClient(
        <PresetSyncBadge presetId="p-1" initialStatus="needs_review" />,
      ),
    );

    fireEvent.click(screen.getByTestId('preset-sync-badge-p-1'));

    await waitFor(() => {
      expect(screen.getByTestId('sync-report-drawer')).toBeInTheDocument();
    });
  });

  it('non-interactive mode disables the click', () => {
    render(
      withQueryClient(
        <PresetSyncBadge
          presetId="p-1"
          initialStatus="stale"
          interactive={false}
        />,
      ),
    );
    const badge = screen.getByTestId('preset-sync-badge-p-1');
    expect(badge).toBeDisabled();

    fireEvent.click(badge);
    expect(screen.queryByTestId('sync-report-drawer')).not.toBeInTheDocument();
  });

  it('uses fetched report status when initialStatus is omitted', async () => {
    render(
      withQueryClient(<PresetSyncBadge presetId="p-1" />),
    );

    await waitFor(() => {
      expect(getSyncReport).toHaveBeenCalledWith('p-1');
    });

    await waitFor(() => {
      const badge = screen.getByTestId('preset-sync-badge-p-1');
      expect(badge).toHaveAttribute('data-status', 'needs_review');
    });
  });
});
