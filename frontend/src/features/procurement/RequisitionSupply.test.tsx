// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Suggested supplier and needed-by date of a requisition line (issue #516).
//
// A single suggestion from the lines can be adopted with one click and is
// never applied by itself; several suggestions are only named. Picking a
// schedule activity clears the old date so the server proposes a new one, and
// a moved activity is reported without touching the date. The pure helpers
// keep the BOQ's suggestion through a buy-list handoff, an edit and a merge.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));

import { apiGet } from '@/shared/lib/api';
import { LineSupplyCell, SuggestedSupplierHint } from './RequisitionSupply';
import {
  buildRequisitionLinesFromBuyList,
  daysBetween,
  lineToInput,
  mergeRequisitionLines,
  type Requisition,
  type RequisitionLine,
  type RequisitionLineIn,
} from './requisitionsApi';

const mockGet = vi.mocked(apiGet);
const V1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const V2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const ACT = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const P1 = '11111111-1111-4111-8111-111111111111';

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function req(over: Partial<Requisition> = {}): Requisition {
  return {
    id: 'r1',
    project_id: 'p1',
    req_number: 'MR-0001',
    status: 'draft',
    title: null,
    required_date: null,
    notes: null,
    requester_id: null,
    po_id: null,
    items: [],
    reconciliation: {},
    history: [],
    created_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T00:00:00Z',
    ...over,
  };
}

function stored(over: Partial<RequisitionLine> = {}): RequisitionLine {
  return {
    id: 'l1',
    description: 'Concrete',
    unit: 'm3',
    quantity_requested: '10',
    quantity_ordered: '0',
    quantity_received: '0',
    quantity_consumed: '0',
    quantity_outstanding: '10',
    catalog_item_id: null,
    cost_line_id: null,
    sort_order: 0,
    sources: [],
    ...over,
  };
}

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes('schedule-activities')
        ? {
            items: [
              { id: ACT, name: 'Pour slab', schedule_name: 'Master', start_date: '2026-11-10', end_date: null, activity_type: 'task' },
            ],
            total: 1,
            offset: 0,
            limit: 1000,
          }
        : {
            items: [
              { id: V1, code: 'V-1', name: 'Beton Nord', status: 'active' },
              { id: V2, code: 'V-2', name: 'Kies Sued', status: 'active' },
            ],
            total: 2,
            offset: 0,
            limit: 200,
          },
    ) as never,
  );
});

