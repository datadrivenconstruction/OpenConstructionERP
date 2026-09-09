// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435. The routes that record where a line of a variation's bill came
// from have existed since the bill shipped, and the bill editor never called
// them, so a line typed in after the bill was opened stayed untraced for as
// long as it existed. This drawer is the control that was missing, and every
// assertion here is on the body that leaves the browser, exactly and not as a
// subset: the server replaces the trace row whole, so a body that dropped the
// change kind would still be accepted with a 200 and record the line as
// added scope it does not add.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { VariationTraceDrawer, buildTracePayload, traceSaysSomething } from './VariationTraceDrawer';
import type { Position } from './api';
import type { VariationBOQTrace } from '@/features/variations/api';

const POSITION = {
  id: 'pos-1',
  boq_id: 'boq-1',
  parent_id: null,
  ordinal: '0010',
  description: 'Bored piles 600mm, omitted at grid F',
  unit: 'm',
  quantity: 40,
  unit_rate: 180,
  total: 7200,
  classification: {},
  source: 'manual',
  confidence: null,
  sort_order: 10,
  validation_status: 'pending',
  metadata: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as unknown as Position;

const CONTRACT_LINE = {
  id: 'cl-1',
  contract_id: 'ct-1',
  parent_line_id: null,
  code: 'C.2.10',
  description: 'Bored piles 600mm',
  scope_section: null,
  line_type: 'work',
  unit: 'm',
  quantity: '40',
  unit_rate: '180.00',
  total_value: '7200.00',
  order_index: 1,
  metadata: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TRACED: VariationBOQTrace = {
  id: 'tr-1',
  variation_request_id: 'vr-1',
  boq_id: 'boq-1',
  position_id: 'pos-1',
  origin: 'contract_line',
  source_boq_id: null,
  source_position_id: null,
  contract_id: 'ct-1',
  contract_line_id: 'cl-1',
  change_kind: 'modified',
  note: 'Re-measured after the ground survey',
  created_at: '2026-01-02T00:00:00Z',
};

function routeGet() {
  api.apiGet.mockImplementation((path: string) => {
    if (path.includes('/contracts/contracts/ct-1/lines')) return Promise.resolve([CONTRACT_LINE]);
    if (path.includes('/contracts/contracts/')) {
      return Promise.resolve({
        items: [{ id: 'ct-1', code: 'MC-01', title: 'Main works', project_id: 'p-1' }],
        total: 1,
        offset: 0,
        limit: 200,
      });
    }
    if (path.includes('/boq/boqs/')) return Promise.resolve([]);
    return Promise.reject(new Error(`no fixture for ${path}`));
  });
}

function renderDrawer(trace: VariationBOQTrace | undefined, opts: { readOnly?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <VariationTraceDrawer
        variationRequestId="vr-1"
        projectId="p-1"
        position={POSITION}
        trace={trace}
        readOnly={opts.readOnly ?? false}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose };
}

const TRACE_PATH = '/v1/variations/variation-requests/vr-1/boq/lines/pos-1/trace';

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPut.mockReset();
  api.apiDelete.mockReset();
  api.apiPut.mockResolvedValue({ ...TRACED, change_kind: 'removed' });
  api.apiDelete.mockResolvedValue({ ...TRACED, contract_line_id: null, contract_id: null, change_kind: 'added', note: '' });
  routeGet();
});

