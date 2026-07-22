// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Preliminaries (general conditions) estimator.
 *
 * Prices the project preliminaries that sit alongside the measured work: site
 * establishment, site staff, temporary works, standing plant and welfare. Each
 * item is either time-related (a rate per period times the number of periods it
 * stands on site) or a fixed one-off. The page keeps two editable tables and
 * shows live category subtotals and a grand preliminaries total that adds to the
 * estimate.
 *
 * Money arrives from the API as Decimal-as-string; it is only ever formatted for
 * display (formatCurrency). The live totals are computed with the pure preview
 * math in ./api (cent-rounded, drift-free); the backend summary is authoritative.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { Plus, Trash2, Clock, Package, Lightbulb } from 'lucide-react';
import { Button, Card, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { EstimateRollupCard } from '@/features/estimate-rollup';
import {
  fetchPrelimItems,
  createPrelimItem,
  updatePrelimItem,
  deletePrelimItem,
  fetchPreliminariesSummary,
  fetchStarterChecklist,
  previewRollup,
  previewLineTotal,
  PRELIM_CATEGORIES,
  type PrelimItem,
  type PrelimItemType,
  type PrelimLineLike,
  type StarterChecklistItem,
} from './api';

interface Project {
  id: string;
  name: string;
}

const INPUT_CLS =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm ' +
  'text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none ' +
  'focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-900/40';

const NUM_CLS = INPUT_CLS + ' text-right tabular-nums';

/** One editable row in a table (lifted so the totals recompute as you type). */
interface EditableRow {
  id: string;
  label: string;
  category: string;
  item_type: PrelimItemType;
  rate_per_period: string;
  periods: string;
  fixed_amount: string;
  sort_order: number;
  dirty: boolean;
}

function toEditable(item: PrelimItem): EditableRow {
  return {
    id: item.id,
    label: item.label ?? '',
    category: item.category ?? 'general',
    item_type: item.item_type,
    rate_per_period: item.rate_per_period ?? '0',
    periods: item.periods ?? '0',
    fixed_amount: item.fixed_amount ?? '0',
    sort_order: item.sort_order ?? 0,
    dirty: false,
  };
}

/**
 * Merge freshly loaded server items into the working rows: keep unsaved (dirty)
 * local edits, refresh clean rows from the server, add new ids and drop removed
 * ones. This lets a save or an add refresh the list without clobbering a value
 * the user is still typing elsewhere.
 */
function reconcile(prev: EditableRow[], server: PrelimItem[]): EditableRow[] {
  const prevById = new Map(prev.map((row): [string, EditableRow] => [row.id, row]));
  return server.map((item) => {
    const existing = prevById.get(item.id);
    return existing && existing.dirty ? existing : toEditable(item);
  });
}

/** A money string safe to send: blank becomes "0" so the Decimal parse succeeds. */
function money(value: string): string {
  return value.trim() === '' ? '0' : value.trim();
}

function humanize(key: string): string {
  return key
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function useCategoryLabel(): (key: string) => string {
  const { t } = useTranslation();
  return (key: string) =>
    t(`preliminaries.category_${key}`, { defaultValue: humanize(key) });
}

export function PreliminariesPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const categoryLabel = useCategoryLabel();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';

  const {
    data: itemsData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['prelim-items', projectId],
    queryFn: () => fetchPrelimItems(projectId),
    enabled: !!projectId,
  });

  // Authoritative server roll-up (shown as a confirmation alongside the live one).
  const { data: serverSummary } = useQuery({
    queryKey: ['prelim-summary', projectId],
    queryFn: () => fetchPreliminariesSummary(projectId),
    enabled: !!projectId,
  });

  const { data: checklist = [] } = useQuery({
    queryKey: ['prelim-checklist'],
    queryFn: fetchStarterChecklist,
    staleTime: 30 * 60_000,
  });

  const [rows, setRows] = useState<EditableRow[]>([]);

  // Reconcile server items into the working rows whenever the list changes. The
  // dependency is the query data object - a stable reference until it actually
  // changes - never a freshly defaulted array, so this never re-runs in a loop.
  useEffect(() => {
    if (itemsData) setRows((prev) => reconcile(prev, itemsData));
  }, [itemsData]);

  const liveRollup = useMemo(() => previewRollup(rows as PrelimLineLike[]), [rows]);

  const invalidateSummary = () =>
    qc.invalidateQueries({ queryKey: ['prelim-summary', projectId] });

  const saveRowMut = useMutation({
    mutationFn: (row: EditableRow) =>
      updatePrelimItem(
        row.id,
        row.item_type === 'fixed'
          ? { label: row.label, category: row.category, fixed_amount: money(row.fixed_amount) }
          : {
              label: row.label,
              category: row.category,
              rate_per_period: money(row.rate_per_period),
              periods: money(row.periods),
            },
      ),
    onSuccess: (saved) => {
      setRows((prev) => prev.map((r) => (r.id === saved.id ? toEditable(saved) : r)));
      invalidateSummary();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('preliminaries.save_failed', { defaultValue: 'Could not save the item' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePrelimItem(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prelim-items', projectId] });
      invalidateSummary();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('preliminaries.delete_failed', { defaultValue: 'Could not delete the item' }),
        message: getErrorMessage(err),
      }),
  });

  const createMut = useMutation({
    mutationFn: (payload: { item_type: PrelimItemType; label: string; category: string }) =>
      createPrelimItem({
        project_id: projectId,
        item_type: payload.item_type,
        label: payload.label,
        category: payload.category,
        sort_order: rows.length,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prelim-items', projectId] });
      invalidateSummary();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('preliminaries.add_failed', { defaultValue: 'Could not add the item' }),
        message: getErrorMessage(err),
      }),
  });

  const patchRow = (id: string, patch: Partial<EditableRow>) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch, dirty: true } : r)));

  const saveRow = (id: string) => {
    const row = rows.find((r) => r.id === id);
    if (row && row.dirty) saveRowMut.mutate(row);
  };

  if (!projectId) {
    return <RequiresProject>{null}</RequiresProject>;
  }

  const timeRows = rows.filter((r) => r.item_type === 'time_related');
  const fixedRows = rows.filter((r) => r.item_type === 'fixed');

  return (
    <div className="space-y-6">
      <PageHeader
        srTitle={t('preliminaries.title', { defaultValue: 'Preliminaries' })}
        subtitle={t('preliminaries.subtitle', {
          defaultValue:
            'Price the general conditions - site establishment, staff, temporary works, standing plant and welfare - as time-related items times the project duration plus fixed one-offs. The total adds to the estimate alongside the measured work.',
        })}
      />

      {/* How these preliminaries roll into the whole estimate total. */}
      <EstimateRollupCard projectId={projectId} />

      {isLoading ? (
        <SkeletonTable rows={5} columns={5} />
      ) : isError ? (
        <RecoveryCard error={error} onRetry={() => refetch()} />
      ) : (
        <>
          <SummaryStrip
            grandTotal={liveRollup.grandTotal}
            timeTotal={liveRollup.timeRelatedTotal}
            fixedTotal={liveRollup.fixedTotal}
            itemCount={liveRollup.itemCount}
            serverGrandTotal={serverSummary?.grand_total}
          />

          {liveRollup.categories.length > 0 && (
            <CategoryBreakdown rollup={liveRollup} categoryLabel={categoryLabel} />
          )}

          <StarterChecklistBar
            checklist={checklist}
            disabled={createMut.isPending}
            categoryLabel={categoryLabel}
            onPick={(suggestion) =>
              createMut.mutate({
                item_type: suggestion.item_type,
                label: suggestion.label,
                category: suggestion.category,
              })
            }
          />

          <ItemsTable
            kind="time_related"
            rows={timeRows}
            subtotal={liveRollup.timeRelatedTotal}
            categoryLabel={categoryLabel}
            onPatch={patchRow}
            onSave={saveRow}
            onDelete={(id) => deleteMut.mutate(id)}
            onAdd={(label, category) =>
              createMut.mutate({ item_type: 'time_related', label, category })
            }
            adding={createMut.isPending}
          />

          <ItemsTable
            kind="fixed"
            rows={fixedRows}
            subtotal={liveRollup.fixedTotal}
            categoryLabel={categoryLabel}
            onPatch={patchRow}
            onSave={saveRow}
            onDelete={(id) => deleteMut.mutate(id)}
            onAdd={(label, category) => createMut.mutate({ item_type: 'fixed', label, category })}
            adding={createMut.isPending}
          />
        </>
      )}
    </div>
  );
}

