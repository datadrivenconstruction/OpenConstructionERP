// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({
  getStructure: vi.fn(),
  listCodeLists: vi.fn(),
  applyCodeList: vi.fn(),
  updateAccount: vi.fn(),
  deleteCodeList: vi.fn(),
  importCodeList: vi.fn(),
}));
const toast = vi.hoisted(() => ({ addToast: vi.fn() }));

vi.mock('./structureApi', async (importOriginal) => {
  const real = await importOriginal<typeof import('./structureApi')>();
  return { ...real, costStructureApi: api };
});
vi.mock('./api', () => ({ costModelApi: { generateSpine: vi.fn() } }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: typeof toast) => unknown) => selector(toast),
    { getState: () => toast },
  ),
}));

import { ApiError } from '@/shared/lib/api';
import { CostStructurePanel, worstSeverity } from './CostStructurePanel';
import type { StructureNode, StructureTree } from './structureApi';

function node(over: Partial<StructureNode>): StructureNode {
  return {
    id: 'n',
    parent_id: null,
    code: '',
    title: '',
    name: '',
    level: 1,
    classification_standard: 'din276',
    status: 'open',
    is_leaf_postable: true,
    own_amount: '0',
    posted: '0',
    children_total: '0',
    total: '0',
    line_count: 0,
    child_count: 0,
    ...over,
  };
}

function tree(over: Partial<StructureTree> = {}): StructureTree {
  return {
    project_id: 'p1',
    currency: 'EUR',
    standards: ['din276'],
    nodes: [
      node({ id: 'a300', code: '300', title: 'Building construction', is_leaf_postable: false, total: '1250.75', children_total: '1250.75', child_count: 1 }),
      node({ id: 'a330', parent_id: 'a300', code: '330', title: 'External walls', level: 2, own_amount: '1000.25', posted: '250.50', total: '1250.75', line_count: 2 }),
    ],
    suspense: [{ kind: 'no_account', line_count: 1, amount: '99.10', line_ids: ['l9'] }],
    total: '1349.85',
    findings: [
      { rule_id: 'structure.suspense', severity: 'warning', message: 'One cost line sits on no account.', suggestion: 'Give it an account.', element_ref: null, details: {} },
    ],
    ...over,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CostStructurePanel projectId="p1" currency="EUR" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  toast.addToast.mockReset();
  api.getStructure.mockResolvedValue(tree());
  api.listCodeLists.mockResolvedValue([
    { key: 'din276', name: 'DIN 276', standard: 'din276', source: 'builtin', pack_slug: null, entry_count: 40, depth: 3 },
    { key: 'own-codes', name: 'Own codes', standard: 'own-codes', source: 'custom', pack_slug: null, entry_count: 3, depth: 1 },
  ]);
});

describe('worstSeverity', () => {
  it('picks error over warning over info', () => {
    const f = (severity: 'error' | 'warning' | 'info') => ({ rule_id: 'r', severity, message: '', suggestion: '', element_ref: null, details: {} });
    expect(worstSeverity([])).toBeNull();
    expect(worstSeverity([f('info'), f('warning')])).toBe('warning');
    expect(worstSeverity([f('warning'), f('error')])).toBe('error');
  });
});

