// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435. The bill view splits the direct cost of a variation's bill by
// what each line does to the contract - added, removed, modified - with the
// net as their sum. The pricing card on the request is where a quantity
// surveyor reads that, and a card that showed only the grand total would
// keep the omission invisible: a bill that adds 2,000 and omits 12,000 reads
// as "-10,000" with nothing to say which part is the omission.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { DetailDrawer } from './VariationsPage';
import type { VariationBOQ, VariationRequest } from './api';

const REQUEST: VariationRequest = {
  id: 'vr-1',
  project_id: 'p-1',
  notice_id: null,
  code: 'VR-001',
  title: 'Omit the piles at grid F, add temporary propping',
  description: '',
  requested_by: null,
  requested_at: null,
  classification: 'scope_change',
  urgency: 'med',
  estimated_cost_impact: '-9000.00',
  estimated_schedule_days: 0,
  currency: 'EUR',
  status: 'draft',
  submitted_at: null,
  decision_at: null,
  decision_notes: '',
  decided_by: null,
  submitted_boq_id: null,
  submitted_boq_total: null,
  submitted_boq_snapshot_id: null,
  agreed_cost_impact: null,
  agreed_basis: '',
  agreed_variance_note: '',
  metadata: {},
  created_at: '2026-08-19T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
};

const BILL: VariationBOQ = {
  variation_request_id: 'vr-1',
  has_boq: true,
  boq_id: 'boq-1',
  name: 'VR-001 - Omit the piles at grid F',
  status: 'draft',
  is_locked: false,
  parent_estimate_id: null,
  position_count: 3,
  base_currency: 'EUR',
  direct_cost: '-9000.00',
  markups_total: '0.00',
  grand_total: '-9000.00',
  is_mixed_currency: false,
  estimated_cost_impact: '-9000.00',
  estimate_matches_boq: true,
  traces: [],
  change_summary: {
    added: { line_count: 1, total: '2000.00' },
    removed: { line_count: 1, total: '-12000.00' },
    modified: { line_count: 1, total: '1000.00' },
    net_total: '-9000.00',
  },
  checks: [],
};

function routeGet(bill: VariationBOQ) {
  api.apiGet.mockImplementation((path: string) => {
    if (path.includes('/variations/variation-requests/vr-1/boq/')) return Promise.resolve(bill);
    if (path.includes('/contracts/contracts/')) {
      return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    }
    if (path.includes('/boq/boqs/')) return Promise.resolve([]);
    return Promise.reject(new Error(`no fixture for ${path}`));
  });
}

function renderRequest() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DetailDrawer
        selected={{ kind: 'requests', id: REQUEST.id }}
        projectId="p-1"
        notices={[]}
        requests={[REQUEST]}
        orders={[]}
        daywork={[]}
        eot={[]}
        currency="EUR"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.apiGet.mockReset();
});

describe('the pricing card splits the bill by what each line does to the contract', () => {
  it('shows the three subtotals with their line counts and the net as their sum', async () => {
    routeGet(BILL);
    renderRequest();

    const summary = await screen.findByTestId('variation-change-summary');
    const text = summary.textContent ?? '';

    expect(text).toContain('Added · 1');
    expect(text).toContain('Removed · 1');
    expect(text).toContain('Modified · 1');
    expect(text).toContain('Net change');
    // The omission is visible as its own negative figure, not folded into
    // the total. The currency sign sits between the minus and the digits
    // ("-€12,000.00") and digit-group separators differ by locale, so match
    // the sign and the digits and let the formatter own the rest.
    expect(within(summary).getAllByText(/-\s?\D{0,3}12[.,\u00a0\u202f ]?000/).length).toBeGreaterThan(0);
    expect(within(summary).getAllByText(/-\s?\D{0,3}9[.,\u00a0\u202f ]?000/).length).toBeGreaterThan(0);
    expect(within(summary).getAllByText(/2[.,\u00a0\u202f ]?000/).length).toBeGreaterThan(0);
  });

  it('shows no split for a bill the server did not split', async () => {
    routeGet({ ...BILL, change_summary: null });
    renderRequest();

    await screen.findByText('Priced total');
    expect(screen.queryByTestId('variation-change-summary')).toBeNull();
  });
});