describe('SuggestedSupplierHint', () => {
  it('offers one suggestion to adopt and applies nothing by itself', async () => {
    const onUse = vi.fn();
    wrap(
      <SuggestedSupplierHint
        req={req({ suggested_vendors: [{ id: V1, name: 'Beton Nord', status: 'active' }] })}
        vendorId=""
        editable
        onUse={onUse}
      />,
    );
    expect(onUse).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Use this supplier' }));
    expect(onUse).toHaveBeenCalledWith(V1);
  });

  it('only names several suggestions and offers no button', () => {
    wrap(
      <SuggestedSupplierHint
        req={req({
          suggested_vendors: [
            { id: V1, name: 'Beton Nord', status: 'active' },
            { id: V2, name: 'Kies Sued', status: 'active' },
          ],
        })}
        vendorId=""
        editable
        onUse={() => {}}
      />,
    );
    expect(screen.getByText(/different suppliers/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('LineSupplyCell', () => {
  it('shows the disagreeing BOQ suggestions on a line', () => {
    const line: RequisitionLineIn = { description: 'Concrete', unit: 'm3', quantity_requested: '10', sources: [] };
    wrap(
      <LineSupplyCell
        projectId="p1"
        line={line}
        stored={stored({
          suggestion_conflict: true,
          source_suggested_vendors: [
            { id: V1, name: 'Beton Nord', status: 'active' },
            { id: V2, name: 'Kies Sued', status: 'active' },
          ],
        })}
        headerDate="2026-11-20"
        editable
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/The BOQ suggests: Beton Nord/)).toBeInTheDocument();
    expect(screen.getByText(/Uses the requisition date/)).toBeInTheDocument();
  });

  it('clears the old date and anchor when an activity is picked', async () => {
    const onChange = vi.fn();
    const line: RequisitionLineIn = {
      description: 'Concrete',
      unit: 'm3',
      quantity_requested: '10',
      required_date: '2026-11-01',
      sources: [],
    };
    wrap(<LineSupplyCell projectId="p1" line={line} headerDate="" editable onChange={onChange} />);
    const select = screen.getByRole('combobox', { name: /From schedule activity/ });
    await screen.findByRole('option', { name: /Pour slab/ });
    await userEvent.selectOptions(select, ACT);
    expect(onChange).toHaveBeenCalledWith({
      schedule_activity_id: ACT,
      schedule_buffer_days: 0,
      required_date: null,
      schedule_anchor_date: null,
    });
  });

  it('reports a moved activity and keeps the agreed date', () => {
    wrap(
      <LineSupplyCell
        projectId="p1"
        line={{ description: 'Concrete', unit: 'm3', quantity_requested: '10', sources: [] }}
        stored={stored({
          required_date: '2026-11-07',
          effective_required_date: '2026-11-07',
          required_date_source: 'schedule',
          schedule_activity_id: ACT,
          schedule_activity_name: 'Pour slab',
          schedule_buffer_days: 3,
          schedule_anchor_date: '2026-11-10',
          schedule_activity_start: '2026-11-17',
          schedule_moved: true,
        })}
        headerDate=""
        editable={false}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/now starts 2026-11-17 \(\+7 days\)/)).toBeInTheDocument();
    expect(screen.getByText(/3 days before Pour slab/)).toBeInTheDocument();
  });
});

describe('suggested supplier through the helpers', () => {
  it('carries the BOQ suggestion of each buy-list source', () => {
    const [line] = buildRequisitionLinesFromBuyList(
      [
        {
          name: 'Concrete',
          unit: 'm3',
          sources: [{ position_id: P1, resource_key: '0:C30', quantity: '5', unit: 'm3', suggested_vendor_id: V1 }],
        },
      ],
      { combineUncoded: false },
    );
    expect(line!.sources[0]!.suggested_vendor_id).toBe(V1);
    expect('suggested_vendor_id' in line!).toBe(false);
  });

  it('keeps the suggestion and the line date when a stored line is edited', () => {
    const input = lineToInput(
      stored({
        suggested_vendor_id: V2,
        required_date: '2026-11-07',
        schedule_activity_id: ACT,
        schedule_buffer_days: 3,
        schedule_anchor_date: '2026-11-10',
        sources: [
          { id: 's1', boq_position_id: P1, resource_key: '0:C30', quantity: '5', unit: 'm3', cost_line_id: null, suggested_vendor_id: V1 },
        ],
      }),
    );
    expect(input).toMatchObject({
      suggested_vendor_id: V2,
      required_date: '2026-11-07',
      schedule_activity_id: ACT,
      schedule_buffer_days: 3,
      schedule_anchor_date: '2026-11-10',
    });
    expect(input.sources[0]!.suggested_vendor_id).toBe(V1);
  });

  it('drops a suggestion the merged lines do not share', () => {
    const a: RequisitionLineIn = { description: 'Sand', unit: 't', quantity_requested: '1', suggested_vendor_id: V1, sources: [] };
    const b: RequisitionLineIn = { ...a, suggested_vendor_id: V2 };
    const c: RequisitionLineIn = { ...a };
    const ab = mergeRequisitionLines([a, b], [0, 1]);
    expect(ab.ok && ab.lines[0]!.suggested_vendor_id).toBeNull();
    const ac = mergeRequisitionLines([a, c], [0, 1]);
    expect(ac.ok && ac.lines[0]!.suggested_vendor_id).toBe(V1);
  });

  it('counts days between two dates', () => {
    expect(daysBetween('2026-11-10', '2026-11-17')).toBe(7);
    expect(daysBetween('2026-11-10', null)).toBeNull();
  });
});
