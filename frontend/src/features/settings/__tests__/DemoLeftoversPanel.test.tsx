// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Settings entry a desktop user has in place of the demo-cleanup command:
// look first, grouped by project and module, and remove only after confirming,
// only the rows that were shown.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

import {
  DemoLeftoversPanel,
  DEMO_LEFTOVERS_REMOVE_URL,
  DEMO_LEFTOVERS_URL,
  groupLeftovers,
  type DemoLeftoversReport,
} from '../DemoLeftoversPanel';

const row = (id: string, project: string, module: string, title: string) => ({
  group: module,
  module,
  table: `oe_${module}`,
  id,
  project_id: project ? `p-${project}` : null,
  project_name: project,
  title,
});

const report: DemoLeftoversReport = {
  real_projects: 2,
  applied: false,
  total: 3,
  groups: { daily_diary: 2, qms_ncrs: 1 },
  rows: [
    row('d1', 'Warehouse Leipzig', 'daily_diary', 'Day shift record for 2026-09-01.'),
    row('d2', 'Warehouse Leipzig', 'daily_diary', 'Day shift record for 2026-09-02.'),
    row('n1', 'Depot Halle', 'qms', 'Honeycombing on column C4'),
  ],
  kept: [{ ...row('k1', 'Depot Halle', 'qms', 'Snag list item'), reason: 'changed after the seed wrote it' }],
  company_rows_kept_reason: '',
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DemoLeftoversPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});
afterEach(cleanup);

describe('DemoLeftoversPanel', () => {
  it('groups rows by project, then module', () => {
    const grouped = groupLeftovers(report.rows);
    expect(grouped.map(([project]) => project)).toEqual(['Depot Halle', 'Warehouse Leipzig']);
    const leipzig = grouped[1]![1];
    expect(leipzig).toHaveLength(1);
    expect(leipzig[0]![0]).toBe('daily_diary');
    expect(leipzig[0]![1].map((r) => r.id)).toEqual(['d1', 'd2']);
  });

  it('removes nothing until the person has looked and confirmed, then only what was shown', async () => {
    apiGet.mockResolvedValue(report);
    apiPost.mockResolvedValue({ ...report, applied: true });
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: /find leftover demo records/i }));
    await waitFor(() => expect(screen.getByTestId('demo-leftovers-preview')).toBeInTheDocument());
    expect(apiGet).toHaveBeenCalledWith(DEMO_LEFTOVERS_URL);
    expect(screen.getByText('Warehouse Leipzig')).toBeInTheDocument();
    expect(screen.getByText('Depot Halle')).toBeInTheDocument();
    expect(screen.getByText(/Snag list item/)).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^remove$/i }));
    expect(apiPost).not.toHaveBeenCalled();
    const buttons = await screen.findAllByRole('button', { name: /^remove$/i });
    fireEvent.click(buttons[buttons.length - 1]!);

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost).toHaveBeenCalledWith(DEMO_LEFTOVERS_REMOVE_URL, { ids: ['d1', 'd2', 'n1'] });
  });

  it('offers no Remove button when nothing was found', async () => {
    apiGet.mockResolvedValue({ ...report, total: 0, rows: [], kept: [] });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /find leftover demo records/i }));
    await waitFor(() => expect(screen.getByTestId('demo-leftovers-preview')).toBeInTheDocument());
    expect(screen.getByText(/No leftover demo records/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^remove$/i })).toBeNull();
  });
});