describe('the trace leaves the browser whole', () => {
  it('puts the contract line and the stated kind under the keys the route reads', async () => {
    renderDrawer(undefined);

    fireEvent.click(screen.getByRole('radio', { name: /Removed/ }));
    // The contract list arrives after the first paint; a select changed
    // before its option exists keeps its empty value.
    await screen.findByRole('option', { name: /MC-01/ });
    fireEvent.change(screen.getByLabelText('Where the scope comes from'), {
      target: { value: 'contract:ct-1' },
    });
    fireEvent.click(await screen.findByRole('radio', { name: 'C.2.10 Bored piles 600mm' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save trace' }));

    await waitFor(() => expect(api.apiPut).toHaveBeenCalledTimes(1));
    // Exact: the server replaces the row whole, so every field is stated,
    // the untouched one as null rather than left out.
    expect(api.apiPut).toHaveBeenCalledWith(TRACE_PATH, {
      contract_line_id: 'cl-1',
      source_position_id: null,
      change_kind: 'removed',
      note: '',
    });
  });

  it('opens on the stored trace and sends it back unchanged when only the note is edited', async () => {
    const { onClose } = renderDrawer(TRACED);

    expect(screen.getByRole('radio', { name: /Modified/ })).toBeChecked();
    expect(screen.getByTestId('variation-trace-current').textContent).toMatch(/Traced to a contract line as modified/);

    fireEvent.change(screen.getByLabelText('Note'), {
      target: { value: 'Re-measured twice' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save trace' }));

    await waitFor(() => expect(api.apiPut).toHaveBeenCalledTimes(1));
    expect(api.apiPut).toHaveBeenCalledWith(TRACE_PATH, {
      contract_line_id: 'cl-1',
      source_position_id: null,
      change_kind: 'modified',
      note: 'Re-measured twice',
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('clears a trace through the delete route and offers no clear on a line that says nothing', async () => {
    renderDrawer(TRACED);

    fireEvent.click(screen.getByRole('button', { name: 'Clear trace' }));

    await waitFor(() => expect(api.apiDelete).toHaveBeenCalledTimes(1));
    expect(api.apiDelete).toHaveBeenCalledWith(TRACE_PATH);
    expect(api.apiPut).not.toHaveBeenCalled();
  });

  it('has nothing to clear on an untraced line', () => {
    renderDrawer(undefined);

    expect(screen.queryByRole('button', { name: 'Clear trace' })).toBeNull();
    expect(screen.getByTestId('variation-trace-current').textContent).toMatch(/Untraced/);
  });

  it('is read only on a locked bill', () => {
    renderDrawer(TRACED, { readOnly: true });

    expect(screen.getByRole('button', { name: 'Save trace' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear trace' })).toBeDisabled();
  });
});

describe('the contradictions the bill would report are said before the save', () => {
  it('warns that a removed line with a positive quantity comes off as a negative one, and still lets it save', async () => {
    renderDrawer(undefined);

    expect(screen.queryByTestId('variation-trace-contradictions')).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: /Removed/ }));

    const warnings = screen.getByTestId('variation-trace-contradictions').textContent ?? '';
    expect(warnings).toMatch(/quantity is positive/);
    // No contract line picked yet either, and that is the second thing said.
    expect(warnings).toMatch(/needs the contract line/);
    expect(screen.getByRole('button', { name: 'Save trace' })).not.toBeDisabled();
  });

  it('says nothing about an added line with a positive quantity', () => {
    renderDrawer(undefined);

    expect(screen.getByRole('radio', { name: /Added/ })).toBeChecked();
    expect(screen.queryByTestId('variation-trace-contradictions')).toBeNull();
  });
});

describe('buildTracePayload', () => {
  it('drops a row picked under the other source kind so the body never names both', () => {
    expect(
      buildTracePayload({ sourceKind: 'boq', selectedRowId: 'src-1', changeKind: 'added', note: '' }),
    ).toEqual({ contract_line_id: null, source_position_id: 'src-1', change_kind: 'added', note: '' });
    expect(
      buildTracePayload({ sourceKind: 'contract', selectedRowId: 'cl-1', changeKind: 'removed', note: 'x' }),
    ).toEqual({ contract_line_id: 'cl-1', source_position_id: null, change_kind: 'removed', note: 'x' });
    expect(
      buildTracePayload({ sourceKind: '', selectedRowId: '', changeKind: 'modified', note: '' }),
    ).toEqual({ contract_line_id: null, source_position_id: null, change_kind: 'modified', note: '' });
  });

  it('knows a manual added row with no note says nothing worth clearing', () => {
    expect(traceSaysSomething(undefined)).toBe(false);
    expect(
      traceSaysSomething({ ...TRACED, contract_id: null, contract_line_id: null, change_kind: 'added', note: '' }),
    ).toBe(false);
    expect(traceSaysSomething({ ...TRACED, contract_id: null, contract_line_id: null, note: '' })).toBe(true);
    expect(traceSaysSomething(TRACED)).toBe(true);
  });
});
