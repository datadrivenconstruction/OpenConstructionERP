// @ts-nocheck
/**
 * Tests for SnapshotDiffView (T11).
 *
 * Covers:
 *   - rendering the summary chips with the right counts
 *   - rendering the added / removed / changed column lists
 *   - the "snapshots are identical" empty-state when the diff is empty
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    diffSnapshots: vi.fn(),
  };
});

import { diffSnapshots } from '../api';
import { SnapshotDiffView } from '../SnapshotDiffView';

const A_ID = 'snap-A';
const B_ID = 'snap-B';

const DIFF_WITH_CHANGES = {
  snapshot_a_id: A_ID,
  snapshot_b_id: B_ID,
  a_label: 'Baseline',
  b_label: 'After remodel',
  a_created_at: '2026-04-01T00:00:00Z',
  b_created_at: '2026-04-27T00:00:00Z',
  columns_added: ['fire_rating', 'thermal_resistance'],
  columns_removed: ['legacy_id'],
  columns_changed: [
    { name: 'thickness_mm', a_dtype: 'object', b_dtype: 'float64' },
  ],
  a_row_count: 100,
  b_row_count: 130,
  rows_added: 30,
  rows_removed: 0,
  schema_hash_match: false,
  is_identical: false,
};

const IDENTICAL_DIFF = {
  snapshot_a_id: A_ID,
  snapshot_b_id: B_ID,
  a_label: 'Day 1',
  b_label: 'Day 2',
  a_created_at: '2026-04-26T00:00:00Z',
  b_created_at: '2026-04-27T00:00:00Z',
  columns_added: [],
  columns_removed: [],
  columns_changed: [],
  a_row_count: 50,
  b_row_count: 50,
  rows_added: 0,
  rows_removed: 0,
  schema_hash_match: true,
  is_identical: true,
};

beforeEach(() => {
  (diffSnapshots as ReturnType<typeof vi.fn>).mockReset();
});

afterEach(() => {
  cleanup();
});

function renderDiff() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SnapshotDiffView snapshotAId={A_ID} snapshotBId={B_ID} />
    </QueryClientProvider>,
  );
}

describe('SnapshotDiffView', () => {
  it('renders summary chips with rows added and columns changed counts', async () => {
    (diffSnapshots as ReturnType<typeof vi.fn>).mockResolvedValue(
      DIFF_WITH_CHANGES,
    );
    renderDiff();

    await waitFor(() =>
      expect(diffSnapshots).toHaveBeenCalledWith({ a: A_ID, b: B_ID }),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId('snapshot-diff-summary-rows-added').textContent,
      ).toContain('30');
      expect(
        screen.getByTestId('snapshot-diff-summary-rows-removed').textContent,
      ).toContain('0');
      expect(
        screen.getByTestId('snapshot-diff-summary-cols-changed').textContent,
      ).toContain('1');
    });
  });

  it('renders one row per added / removed / changed column', async () => {
    (diffSnapshots as ReturnType<typeof vi.fn>).mockResolvedValue(
      DIFF_WITH_CHANGES,
    );
    renderDiff();

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-diff-added')).toBeInTheDocument(),
    );

    expect(
      screen.getByTestId('snapshot-diff-added-fire_rating'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('snapshot-diff-added-thermal_resistance'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('snapshot-diff-removed-legacy_id'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('snapshot-diff-changed-thickness_mm'),
    ).toBeInTheDocument();

    // Both labels must be visible in the header.
    expect(screen.getByTestId('snapshot-diff-a-label').textContent).toContain(
      'Baseline',
    );
    expect(screen.getByTestId('snapshot-diff-b-label').textContent).toContain(
      'After remodel',
    );
  });

  it('renders the identical-state when the diff reports no changes', async () => {
    (diffSnapshots as ReturnType<typeof vi.fn>).mockResolvedValue(
      IDENTICAL_DIFF,
    );
    renderDiff();

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-diff-identical')).toBeInTheDocument(),
    );

    // No column lists when there are no changes.
    expect(screen.queryByTestId('snapshot-diff-added')).not.toBeInTheDocument();
    expect(screen.queryByTestId('snapshot-diff-removed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('snapshot-diff-changed')).not.toBeInTheDocument();
  });

  it('renders the error banner when the diff API call fails', async () => {
    (diffSnapshots as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('nope'),
    );
    renderDiff();
    await waitFor(() =>
      expect(screen.getByTestId('snapshot-diff-error')).toBeInTheDocument(),
    );
  });
});
