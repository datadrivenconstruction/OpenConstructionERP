// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Carry-over in the revision compare drawer:
 *   1. "Carry measurements" posts the project and both revisions.
 *   2. Carried rows awaiting review surface with a count, a per-position
 *      quantity delta, and "Confirm all" sends exactly those ids.
 */

// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PdfCompareDrawer } from '../PdfCompareDrawer';
import { takeoffApi } from '../api';

vi.mock('../api', () => ({
  takeoffApi: {
    compare: vi.fn(),
    createVariation: vi.fn(),
    carryOver: vi.fn(),
    previewCarryOver: vi.fn(),
    confirmCarried: vi.fn(),
  },
}));

const DOCS = [
  { id: 'doc-b', filename: 'rev-b.pdf', pages: 1 },
  { id: 'doc-a', filename: 'rev-a.pdf', pages: 1 },
];

function diff(pending: boolean) {
  return {
    project_id: 'p1',
    from_document_id: 'doc-a',
    to_document_id: 'doc-b',
    measurement_rows: pending
      ? [
          {
            change_type: 'modified',
            measurement_id: 'm-new',
            type: 'distance',
            group_name: 'Walls',
            page: 1,
            label: 'W1',
            old_value: 10,
            new_value: 12,
            measurement_unit: 'm',
            linked_boq_position_id: 'pos-1',
            cost_impact: '100.00',
            cost_currency: 'EUR',
            carry_status: 'needs_review',
            scale_check: 'same',
          },
        ]
      : [],
    summary: {
      measurements: { added: 0, removed: 0, modified: pending ? 1 : 0, unchanged: 0 },
      net_cost_impact: pending ? '100.00' : null,
      cost_currency: pending ? 'EUR' : null,
      from_measurement_count: 1,
      to_measurement_count: pending ? 1 : 0,
      from_measurement_total: 1,
      to_measurement_total: pending ? 1 : 0,
      truncated: false,
      truncation_limit: null,
      carried_needs_review: pending ? 1 : 0,
      position_deltas: pending
        ? [
            {
              position_id: 'pos-1',
              ordinal: '01.001',
              description: 'Wall',
              unit: 'm',
              boq_quantity: '10',
              old_quantity: 10,
              new_quantity: 12,
              delta_quantity: 2,
              cost_impact: '100.00',
              carried_pending: 1,
              measurements: 1,
            },
          ]
        : [],
    },
  };
}

function renderDrawer() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PdfCompareDrawer open onClose={vi.fn()} projectId="p1" documents={DOCS} />
    </QueryClientProvider>,
  );
}

describe('PdfCompareDrawer - carry measurements to a new revision', () => {
  beforeEach(() => vi.clearAllMocks());

  it('carries from the baseline onto the target', async () => {
    takeoffApi.compare.mockResolvedValue(diff(false));
    takeoffApi.carryOver.mockResolvedValue({
      carried: 1,
      carried_ids: ['m-new'],
      already_carried: 0,
      skipped_unreviewed: 0,
      skipped_page_missing: 0,
      scale_checks: { same: 1 },
      revision_link: 'register',
    });
    renderDrawer();
    const btn = await screen.findByTestId('takeoff-carry-over');
    await waitFor(() => expect(btn).not.toBeDisabled());
    fireEvent.click(btn);
    await waitFor(() => expect(takeoffApi.carryOver).toHaveBeenCalledWith('p1', 'doc-a', 'doc-b'));
  });

  it('shows pending copies with the position delta and confirms them', async () => {
    takeoffApi.compare.mockResolvedValue(diff(true));
    takeoffApi.confirmCarried.mockResolvedValue({ confirmed: 1, confirmed_ids: ['m-new'], pushed: 0, not_pending: 0 });
    renderDrawer();
    expect(await screen.findByTestId('takeoff-carry-pending')).toBeInTheDocument();
    const row = await screen.findByTestId('takeoff-position-delta');
    expect(row.textContent).toContain('01.001');
    expect(row.textContent).toContain('+2');
    fireEvent.click(screen.getByTestId('takeoff-carry-confirm-all'));
    await waitFor(() => expect(takeoffApi.confirmCarried).toHaveBeenCalledWith('p1', ['m-new'], false));
  });

  it('previews the page match first, then carries only what the user accepts', async () => {
    takeoffApi.compare.mockResolvedValue(diff(false));
    takeoffApi.previewCarryOver.mockResolvedValue({
      revision_link: 'register',
      pages: [{ old: 1, new: 2, score: 1, method: 'title' }],
      transform: { ok: false },
      items: [
        { measurement_id: 'm-hi', page_old: 1, page_new: 2, confidence: 0.9, band: 'high', points_after: [] },
        { measurement_id: 'm-rev', page_old: 1, page_new: 2, confidence: 0.7, band: 'review', points_after: [] },
      ],
    });
    takeoffApi.carryOver.mockResolvedValue({
      carried: 1,
      carried_ids: ['x'],
      already_carried: 0,
      skipped_unreviewed: 0,
      skipped_page_missing: 0,
      scale_checks: {},
      revision_link: 'register',
    });
    renderDrawer();
    const preview = await screen.findByTestId('takeoff-carry-preview');
    await waitFor(() => expect(preview).not.toBeDisabled());
    fireEvent.click(preview);
    expect(takeoffApi.carryOver).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('takeoff-carry-accept-high'));
    await waitFor(() =>
      expect(takeoffApi.carryOver).toHaveBeenCalledWith('p1', 'doc-a', 'doc-b', {
        align: 'auto',
        pageMap: {},
        measurementIds: ['m-hi'],
      }),
    );
  });
});
