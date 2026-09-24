// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The purchase-order flow, from the page a buyer lands on to the body the
// server receives.
//
// This is the first test this page has had, so it covers the spine of the
// flow rather than one control: the page mounts, the create form opens where a
// buyer expects it, the bill-position picker is reachable there, and the
// position they pick survives all the way into the submitted payload.
//
// The picker half exists because <BillPositionPicker> has a thorough test of
// its own that mounts the component itself. No component test can fail because
// nothing in the app mounts the component, so it stayed green through the three
// days the picker was written, covered and imported by nothing, and coverage
// counted it the whole time. What a component test cannot do is start where a
// buyer starts and press what is actually in front of them.
//
// Assertions key on the per-line accessible name - "Bill position for line 1" -
// because only the picker renders it, and only from inside the per-line map of
// the order form. Matching the bare "Bill position" label would be weaker: the
// picker gives that same text to its own search box as a placeholder, so a hit
// on it would not tell a mounted control apart from its own internals.
//
// The empty-spine test is the negative control and it is why the reachability
// test means anything. It presses the same button with no cost spine behind the
// project, proves the form opened all the same, and requires the picker to be
// absent. Without it, an assertion that merely tracked "the modal is open"
// would pass just as well and prove nothing about the picker.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { ProcurementPage } from './ProcurementPage';
import type { CostSpineLine } from './costSpineApi';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

// Only the request verbs are replaced. The rest of the module is kept as it is
// because the page and everything it pulls in import more than these three
// names, and a factory that returned only the mocks would leave those imports
// undefined at module scope.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() };
});

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

const mockGet = vi.mocked(apiGet);
const mockPost = vi.mocked(apiPost);
const mockPatch = vi.mocked(apiPatch);

const PROJECT_ID = 'p1';

/** The button a buyer presses, by the label they read on it. */
const NEW_PO = 'New Purchase Order';

/** The picker's own accessible name on the first order line. */
const PICKER_LABEL = 'Bill position for line 1';

/** The description input on the same line, used to show the form did open. */
const LINE_ONE_DESCRIPTION = 'Description for line 1';

/** The shape this page posts. Only the parts under test are named. */
interface SubmittedPO {
  project_id: string;
  items: Array<{ description: string; boq_position_id?: string; sort_order: number }>;
}

function spineLine(): CostSpineLine {
  return {
    id: 'cl-1',
    project_id: PROJECT_ID,
    code: '1.1',
    description: 'Reinforced concrete C30/37',
    unit: 'm3',
    source: 'boq',
    boq_position_id: 'pos-1',
    boq_id: 'b1',
    estimate_quantity: '120',
    estimate_unit_rate: '180.00',
    estimate_amount: '21600.00',
    currency: 'EUR',
    status: 'active',
  };
}

/**
 * Answer every endpoint the page and the picker reach on the way in.
 *
 * The cost spine is the only axis the tests vary, since it is what decides
 * whether the picker renders at all. The order register is served empty on
 * purpose: that is a project's first-run state, and its empty panel carries
 * the button a new buyer has in front of them.
 */
function serveApi(spine: CostSpineLine[]) {
  mockGet.mockImplementation((path: string) => {
    if (path.includes('/spine/lines/')) return Promise.resolve(spine);
    if (path.includes('/v1/finance/dashboard/')) return Promise.resolve({ currency: 'EUR' });
    return Promise.resolve({ items: [], total: 0 });
  });
}

function renderProcurementPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProcurementPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The control this file is about, looked up by the one name unique to it. */
function picker() {
  return screen.queryByLabelText(PICKER_LABEL);
}

/** Open the create form the way a buyer does, from the page they land on. */
async function openCreateForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: NEW_PO }));
  return screen.findByRole('dialog', { name: NEW_PO });
}

/** The one order line the form starts with, filled enough to be submittable. */
async function describeFirstLine(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(await screen.findByLabelText(LINE_ONE_DESCRIPTION), text);
}

/**
 * The one POST this page makes when the form is submitted.
 *
 * The call is taken with an explicit check rather than an index under
 * `noUncheckedIndexedAccess`. If the form never posted, this throw is what
 * reports it, naming the defect where it happened; an assertion silencer here
 * would let the `undefined` travel and resurface later as what looks like a
 * wrong value on a field.
 */
