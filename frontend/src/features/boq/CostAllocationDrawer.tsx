// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostAllocationDrawer - put one bill position's money on the cost structure.
//
// A position lands on one cost line, or is split across several by percent
// or by quantity. Targets are cost lines or accounts (an account gets a line
// for this bill made on save). The shares are summed exactly and compared
// with 100 % or the position quantity live, with the backend's 0.01 %
// tolerance, so the save button only lights up for a split the server will
// take. Whatever the server still refuses comes back as a translated problem.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Search, AlertTriangle, CheckCircle2 } from 'lucide-react';

import { Button, SideDrawer } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { costModelApi } from '@/features/costmodel/api';
import {
  costStructureApi,
  problemOf,
  type AllocationRowInput,
  type PositionAllocation,
  type SplitMode,
} from '@/features/costmodel/structureApi';
import { problemMessage } from '@/features/costmodel/problemMessages';
import { MAX_SHARE_DECIMALS, MAX_SHARES, checkShares, normalizeShare, splitPreview } from './allocationMath';

/** Longest search the cost-line endpoint takes (`max_length=200`). */
const MAX_SEARCH = 200;

export interface CostAllocationDrawerProps {
  open: boolean;
  onClose: () => void;
  projectId: string | undefined;
  /** The position's current allocation, from the bill's allocation list. */
  allocation: PositionAllocation | undefined;
  currency?: string;
}

interface Target {
  type: 'line' | 'account';
  id: string;
  code: string;
  label: string;
}

interface DraftRow {
  key: string;
  target: Target;
  share: string;
}

let rowSeq = 0;
const nextKey = () => `r${++rowSeq}`;

function draftFrom(allocation: PositionAllocation | undefined): { mode: SplitMode; rows: DraftRow[] } {
  if (!allocation || allocation.mode === 'none') return { mode: 'percent', rows: [] };
  const mode: SplitMode = allocation.mode === 'quantity' ? 'quantity' : 'percent';
  const rows = allocation.rows.map((r) => ({
    key: nextKey(),
    target: {
      type: 'line' as const,
      id: r.cost_line_id,
      code: r.cost_line_code,
      label: [r.account_code, r.cost_line_description || r.account_title].filter(Boolean).join(' · '),
    },
    // A single allocation is the whole position: 100 %.
    share: allocation.mode === 'single' ? '100' : trimShare(r.share),
  }));
  return { mode, rows };
}

/** A stored share ("30.000000") without its trailing zeros ("30"), exactly, as a decimal string. */
export function trimShare(share: string): string {
  return share.includes('.') ? share.replace(/0+$/, '').replace(/\.$/, '') : share;
}

/** A stored quantity ("610.0000") as people write it ("610"), in the user's number format. */
export function quantityLabel(quantity: string): string {
  const n = Number(quantity);
  if (!Number.isFinite(n)) return quantity;
  return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 4 }).format(n);
}

/** The share to suggest for a new row: whatever is still missing, if positive. */
function suggestedShare(remaining: string): string {
  return remaining.startsWith('-') || remaining === '0' ? '' : remaining;
}

