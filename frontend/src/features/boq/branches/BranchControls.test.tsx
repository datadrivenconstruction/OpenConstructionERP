// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BranchControls } from './BranchControls';
import { branchApi, type BranchNode, type BranchTree } from './branchApi';

function node(id: string, extra: Partial<BranchNode> = {}): BranchNode {
  return {
    boq_id: id,
    name: id,
    is_main: false,
    parent_boq_id: 'main',
    status: 'open',
    note: '',
    is_locked: false,
    created_at: '2026-10-20T10:00:00Z',
    created_by: null,
    author: 'A. Estimator',
    position_count: 3,
    direct_cost: '100',
    grand_total: '100',
    delta_vs_parent: '0',
    base_snapshot_id: null,
    source_snapshot_id: null,
    merged_at: null,
    merged_by: null,
    merge_snapshot_id: null,
    design_option: null,
    ...extra,
  };
}

const tree: BranchTree = {
  main_boq_id: 'main',
  currency: 'EUR',
  can_merge: false,
  nodes: [
    node('main', { name: 'Main estimate', is_main: true, parent_boq_id: null, grand_total: '1000' }),
    node('precast', { name: 'Alternative with precast', grand_total: '900', delta_vs_parent: '-100' }),
    node('ve2', { name: 'Value engineering round 2', status: 'merged', delta_vs_parent: '50' }),
  ],
  design_options: [{ id: 'opt1', name: 'Option B', set_id: 's', set_name: 'Facade', boq_id: null }],
};

function renderControls(boqId: string, branchOfId: string | null = null, onNavigate = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BranchControls
        boqId={boqId}
        boqName="Main estimate"
        branchOfId={branchOfId}
        onNavigate={onNavigate}
        onChanged={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return onNavigate;
}

describe('BranchControls', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the tree with author, totals and deltas and switches branch on click', async () => {
    vi.spyOn(branchApi, 'tree').mockResolvedValue(tree);
    const onNavigate = renderControls('main');
    await waitFor(() => expect(screen.getByTestId('branch-switcher')).toHaveTextContent('2'));
    fireEvent.click(screen.getByTestId('branch-switcher'));
    const list = await screen.findByTestId('branch-tree');
    const items = within(list).getAllByRole('button');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('Main estimate');
    expect(items[0]).toHaveAttribute('aria-current', 'true');
    expect(items[1]).toHaveTextContent('Alternative with precast');
    expect(items[1]).toHaveTextContent('A. Estimator');
    expect(items[1]).toHaveTextContent(/-100/);
    expect(items[2]).toHaveTextContent('merged');
    fireEvent.click(items[1]!);
    expect(onNavigate).toHaveBeenCalledWith('precast');
  });

  it('names the branch being edited and offers merge only with the permission', async () => {
    vi.spyOn(branchApi, 'tree').mockResolvedValue(tree);
    renderControls('precast', 'main');
    await waitFor(() => expect(screen.getByTestId('branch-switcher')).toHaveTextContent('Alternative with precast'));
    fireEvent.click(screen.getByTestId('branch-switcher'));
    const merge = await screen.findByRole('button', { name: /Merge into main/ });
    expect(merge).toBeDisabled();
  });

  it('links a design option to the open estimate', async () => {
    vi.spyOn(branchApi, 'tree').mockResolvedValue(tree);
    const link = vi.spyOn(branchApi, 'linkDesignOption').mockResolvedValue(tree);
    renderControls('precast', 'main');
    fireEvent.click(screen.getByTestId('branch-switcher'));
    const select = await screen.findByDisplayValue('None');
    fireEvent.change(select, { target: { value: 'opt1' } });
    await waitFor(() => expect(link).toHaveBeenCalledWith('precast', 'opt1'));
  });

  it('archives the open branch', async () => {
    vi.spyOn(branchApi, 'tree').mockResolvedValue(tree);
    const update = vi.spyOn(branchApi, 'update').mockResolvedValue(tree);
    renderControls('precast', 'main');
    fireEvent.click(screen.getByTestId('branch-switcher'));
    fireEvent.click(await screen.findByRole('button', { name: /Archive/ }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('precast', { status: 'archived' }));
  });
});
