// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PdfCompareDrawer — takeoff revision compare with cost delta (Item 17).
 *
 * PDF takeoffs have no version table, so a revision compare runs between
 * two uploaded documents (the user uploads revision A and revision B as
 * separate PDFs). The drawer diffs the measurement sets of the two
 * documents and surfaces:
 *   - Measurements tab: added / removed / modified / unchanged rows, with
 *     a money cost impact for any measurement linked to a BOQ position
 *     whose value changed.
 *   - Summary tab: traffic-light tallies + net cost impact.
 *
 * Money is rendered with the shared MoneyDisplay (green/red) and never
 * blends currencies — the backend returns the impact already expressed in
 * the project base currency.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  GitCompare,
  Loader2,
  ArrowRight,
  BarChart3,
  MessageSquare,
  FilePlus2,
  AlertTriangle,
} from 'lucide-react';

import { SideDrawer, MoneyDisplay, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  takeoffApi,
  type TakeoffDocumentResponse,
  type TakeoffCompareResponse,
  type TakeoffMeasurementDiffRow,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

type CompareTab = 'measurements' | 'summary';

export interface PdfCompareDrawerProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Documents already loaded by the page (avoids a second fetch). */
  documents: TakeoffDocumentResponse[];
  /** The document currently open in the viewer (seeds the 'after' side). */
  currentDocumentId?: string | null;
  /** Opens with this pair selected (e.g. from a BOQ line on a revised drawing). */
  initialFromId?: string | null;
  initialToId?: string | null;
}

const CHANGE_DOT: Record<TakeoffMeasurementDiffRow['change_type'], string> = {
  added: 'bg-emerald-500',
  removed: 'bg-red-500',
  modified: 'bg-amber-500',
  unchanged: 'bg-slate-400',
};

function ChangeBadge({ type }: { type: TakeoffMeasurementDiffRow['change_type'] }) {
  const { t } = useTranslation();
  const label = t(`takeoff_compare.change_${type}`, {
    defaultValue:
      type === 'added'
        ? 'Added'
        : type === 'removed'
          ? 'Removed'
          : type === 'modified'
            ? 'Modified'
            : 'Unchanged',
  });
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-content-secondary">
      <span className={clsx('h-2 w-2 rounded-full', CHANGE_DOT[type])} />
      {label}
    </span>
  );
}

