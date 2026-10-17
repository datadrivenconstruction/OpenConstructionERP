// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Read-only "Cost allocation" cell of the BOQ grid: where a position's money
// lands on the cost structure. One target shows its account and cost line
// codes, a split shows how many parts it has, and a position on nothing shows
// an unallocated marker. Clicking the cell opens the allocation drawer; the
// cell itself never edits.

import type { ICellRendererParams } from 'ag-grid-community';
import { AlertTriangle, GitFork } from 'lucide-react';

import type { PositionAllocation } from '@/features/costmodel/structureApi';

type T = (key: string, opts?: Record<string, string | number>) => string;

/** What the grid context carries for this column. */
export interface CostAllocationGridContext {
  t?: T;
  /** Allocation of every costed position of the bill, keyed by position id. */
  costAllocations?: Map<string, PositionAllocation>;
  /** Opens the allocation drawer for a position. */
  onOpenCostAllocation?: (positionId: string) => void;
}

export type AllocationCellView =
  | { kind: 'single'; label: string; valid: boolean; suspense: boolean }
  | { kind: 'split'; parts: number; valid: boolean; suspense: boolean }
  | { kind: 'none' };

/** How a position's allocation reads in one cell. */
export function allocationCellView(allocation: PositionAllocation): AllocationCellView {
  if (allocation.mode === 'none' || allocation.rows.length === 0) return { kind: 'none' };
  if (allocation.mode === 'single' || allocation.rows.length === 1) {
    const row = allocation.rows[0]!;
    const label = [row.account_code, row.cost_line_code].filter(Boolean).join(' · ');
    // A one-row quantity split goes stale like any split when the position is
    // remeasured, so validity travels with the single view as well.
    return {
      kind: 'single',
      label: label || row.cost_line_description,
      valid: allocation.valid,
      suspense: Boolean(allocation.in_suspense),
    };
  }
  return { kind: 'split', parts: allocation.rows.length, valid: allocation.valid, suspense: Boolean(allocation.in_suspense) };
}

/** Used only when the grid context carries no `t`: the English default, interpolated. */
const fallbackT: T = (key, opts) =>
  String(opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));

export function CostAllocationCellRenderer(params: ICellRendererParams) {
  const { data } = params;
  const ctx = params.context as CostAllocationGridContext | undefined;
  if (!data || data._isFooter || data._isSection || data._isResource || data._isAddResource) return null;
  const id = data.id as string | undefined;
  const allocation = id ? ctx?.costAllocations?.get(id) : undefined;
  if (!id || !allocation) return null;
  const t = ctx?.t ?? fallbackT;
  const view = allocationCellView(allocation);
  const open = () => ctx?.onOpenCostAllocation?.(id);

  let content: React.ReactNode;
  let title: string;
  if (view.kind === 'single' && !view.valid) {
    title = t('boq.cost_allocation.invalid_tip', {
      defaultValue: 'The shares no longer add up, for example after the quantity changed. Click to fix them.',
    });
    content = (
      <span className="inline-flex min-w-0 items-center gap-1 text-2xs text-semantic-error">
        <AlertTriangle size={11} className="shrink-0" />
        <span className="truncate font-mono">{view.label}</span>
      </span>
    );
  } else if (view.kind === 'single' && view.suspense) {
    // On a cost line, yet on no account: the money sits in suspense, not on the structure.
    title = t('boq.cost_allocation.suspense_tip', {
      defaultValue: 'Its cost line has no account, so the money sits in suspense. Click to move it onto an account.',
    });
    content = (
      <span className="inline-flex min-w-0 items-center gap-1 text-2xs text-amber-700 dark:text-amber-300">
        <AlertTriangle size={11} className="shrink-0" />
        <span className="shrink-0 font-medium">{t('boq.cost_allocation.suspense_cell', { defaultValue: 'No account' })}</span>
        <span className="truncate font-mono text-content-tertiary">{view.label}</span>
      </span>
    );
  } else if (view.kind === 'single') {
    title = t('boq.cost_allocation.single_tip', {
      defaultValue: 'On one cost line. Click to split or move it.',
    });
    content = <span className="truncate font-mono text-2xs text-content-primary">{view.label}</span>;
  } else if (view.kind === 'split') {
    const warn = !view.valid || view.suspense;
    title = !view.valid
      ? t('boq.cost_allocation.invalid_tip', {
          defaultValue: 'The shares no longer add up, for example after the quantity changed. Click to fix them.',
        })
      : view.suspense
        ? t('boq.cost_allocation.suspense_tip', {
            defaultValue: 'Its cost line has no account, so the money sits in suspense. Click to move it onto an account.',
          })
        : t('boq.cost_allocation.split_tip', { defaultValue: 'Split across several cost lines. Click to see the shares.' });
    const tone = !view.valid ? 'text-semantic-error' : view.suspense ? 'text-amber-700 dark:text-amber-300' : 'text-oe-blue';
    content = (
      <span className={`inline-flex items-center gap-1 text-2xs ${tone}`}>
        {warn ? <AlertTriangle size={11} /> : <GitFork size={11} />}
        {t('boq.cost_allocation.split_cell', { defaultValue: 'Split ({{parts}})', parts: view.parts })}
      </span>
    );
  } else {
    title = t('boq.cost_allocation.none_tip', {
      defaultValue: 'Not on any cost line, so its money is missing from cost control. Click to allocate it.',
    });
    content = (
      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-2xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
        {t('boq.cost_allocation.none_cell', { defaultValue: 'Unallocated' })}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        open();
      }}
      title={title}
      data-testid={`cost-allocation-cell-${id}`}
      className="flex h-full w-full min-w-0 items-center text-start hover:underline"
    >
      {content}
    </button>
  );
}
