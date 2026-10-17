// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';

const spine = vi.hoisted(() => ({ getSpineAccounts: vi.fn(), getSpineLines: vi.fn() }));
const structure = vi.hoisted(() => ({ putAllocation: vi.fn(), clearAllocation: vi.fn() }));

vi.mock('@/features/costmodel/api', () => ({ costModelApi: spine }));
vi.mock('@/features/costmodel/structureApi', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/features/costmodel/structureApi')>();
  return { ...real, costStructureApi: structure };
});

import { ApiError } from '@/shared/lib/api';
import type { PositionAllocation } from '@/features/costmodel/structureApi';
import { CostAllocationDrawer, quantityLabel, trimShare } from './CostAllocationDrawer';

function allocation(over: Partial<PositionAllocation> = {}): PositionAllocation {
  return {
    position_id: 'pos-1',
    boq_id: 'boq-1',
    ordinal: '01.010',
    description: 'Concrete walls',
    unit: 'm3',
    quantity: '300',
    total: '1000.00',
    mode: 'single',
    rows: [
      {
        cost_line_id: 'line-1',
        cost_line_code: 'CL-1',
        cost_line_description: 'Walls',
        account_id: 'acc-330',
        account_code: '330',
        account_title: 'External walls',
        account_postable: true,
        share: '1',
        fraction: '1',
        amount: '1000.00',
      },
    ],
    valid: true,
    problem: null,
    share_total: '1',
    share_expected: '1',
    in_suspense: false,
    ...over,
  };
}

/** Metas of the mutations that reached the global error handler, as main.tsx wires it. */
const globalErrors: Array<Record<string, unknown> | undefined> = [];

function renderDrawer(a: PositionAllocation | undefined = allocation()) {
  const onClose = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    mutationCache: new MutationCache({ onError: (_e, _v, _c, m) => void globalErrors.push(m.meta) }),
  });
  render(
    <QueryClientProvider client={client}>
      <CostAllocationDrawer open onClose={onClose} projectId="p1" allocation={a} currency="EUR" />
    </QueryClientProvider>,
  );
  return { onClose };
}

beforeEach(() => {
  spine.getSpineAccounts.mockReset().mockResolvedValue([
    { id: 'acc-340', project_id: 'p1', parent_id: null, code: '340', name: '340', title: 'Internal walls', classification_standard: 'din276', status: 'open', sort_order: 0, is_leaf_postable: true },
    { id: 'acc-300', project_id: 'p1', parent_id: null, code: '300', name: '300', title: 'Building', classification_standard: 'din276', status: 'open', sort_order: 0, is_leaf_postable: false },
  ]);
  spine.getSpineLines.mockReset().mockResolvedValue([]);
  structure.putAllocation.mockReset();
  structure.clearAllocation.mockReset();
  globalErrors.length = 0;
});

