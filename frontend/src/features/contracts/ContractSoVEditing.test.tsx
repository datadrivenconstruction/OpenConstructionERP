// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a person can do to a contract they are still writing, and in what
// money a new contract and a new claim start.
//
// All four of these were walked on a running instance rather than read:
//   * the first line of every contract was saved with no unit, because the
//     add-line form that shows when there are no lines yet had no unit field,
//     and the compliance gate then refused to sign over it for ever;
//   * a line, once saved, could not be corrected or removed from the screen
//     at all, so the typo was permanent;
//   * a new claim was seeded in euros whatever the contract was in;
//   * a new contract was seeded in euros whatever the project was in.
//
// The API layer is exercised for real here (the mock is on apiGet/apiPost/
// apiPatch/apiDelete), so a wrong URL fails the test rather than passing it.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

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

// One spy for every toast, so a test can read what the person was told.
const toast = vi.hoisted(() => ({ addToast: vi.fn() }));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof toast.addToast }) => unknown) =>
    sel({ addToast: toast.addToast }),
}));

import { ApiError } from '@/shared/lib/api';
import {
  ContractDetailDrawer,
  CreateContractModal,
  NewClaimModal,
} from './ContractsPage';
import type { ContractItem, ContractLine, ProgressClaimItem } from './api';

const CONTRACT_ID = 'ctr-1';
const LINE_ID = 'line-1';
const OTHER_LINE_ID = 'line-2';