describe('<CostStructurePanel>', () => {
  it('renders the tree with own, posted and total, the suspense row and the findings', async () => {
    renderPanel();
    const row330 = await screen.findByTestId('structure-row-330');
    expect(row330).toHaveTextContent('External walls');
    expect(row330).toHaveTextContent(/1[,.\s\u00a0\u202f]?000[.,]25/);
    expect(row330).toHaveTextContent(/250[.,]50/);
    expect(screen.getByTestId('structure-row-300')).toHaveTextContent('Heading');
    expect(screen.getByTestId('structure-suspense-no_account')).toHaveTextContent(/cost lines on no account/);
    expect(screen.getByTestId('structure-total')).toHaveTextContent(/1[,.\s\u00a0\u202f]?349[.,]85/);
    expect(screen.getByTestId('structure-traffic-light')).toHaveAttribute('data-severity', 'warning');
    expect(screen.getByTestId('structure-findings')).toHaveTextContent('One cost line sits on no account.');
  });

  it('collapses and expands a parent', async () => {
    renderPanel();
    await screen.findByTestId('structure-row-330');
    fireEvent.click(within(screen.getByTestId('structure-row-300')).getByRole('button', { name: 'Collapse' }));
    expect(screen.queryByTestId('structure-row-330')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Expand all'));
    expect(screen.getByTestId('structure-row-330')).toBeInTheDocument();
  });

  it('saves title, own amount and postability through PATCH', async () => {
    api.updateAccount.mockResolvedValue({});
    renderPanel();
    const row = await screen.findByTestId('structure-row-330');
    fireEvent.click(within(row).getByRole('button', { name: 'Edit account' }));
    fireEvent.change(within(row).getByLabelText('Title'), { target: { value: 'Outer walls' } });
    fireEvent.change(within(row).getByLabelText('Own amount'), { target: { value: '1200,5' } });
    fireEvent.click(within(row).getByRole('checkbox'));
    fireEvent.click(within(row).getByRole('button', { name: /Save/ }));
    await waitFor(() =>
      expect(api.updateAccount).toHaveBeenCalledWith('a330', {
        title: 'Outer walls',
        own_amount: '1200.5',
        is_leaf_postable: false,
      }),
    );
  });

  it('refuses an own amount that is not a number', async () => {
    renderPanel();
    const row = await screen.findByTestId('structure-row-330');
    fireEvent.click(within(row).getByRole('button', { name: 'Edit account' }));
    fireEvent.change(within(row).getByLabelText('Own amount'), { target: { value: '12.345' } });
    fireEvent.click(within(row).getByRole('button', { name: /Save/ }));
    expect(within(row).getByRole('alert')).toHaveTextContent(/at most two decimals/);
    expect(api.updateAccount).not.toHaveBeenCalled();
  });

  it('applies the chosen code list down to a level and reports a mismatch', async () => {
    api.applyCodeList.mockRejectedValueOnce(
      new ApiError(409, 'Conflict', {
        detail: { problem: 'structure_standard_mismatch', message: 'x', params: { standard: 'din276', requested: 'own-codes' } },
      }),
    );
    renderPanel();
    await screen.findByTestId('structure-row-330');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Own codes' })).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('structure-code-list'), { target: { value: 'own-codes' } });
    fireEvent.click(screen.getByRole('button', { name: /Build from code list/ }));
    await waitFor(() => expect(api.applyCodeList).toHaveBeenCalledWith('p1', 'own-codes', null));
    await waitFor(() => expect(toast.addToast).toHaveBeenCalled());
    expect(toast.addToast.mock.calls[0]![0].message).toBe(
      'The cost structure is built on din276, so it cannot take codes of own-codes.',
    );
    // A custom list can be deleted from here; a shipped one cannot.
    expect(screen.getByRole('button', { name: /Delete code list/ })).toBeInTheDocument();
  });

  it('says so when the code lists cannot be loaded instead of offering none', async () => {
    api.listCodeLists.mockRejectedValue(new ApiError(500, 'Server Error', null));
    renderPanel();
    expect(await screen.findByTestId('structure-code-lists-error')).toHaveTextContent('The code lists could not be loaded.');
    expect(screen.queryByRole('option', { name: 'No code lists' })).not.toBeInTheDocument();
    api.listCodeLists.mockResolvedValue([]);
    fireEvent.click(within(screen.getByTestId('structure-code-lists-error')).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(api.listCodeLists).toHaveBeenCalledTimes(2));
  });

  it('forgets the level when another code list is chosen', async () => {
    api.applyCodeList.mockResolvedValue({ key: 'own-codes', accounts_created: 1 });
    renderPanel();
    await screen.findByTestId('structure-row-330');
    await waitFor(() => expect(screen.getByRole('option', { name: 'Own codes' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Down to level'), { target: { value: '3' } });
    fireEvent.change(screen.getByTestId('structure-code-list'), { target: { value: 'own-codes' } });
    fireEvent.click(screen.getByRole('button', { name: /Build from code list/ }));
    await waitFor(() => expect(api.applyCodeList).toHaveBeenCalledWith('p1', 'own-codes', null));
  });

  it('shows an empty state when there is no structure', async () => {
    api.getStructure.mockResolvedValue(tree({ nodes: [], suspense: [], findings: [], total: '0' }));
    renderPanel();
    expect(await screen.findByText('No cost structure yet')).toBeInTheDocument();
  });

  it('reads empty suspense buckets as no structure, with no green light', async () => {
    // The server lists both buckets even when they carry nothing.
    api.getStructure.mockResolvedValue(
      tree({
        nodes: [],
        suspense: [
          { kind: 'no_account', line_count: 0, amount: '0', line_ids: [] },
          { kind: 'invalid_account', line_count: 0, amount: '0', line_ids: [] },
        ],
        findings: [],
        total: '0',
      }),
    );
    renderPanel();
    expect(await screen.findByText('No cost structure yet')).toBeInTheDocument();
    expect(screen.queryByTestId('structure-traffic-light')).not.toBeInTheDocument();
    expect(screen.queryByText('Expand all')).not.toBeInTheDocument();
  });
});
