// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Allowances & contingency register.
 *
 * The money an estimate carries but has not yet measured: provisional sums,
 * prime-cost sums and design / construction contingencies. Each allowance holds
 * an amount, and scope firms up by drawing down against it. The register rolls
 * the remaining allowances into the estimate total (per currency, never blended)
 * and shows how much has been spent against each.
 *
 * Money arrives from the API as Decimal-as-string; it is only ever formatted for
 * display (formatCurrency) or coerced to a finite number for a comparison
 * (toNum). We never do arithmetic that assumes a JS number on a wire value.
 */

import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { Plus, Trash2, TrendingDown, AlertTriangle, Wallet } from 'lucide-react';
import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { EstimateRollupCard } from '@/features/estimate-rollup';
import {
  ALLOWANCE_TYPES,
  ALLOWANCE_TYPE_DEFAULT_LABELS,
  allowanceTypeLabelKey,
  createAllowance,
  createDrawdown,
  deleteAllowance,
  fetchAllowances,
  fetchRegisterSummary,
  groupAllowancesByType,
  type Allowance,
  type AllowanceRegisterSummary,
  type AllowanceType,
  type CurrencyRollup,
} from './api';

interface Project {
  id: string;
  name: string;
}

const INPUT_CLS =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm ' +
  'text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none ' +
  'focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-900/40';

/** Localised label for an allowance type, with an English default. */
function useTypeLabel(): (type: AllowanceType) => string {
  const { t } = useTranslation();
  return (type: AllowanceType) =>
    t(allowanceTypeLabelKey(type), { defaultValue: ALLOWANCE_TYPE_DEFAULT_LABELS[type] });
}

/* ── Per-currency summary ──────────────────────────────────────────────── */