export function PdfCompareDrawer({
  open,
  onClose,
  projectId,
  documents,
  currentDocumentId,
  initialFromId,
  initialToId,
}: PdfCompareDrawerProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<CompareTab>('summary');
  const [fromId, setFromId] = useState<string>('');
  const [toId, setToId] = useState<string>('');
  const [hideUnchanged, setHideUnchanged] = useState(true);

  // Seed defaults: target = current doc (or newest), baseline = the next
  // newest different document. ``documents`` is page-ordered newest-first.
  useEffect(() => {
    if (documents.length === 0) return;
    const newest = documents[0];
    if (!newest) return;
    const target = currentDocumentId || newest.id;
    setToId((cur) => cur || target);
    const baseline = documents.find((d) => d.id !== target) ?? newest;
    setFromId((cur) => cur || baseline.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documents, currentDocumentId]);

  useEffect(() => {
    if (!open || !initialFromId || !initialToId) return;
    setFromId(initialFromId);
    setToId(initialToId);
  }, [open, initialFromId, initialToId]);

  const canCompare = !!fromId && !!toId && fromId !== toId && !!projectId;

  const diffQuery = useQuery<TakeoffCompareResponse>({
    queryKey: ['takeoff-compare', projectId, fromId, toId],
    queryFn: () => takeoffApi.compare(projectId, fromId, toId),
    enabled: open && canCompare,
  });

  const diff = diffQuery.data;

  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  // The diff has a real change when any tally bucket other than "unchanged"
  // is non-zero. With no change there is nothing to turn into a variation.
  const hasChanges = useMemo(() => {
    if (!diff) return false;
    const m = diff.summary.measurements;
    return (m.added ?? 0) + (m.removed ?? 0) + (m.modified ?? 0) > 0;
  }, [diff]);

  const createVariationMutation = useMutation({
    mutationFn: () => {
      if (!canCompare) throw new Error('no comparison selected');
      return takeoffApi.createVariation(projectId, fromId, toId);
    },
    onSuccess: (result) => {
      addToast(
        {
          type: 'success',
          title: t('takeoff_compare.variation_created', {
            defaultValue: 'Draft variation {{code}} created',
            code: result.code,
          }),
          message: t('takeoff_compare.variation_created_hint', {
            defaultValue: 'Review and confirm it in the variations module before submitting.',
          }),
          action: {
            label: t('takeoff_compare.view_variation', { defaultValue: 'View variation' }),
            onClick: () => navigate('/variations'),
          },
        },
        { duration: 8000 },
      );
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('takeoff_compare.variation_error', {
          defaultValue: 'Could not create the variation. Please try again.',
        }),
      });
    },
  });

  const rows = useMemo(
    () =>
      (diff?.measurement_rows ?? []).filter(
        (r) => !hideUnchanged || r.change_type !== 'unchanged',
      ),
    [diff, hideUnchanged],
  );

  const tabs: { id: CompareTab; label: string; icon: typeof BarChart3; count: number }[] = [
    {
      id: 'summary',
      label: t('takeoff_compare.tab_summary', { defaultValue: 'Summary' }),
      icon: BarChart3,
      count: 0,
    },
    {
      id: 'measurements',
      label: t('takeoff_compare.tab_measurements', { defaultValue: 'Measurements' }),
      icon: MessageSquare,
      count: rows.length,
    },
  ];

  const docLabel = (d: TakeoffDocumentResponse) => `${d.filename} (${d.pages}p)`;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      widthClass="max-w-2xl"
      title={
        <span className="inline-flex items-center gap-2">
          <GitCompare size={16} className="text-oe-blue" />
          {t('takeoff_compare.title', { defaultValue: 'Compare revisions' })}
        </span>
      }
      subtitle={t('takeoff_compare.subtitle', {
        defaultValue: 'Diff two takeoff PDFs with cost delta',
      })}
    >
      <div className="flex flex-col gap-4 p-5">
        {/* Document pickers */}
        <div className="flex items-end gap-2">
          <label className="flex-1 min-w-0">
            <span className="block text-[11px] font-medium text-content-tertiary mb-1">
              {t('takeoff_compare.from_document', { defaultValue: 'Baseline (before)' })}
            </span>
            <select
              value={fromId}
              onChange={(e) => setFromId(e.target.value)}
              disabled={documents.length === 0}
              data-testid="takeoff-compare-from"
              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue"
            >
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {docLabel(d)}
                </option>
              ))}
            </select>
          </label>
          <ArrowRight size={16} className="mb-2 shrink-0 text-content-tertiary" />
          <label className="flex-1 min-w-0">
            <span className="block text-[11px] font-medium text-content-tertiary mb-1">
              {t('takeoff_compare.to_document', { defaultValue: 'Target (after)' })}
            </span>
            <select
              value={toId}
              onChange={(e) => setToId(e.target.value)}
              disabled={documents.length === 0}
              data-testid="takeoff-compare-to"
              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue"
            >
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {docLabel(d)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {documents.length < 2 && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-content-secondary">
            {t('takeoff_compare.need_two_documents', {
              defaultValue:
                'You need at least two uploaded takeoff PDFs to compare. Upload an updated revision to compare against the current one.',
            })}
          </p>
        )}

        {fromId === toId && documents.length >= 2 && (
          <p className="text-xs text-content-tertiary">
            {t('takeoff_compare.pick_two', {
              defaultValue: 'Pick two different documents to compare.',
            })}
          </p>
        )}

        {/* Hide unchanged */}
        <div className="border-y border-border-light py-2">
          <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={hideUnchanged}
              onChange={(e) => setHideUnchanged(e.target.checked)}
              data-testid="takeoff-compare-hide-unchanged"
              className="h-3.5 w-3.5 accent-oe-blue"
            />
            {t('takeoff_compare.hide_unchanged', { defaultValue: 'Hide unchanged' })}
          </label>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 rounded-lg bg-surface-secondary p-1">
          {tabs.map(({ id, label, icon: Icon, count }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              data-testid={`takeoff-compare-tab-${id}`}
              className={clsx(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors',
                tab === id
                  ? 'bg-surface-elevated text-oe-blue shadow-sm'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              <Icon size={13} />
              <span className="truncate">{label}</span>
              {count > 0 && (
                <Badge variant="neutral" className="ml-0.5 text-[9px]">
                  {count}
                </Badge>
              )}
            </button>
          ))}
        </div>

        {/* States */}
        {canCompare && diffQuery.isLoading && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
            {t('takeoff_compare.loading', { defaultValue: 'Computing diff…' })}
          </div>
        )}
        {canCompare && diffQuery.isError && (
          <p className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-500">
            {t('takeoff_compare.error', {
              defaultValue: 'Could not compute the comparison. Please try again.',
            })}
          </p>
        )}

        {diff && !diffQuery.isLoading && (
          <>
            {tab === 'summary' && (
              <SummaryTab
                diff={diff}
                canCreateVariation={hasChanges && canCompare}
                creating={createVariationMutation.isPending}
                onCreateVariation={() => createVariationMutation.mutate()}
              />
            )}
            {tab === 'measurements' && <MeasurementsTab rows={rows} hideUnchanged={hideUnchanged} />}
          </>
        )}
      </div>
    </SideDrawer>
  );
}