describe('<CostAllocationDrawer>', () => {
  it('starts a single allocation at 100 % and offers only postable accounts', async () => {
    renderDrawer();
    expect(screen.getByLabelText('Share for CL-1')).toHaveValue('100');
    expect(screen.getByTestId('cost-allocation-sum')).toHaveTextContent('100 / 100 %');
    const candidates = screen.getByTestId('cost-allocation-candidates');
    expect(await within(candidates).findByText('Internal walls')).toBeInTheDocument();
    expect(within(candidates).queryByText('Building')).not.toBeInTheDocument();
  });

  it('splits by percent, checks the sum live and saves the vector', async () => {
    structure.putAllocation.mockResolvedValue(allocation({ mode: 'percent' }));
    const { onClose } = renderDrawer();
    fireEvent.click(await screen.findByText('Internal walls'));
    // The new row is offered what is missing (nothing, at 100 %), so the sum is off until edited.
    fireEvent.change(screen.getByLabelText('Share for CL-1'), { target: { value: '60' } });
    fireEvent.change(screen.getByLabelText('Share for 340'), { target: { value: '39,98' } });
    expect(screen.getByRole('alert')).toHaveTextContent('The shares add up to 99.98 % instead of 100 %.');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Share for 340'), { target: { value: '39.995' } });
    expect(screen.getByText('The shares add up.')).toBeInTheDocument();
    // The amounts preview the split to the cent, normalised to the shares' own
    // sum as the server does: 60 / 99.995 of 1000.00 is 600.03, the rest 399.97.
    const rows = screen.getByTestId('cost-allocation-rows');
    expect(rows).toHaveTextContent(/600[.,]03/);
    expect(rows).toHaveTextContent(/399[.,]97/);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(structure.putAllocation).toHaveBeenCalledWith('pos-1', {
        mode: 'percent',
        rows: [
          { cost_line_id: 'line-1', share: '60' },
          { control_account_id: 'acc-340', share: '39.995' },
        ],
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('splits by quantity against the position quantity', async () => {
    renderDrawer();
    fireEvent.click(screen.getByLabelText(/Quantity \(of 300 m3\)/));
    fireEvent.click(await screen.findByText('Internal walls'));
    fireEvent.change(screen.getByLabelText('Share for CL-1'), { target: { value: '120' } });
    fireEvent.change(screen.getByLabelText('Share for 340'), { target: { value: '180' } });
    expect(screen.getByTestId('cost-allocation-sum')).toHaveTextContent('300 / 300 m3');
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('shows a refused save as the translated problem', async () => {
    structure.putAllocation.mockRejectedValue(
      new ApiError(400, 'Bad Request', { detail: { problem: 'line_of_other_bill', message: 'x', params: {} } }),
    );
    renderDrawer();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('A share points at a cost line that belongs to another bill.')).toBeInTheDocument();
    // The drawer says it in the user's language; the global toast must not repeat it raw.
    expect(globalErrors).toEqual([{ suppressGlobalErrorToast: true }]);
  });

  it('opens a stored split with its shares as people typed them', () => {
    expect(trimShare('30.000000')).toBe('30');
    expect(trimShare('12.500000')).toBe('12.5');
    expect(trimShare('120')).toBe('120');
    const second = { ...allocation().rows[0]!, cost_line_id: 'line-2', cost_line_code: 'CL-2', share: '70.000000' };
    renderDrawer(allocation({ mode: 'percent', rows: [{ ...allocation().rows[0]!, share: '30.000000' }, second] }));
    expect(screen.getByLabelText('Share for CL-1')).toHaveValue('30');
    expect(screen.getByLabelText('Share for CL-2')).toHaveValue('70');
  });

  it('writes the position quantity the way people write it', () => {
    expect(quantityLabel('610.0000')).toBe('610');
    expect(quantityLabel('12.5000')).toBe('12.5');
    renderDrawer(allocation({ quantity: '610.0000', unit: 'm2' }));
    expect(screen.getByLabelText(/Quantity \(of 610 m2\)/)).toBeInTheDocument();
  });

  it('removes the allocation', async () => {
    structure.clearAllocation.mockResolvedValue(allocation({ mode: 'none', rows: [] }));
    const { onClose } = renderDrawer();
    fireEvent.click(screen.getByRole('button', { name: /Remove allocation/ }));
    await waitFor(() => expect(structure.clearAllocation).toHaveBeenCalledWith('pos-1'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('does not offer a cost line of another bill', async () => {
    spine.getSpineLines.mockResolvedValue([
      { id: 'line-own', project_id: 'p1', control_account_id: 'acc-340', code: 'CL-OWN', description: 'Own bill line', unit: 'm3', source: 'boq', boq_position_id: null, boq_id: 'boq-1', currency: 'EUR', estimate_quantity: '0', estimate_unit_rate: '0', estimate_amount: '0', status: 'active' },
      { id: 'line-free', project_id: 'p1', control_account_id: null, code: 'CL-FREE', description: 'Line on no bill', unit: '', source: 'manual', boq_position_id: null, boq_id: null, currency: 'EUR', estimate_quantity: '0', estimate_unit_rate: '0', estimate_amount: '0', status: 'active' },
      { id: 'line-other', project_id: 'p1', control_account_id: 'acc-340', code: 'CL-OTHER', description: 'Other bill line', unit: 'm3', source: 'boq', boq_position_id: null, boq_id: 'boq-2', currency: 'EUR', estimate_quantity: '0', estimate_unit_rate: '0', estimate_amount: '0', status: 'active' },
    ]);
    renderDrawer();
    const candidates = screen.getByTestId('cost-allocation-candidates');
    expect(await within(candidates).findByText('Own bill line')).toBeInTheDocument();
    expect(within(candidates).getByText('Line on no bill')).toBeInTheDocument();
    expect(within(candidates).queryByText('Other bill line')).not.toBeInTheDocument();
  });

  it('says so when the candidates cannot be loaded instead of "Nothing matches"', async () => {
    spine.getSpineLines.mockRejectedValue(new ApiError(500, 'Server Error', null));
    renderDrawer();
    const candidates = screen.getByTestId('cost-allocation-candidates');
    expect(await within(candidates).findByText('Cost lines and accounts could not be loaded.')).toBeInTheDocument();
    expect(within(candidates).queryByText('Nothing matches.')).not.toBeInTheDocument();
    spine.getSpineLines.mockResolvedValue([]);
    fireEvent.click(within(candidates).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(spine.getSpineLines).toHaveBeenCalledTimes(2));
  });

  it('holds back a share the server would refuse for its precision', async () => {
    renderDrawer();
    fireEvent.click(await screen.findByText('Internal walls'));
    fireEvent.change(screen.getByLabelText('Share for CL-1'), { target: { value: '60.0000001' } });
    fireEvent.change(screen.getByLabelText('Share for 340'), { target: { value: '39.9999999' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Too many decimals in a share. Allowed: 6.');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('labels the candidate search for assistive technology', () => {
    renderDrawer();
    expect(screen.getByRole('textbox', { name: 'Find a cost line or account by code or text' })).toBeInTheDocument();
  });

  it('names a stored split that no longer adds up', () => {
    renderDrawer(
      allocation({
        mode: 'quantity',
        valid: false,
        problem: 'shares_do_not_add_up',
        share_total: '300',
        share_expected: '400',
        rows: [
          { ...allocation().rows[0]!, share: '120' },
          { ...allocation().rows[0]!, cost_line_id: 'line-2', cost_line_code: 'CL-2', share: '180' },
        ],
      }),
    );
    expect(screen.getByText(/The stored split no longer adds up: The shares add up to 300 instead of 400\./)).toBeInTheDocument();
  });
});
