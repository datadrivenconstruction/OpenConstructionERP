// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435. Three fields the API has accepted for months and the screen
// never sent: the negotiated amount on an approval, the sources a variation
// bill is seeded from, and the contract a promoted order amends. Each was
// built, tested and shipped on the backend, and in each case the browser
// posted a body without the field, so the feature existed and was unreachable.
//
// Every assertion here is on the body that leaves the browser, and on the
// exact body rather than a subset. That is deliberate and it is the whole
// point of the file. `_DecisionBody` in the router is a plain Pydantic model
// with no `extra="forbid"`, so posting the agreed figure under the name the
// server SERVES it back as - `agreed_cost_impact` rather than the request key
// `decided_amount` - is accepted with a 200, silently dropped, and recorded as
// the submitted bill total on a priced-bill basis. That is this issue's own
// bug, reproduced by a fix that looked correct. A test asserting that a field
// rendered, that a button was clickable, or that the payload merely contained
// the number would pass on all of it.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateSpy,
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

// Only the four verbs are replaced. `getErrorMessage`, `getAuthToken` and the
// download helpers stay real, because the modules under test and the contracts
// and BOQ clients they reach into all import them from here too.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { DetailDrawer } from './VariationsPage';
import type { VariationRequest } from './api';

const REQUEST: VariationRequest = {
  id: 'vr-1',
  project_id: 'p-1',
  notice_id: null,
  code: 'VR-001',
  title: 'Re-measure of the piling to grid F',
  description: '',
  requested_by: null,
  requested_at: null,
  classification: 'scope_change',
  urgency: 'med',
  // The reporter's own example: claimed at 12,000, priced at 7,500, settled
  // at 7,200.
  estimated_cost_impact: '12000.00',
  estimated_schedule_days: 4,
  currency: 'EUR',
  status: 'submitted',
  submitted_at: '2026-08-20T09:00:00Z',
  decision_at: null,
  decision_notes: '',
  decided_by: null,
  submitted_boq_id: 'boq-1',
  submitted_boq_total: '7500.00',
  agreed_cost_impact: null,
  agreed_basis: '',
  agreed_variance_note: '',
  metadata: {},
  created_at: '2026-08-19T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
};

const NO_BILL = {
  variation_request_id: 'vr-1',
  has_boq: false,
  boq_id: null,
  name: '',
  status: '',
  is_locked: false,
  parent_estimate_id: null,
  position_count: 0,
  base_currency: '',
  direct_cost: null,
  markups_total: null,
  grand_total: null,
  is_mixed_currency: false,
  estimated_cost_impact: '12000.00',
  estimate_matches_boq: false,
  traces: [],
  checks: [],
};

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