function submittedPO(): { path: string; body: SubmittedPO } {
  const call = mockPost.mock.calls[0];
  if (!call) throw new Error('The form made no POST request, so there is no payload to read.');
  const [path, body] = call;
  return { path, body: body as SubmittedPO };
}

/** The first order line of a submitted payload, or a failure that names itself. */
function firstLineOf(body: SubmittedPO): SubmittedPO['items'][number] {
  const line = body.items[0];
  if (!line) throw new Error('The submitted purchase order carried no order lines.');
  return line;
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPost.mockResolvedValue({});
  // `useParams` is mocked globally to `{}`, so the active project can only come
  // from the switcher store - the same place the header's project picker puts
  // it. Route params would be silently ignored here.
  useProjectContextStore.setState({ activeProjectId: PROJECT_ID, activeProjectName: 'Riverside' });
});

describe('opening the purchase-order form', () => {
  it('takes a buyer from the page they land on to the create form', async () => {
    const user = userEvent.setup();
    serveApi([spineLine()]);
    renderProcurementPage();

    const dialog = await openCreateForm(user);

    // Arrived where a buyer expects: the form, on its Items section, with the
    // first order line ready to be typed into.
    // Matched loosely: the heading also carries the required-field marker, so
    // its text content is "Items *" rather than "Items".
    expect(within(dialog).getByRole('heading', { name: /Items/ })).toBeInTheDocument();
    expect(within(dialog).getByLabelText(LINE_ONE_DESCRIPTION)).toBeInTheDocument();
  });
});

describe('reaching the bill-position picker from the procurement page', () => {
  it('does not already hold the picker on landing, so getting to it takes the click', async () => {
    serveApi([spineLine()]);
    renderProcurementPage();

    // Waiting for the button first matters: without it "absent" would only mean
    // the register had not finished loading, which is true of any control.
    expect(await screen.findByRole('button', { name: NEW_PO })).toBeInTheDocument();
    expect(picker()).toBeNull();
  });

  it('gets a buyer from the page they land on to the picker, with no URL to know', async () => {
    const user = userEvent.setup();
    serveApi([spineLine()]);
    renderProcurementPage();

    await openCreateForm(user);

    const control = await screen.findByLabelText(PICKER_LABEL);
    expect(control).toBeInTheDocument();

    // And it arrives carrying the bill rather than as an empty shell, which is
    // the difference between a control that mounted and one that is usable.
    expect(
      within(control).getByRole('option', { name: '1.1 - Reinforced concrete C30/37 (m3)' }),
    ).toBeInTheDocument();
  });

  it('opens the same form and no picker when the project has no cost spine', async () => {
    const user = userEvent.setup();
    serveApi([]);
    renderProcurementPage();

    await openCreateForm(user);

    // The form is open and line 1 is there to be typed into, so the absence
    // below is the picker declining to render and not the click missing.
    expect(await screen.findByLabelText(LINE_ONE_DESCRIPTION)).toBeInTheDocument();
    expect(picker()).toBeNull();
  });
});

describe('the picked position reaching the server', () => {
  it('sends the position the buyer chose on the line they chose it for', async () => {
    const user = userEvent.setup();
    serveApi([spineLine()]);
    renderProcurementPage();

    await openCreateForm(user);
    await describeFirstLine(user, 'Concrete for the raft');
    await user.selectOptions(await screen.findByLabelText(PICKER_LABEL), 'pos-1');

    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));

    const { path, body } = submittedPO();
    expect(path).toBe('/v1/procurement/');
    expect(body.project_id).toBe(PROJECT_ID);
    expect(body.items).toHaveLength(1);

    const line = firstLineOf(body);
    expect(line.description).toBe('Concrete for the raft');
    expect(line.boq_position_id).toBe('pos-1');
  });

  it('leaves the field off entirely when the buyer attributes nothing', async () => {
    const user = userEvent.setup();
    serveApi([spineLine()]);
    renderProcurementPage();

    await openCreateForm(user);
    await describeFirstLine(user, 'Sundries');

    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));

    // Absent, not null. The field is optional on POItemCreate and an omitted
    // one reads as an unlinked line, where a null would ask the server to
    // resolve nothing. This pins the distinction the form deliberately makes.
    const { body } = submittedPO();
    expect(firstLineOf(body).boq_position_id).toBeUndefined();

    // And the same claim about what actually leaves the browser: an undefined
    // value drops the key on serialisation, so the request carries no mention
    // of the field at all.
    expect(JSON.stringify(body)).not.toContain('boq_position_id');
  });
});

