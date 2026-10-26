// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dialog writes nothing while a conflict has no decision, sends exactly the
// lines that stay ticked with the decisions taken on them, and a merge needs an
// explicit confirmation.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CherryPickDialog, type CherryPickMode } from './CherryPickDialog';
import { branchApi, type ApplyPlan, type BranchNode } from './branchApi';

function node(id: string, isMain: boolean, parent: string | null = null): BranchNode {
  return {
    boq_id: id,
    name: isMain ? 'Main estimate' : `Branch ${id}`,
    is_main: isMain,
    parent_boq_id: parent,
    status: 'open',
    note: '',
    is_locked: false,
    created_at: '2026-10-20T10:00:00Z',
    created_by: null,
    author: 'Estimator',
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
  };
}

const nodes = [node('main', true), node('b1', false, 'main'), node('b2', false, 'main')];

const plan: ApplyPlan = {
  source_boq_id: 'b1',
  target_boq_id: 'b2',
  base_known: true,
  conflicts: 1,
  items: [
    {
      key: 'k1',
      action: 'update',
      conflict: true,
      ordinal: '1.1',
      description: 'Slab',
      is_section: false,
      parent_key: null,
      depth: 0,
      fields: { unit_rate: { base: '120', source: '110', target: '125' } },
    },
    {
      key: 'k2',
      action: 'add',
      conflict: false,
      ordinal: '1.4',
      description: 'Precast beams',
      is_section: false,
      parent_key: null,
      depth: 0,
      fields: {},
    },
  ],
};

const result = {
  target_boq_id: 'b2',
  snapshot_id: 's1',
  added: 1,
  updated: 1,
  removed: 0,
  kept_target: 0,
  skipped: [],
  status: null,
};

function renderDialog(mode: CherryPickMode, currentBoqId: string, onApplied = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CherryPickDialog
        mode={mode}
        nodes={nodes}
        currentBoqId={currentBoqId}
        isOpen
        onClose={vi.fn()}
        onApplied={onApplied}
      />
    </QueryClientProvider>,
  );
  return onApplied;
}

describe('CherryPickDialog', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('keeps apply disabled until every selected conflict is decided, then sends the choice', async () => {
    const planSpy = vi.spyOn(branchApi, 'plan').mockResolvedValue(plan);
    const pick = vi.spyOn(branchApi, 'cherryPick').mockResolvedValue(result);
    const onApplied = renderDialog('cherry-pick', 'b2');

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b1' } });
    await waitFor(() => expect(planSpy).toHaveBeenCalledWith('b2', 'b1'));
    expect(await screen.findAllByTestId('plan-item')).toHaveLength(2);
    expect(screen.getByText('110')).toBeInTheDocument();
    expect(screen.getByText('125')).toBeInTheDocument();

    const apply = screen.getByRole('button', { name: /Apply selected/ });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Keep the version here'));
    expect(apply).not.toBeDisabled();
    fireEvent.click(apply);
    await waitFor(() => expect(pick).toHaveBeenCalledWith('b2', 'b1', ['k1', 'k2'], { k1: 'target' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith('b2'));
  });

  it('unticking the conflicting line drops its decision and lets the rest through', async () => {
    vi.spyOn(branchApi, 'plan').mockResolvedValue(plan);
    const pick = vi.spyOn(branchApi, 'cherryPick').mockResolvedValue(result);
    renderDialog('cherry-pick', 'b2');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b1' } });
    fireEvent.click(await screen.findByLabelText('1.1 Slab'));
    fireEvent.click(screen.getByRole('button', { name: /Apply selected/ }));
    await waitFor(() => expect(pick).toHaveBeenCalledWith('b2', 'b1', ['k2'], {}));
  });

  it('a merge targets main, takes every line and needs the confirmation', async () => {
    const planSpy = vi.spyOn(branchApi, 'plan').mockResolvedValue({ ...plan, conflicts: 0, items: [plan.items[1]!] });
    const merge = vi.spyOn(branchApi, 'merge').mockResolvedValue({ ...result, target_boq_id: 'main', status: 'merged' });
    renderDialog('merge', 'b1');
    await waitFor(() => expect(planSpy).toHaveBeenCalledWith('main', 'b1'));
    await screen.findAllByTestId('plan-item');
    expect(screen.getByLabelText('1.4 Precast beams')).toBeDisabled();
    const button = screen.getByRole('button', { name: /^Merge$/ });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/rewrites the main estimate/));
    fireEvent.click(button);
    await waitFor(() => expect(merge).toHaveBeenCalledWith('b1', {}, false));
  });

  it('warns when the branch point is unknown', async () => {
    vi.spyOn(branchApi, 'plan').mockResolvedValue({ ...plan, base_known: false });
    renderDialog('cherry-pick', 'b2');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'b1' } });
    expect(await screen.findByText(/branch point snapshot is gone/)).toBeInTheDocument();
  });
});