/** Routes a GET by path so every screen under test reads real-shaped data. */
function routeGet(overrides: Record<string, unknown> = {}) {
  api.apiGet.mockImplementation((path: string) => {
    for (const [fragment, value] of Object.entries(overrides)) {
      if (path.includes(fragment)) return Promise.resolve(value);
    }
    if (path.includes('/variations/variation-requests/vr-1/boq/')) {
      return Promise.resolve(NO_BILL);
    }
    if (path.includes('/contracts/contracts/ct-1/lines')) {
      return Promise.resolve([CONTRACT_LINE]);
    }
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

function renderRequest(request: VariationRequest) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DetailDrawer
        selected={{ kind: 'requests', id: request.id }}
        projectId="p-1"
        notices={[]}
        requests={[request]}
        orders={[]}
        daywork={[]}
        eot={[]}
        currency="EUR"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

/** The bodies posted to one route, in order. */
function bodiesFor(fragment: string): unknown[] {
  return api.apiPost.mock.calls
    .filter((call) => String(call[0]).includes(fragment))
    .map((call) => call[1]);
}

beforeEach(() => {
  navigateSpy.mockClear();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPost.mockResolvedValue({ id: 'new-1', name: 'bill', project_id: 'p-1' });
  routeGet();
});

describe('the negotiated amount reaches the server', () => {
  it('posts the agreed figure and its reason under the keys the route reads', async () => {
    renderRequest(REQUEST);

    fireEvent.click(screen.getByLabelText('Approve a negotiated amount'));
    fireEvent.change(screen.getByLabelText('Agreed amount'), {
      target: { value: '7200' },
    });
    fireEvent.change(screen.getByLabelText('What was negotiated'), {
      target: { value: 'Settled at 7,200 after the joint re-measure of grid F.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));

    await waitFor(() => expect(bodiesFor('/approve')).toHaveLength(1));
    // Exact, not `objectContaining`: the wire key is `decided_amount`, and the
    // same number under `agreed_cost_impact` would be dropped with a 200.
    expect(api.apiPost).toHaveBeenCalledWith(
      '/v1/variations/variation-requests/vr-1/approve',
      {
        decided_amount: '7200',
        agreed_variance_note: 'Settled at 7,200 after the joint re-measure of grid F.',
      },
    );
  });

  it('sends the amount as typed rather than as a parsed number', async () => {
    renderRequest(REQUEST);

    fireEvent.click(screen.getByLabelText('Approve a negotiated amount'));
    fireEvent.change(screen.getByLabelText('Agreed amount'), {
      target: { value: '7200.05' },
    });
    fireEvent.change(screen.getByLabelText('What was negotiated'), {
      target: { value: 'Rounded to the re-measured quantity.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));

    await waitFor(() => expect(bodiesFor('/approve')).toHaveLength(1));
    const body = bodiesFor('/approve')[0] as { decided_amount: unknown };
    expect(body.decided_amount).toBe('7200.05');
    expect(typeof body.decided_amount).toBe('string');
  });

  it('refuses to send a departure from the submitted total with no reason', async () => {
    renderRequest(REQUEST);

    fireEvent.click(screen.getByLabelText('Approve a negotiated amount'));
    fireEvent.change(screen.getByLabelText('Agreed amount'), {
      target: { value: '7200' },
    });

    expect(screen.getByRole('button', { name: /Approve/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));
    expect(bodiesFor('/approve')).toHaveLength(0);
  });

  it('asks for no reason when the agreed amount is the amount that was submitted', async () => {
    renderRequest(REQUEST);

    fireEvent.click(screen.getByLabelText('Approve a negotiated amount'));
    fireEvent.change(screen.getByLabelText('Agreed amount'), {
      target: { value: '7500' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));

    await waitFor(() => expect(bodiesFor('/approve')).toHaveLength(1));
    expect(bodiesFor('/approve')[0]).toEqual({ decided_amount: '7500' });
  });

  it('names no amount at all when the submitted pricing state is accepted', async () => {
    renderRequest(REQUEST);

    fireEvent.change(screen.getByPlaceholderText('Decision notes…'), {
      target: { value: 'Priced fairly against the contract rates.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));

    await waitFor(() => expect(bodiesFor('/approve')).toHaveLength(1));
    // No `decided_amount`, which is what makes the server record a basis of
    // `priced_boq` rather than filing every approval as a negotiation.
    expect(bodiesFor('/approve')[0]).toEqual({
      decision_notes: 'Priced fairly against the contract rates.',
    });
  });

  it('shows a decided request what was agreed and on what footing', () => {
    renderRequest({
      ...REQUEST,
      status: 'approved',
      agreed_cost_impact: '7200.00',
      agreed_basis: 'negotiated',
      agreed_variance_note: 'Settled after the joint re-measure.',
    });

    expect(screen.getByText('Agreed value')).toBeTruthy();
    expect(screen.getByText('Negotiated')).toBeTruthy();
    expect(screen.getByText('Settled after the joint re-measure.')).toBeTruthy();
  });
});

describe('a variation bill is seeded from the scope it is priced against', () => {
  it('posts the chosen schedule-of-values lines so trace rows get written', async () => {
    renderRequest(REQUEST);

    fireEvent.click(await screen.findByRole('button', { name: /Open a bill/ }));
    // The option has to exist before the select can be set to it, and the
    // contracts arrive a tick after the picker renders.
    await screen.findByRole('option', { name: /MC-01/ });
    fireEvent.change(screen.getByLabelText('Where the scope comes from'), {
      target: { value: 'contract:ct-1' },
    });
    fireEvent.click(await screen.findByLabelText('C.2.10 Bored piles 600mm'));
    fireEvent.click(screen.getByRole('button', { name: /Open bill from 1 line/ }));

    await waitFor(() => expect(bodiesFor('/boq/')).toHaveLength(1));
    expect(api.apiPost).toHaveBeenCalledWith(
      '/v1/variations/variation-requests/vr-1/boq/',
      { source_contract_lines: [{ contract_line_id: 'cl-1', quantity: '40' }] },
    );
  });

  it('carries the re-measured quantity rather than the contracted one', async () => {
    renderRequest(REQUEST);

    fireEvent.click(await screen.findByRole('button', { name: /Open a bill/ }));
    // The option has to exist before the select can be set to it, and the
    // contracts arrive a tick after the picker renders.
    await screen.findByRole('option', { name: /MC-01/ });
    fireEvent.change(screen.getByLabelText('Where the scope comes from'), {
      target: { value: 'contract:ct-1' },
    });
    fireEvent.click(await screen.findByLabelText('C.2.10 Bored piles 600mm'));
    fireEvent.change(screen.getByLabelText('Quantity this variation changes'), {
      target: { value: '12' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Open bill from 1 line/ }));

    await waitFor(() => expect(bodiesFor('/boq/')).toHaveLength(1));
    expect(bodiesFor('/boq/')[0]).toEqual({
      source_contract_lines: [{ contract_line_id: 'cl-1', quantity: '12' }],
    });
  });

  it('still opens an empty bill for scope nobody has contracted yet', async () => {
    renderRequest(REQUEST);

    fireEvent.click(await screen.findByRole('button', { name: /Open a bill/ }));
    fireEvent.click(screen.getByRole('button', { name: /Open an empty bill/ }));

    await waitFor(() => expect(bodiesFor('/boq/')).toHaveLength(1));
    expect(bodiesFor('/boq/')[0]).toEqual({});
  });
});

describe('a promoted order names the contract it amends', () => {
  const APPROVED: VariationRequest = {
    ...REQUEST,
    status: 'approved',
    agreed_cost_impact: '7200.00',
    agreed_basis: 'negotiated',
  };

  it('sends the contract the user chose', async () => {
    renderRequest(APPROVED);

    await screen.findByLabelText('Contract this order amends');
    await screen.findByRole('option', { name: /MC-01/ });
    fireEvent.change(screen.getByLabelText('Contract this order amends'), {
      target: { value: 'ct-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Convert to Order/ }));

    await waitFor(() => expect(bodiesFor('/convert-to-vo')).toHaveLength(1));
    expect(bodiesFor('/convert-to-vo')[0]).toEqual({
      currency: 'EUR',
      affected_contract_id: 'ct-1',
    });
  });

  it('defaults to the contract the priced scope traces back to', async () => {
    routeGet({
      '/variations/variation-requests/vr-1/boq/': {
        ...NO_BILL,
        has_boq: true,
        boq_id: 'boq-1',
        name: 'VR-001 bill',
        position_count: 1,
        grand_total: '7500.00',
        base_currency: 'EUR',
        traces: [
          {
            id: 'tr-1',
            variation_request_id: 'vr-1',
            boq_id: 'boq-1',
            position_id: 'pos-1',
            origin: 'contract_line',
            source_boq_id: null,
            source_position_id: null,
            contract_id: 'ct-1',
            contract_line_id: 'cl-1',
            note: '',
            created_at: '2026-08-21T09:00:00Z',
          },
        ],
      },
    });
    renderRequest(APPROVED);

    await waitFor(() =>
      expect(
        (screen.getByLabelText('Contract this order amends') as HTMLSelectElement).value,
      ).toBe('ct-1'),
    );
    fireEvent.click(screen.getByRole('button', { name: /Convert to Order/ }));

    await waitFor(() => expect(bodiesFor('/convert-to-vo')).toHaveLength(1));
    expect(bodiesFor('/convert-to-vo')[0]).toEqual({
      currency: 'EUR',
      affected_contract_id: 'ct-1',
    });
  });

  it('leaves the link out when there is nothing to link to', async () => {
    renderRequest(APPROVED);

    await screen.findByLabelText('Contract this order amends');
    fireEvent.click(screen.getByRole('button', { name: /Convert to Order/ }));

    await waitFor(() => expect(bodiesFor('/convert-to-vo')).toHaveLength(1));
    expect(bodiesFor('/convert-to-vo')[0]).toEqual({ currency: 'EUR' });
  });
});