// Past draft, the server holds an order's vendor, currency, lines and amounts
// fixed and answers a change to them with a 409. The Edit form used to open
// with all of them editable, so a buyer could type new figures into an issued
// order and only learn at Save that it could not work. The draft case is the
// control: the same form on a draft keeps every field open.
describe('editing an order past draft', () => {
  function servePO(status: string) {
    const listed = {
      id: 'po-1',
      project_id: PROJECT_ID,
      po_number: 'PO-0001',
      vendor_name: 'Acme Supplies',
      vendor_contact_id: 'c-1',
      issue_date: '2026-09-01',
      delivery_date: '2026-10-01',
      amount_total: '1190.00',
      currency_code: 'EUR',
      status,
      description: '',
      line_items_count: 1,
      created_at: '2026-09-01T00:00:00Z',
    };
    const full = {
      ...listed,
      po_type: 'standard',
      amount_subtotal: '1000.00',
      tax_amount: '190.00',
      payment_terms: 'Net 30',
      notes: '',
      items: [
        {
          id: 'it-1',
          description: 'Rebar B500B',
          quantity: '10',
          unit: 't',
          unit_rate: '100.00',
          amount: '1000.00',
          boq_position_id: null,
          sort_order: 0,
        },
      ],
    };
    mockGet.mockImplementation((path: string) => {
      if (path === '/v1/procurement/po-1') return Promise.resolve(full);
      if (path === '/v1/procurement/po-1/match-status/') return Promise.resolve({ overall_status: 'ok', lines: [] });
      if (path.startsWith('/v1/procurement/?project_id=')) return Promise.resolve({ items: [listed], total: 1 });
      if (path.includes('/spine/lines/')) return Promise.resolve([]);
      if (path.includes('/v1/finance/dashboard/')) return Promise.resolve({ currency: 'EUR' });
      return Promise.resolve({ items: [], total: 0 });
    });
  }

  async function openEdit(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: 'Edit purchase order' }));
    return screen.findByRole('dialog', { name: 'Edit purchase order' });
  }

  beforeEach(() => {
    mockPatch.mockReset();
    mockPatch.mockResolvedValue({});
    useAuthStore.setState({ userRole: 'manager' });
  });

  it('locks the figures of an issued order and sends none of them on Save', async () => {
    const user = userEvent.setup();
    servePO('issued');
    renderProcurementPage();

    const dialog = await openEdit(user);
    expect(within(dialog).getByRole('note')).toBeInTheDocument();
    expect(within(dialog).getByLabelText(LINE_ONE_DESCRIPTION)).toBeDisabled();
    expect(within(dialog).getByLabelText('Quantity for line 1')).toBeDisabled();
    expect(within(dialog).getByLabelText('Unit rate for line 1')).toBeDisabled();
    expect(within(dialog).getByLabelText('Remove line 1')).toBeDisabled();
    expect(within(dialog).getByLabelText('Tax')).toBeDisabled();
    expect(within(dialog).getByLabelText('Currency')).toBeDisabled();
    expect(within(dialog).getByLabelText('Vendor')).toBeDisabled();
    expect(within(dialog).queryByRole('button', { name: 'Add Item' })).toBeNull();

    // What stays open still saves.
    await user.type(within(dialog).getByPlaceholderText('Optional notes or special instructions...'), 'Gate 3');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const [path, body] = mockPatch.mock.calls[0]!;
    expect(path).toBe('/v1/procurement/po-1');
    expect(body).toEqual({ notes: 'Gate 3' });
  });

  it('keeps every field open on a draft', async () => {
    const user = userEvent.setup();
    servePO('draft');
    renderProcurementPage();

    const dialog = await openEdit(user);
    expect(within(dialog).queryByRole('note')).toBeNull();
    expect(within(dialog).getByLabelText(LINE_ONE_DESCRIPTION)).toBeEnabled();
    expect(within(dialog).getByLabelText('Tax')).toBeEnabled();
    expect(within(dialog).getByLabelText('Currency')).toBeEnabled();
    expect(within(dialog).getByRole('button', { name: 'Add Item' })).toBeInTheDocument();
  });
});