function contract(overrides: Partial<ContractItem> = {}): ContractItem {
  return {
    id: CONTRACT_ID,
    code: 'C-001',
    title: 'Main works',
    contract_type: 'lump_sum',
    counterparty_type: 'subcontractor',
    counterparty_id: null,
    project_id: 'p-1',
    parent_contract_id: null,
    start_date: '2026-05-01',
    end_date: null,
    total_value: '1000',
    original_contract_value: null,
    currency: 'USD',
    retention_percent: '5',
    retention_release_event: 'substantial_completion',
    status: 'draft',
    signed_at: null,
    template_code: null,
    template_version: null,
    terms: {},
    created_by: null,
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

function line(overrides: Partial<ContractLine> = {}): ContractLine {
  return {
    id: LINE_ID,
    contract_id: CONTRACT_ID,
    parent_line_id: null,
    code: 'A1',
    description: 'Concrete',
    scope_section: null,
    line_type: 'work',
    unit: 'm3',
    quantity: '10',
    unit_rate: '100',
    total_value: '1000',
    order_index: 0,
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

/** A certified claim on the contract, the kind the payer already holds. */
function claim(overrides: Partial<ProgressClaimItem> = {}): ProgressClaimItem {
  return {
    id: 'claim-1',
    contract_id: CONTRACT_ID,
    claim_number: 'PC-1',
    period_start: '2026-05-01',
    period_end: '2026-05-31',
    claim_date: null,
    gross_amount: '250',
    retention_amount: '12.5',
    prior_claims_total: '0',
    net_due: '237.5',
    status: 'certified',
    submitted_at: null,
    approved_at: null,
    paid_at: null,
    currency: 'USD',
    metadata: {},
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  };
}

/**
 * Answer the two reads these tests are about; `lines` is the schedule of
 * values and `claims` the contract's claim history. Everything else the
 * drawer asks for - the dashboard, the analytics panels, the retention
 * ledger - is refused rather than answered with an invented body: a panel
 * given the wrong shape either throws or, worse, renders something that
 * reads like data. Refused, each panel shows its own empty state and the
 * schedule of values is left to be tested.
 */
function seedReads(lines: ContractLine[], claims: ProgressClaimItem[] = []) {
  api.apiGet.mockImplementation((path: string) => {
    if (path.endsWith('/lines')) return Promise.resolve(lines);
    if (path.startsWith('/v1/contracts/progress-claims/?'))
      return Promise.resolve({ items: claims, total: claims.length, offset: 0, limit: 200 });
    return Promise.reject(new Error(`not mocked: ${path}`));
  });
}

function renderDrawer(c: ContractItem) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ContractDetailDrawer contractId={c.id} contracts={[c]} onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPatch.mockReset();
  api.apiDelete.mockReset();
  toast.addToast.mockReset();
  seedReads([]);
});

/** How many times the schedule of values has been read so far. */
function lineReads(): number {
  return api.apiGet.mock.calls.filter(([path]) => String(path).endsWith('/lines')).length;
}

/** The server's refusal, shaped the way the API client throws it. */
function refusal(error: string): ApiError {
  return new ApiError(409, 'Conflict', {
    detail: { error, message: 'The server explains itself in English here.' },
  });
}

afterEach(() => cleanup());

describe('the first line of a contract', () => {
  it('is asked for its unit, the same as every line after it', async () => {
    // Every contract starts with no lines, so this form is the one line one
    // always goes through. Without a unit here the compliance gate refuses
    // the signature with boq_quality.empty_unit and there is no way back.
    api.apiPost.mockResolvedValue(line());
    renderDrawer(contract());

    fireEvent.click(await screen.findByRole('button', { name: /Add line/i }));
    const unit = await screen.findByPlaceholderText('Unit');
    fireEvent.change(screen.getByPlaceholderText('Description'), {
      target: { value: 'Concrete' },
    });
    fireEvent.change(screen.getByPlaceholderText('Qty'), { target: { value: '10' } });
    fireEvent.change(unit, { target: { value: 'm3' } });
    fireEvent.change(screen.getByPlaceholderText('Rate'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(1));
    expect(api.apiPost).toHaveBeenCalledWith(
      `/v1/contracts/contracts/${CONTRACT_ID}/lines`,
      expect.objectContaining({ unit: 'm3', description: 'Concrete' }),
    );
  });
});

describe('a line of the schedule of values', () => {
  it('can be corrected on the row, and only what changed is sent', async () => {
    seedReads([line()]);
    api.apiPatch.mockResolvedValue(line({ unit_rate: '120' }));
    renderDrawer(contract());

    const row = await screen.findByTestId(`sov-row-${LINE_ID}`);
    fireEvent.click(within(row).getByRole('button', { name: /^Edit$/i }));
    fireEvent.change(screen.getByLabelText('Rate'), { target: { value: '120' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(api.apiPatch).toHaveBeenCalledTimes(1));
    // The description was not touched, so it is not sent back: another
    // person's correction to it is not undone by this one.
    expect(api.apiPatch).toHaveBeenCalledWith(`/v1/contracts/contracts/lines/${LINE_ID}`, {
      unit_rate: 120,
    });
  });

  it('is removed only after the question is asked', async () => {
    seedReads([line()]);
    api.apiDelete.mockResolvedValue(undefined);
    renderDrawer(contract());

    // Scoped to the row: the drawer carries its own Delete, for the contract.
    const row = await screen.findByTestId(`sov-row-${LINE_ID}`);
    fireEvent.click(within(row).getByRole('button', { name: /^Delete$/i }));
    expect(api.apiDelete).not.toHaveBeenCalled();

    // The question, not the row behind it: both carry a Delete.
    const dialog = await screen.findByRole('alertdialog', { name: /Remove this line/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /^Delete$/i }));
    await waitFor(() => expect(api.apiDelete).toHaveBeenCalledTimes(1));
    expect(api.apiDelete).toHaveBeenCalledWith(`/v1/contracts/contracts/lines/${LINE_ID}`);
  });

  it('is left alone once the contract is signed, and says why', async () => {
    // A signed scope is changed with a variation, which both sides see. The
    // server refuses the edit and the delete on a signed contract as well.
    seedReads([line()]);
    renderDrawer(contract({ status: 'active' }));

    await screen.findByTestId('sov-lines-locked');
    const row = screen.getByTestId(`sov-row-${LINE_ID}`);
    expect(within(row).queryByRole('button', { name: /^Edit$/i })).toBeNull();
    expect(within(row).queryByRole('button', { name: /^Delete$/i })).toBeNull();
  });

  it('is left alone once a claim has billed on it, even on a draft contract', async () => {
    // Nothing ties a claim to the contract's status, so a draft can carry a
    // certified claim. Deleting the line would take the claim's lines with it
    // (the foreign key cascades), and a new rate would restate what the
    // certificate says was done. The server refuses both; the screen must
    // not offer them and then show the refusal as an error.
    seedReads([line({ billed: true })], [claim()]);
    renderDrawer(contract({ status: 'draft' }));

    const note = await screen.findByTestId('sov-lines-billed');
    const row = screen.getByTestId(`sov-row-${LINE_ID}`);
    expect(within(row).queryByRole('button', { name: /^Edit$/i })).toBeNull();
    expect(within(row).queryByRole('button', { name: /^Delete$/i })).toBeNull();
    // The signed-contract sentence would be false here: the contract is not
    // signed. The note names the claim as the reason instead.
    expect(screen.queryByTestId('sov-lines-locked')).toBeNull();
    expect(note.textContent).toMatch(/progress claim/i);
    expect(note.textContent).not.toMatch(/signed/i);
  });

  it('still corrects the lines no claim has billed on, next to one that is', async () => {
    // The lock is a fact about each line, not about the contract. A line
    // added after the first claim, or one the claim did not bill, is still
    // the draft it looks like, and the server lets it be changed.
    seedReads(
      [line({ billed: true }), line({ id: OTHER_LINE_ID, code: 'A2', billed: false })],
      [claim()],
    );
    renderDrawer(contract({ status: 'draft' }));

    const other = await screen.findByTestId(`sov-row-${OTHER_LINE_ID}`);
    expect(within(other).getByRole('button', { name: /^Edit$/i })).toBeTruthy();
    expect(within(other).getByRole('button', { name: /^Delete$/i })).toBeTruthy();
    const billed = screen.getByTestId(`sov-row-${LINE_ID}`);
    expect(within(billed).queryByRole('button', { name: /^Edit$/i })).toBeNull();
    // A locked row keeps its cell, so its figures stay under their headings.
    expect(billed.querySelectorAll('td')).toHaveLength(other.querySelectorAll('td').length);
  });

  it('says why in the reader’s words when a claim billed on it after the list was read', async () => {
    // The listing said unbilled; a claim billed on the line since. The server
    // refuses the delete, and the person is told the reason the note gives,
    // not the server's English sentence, and the lines are read again so the
    // row stops offering what was just refused.
    seedReads([line()]);
    api.apiDelete.mockRejectedValue(refusal('contract_line_billed'));
    renderDrawer(contract());

    const row = await screen.findByTestId(`sov-row-${LINE_ID}`);
    const readsBefore = lineReads();
    fireEvent.click(within(row).getByRole('button', { name: /^Delete$/i }));
    const dialog = await screen.findByRole('alertdialog', { name: /Remove this line/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /^Delete$/i }));

    await waitFor(() => expect(toast.addToast).toHaveBeenCalledTimes(1));
    const told = toast.addToast.mock.calls[0]![0] as { type: string; title: string };
    expect(told.type).toBe('error');
    expect(told.title).toMatch(/progress claim has billed/i);
    expect(told.title).not.toMatch(/explains itself/i);
    await waitFor(() => expect(lineReads()).toBeGreaterThan(readsBefore));
  });

  it('says the contract was signed when the server refuses a correction for that', async () => {
    seedReads([line()]);
    api.apiPatch.mockRejectedValue(refusal('contract_lines_frozen'));
    renderDrawer(contract());

    const row = await screen.findByTestId(`sov-row-${LINE_ID}`);
    fireEvent.click(within(row).getByRole('button', { name: /^Edit$/i }));
    fireEvent.change(screen.getByLabelText('Rate'), { target: { value: '120' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(toast.addToast).toHaveBeenCalledTimes(1));
    const told = toast.addToast.mock.calls[0]![0] as { title: string };
    expect(told.title).toMatch(/signed contract/i);
    expect(told.title).not.toMatch(/explains itself/i);
    // The edit is closed rather than left open on a write that cannot land.
    await waitFor(() => expect(screen.queryByLabelText('Rate')).toBeNull());
  });

  it('still passes on any other failure as it came', async () => {
    seedReads([line()]);
    api.apiDelete.mockRejectedValue(
      new ApiError(500, 'Internal Server Error', { detail: 'Disk full' }),
    );
    renderDrawer(contract());

    const row = await screen.findByTestId(`sov-row-${LINE_ID}`);
    fireEvent.click(within(row).getByRole('button', { name: /^Delete$/i }));
    const dialog = await screen.findByRole('alertdialog', { name: /Remove this line/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /^Delete$/i }));

    await waitFor(() => expect(toast.addToast).toHaveBeenCalledTimes(1));
    expect((toast.addToast.mock.calls[0]![0] as { title: string }).title).toMatch(/Disk full/);
  });
});

describe('the money a new record starts in', () => {
  it('is the contract’s on a new claim, not a guess', async () => {
    api.apiPost.mockResolvedValue({ id: 'claim-1' });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewClaimModal
            contracts={[contract({ currency: 'USD' })]}
            defaultContractId={CONTRACT_ID}
            onClose={vi.fn()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect((screen.getByTestId('claim-currency') as HTMLInputElement).value).toBe('USD');
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(1));
    // The certificate prints the contract's figures; the sign on them has to
    // be the contract's too.
    expect(api.apiPost).toHaveBeenCalledWith(
      '/v1/contracts/progress-claims/',
      expect.objectContaining({ currency: 'USD' }),
    );
  });

  it("is the project's on a new contract", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CreateContractModal projectId="p-1" defaultCurrency="GBP" onClose={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const field = screen
      .getAllByRole('textbox')
      .find((el) => (el as HTMLInputElement).maxLength === 3) as HTMLInputElement;
    expect(field.value).toBe('GBP');
  });
});

describe('a claim just created', () => {
  it('is in the list the dialog closes onto, for the contract it was raised against', async () => {
    const created = { id: 'claim-9', claim_number: 'PC-001', contract_id: 'ctr-2', status: 'draft' };
    seedReads([], [created as unknown as ProgressClaimItem]);
    api.apiPost.mockResolvedValue(created);
    const order: string[] = [];
    api.apiGet.mockImplementation((path: string) => {
      order.push(path);
      return Promise.resolve({ items: [created], total: 1, offset: 0, limit: 200 });
    });
    const onClose = vi.fn(() => order.push('close'));
    const onCreated = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewClaimModal
            contracts={[contract({ id: 'ctr-2', status: 'active' })]}
            defaultContractId={CONTRACT_ID}
            onClose={onClose}
            onCreated={onCreated}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));

    // The list for the claim's own contract was read before the dialog closed,
    // so the register never shows its empty state for a claim that exists.
    const listRead = order.findIndex((p) => p.includes('contract_id=ctr-2'));
    expect(listRead).toBeGreaterThanOrEqual(0);
    expect(listRead).toBeLessThan(order.indexOf('close'));
    expect(onCreated).toHaveBeenCalledWith('ctr-2');
    expect(client.getQueryData(['contracts', 'claims', 'ctr-2'])).toMatchObject({ total: 1 });
  });
});
