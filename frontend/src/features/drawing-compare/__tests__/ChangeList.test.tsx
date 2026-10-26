// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The change list of a stored compare: filters, triage, follow-ups and the
 * re-measure dry run the user confirms before anything is flagged. The
 * network is stubbed at the shared api helpers.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn() };
});

import { apiDelete, apiPatch, apiPost } from '@/shared/lib/api';
import { ChangeList, filterChanges } from '../components/ChangeList';
import type { Comparison, DrawingChange } from '../api';

function change(seq: number, over: Partial<DrawingChange> = {}): DrawingChange {
  return {
    id: `ch-${seq}`,
    comparison_id: 'cmp-1',
    seq,
    kind: 'modified',
    page: 1,
    x: 10,
    y: 10,
    w: 20,
    h: 20,
    score: 100,
    old_text: null,
    new_text: null,
    layer: null,
    entity_type: null,
    details: {},
    thumbnail: null,
    status: 'open',
    comment: null,
    rfi_id: null,
    markup_id: null,
    flagged_at: null,
    flagged_measurement_ids: [],
    flagged_annotation_ids: [],
    flagged_position_ids: [],
    reviewed_by: null,
    updated_at: '2026-10-25T10:00:00Z',
    ...over,
  };
}

function comparison(changes: DrawingChange[]): Comparison {
  return {
    id: 'cmp-1',
    project_id: 'p-1',
    name: 'A-101 C / B',
    source_kind: 'pdf',
    old_ref_id: 'a',
    new_ref_id: 'b',
    old_page: 1,
    new_page: 1,
    old_label: 'A-101 B.pdf',
    new_label: 'A-101 C.pdf',
    old_revision: 'B',
    new_revision: 'C',
    page_width: 1000,
    page_height: 700,
    alignment: { method: 'auto', matrix: [1, 0, 0, 1, 0, 0], confidence: 0.9 },
    settings: {},
    summary: { total: changes.length },
    created_by: 'u',
    created_at: '2026-10-25T10:00:00Z',
    updated_at: '2026-10-25T10:00:00Z',
    changes,
  };
}

function renderList(changes: DrawingChange[], canWrite = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSelect = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ChangeList comparison={comparison(changes)} selectedId={null} onSelect={onSelect} canWrite={canWrite} />
    </QueryClientProvider>,
  );
  return { onSelect };
}

describe('ChangeList', () => {
  beforeEach(() => vi.clearAllMocks());

  it('filters by status', () => {
    const rows = [change(1), change(2, { status: 'relevant' }), change(3, { status: 'not_relevant' })];
    expect(filterChanges(rows, 'all')).toHaveLength(3);
    expect(filterChanges(rows, 'relevant').map((c) => c.seq)).toEqual([2]);
    renderList(rows);
    fireEvent.click(screen.getByRole('tab', { name: /Not relevant/ }));
    expect(screen.queryByTestId('drawing-compare-change-1')).toBeNull();
    expect(screen.getByTestId('drawing-compare-change-3')).toBeTruthy();
  });

  it('shows the empty state when the revisions match', () => {
    renderList([]);
    expect(screen.getByText('No changes found')).toBeTruthy();
  });

  it('shows a changed value old and new', () => {
    renderList([change(1, { kind: 'text', old_text: '3200', new_text: '3400' })]);
    expect(screen.getByText('3200')).toBeTruthy();
    expect(screen.getByText('3400')).toBeTruthy();
  });

  it('triages, comments and raises an RFI and a cloud', async () => {
    (apiPatch as ReturnType<typeof vi.fn>).mockResolvedValue(change(1, { status: 'relevant' }));
    (apiPost as ReturnType<typeof vi.fn>).mockResolvedValue({ target_id: 'r-1', label: 'RFI-001', change: change(1) });
    renderList([change(1)]);
    fireEvent.click(screen.getByRole('button', { name: /^Relevant$/ }));
    await waitFor(() => expect(apiPatch).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1', { status: 'relevant' }));
    const box = screen.getByPlaceholderText('Comment for the team');
    fireEvent.change(box, { target: { value: 'Stair moved 300 mm' } });
    fireEvent.blur(box);
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1', { comment: 'Stair moved 300 mm' }),
    );
    fireEvent.click(screen.getByRole('button', { name: /RFI/ }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1/rfi/', {}));
    fireEvent.click(screen.getByRole('button', { name: /Cloud/ }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1/markup/', {}));
  });

  it('runs a dry run first and flags only after confirmation', async () => {
    const preview = {
      change_id: 'ch-1',
      dry_run: true,
      items: [{ id: 'm-1', source: 'takeoff', document_id: 'b', page: 1, label: 'Wall W1', revision: 'new', linked_boq_position_id: 'p-1' }],
      positions: [{ id: 'p-1', ordinal: '01.001', description: 'Partition wall' }],
      flagged_at: null,
    };
    (apiPost as ReturnType<typeof vi.fn>).mockResolvedValue(preview);
    renderList([change(1)]);
    fireEvent.click(screen.getByRole('button', { name: /Re-measure/ }));
    await screen.findByText('Wall W1');
    expect(screen.getByText('Partition wall')).toBeTruthy();
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1/remeasure/?dry_run=true', {});
    fireEvent.click(screen.getByTestId('drawing-compare-remeasure-confirm'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1/remeasure/?dry_run=false', {}),
    );
  });

  it('offers to lift flags once re-measured', async () => {
    (apiDelete as ReturnType<typeof vi.fn>).mockResolvedValue(change(1));
    renderList([change(1, { flagged_at: '2026-10-25T11:00:00Z', flagged_measurement_ids: ['m-1'], flagged_position_ids: ['p-1'] })]);
    expect(screen.getByText(/1 quantities and 1 BOQ positions flagged/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Re-measured/ }));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/v1/drawing-compare/changes/ch-1/remeasure/'));
  });

  it('hides every action from a reader without write access', () => {
    renderList([change(1, { comment: 'Checked on site' })], false);
    expect(screen.queryByRole('button', { name: /RFI/ })).toBeNull();
    expect(screen.getByText('Checked on site')).toBeTruthy();
  });
});
