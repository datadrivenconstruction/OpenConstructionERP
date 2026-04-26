// @ts-nocheck
/**
 * Tests for DataTable (T06).
 *
 * Covers:
 *   - renders columns + rows from getSnapshotRows response
 *   - clicking a column header issues a re-fetch with order_by
 *   - second click on the same column flips the direction (asc → desc)
 *   - empty state appears when total = 0
 *   - pagination Next button advances offset
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
    getSnapshotRows: vi.fn(),
  };
});

import { getSnapshotRows } from '../api';
import { DataTable } from '../DataTable';

function withQueryClient(child: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{child}</QueryClientProvider>;
}

const baseRows = {
  snapshot_id: 's1',
  columns: ['category', 'thickness_mm'],
  rows: [
    { category: 'wall', thickness_mm: 240 },
    { category: 'wall', thickness_mm: 180 },
    { category: 'door', thickness_mm: 45 },
  ],
  total: 3,
  limit: 50,
  offset: 0,
};

beforeEach(() => {
  (getSnapshotRows as ReturnType<typeof vi.fn>).mockReset();
  (getSnapshotRows as ReturnType<typeof vi.fn>).mockResolvedValue(baseRows);
});

afterEach(() => {
  cleanup();
});

describe('DataTable', () => {
  it('renders the column headers and row cells', async () => {
    render(withQueryClient(<DataTable snapshotId="s1" />));

    await waitFor(() => {
      expect(screen.getByTestId('data-table-header-category')).toBeInTheDocument();
    });
    expect(screen.getByTestId('data-table-row-0')).toHaveTextContent('wall');
    expect(screen.getByTestId('data-table-row-2')).toHaveTextContent('door');
  });

  it('clicking a header issues a sorted query (asc first, then desc)', async () => {
    render(withQueryClient(<DataTable snapshotId="s1" />));

    await waitFor(() => {
      expect(screen.getByTestId('data-table-header-thickness_mm')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('data-table-header-thickness_mm'));
    await waitFor(() => {
      const calls = (getSnapshotRows as ReturnType<typeof vi.fn>).mock.calls;
      const last = calls[calls.length - 1];
      expect(last?.[1]?.orderBy).toBe('thickness_mm:asc');
    });

    fireEvent.click(screen.getByTestId('data-table-header-thickness_mm'));
    await waitFor(() => {
      const calls = (getSnapshotRows as ReturnType<typeof vi.fn>).mock.calls;
      const last = calls[calls.length - 1];
      expect(last?.[1]?.orderBy).toBe('thickness_mm:desc');
    });
  });

  it('shows the empty state when total is zero', async () => {
    (getSnapshotRows as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseRows,
      rows: [],
      total: 0,
    });
    render(withQueryClient(<DataTable snapshotId="s1" />));

    await waitFor(() => {
      expect(screen.getByTestId('data-table-empty')).toBeInTheDocument();
    });
  });

  it('Next button advances the page offset', async () => {
    (getSnapshotRows as ReturnType<typeof vi.fn>).mockImplementation(
      async (_id, opts) => ({
        ...baseRows,
        rows: baseRows.rows,
        total: 100,
        offset: opts?.offset ?? 0,
        limit: opts?.limit ?? 50,
      }),
    );

    render(withQueryClient(<DataTable snapshotId="s1" pageSize={10} />));

    // Wait for initial load.
    await waitFor(() => {
      expect(screen.getByTestId('data-table-header-category')).toBeInTheDocument();
    });
    expect(screen.getByTestId('data-table-page')).toHaveTextContent('1 / 10');

    fireEvent.click(screen.getByTestId('data-table-next'));

    await waitFor(() => {
      const calls = (getSnapshotRows as ReturnType<typeof vi.fn>).mock.calls;
      const last = calls[calls.length - 1];
      expect(last?.[1]?.offset).toBe(10);
    });
  });

  it('forwards columns + filters to the API call', async () => {
    render(
      withQueryClient(
        <DataTable
          snapshotId="s1"
          columns={['category']}
          filters={{ category: ['wall'] }}
        />,
      ),
    );

    await waitFor(() => {
      const calls = (getSnapshotRows as ReturnType<typeof vi.fn>).mock.calls;
      const last = calls[calls.length - 1];
      expect(last?.[1]?.columns).toEqual(['category']);
      expect(last?.[1]?.filters).toEqual({ category: ['wall'] });
    });
  });
});