export function CostAllocationDrawer({ open, onClose, projectId, allocation, currency }: CostAllocationDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<SplitMode>('percent');
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [serverError, setServerError] = useState<string | null>(null);

  // Reset the draft whenever the drawer opens on a position.
  const positionId = allocation?.position_id;
  useEffect(() => {
    if (!open) return;
    const d = draftFrom(allocation);
    setMode(d.mode);
    setRows(d.rows);
    setSearch('');
    setDebounced('');
    setServerError(null);
    // Only a new position (or reopening) resets; a refetch of the same one keeps the draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, positionId]);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(search.trim().slice(0, MAX_SEARCH)), 250);
    return () => clearTimeout(id);
  }, [search]);

  const accountsQuery = useQuery({
    queryKey: ['spine-accounts', projectId],
    queryFn: () => costModelApi.getSpineAccounts(projectId!),
    enabled: open && !!projectId,
    staleTime: 60_000,
  });
  const linesQuery = useQuery({
    queryKey: ['spine-lines-search', projectId, debounced],
    queryFn: () => costModelApi.getSpineLines(projectId!, { search: debounced || undefined, limit: 50 }),
    enabled: open && !!projectId,
    staleTime: 30_000,
  });

  const chosen = useMemo(() => new Set(rows.map((r) => `${r.target.type}:${r.target.id}`)), [rows]);
  const candidates = useMemo<Target[]>(() => {
    const q = debounced.toLowerCase();
    const accounts = (accountsQuery.data ?? [])
      .filter((a) => a.is_leaf_postable !== false && a.status !== 'closed')
      .filter((a) => !q || a.code.toLowerCase().includes(q) || (a.title || a.name).toLowerCase().includes(q))
      .slice(0, 30)
      .map((a) => ({ type: 'account' as const, id: a.id, code: a.code, label: a.title || a.name }));
    // A cost line that carries another bill is refused on save
    // (`line_of_other_bill`), so it is not offered.
    const boqId = allocation?.boq_id;
    const lines = (linesQuery.data ?? []).filter((l) => !l.boq_id || l.boq_id === boqId).map((l) => ({
      type: 'line' as const,
      id: l.id,
      code: l.code,
      label: l.description,
    }));
    return [...accounts, ...lines].filter((c) => !chosen.has(`${c.type}:${c.id}`));
  }, [accountsQuery.data, linesQuery.data, debounced, chosen, allocation?.boq_id]);
  const candidatesLoading = accountsQuery.isLoading || linesQuery.isLoading;
  const candidatesFailed = accountsQuery.isError || linesQuery.isError;

  const quantity = allocation?.quantity ?? '0';
  const check = checkShares(mode, rows.map((r) => r.share), quantity);
  const preview = splitPreview(allocation?.total ?? '0', rows.map((r) => r.share));
  const duplicate = chosen.size !== rows.length;
  const quantityless = mode === 'quantity' && checkShares('quantity', ['1'], quantity).expected === '0';
  const tooMany = rows.length > MAX_SHARES;
  const canSave =
    rows.length > 0 && check.sharesValid && check.addsUp && !check.tooPrecise && !tooMany && !duplicate && !quantityless;

  const invalidate = () => {
    if (allocation) queryClient.invalidateQueries({ queryKey: ['boq-allocations', allocation.boq_id] });
    queryClient.invalidateQueries({ queryKey: ['spine', projectId] });
    queryClient.invalidateQueries({ queryKey: ['cost-structure', projectId] });
  };
  const describe = (err: unknown) => {
    const problem = problemOf(err);
    return problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err);
  };

  const save = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => {
      const body: AllocationRowInput[] = rows.map((r) => {
        const share = normalizeShare(r.share) ?? r.share;
        return r.target.type === 'line'
          ? { cost_line_id: r.target.id, share }
          : { control_account_id: r.target.id, share };
      });
      return costStructureApi.putAllocation(allocation!.position_id, { mode, rows: body });
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (err) => setServerError(describe(err)),
  });
  const clear = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => costStructureApi.clearAllocation(allocation!.position_id),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (err) => setServerError(describe(err)),
  });
  const busy = save.isPending || clear.isPending;

  const addTarget = (target: Target) => {
    setServerError(null);
    setRows((prev) => [...prev, { key: nextKey(), target, share: prev.length === 0 && mode === 'percent' ? '100' : suggestedShare(check.remaining) }]);
  };
  const setShare = (key: string, share: string) => {
    setServerError(null);
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, share } : r)));
  };
  const removeRow = (key: string) => {
    setServerError(null);
    setRows((prev) => prev.filter((r) => r.key !== key));
  };
  const switchMode = (next: SplitMode) => {
    if (next === mode) return;
    setServerError(null);
    setMode(next);
    // Shares of one mode mean nothing in the other, so they are cleared.
    setRows((prev) => prev.map((r) => ({ ...r, share: '' })));
  };

  const money = (v: string) => formatCurrency(v, currency);
  const unitLabel = mode === 'percent' ? '%' : allocation?.unit || '';

  let status: React.ReactNode = null;
  if (duplicate) {
    status = problemMessage(t, 'duplicate_target');
  } else if (tooMany) {
    status = problemMessage(t, 'too_many_shares', { max: MAX_SHARES });
  } else if (quantityless) {
    status = problemMessage(t, 'quantity_split_without_quantity');
  } else if (rows.length > 0 && !check.sharesValid) {
    status = problemMessage(t, 'share_not_positive');
  } else if (check.tooPrecise) {
    status = problemMessage(t, 'share_too_precise', { max: MAX_SHARE_DECIMALS });
  } else if (rows.length > 0 && !check.addsUp) {
    status = problemMessage(t, 'shares_do_not_add_up', {
      total: `${check.total} ${unitLabel}`.trim(),
      expected: `${check.expected} ${unitLabel}`.trim(),
    });
  }

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={busy}
      backdropCloses={false}
      widthClass="max-w-2xl"
      title={t('boq.cost_allocation.drawer_title', { defaultValue: 'Cost allocation' })}
      subtitle={
        allocation ? (
          <span>
            <span className="font-mono">{allocation.ordinal}</span> {allocation.description}
            <span className="ms-2 text-content-tertiary">{money(allocation.total)}</span>
          </span>
        ) : undefined
      }
    >
      {!allocation ? (
        <p className="p-4 text-sm text-content-tertiary">
          {t('boq.cost_allocation.not_costed', {
            defaultValue: 'This position carries no money yet, so there is nothing to allocate.',
          })}
        </p>
      ) : (
        <div className="space-y-4 p-4" data-testid="cost-allocation-drawer">
          {!allocation.valid && allocation.problem && (
            <div className="flex items-start gap-2 rounded-md bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              {t('boq.cost_allocation.stored_invalid', {
                defaultValue: 'The stored split no longer adds up: {{reason}}',
                reason: problemMessage(t, allocation.problem, {
                  total: allocation.share_total,
                  expected: allocation.share_expected,
                }),
              })}
            </div>
          )}

          <fieldset className="flex items-center gap-4 text-sm">
            <legend className="sr-only">{t('boq.cost_allocation.mode', { defaultValue: 'Split by' })}</legend>
            <span className="text-xs text-content-tertiary">{t('boq.cost_allocation.mode', { defaultValue: 'Split by' })}</span>
            <label className="flex items-center gap-1.5">
              <input type="radio" name="alloc-mode" checked={mode === 'percent'} onChange={() => switchMode('percent')} />
              {t('boq.cost_allocation.mode_percent', { defaultValue: 'Percent' })}
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" name="alloc-mode" checked={mode === 'quantity'} onChange={() => switchMode('quantity')} />
              {t('boq.cost_allocation.mode_quantity', {
                defaultValue: 'Quantity (of {{quantity}} {{unit}})',
                quantity: quantityLabel(allocation.quantity),
                unit: allocation.unit,
              })}
            </label>
          </fieldset>

          <table className="w-full text-sm" data-testid="cost-allocation-rows">
            <thead>
              <tr className="text-start text-2xs uppercase text-content-tertiary">
                <th className="py-1 pe-2">{t('boq.cost_allocation.col_target', { defaultValue: 'Cost line or account' })}</th>
                <th className="w-28 py-1 pe-2 text-end">
                  {mode === 'percent'
                    ? t('boq.cost_allocation.col_share_pct', { defaultValue: 'Share %' })
                    : t('boq.cost_allocation.col_share_qty', { defaultValue: 'Quantity' })}
                </th>
                <th className="w-28 py-1 pe-2 text-end">{t('boq.cost_allocation.col_amount', { defaultValue: 'Amount' })}</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-3 text-center text-xs text-content-tertiary">
                    {t('boq.cost_allocation.no_rows', {
                      defaultValue: 'Not allocated. Pick a cost line or an account below.',
                    })}
                  </td>
                </tr>
              )}
              {rows.map((r, i) => (
                <tr key={r.key} className="border-t border-border-light">
                  <td className="py-1.5 pe-2">
                    <span className="me-1.5 rounded bg-surface-secondary px-1 py-0.5 text-2xs text-content-tertiary">
                      {r.target.type === 'account'
                        ? t('boq.cost_allocation.kind_account', { defaultValue: 'Account' })
                        : t('boq.cost_allocation.kind_line', { defaultValue: 'Cost line' })}
                    </span>
                    <span className="font-mono text-xs">{r.target.code}</span>
                    <span className="ms-1.5 text-content-secondary">{r.target.label}</span>
                  </td>
                  <td className="py-1.5 pe-2">
                    <input
                      type="text"
                      inputMode="decimal"
                      value={r.share}
                      onChange={(e) => setShare(r.key, e.target.value)}
                      aria-label={t('boq.cost_allocation.share_for', { defaultValue: 'Share for {{code}}', code: r.target.code })}
                      className="h-7 w-full rounded-md border border-border bg-surface-primary px-2 text-end tabular-nums"
                    />
                  </td>
                  <td className="py-1.5 pe-2 text-end tabular-nums text-content-secondary">{money(preview[i] ?? '0')}</td>
                  <td className="py-1.5">
                    <button
                      type="button"
                      onClick={() => removeRow(r.key)}
                      aria-label={t('boq.cost_allocation.remove_row', { defaultValue: 'Remove share' })}
                      className="text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            {rows.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-border">
                  <th className="py-1.5 pe-2 text-start text-xs font-semibold">
                    {t('boq.cost_allocation.sum', { defaultValue: 'Sum' })}
                  </th>
                  <td className="py-1.5 pe-2 text-end text-xs font-semibold tabular-nums" data-testid="cost-allocation-sum">
                    {check.total} / {check.expected} {unitLabel}
                  </td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            )}
          </table>

          <div aria-live="polite">
            {status ? (
              <p className="flex items-start gap-2 text-xs text-semantic-error" role="alert">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                {status}
              </p>
            ) : rows.length > 0 ? (
              <p className="flex items-center gap-2 text-xs text-semantic-success">
                <CheckCircle2 size={14} />
                {t('boq.cost_allocation.adds_up', { defaultValue: 'The shares add up.' })}
              </p>
            ) : null}
            {serverError && (
              <p className="mt-1 flex items-start gap-2 text-xs text-semantic-error" role="alert">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                {serverError}
              </p>
            )}
          </div>

          <div className="rounded-md border border-border-light">
            <div className="flex items-center gap-1.5 border-b border-border-light px-2 py-1.5">
              <Search size={13} className="text-content-tertiary" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('boq.cost_allocation.search', { defaultValue: 'Find a cost line or account by code or text' })}
                aria-label={t('boq.cost_allocation.search', { defaultValue: 'Find a cost line or account by code or text' })}
                maxLength={MAX_SEARCH}
                className="flex-1 bg-transparent text-sm outline-none"
              />
            </div>
            <ul className="max-h-56 overflow-y-auto p-1" data-testid="cost-allocation-candidates">
              {candidatesLoading && (
                <li className="px-2 py-2 text-xs text-content-tertiary">
                  {t('boq.cost_allocation.loading', { defaultValue: 'Loading cost lines and accounts...' })}
                </li>
              )}
              {!candidatesLoading && candidatesFailed && (
                <li className="flex items-center gap-2 px-2 py-2 text-xs text-semantic-error" role="alert">
                  <AlertTriangle size={13} className="shrink-0" />
                  {t('boq.cost_allocation.candidates_failed', {
                    defaultValue: 'Cost lines and accounts could not be loaded.',
                  })}
                  <button
                    type="button"
                    className="ms-auto text-oe-blue hover:underline"
                    onClick={() => {
                      if (accountsQuery.isError) void accountsQuery.refetch();
                      if (linesQuery.isError) void linesQuery.refetch();
                    }}
                  >
                    {t('common.retry', { defaultValue: 'Retry' })}
                  </button>
                </li>
              )}
              {!candidatesLoading && !candidatesFailed && candidates.length === 0 && (
                <li className="px-2 py-2 text-xs text-content-tertiary">
                  {t('boq.cost_allocation.no_candidates', { defaultValue: 'Nothing matches.' })}
                </li>
              )}
              {candidates.map((c) => (
                <li key={`${c.type}:${c.id}`}>
                  <button
                    type="button"
                    onClick={() => addTarget(c)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1 text-start text-sm hover:bg-surface-secondary"
                  >
                    <Plus size={12} className="text-oe-blue" />
                    <span className="rounded bg-surface-secondary px-1 py-0.5 text-2xs text-content-tertiary">
                      {c.type === 'account'
                        ? t('boq.cost_allocation.kind_account', { defaultValue: 'Account' })
                        : t('boq.cost_allocation.kind_line', { defaultValue: 'Cost line' })}
                    </span>
                    <span className="font-mono text-xs">{c.code}</span>
                    <span className="truncate text-content-secondary">{c.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-border-light pt-3">
            <Button
              variant="ghost"
              icon={<Trash2 size={14} />}
              disabled={allocation.mode === 'none' || busy}
              loading={clear.isPending}
              onClick={() => clear.mutate()}
            >
              {t('boq.cost_allocation.clear', { defaultValue: 'Remove allocation' })}
            </Button>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={onClose} disabled={busy}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button variant="primary" disabled={!canSave || busy} loading={save.isPending} onClick={() => save.mutate()}>
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          </div>
        </div>
      )}
    </SideDrawer>
  );
}