/* ── Summary strip ─────────────────────────────────────────────────────── */

function SummaryStrip({
  grandTotal,
  timeTotal,
  fixedTotal,
  itemCount,
  serverGrandTotal,
}: {
  grandTotal: number;
  timeTotal: number;
  fixedTotal: number;
  itemCount: number;
  serverGrandTotal: string | undefined;
}) {
  const { t } = useTranslation();
  const tiles = [
    {
      label: t('preliminaries.time_related_total', { defaultValue: 'Time-related' }),
      value: formatCurrency(timeTotal),
    },
    {
      label: t('preliminaries.fixed_total', { defaultValue: 'Fixed one-off' }),
      value: formatCurrency(fixedTotal),
    },
    {
      label: t('preliminaries.grand_total', { defaultValue: 'Preliminaries total' }),
      value: formatCurrency(grandTotal),
      strong: true,
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {tiles.map((tile) => (
        <Card key={tile.label} padding="sm">
          <div className="text-2xs uppercase tracking-wide text-content-tertiary">{tile.label}</div>
          <div
            className={
              'mt-1 tabular-nums ' +
              (tile.strong ? 'text-2xl font-bold text-content-primary' : 'text-lg font-semibold text-content-secondary')
            }
          >
            {tile.value}
          </div>
          {tile.strong && (
            <div className="mt-0.5 text-xs text-content-tertiary">
              {t('preliminaries.item_count', {
                defaultValue: '{{count}} items',
                count: itemCount,
              })}
              {serverGrandTotal !== undefined && (
                <span className="ml-1">
                  {t('preliminaries.server_confirmed', {
                    defaultValue: '(saved: {{value}})',
                    value: formatCurrency(serverGrandTotal),
                  })}
                </span>
              )}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

/* ── Category breakdown (live subtotals) ───────────────────────────────── */

function CategoryBreakdown({
  rollup,
  categoryLabel,
}: {
  rollup: ReturnType<typeof previewRollup>;
  categoryLabel: (key: string) => string;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <h2 className="mb-3 text-sm font-semibold text-content-primary">
        {t('preliminaries.by_category', { defaultValue: 'By category' })}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-2 pr-3 font-medium">{t('preliminaries.col_category', { defaultValue: 'Category' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.time_related_total', { defaultValue: 'Time-related' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.fixed_total', { defaultValue: 'Fixed' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.col_total', { defaultValue: 'Total' })}</th>
            </tr>
          </thead>
          <tbody>
            {rollup.categories.map((cat) => (
              <tr key={cat.category} className="border-b border-border-light/60">
                <td className="py-2 pr-3 font-medium text-content-primary">{categoryLabel(cat.category)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{formatCurrency(cat.timeRelatedTotal)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{formatCurrency(cat.fixedTotal)}</td>
                <td className="py-2 pr-3 text-right font-semibold tabular-nums text-content-primary">{formatCurrency(cat.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border-light font-semibold text-content-primary">
              <td className="py-2 pr-3">{t('preliminaries.grand_total', { defaultValue: 'Preliminaries total' })}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(rollup.timeRelatedTotal)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(rollup.fixedTotal)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(rollup.grandTotal)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

/* ── Starter checklist ─────────────────────────────────────────────────── */

function StarterChecklistBar({
  checklist,
  disabled,
  categoryLabel,
  onPick,
}: {
  checklist: StarterChecklistItem[];
  disabled: boolean;
  categoryLabel: (key: string) => string;
  onPick: (item: StarterChecklistItem) => void;
}) {
  const { t } = useTranslation();
  if (checklist.length === 0) return null;
  return (
    <Card padding="md">
      <div className="mb-2 flex items-center gap-2">
        <Lightbulb size={16} className="shrink-0 text-amber-500" />
        <h2 className="text-sm font-semibold text-content-primary">
          {t('preliminaries.checklist_title', { defaultValue: 'Common preliminaries' })}
        </h2>
      </div>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('preliminaries.checklist_hint', {
          defaultValue: 'Add a common item, then fill in the rate and duration (or a fixed amount).',
        })}
      </p>
      <div className="flex flex-wrap gap-2">
        {checklist.map((suggestion) => (
          <button
            key={`${suggestion.category}:${suggestion.label}`}
            type="button"
            disabled={disabled}
            onClick={() => onPick(suggestion)}
            title={categoryLabel(suggestion.category)}
            className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-3 py-1 text-xs text-content-secondary hover:border-oe-blue hover:text-content-primary disabled:opacity-50"
          >
            <Plus size={12} className="shrink-0" />
            {suggestion.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

/* ── Items table (editable) ────────────────────────────────────────────── */

function ItemsTable({
  kind,
  rows,
  subtotal,
  categoryLabel,
  onPatch,
  onSave,
  onDelete,
  onAdd,
  adding,
}: {
  kind: PrelimItemType;
  rows: EditableRow[];
  subtotal: number;
  categoryLabel: (key: string) => string;
  onPatch: (id: string, patch: Partial<EditableRow>) => void;
  onSave: (id: string) => void;
  onDelete: (id: string) => void;
  onAdd: (label: string, category: string) => void;
  adding: boolean;
}) {
  const { t } = useTranslation();
  const isTime = kind === 'time_related';
  const title = isTime
    ? t('preliminaries.time_related_items', { defaultValue: 'Time-related items' })
    : t('preliminaries.fixed_items', { defaultValue: 'Fixed one-off items' });
  const Icon = isTime ? Clock : Package;

  return (
    <Card padding="md">
      <div className="mb-3 flex items-center gap-2">
        <Icon size={16} className="shrink-0 text-content-tertiary" />
        <h2 className="text-sm font-semibold text-content-primary">{title}</h2>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title={t('preliminaries.no_items', { defaultValue: 'No items yet' })}
          description={
            isTime
              ? t('preliminaries.no_time_items_desc', {
                  defaultValue: 'Add resources that stand on site for a duration and price them per period.',
                })
              : t('preliminaries.no_fixed_items_desc', {
                  defaultValue: 'Add one-off charges such as mobilisation, set-up or the final clean.',
                })
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pr-3 font-medium">{t('preliminaries.col_item', { defaultValue: 'Item' })}</th>
                <th className="py-2 pr-3 font-medium">{t('preliminaries.col_category', { defaultValue: 'Category' })}</th>
                {isTime ? (
                  <>
                    <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.col_rate', { defaultValue: 'Rate / period' })}</th>
                    <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.col_periods', { defaultValue: 'Periods' })}</th>
                  </>
                ) : (
                  <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.col_amount', { defaultValue: 'Amount' })}</th>
                )}
                <th className="py-2 pr-3 text-right font-medium">{t('preliminaries.col_line_total', { defaultValue: 'Line total' })}</th>
                <th className="py-2 pl-1" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-border-light/60">
                  <td className="py-1.5 pr-3">
                    <input
                      className={INPUT_CLS}
                      value={row.label}
                      placeholder={t('preliminaries.item_placeholder', { defaultValue: 'Description' })}
                      aria-label={t('preliminaries.col_item', { defaultValue: 'Item' })}
                      onChange={(e) => onPatch(row.id, { label: e.target.value })}
                      onBlur={() => onSave(row.id)}
                    />
                  </td>
                  <td className="py-1.5 pr-3">
                    <select
                      className={INPUT_CLS}
                      value={row.category}
                      aria-label={t('preliminaries.col_category', { defaultValue: 'Category' })}
                      onChange={(e) => onPatch(row.id, { category: e.target.value })}
                      onBlur={() => onSave(row.id)}
                    >
                      {(PRELIM_CATEGORIES.includes(row.category as (typeof PRELIM_CATEGORIES)[number])
                        ? [...PRELIM_CATEGORIES]
                        : [...PRELIM_CATEGORIES, row.category]
                      ).map((key) => (
                        <option key={key} value={key}>
                          {categoryLabel(key)}
                        </option>
                      ))}
                    </select>
                  </td>
                  {isTime ? (
                    <>
                      <td className="py-1.5 pr-3">
                        <input
                          className={NUM_CLS}
                          inputMode="decimal"
                          value={row.rate_per_period}
                          aria-label={t('preliminaries.col_rate', { defaultValue: 'Rate / period' })}
                          onChange={(e) => onPatch(row.id, { rate_per_period: e.target.value })}
                          onBlur={() => onSave(row.id)}
                        />
                      </td>
                      <td className="py-1.5 pr-3">
                        <input
                          className={NUM_CLS}
                          inputMode="decimal"
                          value={row.periods}
                          aria-label={t('preliminaries.col_periods', { defaultValue: 'Periods' })}
                          onChange={(e) => onPatch(row.id, { periods: e.target.value })}
                          onBlur={() => onSave(row.id)}
                        />
                      </td>
                    </>
                  ) : (
                    <td className="py-1.5 pr-3">
                      <input
                        className={NUM_CLS}
                        inputMode="decimal"
                        value={row.fixed_amount}
                        aria-label={t('preliminaries.col_amount', { defaultValue: 'Amount' })}
                        onChange={(e) => onPatch(row.id, { fixed_amount: e.target.value })}
                        onBlur={() => onSave(row.id)}
                      />
                    </td>
                  )}
                  <td className="py-1.5 pr-3 text-right font-semibold tabular-nums text-content-primary">
                    {formatCurrency(previewLineTotal(row as PrelimLineLike))}
                  </td>
                  <td className="py-1.5 pl-1 text-right">
                    <button
                      type="button"
                      onClick={() => onDelete(row.id)}
                      className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                      aria-label={t('preliminaries.delete_item', { defaultValue: 'Delete item' })}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border-light font-semibold text-content-primary">
                <td className="py-2 pr-3" colSpan={isTime ? 4 : 3}>
                  {t('preliminaries.subtotal', { defaultValue: 'Subtotal' })}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(subtotal)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <AddItemForm kind={kind} categoryLabel={categoryLabel} disabled={adding} onAdd={onAdd} />
    </Card>
  );
}

/* ── Add item form ─────────────────────────────────────────────────────── */

function AddItemForm({
  kind,
  categoryLabel,
  disabled,
  onAdd,
}: {
  kind: PrelimItemType;
  categoryLabel: (key: string) => string;
  disabled: boolean;
  onAdd: (label: string, category: string) => void;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState('');
  const [category, setCategory] = useState<string>(kind === 'time_related' ? 'site_staff' : 'general');

  const submit = () => {
    const trimmed = label.trim();
    if (!trimmed) return;
    onAdd(trimmed, category);
    setLabel('');
  };

  return (
    <div className="mt-3 grid grid-cols-1 items-end gap-2 rounded-lg border border-dashed border-border-light p-3 sm:grid-cols-6">
      <input
        className={`${INPUT_CLS} sm:col-span-3`}
        value={label}
        placeholder={t('preliminaries.add_placeholder', { defaultValue: 'New item description' })}
        aria-label={t('preliminaries.col_item', { defaultValue: 'Item' })}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit();
        }}
      />
      <select
        className={`${INPUT_CLS} sm:col-span-2`}
        value={category}
        aria-label={t('preliminaries.col_category', { defaultValue: 'Category' })}
        onChange={(e) => setCategory(e.target.value)}
      >
        {PRELIM_CATEGORIES.map((key) => (
          <option key={key} value={key}>
            {categoryLabel(key)}
          </option>
        ))}
      </select>
      <Button variant="secondary" size="sm" disabled={disabled || !label.trim()} onClick={submit}>
        <Plus size={14} className="mr-1 shrink-0" />
        {t('preliminaries.add', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}