/* ── Summary tab ───────────────────────────────────────────────────────── */

function SummaryTab({
  diff,
  canCreateVariation,
  creating,
  onCreateVariation,
}: {
  diff: TakeoffCompareResponse;
  canCreateVariation: boolean;
  creating: boolean;
  onCreateVariation: () => void;
}) {
  const { t } = useTranslation();
  const { summary } = diff;
  const tally = summary.measurements;
  const rows: { key: 'added' | 'removed' | 'modified'; color: string; label: string }[] = [
    { key: 'added', color: 'text-emerald-500', label: t('takeoff_compare.change_added', { defaultValue: 'Added' }) },
    { key: 'removed', color: 'text-red-500', label: t('takeoff_compare.change_removed', { defaultValue: 'Removed' }) },
    { key: 'modified', color: 'text-amber-500', label: t('takeoff_compare.change_modified', { defaultValue: 'Modified' }) },
  ];
  return (
    <div className="flex flex-col gap-4">
      {/* The backend stops at a row ceiling on very large revisions. Saying so
          matters more than the tally itself: a silent cap reads as "nothing
          else changed", which is exactly the wrong conclusion to hand someone
          pricing a variation off this screen. */}
      {summary.truncated && (
        <div
          data-testid="takeoff-compare-truncated"
          className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" />
          <p className="text-xs text-content-secondary">
            {t('takeoff_compare.truncated_notice', {
              defaultValue:
                'Only the first {{n}} measurements of each revision were compared. Changes beyond that limit are not counted below.',
              n: summary.truncation_limit ?? summary.from_measurement_count,
            })}
          </p>
        </div>
      )}

      <div className="rounded-lg border border-border-light p-3">
        <div className="text-[11px] font-medium text-content-tertiary mb-2">
          {t('takeoff_compare.measurements_heading', { defaultValue: 'Measurement changes' })}
        </div>
        <div className="flex flex-col gap-1">
          {rows.map(({ key, color, label }) => (
            <div key={key} className="flex items-center justify-between text-xs">
              <span className={color}>{label}</span>
              <span className="tabular-nums font-semibold text-content-primary">{tally[key] ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border-light p-3">
        <div className="text-[11px] font-medium text-content-tertiary mb-1">
          {t('takeoff_compare.net_cost_impact', { defaultValue: 'Net cost impact' })}
        </div>
        {summary.net_cost_impact != null && summary.cost_currency ? (
          <MoneyDisplay
            amount={summary.net_cost_impact}
            currency={summary.cost_currency}
            colorize
            className="text-lg font-semibold"
          />
        ) : (
          <p className="text-xs text-content-tertiary">
            {t('takeoff_compare.no_cost_impact', {
              defaultValue:
                'No cost impact - no linked BOQ measurement changed value between these revisions.',
            })}
          </p>
        )}

        {/* Create-variation-from-delta handoff (Item 17). Disabled when the
            two documents are identical / there are no changes. Creates a
            DRAFT variation the user confirms in the variations module. */}
        <button
          type="button"
          onClick={onCreateVariation}
          disabled={!canCreateVariation || creating}
          data-testid="takeoff-compare-create-variation"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-oe-blue px-3 py-2 text-xs font-semibold text-white transition hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {creating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <FilePlus2 size={14} />
          )}
          {t('takeoff_compare.create_variation', { defaultValue: 'Create variation from delta' })}
        </button>
        {!canCreateVariation && (
          <p className="mt-1 text-[10px] text-content-tertiary">
            {t('takeoff_compare.create_variation_disabled', {
              defaultValue: 'Pick two documents with at least one change to raise a variation.',
            })}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-content-secondary">
        <span>
          {t('takeoff_compare.count_from', {
            defaultValue: 'Before: {{n}} measurements',
            n: summary.from_measurement_total,
          })}
        </span>
        <ArrowRight size={13} className="text-content-tertiary" />
        <span>
          {t('takeoff_compare.count_to', {
            defaultValue: 'After: {{n}} measurements',
            n: summary.to_measurement_total,
          })}
        </span>
      </div>
    </div>
  );
}

/* ── Measurements tab ──────────────────────────────────────────────────── */

function MeasurementsTab({
  rows,
  hideUnchanged,
}: {
  rows: TakeoffMeasurementDiffRow[];
  hideUnchanged: boolean;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-content-tertiary">
        {hideUnchanged
          ? t('takeoff_compare.no_changes', { defaultValue: 'No measurement changes between these revisions.' })
          : t('takeoff_compare.no_measurements', { defaultValue: 'No measurements on either revision.' })}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => (
        <div
          key={r.measurement_id}
          className="rounded-lg border border-border-light p-3"
          data-testid="takeoff-compare-row"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-content-primary truncate">
              {r.label || `${r.group_name} · ${r.type}`}
            </span>
            <ChangeBadge type={r.change_type} />
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-xs text-content-secondary">
            <span className="text-[10px] text-content-tertiary">
              {t('takeoff_compare.page_n', { defaultValue: 'p.{{n}}', n: r.page })}
            </span>
            <span className="tabular-nums">{r.old_value != null ? fmtFixed(r.old_value, 2) : '—'}</span>
            <ArrowRight size={12} className="text-content-tertiary" />
            <span className="tabular-nums font-medium text-content-primary">
              {r.new_value != null ? fmtFixed(r.new_value, 2) : '—'}
            </span>
            {r.measurement_unit && <span className="text-content-tertiary">{r.measurement_unit}</span>}
          </div>
          {r.linked_boq_position_id && (
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <span className="text-[10px] text-content-tertiary">
                {t('takeoff_compare.linked_boq', { defaultValue: 'Linked to BOQ position' })}
              </span>
              {r.cost_impact != null && r.cost_currency ? (
                <MoneyDisplay
                  amount={r.cost_impact}
                  currency={r.cost_currency}
                  colorize
                  className="text-xs font-semibold"
                />
              ) : (
                <span className="text-[10px] text-content-tertiary">
                  {t('takeoff_compare.no_value_change', { defaultValue: 'No value change' })}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