function CurrencySummary({ row }: { row: CurrencyRollup }) {
  const { t } = useTranslation();
  const remainingNegative = toNum(row.remaining) < 0;

  const tiles: { label: string; value: string; emphasis?: boolean; bad?: boolean }[] = [
    {
      label: t('allowances.total_held', { defaultValue: 'Total held' }),
      value: formatCurrency(row.held, row.currency),
    },
    {
      label: t('allowances.total_drawn', { defaultValue: 'Drawn down' }),
      value: formatCurrency(row.drawn, row.currency),
    },
    {
      label: t('allowances.total_remaining', { defaultValue: 'Remaining in estimate' }),
      value: formatCurrency(row.remaining, row.currency),
      emphasis: true,
      bad: remainingNegative,
    },
  ];

  return (
    <Card padding="sm">
      <div className="mb-2 flex items-center gap-2">
        <Wallet size={14} className="text-content-tertiary" />
        <span className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {row.currency || t('allowances.no_currency', { defaultValue: 'Unspecified currency' })}
        </span>
        {row.overdrawn && (
          <Badge variant="warning">{t('allowances.overdrawn', { defaultValue: 'Over-drawn' })}</Badge>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3">
        {tiles.map((tile) => (
          <div key={tile.label}>
            <div className="text-2xs uppercase tracking-wide text-content-tertiary">{tile.label}</div>
            <div
              className={
                'mt-1 font-bold tabular-nums ' +
                (tile.emphasis ? 'text-lg ' : 'text-base ') +
                (tile.bad ? 'text-semantic-error' : 'text-content-primary')
              }
            >
              {tile.value}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ── Add-allowance form ────────────────────────────────────────────────── */

function AddAllowanceForm({
  projectId,
  onAdded,
  onCancel,
}: {
  projectId: string;
  onAdded: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const typeLabel = useTypeLabel();
  const addToast = useToastStore((s) => s.addToast);
  const [label, setLabel] = useState('');
  const [type, setType] = useState<AllowanceType>('provisional_sum');
  const [held, setHeld] = useState('');
  const [currency, setCurrency] = useState('');

  const mutation = useMutation({
    mutationFn: () =>
      createAllowance(projectId, {
        label,
        allowance_type: type,
        held_amount: held || '0',
        currency: currency || undefined,
      }),
    onSuccess: () => {
      setLabel('');
      setHeld('');
      setCurrency('');
      setType('provisional_sum');
      onAdded();
      addToast({ type: 'success', title: t('allowances.added', { defaultValue: 'Allowance added' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('allowances.add_failed', { defaultValue: 'Could not add allowance' }),
        message: getErrorMessage(err),
      }),
  });

  return (
    <Card padding="md">
      <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-6">
        <div className="sm:col-span-2">
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('allowances.col_label', { defaultValue: 'Description' })}
          </label>
          <input
            className={INPUT_CLS}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('allowances.label_placeholder', { defaultValue: 'e.g. Kitchen fit-out PC sum' })}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('allowances.col_type', { defaultValue: 'Type' })}
          </label>
          <select
            className={INPUT_CLS}
            value={type}
            onChange={(e) => setType(e.target.value as AllowanceType)}
            aria-label={t('allowances.col_type', { defaultValue: 'Type' })}
          >
            {ALLOWANCE_TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {typeLabel(tp)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('allowances.col_held', { defaultValue: 'Held amount' })}
          </label>
          <input
            className={INPUT_CLS}
            inputMode="decimal"
            value={held}
            onChange={(e) => setHeld(e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('allowances.col_currency', { defaultValue: 'Currency' })}
          </label>
          <input
            className={INPUT_CLS}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            placeholder="USD"
            maxLength={3}
          />
        </div>
        <div className="col-span-2 flex items-center gap-2 sm:col-span-6">
          <Button
            variant="primary"
            size="sm"
            disabled={mutation.isPending || !label.trim()}
            onClick={() => mutation.mutate()}
          >
            <Plus size={14} className="mr-1 shrink-0" />
            {t('allowances.create', { defaultValue: 'Add allowance' })}
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/* ── Add-drawdown inline form ──────────────────────────────────────────── */

function DrawdownForm({
  allowance,
  onDone,
  onCancel,
}: {
  allowance: Allowance;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');

  const mutation = useMutation({
    mutationFn: () => createDrawdown(allowance.id, { amount: amount || '0', note: note || undefined }),
    onSuccess: () => {
      onDone();
      addToast({ type: 'success', title: t('allowances.drawdown_added', { defaultValue: 'Drawdown recorded' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('allowances.drawdown_failed', { defaultValue: 'Could not record drawdown' }),
        message: getErrorMessage(err),
      }),
  });

  return (
    <div className="grid grid-cols-2 items-end gap-2 rounded-lg border border-dashed border-border-light bg-surface-secondary/40 p-3 sm:grid-cols-6">
      <input
        className={INPUT_CLS}
        inputMode="decimal"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        placeholder={t('allowances.drawdown_amount', { defaultValue: 'Amount to draw' })}
        aria-label={t('allowances.drawdown_amount', { defaultValue: 'Amount to draw' })}
      />
      <input
        className={`${INPUT_CLS} sm:col-span-3`}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={t('allowances.drawdown_note', { defaultValue: 'Note (what firmed up)' })}
        aria-label={t('allowances.drawdown_note', { defaultValue: 'Note (what firmed up)' })}
      />
      <Button
        variant="secondary"
        size="sm"
        disabled={mutation.isPending || toNum(amount) <= 0}
        onClick={() => mutation.mutate()}
      >
        {t('allowances.record', { defaultValue: 'Record' })}
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
    </div>
  );
}

/* ── Register table ────────────────────────────────────────────────────── */

function RegisterTable({
  allowances,
  openDrawdownFor,
  onOpenDrawdown,
  onCloseDrawdown,
  onDrawdownDone,
  onDelete,
}: {
  allowances: Allowance[];
  openDrawdownFor: string | null;
  onOpenDrawdown: (id: string) => void;
  onCloseDrawdown: () => void;
  onDrawdownDone: () => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const typeLabel = useTypeLabel();
  const groups = useMemo(() => groupAllowancesByType(allowances), [allowances]);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
            <th className="py-2 pr-3 font-medium">{t('allowances.col_label', { defaultValue: 'Description' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('allowances.col_held', { defaultValue: 'Held' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('allowances.col_drawn', { defaultValue: 'Drawn' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('allowances.col_remaining', { defaultValue: 'Remaining' })}</th>
            <th className="py-2 pl-1" />
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <Fragment key={group.type}>
              <tr className="bg-surface-secondary/40">
                <td
                  colSpan={5}
                  className="py-1.5 pl-1 text-2xs font-semibold uppercase tracking-wide text-content-secondary"
                >
                  {typeLabel(group.type)}
                </td>
              </tr>
              {group.items.map((a) => {
                const remainingNegative = toNum(a.remaining) < 0;
                return (
                  <Fragment key={a.id}>
                    <tr className="border-b border-border-light/60 hover:bg-surface-secondary/40">
                      <td className="py-2 pr-3 text-content-primary">
                        <span className="inline-flex items-center gap-1.5">
                          {a.label || '-'}
                          {a.overdrawn && (
                            <span title={t('allowances.overdrawn', { defaultValue: 'Over-drawn' })}>
                              <AlertTriangle size={13} className="text-amber-500" />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                        {formatCurrency(a.held_amount, a.currency)}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-content-tertiary">
                        {formatCurrency(a.drawn, a.currency)}
                      </td>
                      <td
                        className={
                          'py-2 pr-3 text-right font-semibold tabular-nums ' +
                          (remainingNegative ? 'text-semantic-error' : 'text-content-primary')
                        }
                      >
                        {formatCurrency(a.remaining, a.currency)}
                      </td>
                      <td className="py-2 pl-1">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => onOpenDrawdown(a.id)}
                            className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-2xs font-medium text-oe-blue hover:bg-blue-50 dark:hover:bg-blue-900/20"
                          >
                            <TrendingDown size={13} />
                            {t('allowances.draw_down', { defaultValue: 'Draw down' })}
                          </button>
                          <button
                            type="button"
                            onClick={() => onDelete(a.id)}
                            className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                            aria-label={t('allowances.delete', { defaultValue: 'Delete allowance' })}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {openDrawdownFor === a.id && (
                      <tr>
                        <td colSpan={5} className="py-2">
                          <DrawdownForm allowance={a} onDone={onDrawdownDone} onCancel={onCloseDrawdown} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function AllowancesPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';

  const [showAdd, setShowAdd] = useState(false);
  const [openDrawdownFor, setOpenDrawdownFor] = useState<string | null>(null);

  const {
    data: allowances = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['allowances', projectId],
    queryFn: () => fetchAllowances(projectId),
    enabled: !!projectId,
  });

  const { data: summary } = useQuery<AllowanceRegisterSummary>({
    queryKey: ['allowances-summary', projectId],
    queryFn: () => fetchRegisterSummary(projectId),
    enabled: !!projectId,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['allowances', projectId] });
    qc.invalidateQueries({ queryKey: ['allowances-summary', projectId] });
  };

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteAllowance(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('allowances.deleted', { defaultValue: 'Allowance deleted' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('allowances.delete_failed', { defaultValue: 'Could not delete allowance' }),
        message: getErrorMessage(err),
      }),
  });

  const currencyRows = useMemo(() => summary?.by_currency ?? [], [summary]);

  if (!projectId) {
    return <RequiresProject>{null}</RequiresProject>;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        srTitle={t('allowances.title', { defaultValue: 'Allowances & contingency' })}
        subtitle={t('allowances.subtitle', {
          defaultValue:
            'Track provisional sums, prime-cost sums and contingencies carried in the estimate, and draw them down as scope firms up.',
        })}
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowAdd((v) => !v)}>
            <Plus size={16} className="mr-1.5 shrink-0" />
            {t('allowances.new', { defaultValue: 'New allowance' })}
          </Button>
        }
      />

      {/* How the remaining allowances roll into the whole estimate total. */}
      <EstimateRollupCard projectId={projectId} />

      {showAdd && (
        <AddAllowanceForm
          projectId={projectId}
          onAdded={() => {
            invalidate();
            setShowAdd(false);
          }}
          onCancel={() => setShowAdd(false)}
        />
      )}

      {/* Per-currency summary (remaining is the figure carried into the estimate) */}
      {currencyRows.length > 0 && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {currencyRows.map((row) => (
            <CurrencySummary key={row.currency || '_'} row={row} />
          ))}
        </div>
      )}

      <Card padding="md">
        <h2 className="mb-3 text-sm font-semibold text-content-primary">
          {t('allowances.register', { defaultValue: 'Register' })}
        </h2>
        {isLoading ? (
          <SkeletonTable rows={4} columns={5} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : allowances.length === 0 ? (
          <EmptyState
            title={t('allowances.empty_title', { defaultValue: 'No allowances yet' })}
            description={t('allowances.empty_desc', {
              defaultValue:
                'Add a provisional sum, prime-cost sum or contingency to carry it in the estimate before it is measured.',
            })}
          />
        ) : (
          <RegisterTable
            allowances={allowances}
            openDrawdownFor={openDrawdownFor}
            onOpenDrawdown={(id) => setOpenDrawdownFor(id)}
            onCloseDrawdown={() => setOpenDrawdownFor(null)}
            onDrawdownDone={() => {
              setOpenDrawdownFor(null);
              invalidate();
            }}
            onDelete={(id) => deleteMut.mutate(id)}
          />
        )}
      </Card>
    </div>
  );
}

export default AllowancesPage;
