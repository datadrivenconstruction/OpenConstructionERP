// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  CopyPlus,
  CheckCheck,
} from 'lucide-react';

import { SideDrawer, MoneyDisplay, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  takeoffApi,
  type CarryAlignOptions,
  type TakeoffDocumentResponse,
  type TakeoffCompareResponse,
  type TakeoffMeasurementDiffRow,
  type TakeoffPositionDelta,
} from './api';
import { getErrorMessage } from '@/shared/lib/api';
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

  const queryClient = useQueryClient();
  const refreshCompare = () =>
    queryClient.invalidateQueries({ queryKey: ['takeoff-compare', projectId, fromId, toId] });

  const carryMutation = useMutation({
    mutationFn: (opts?: CarryAlignOptions) =>
      opts
        ? takeoffApi.carryOver(projectId, fromId, toId, opts)
        : takeoffApi.carryOver(projectId, fromId, toId),
    onSuccess: (r) => {
      refreshCompare();
      const rescaled = (r.scale_checks.changed ?? 0) + (r.scale_checks.unverified ?? 0);
      addToast(
        {
          type: r.carried > 0 ? 'success' : 'info',
          title: t('takeoff_compare.carry_done', {
            defaultValue: '{{n}} measurements carried onto the new revision',
            n: r.carried,
          }),
          message: [
            r.already_carried > 0
              ? t('takeoff_compare.carry_already', {
                  defaultValue: '{{n}} were carried before.',
                  n: r.already_carried,
                })
              : '',
            rescaled > 0
              ? t('takeoff_compare.carry_scale_hint', {
                  defaultValue: '{{n}} sit on a sheet with a different or missing scale: check them first.',
                  n: rescaled,
                })
              : '',
            (r.remeasure_ids?.length ?? 0) > 0
              ? t('takeoff_compare.carry_remeasure', {
                  defaultValue: '{{n}} could not be placed with enough confidence: measure them again.',
                  n: r.remeasure_ids?.length ?? 0,
                })
              : '',
            r.revision_link !== 'register'
              ? t('takeoff_compare.carry_unlinked', {
                  defaultValue: 'Project Files does not link these two files as revisions of one drawing.',
                })
              : '',
          ]
            .filter(Boolean)
            .join(' '),
        },
        { duration: 8000 },
      );
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const [pushQuantity, setPushQuantity] = useState(false);
  const confirmMutation = useMutation({
    mutationFn: (ids: string[]) => takeoffApi.confirmCarried(projectId, ids, pushQuantity),
    onSuccess: (r) => {
      refreshCompare();
      if (r.pushed > 0) queryClient.invalidateQueries({ queryKey: ['boq'] });
      addToast({
        type: 'success',
        title: t('takeoff_compare.carry_confirmed', {
          defaultValue: '{{n}} carried measurements confirmed',
          n: r.confirmed,
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const pendingIds = useMemo(
    () =>
      (diff?.measurement_rows ?? [])
        .filter((r) => r.carry_status === 'needs_review')
        .map((r) => r.measurement_id),
    [diff],
  );

  const rows = useMemo(
    () =>
      (diff?.measurement_rows ?? []).filter(
        (r) => !hideUnchanged || r.change_type !== 'unchanged' || r.carry_status === 'needs_review',
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

        {canCompare && (
          <button
            type="button"
            onClick={() =>
              navigate(`/drawing-compare?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`)
            }
            className="inline-flex items-center gap-1.5 self-start text-xs font-medium text-oe-blue hover:underline"
            data-testid="takeoff-compare-visual"
          >
            <GitCompare size={13} />
            {t('takeoff_compare.open_visual', { defaultValue: 'Compare the sheets visually and list every change' })}
          </button>
        )}

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
              <>
                <CarryOverPanel
                  canCarry={canCompare && (diff.summary.from_measurement_total ?? 0) > 0}
                  carrying={carryMutation.isPending}
                  onCarry={(opts) => carryMutation.mutate(opts)}
                  projectId={projectId}
                  fromId={fromId}
                  toId={toId}
                  pendingCount={pendingIds.length}
                  confirming={confirmMutation.isPending}
                  onConfirmAll={() => confirmMutation.mutate(pendingIds)}
                  pushQuantity={pushQuantity}
                  onPushQuantity={setPushQuantity}
                />
                <PositionDeltas deltas={diff.summary.position_deltas ?? []} currency={diff.summary.cost_currency} />
                <SummaryTab
                  diff={diff}
                  canCreateVariation={hasChanges && canCompare}
                  creating={createVariationMutation.isPending}
                  onCreateVariation={() => createVariationMutation.mutate()}
                />
              </>
            )}
            {tab === 'measurements' && (
              <MeasurementsTab
                rows={rows}
                hideUnchanged={hideUnchanged}
                confirming={confirmMutation.isPending}
                onConfirm={(id) => confirmMutation.mutate([id])}
              />
            )}
          </>
        )}
      </div>
    </SideDrawer>
  );
}

/* ── Carry-over onto the new revision ──────────────────────────────────── */

function CarryOverPanel({
  canCarry,
  carrying,
  onCarry,
  projectId,
  fromId,
  toId,
  pendingCount,
  confirming,
  onConfirmAll,
  pushQuantity,
  onPushQuantity,
}: {
  canCarry: boolean;
  carrying: boolean;
  onCarry: (opts?: CarryAlignOptions) => void;
  projectId: string;
  fromId: string;
  toId: string;
  pendingCount: number;
  confirming: boolean;
  onConfirmAll: () => void;
  pushQuantity: boolean;
  onPushQuantity: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-4 rounded-lg border border-border-light p-3" data-testid="takeoff-carry-panel">
      <div className="text-[11px] font-medium text-content-tertiary mb-1">
        {t('takeoff_compare.carry_heading', { defaultValue: 'Carry measurements to the new revision' })}
      </div>
      <p className="text-[11px] text-content-secondary">
        {t('takeoff_compare.carry_hint', {
          defaultValue:
            'Copies every confirmed measurement of the baseline onto the target at the same place, re-checks the scale, and marks each copy for review.',
        })}
      </p>
      <button
        type="button"
        onClick={() => onCarry()}
        disabled={!canCarry || carrying}
        data-testid="takeoff-carry-over"
        className="mt-2 inline-flex items-center gap-2 rounded-md border border-oe-blue px-3 py-1.5 text-xs font-semibold text-oe-blue transition hover:bg-oe-blue/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {carrying ? <Loader2 size={14} className="animate-spin" /> : <CopyPlus size={14} />}
        {t('takeoff_compare.carry_action', { defaultValue: 'Carry measurements' })}
      </button>
      <CarryAlignment
        enabled={canCarry && !carrying}
        projectId={projectId}
        fromId={fromId}
        toId={toId}
        onCarry={onCarry}
      />
      {pendingCount > 0 && (
        <div
          className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-2"
          data-testid="takeoff-carry-pending"
        >
          <p className="text-xs text-content-primary">
            {t('takeoff_compare.carry_pending', {
              defaultValue: '{{n}} carried measurements need review on the new sheet.',
              n: pendingCount,
            })}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-1.5 text-[11px] text-content-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={pushQuantity}
                onChange={(e) => onPushQuantity(e.target.checked)}
                className="h-3.5 w-3.5 accent-oe-blue"
              />
              {t('takeoff_compare.carry_push', { defaultValue: 'Also update the linked BOQ quantities' })}
            </label>
            <button
              type="button"
              onClick={onConfirmAll}
              disabled={confirming}
              data-testid="takeoff-carry-confirm-all"
              className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-50"
            >
              <CheckCheck size={13} />
              {t('takeoff_compare.carry_confirm_all', { defaultValue: 'Confirm all after review' })}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sheet match + alignment preview (writes nothing until accepted) ────── */

const BAND_CLASS: Record<string, string> = {
  high: 'bg-emerald-500/10 text-emerald-600',
  review: 'bg-amber-500/10 text-amber-600',
  remeasure: 'bg-red-500/10 text-red-500',
};

function CarryAlignment({
  enabled,
  projectId,
  fromId,
  toId,
  onCarry,
}: {
  enabled: boolean;
  projectId: string;
  fromId: string;
  toId: string;
  onCarry: (opts?: CarryAlignOptions) => void;
}) {
  const { t } = useTranslation();
  const [pageMap, setPageMap] = useState<Record<number, number>>({});
  const previewMutation = useMutation({
    mutationFn: (map?: Record<number, number>) =>
      takeoffApi.previewCarryOver(projectId, fromId, toId, map),
  });
  const previewError = previewMutation.isError ? getErrorMessage(previewMutation.error) : '';
  const preview = previewMutation.data;
  const counts = { high: 0, review: 0, remeasure: 0 } as Record<string, number>;
  for (const it of preview?.items ?? []) counts[it.band] = (counts[it.band] ?? 0) + 1;
  const highIds = (preview?.items ?? []).filter((i) => i.band === 'high').map((i) => i.measurement_id);
  const newPages = (preview?.pages ?? []).map((p) => p.new).filter((n): n is number => n != null);
  const pageOptions = Array.from(new Set([...newPages, ...Object.values(pageMap)])).sort((a, b) => a - b);

  return (
    <div className="mt-3 border-t border-border-light pt-3" data-testid="takeoff-carry-align">
      <p className="text-[11px] text-content-secondary">
        {t('takeoff_compare.carry_align_hint', {
          defaultValue:
            'Sheets moved or inserted? Match the pages by sheet number and title first, and see how sure each placement is before anything is copied.',
        })}
      </p>
      <button
        type="button"
        onClick={() => previewMutation.mutate(Object.keys(pageMap).length ? pageMap : undefined)}
        disabled={!enabled || previewMutation.isPending}
        data-testid="takeoff-carry-preview"
        className="mt-2 inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs font-semibold text-content-primary transition hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {previewMutation.isPending && <Loader2 size={14} className="animate-spin" />}
        {t('takeoff_compare.carry_match_pages', { defaultValue: 'Match pages' })}
      </button>
      {previewError && (
        <p role="alert" className="mt-2 text-[11px] text-semantic-error" data-testid="takeoff-carry-preview-error">
          {previewError}
        </p>
      )}
      {preview && preview.pages.length === 0 && (
        <p className="mt-2 text-[11px] text-content-tertiary">
          {t('takeoff_compare.carry_no_pages', { defaultValue: 'No pages could be matched between the two revisions.' })}
        </p>
      )}
      {preview && (
        <div className="mt-2" data-testid="takeoff-carry-preview-result">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-start text-content-tertiary">
                <th className="py-1 font-medium">
                  {t('takeoff_compare.carry_page_old', { defaultValue: 'Old page' })}
                </th>
                <th className="py-1 font-medium">
                  {t('takeoff_compare.carry_page_new', { defaultValue: 'New page' })}
                </th>
                <th className="py-1 text-end font-medium">
                  {t('takeoff_compare.carry_page_score', { defaultValue: 'Match' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {preview.pages.map((p) => (
                <tr key={p.old} className="border-t border-border-light">
                  <td className="py-1 tabular-nums">{p.old}</td>
                  <td className="py-1">
                    <select
                      aria-label={t('takeoff_compare.carry_page_override', {
                        defaultValue: 'New page for old page {{n}}',
                        n: p.old,
                      })}
                      value={pageMap[p.old] ?? p.new ?? ''}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setPageMap((m) => (v ? { ...m, [p.old]: v } : m));
                      }}
                      className="rounded border border-border bg-surface-primary px-1 py-0.5 text-[11px]"
                    >
                      {p.new == null && !pageMap[p.old] && <option value="">-</option>}
                      {pageOptions.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-1 text-end tabular-nums text-content-secondary" title={p.method}>
                    {p.new == null ? '-' : `${Math.round(p.score * 100)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {(['high', 'review', 'remeasure'] as const).map((band) => (
              <span
                key={band}
                className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${BAND_CLASS[band]}`}
              >
                {t(`takeoff_compare.carry_band_${band}`, { defaultValue: band })}: {counts[band] ?? 0}
              </span>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => previewMutation.mutate(Object.keys(pageMap).length ? pageMap : undefined)}
              disabled={previewMutation.isPending || Object.keys(pageMap).length === 0}
              className="rounded-md border border-border px-2.5 py-1 text-[11px] font-semibold disabled:opacity-50"
            >
              {t('takeoff_compare.carry_recheck', { defaultValue: 'Re-check with my pages' })}
            </button>
            <button
              type="button"
              onClick={() => onCarry({ align: 'auto', pageMap, measurementIds: highIds })}
              disabled={!enabled || highIds.length === 0}
              data-testid="takeoff-carry-accept-high"
              className="rounded-md border border-oe-blue px-2.5 py-1 text-[11px] font-semibold text-oe-blue disabled:opacity-50"
            >
              {t('takeoff_compare.carry_accept_high', { defaultValue: 'Carry high confidence only' })}
            </button>
            <button
              type="button"
              onClick={() => onCarry({ align: 'auto', pageMap })}
              disabled={!enabled}
              data-testid="takeoff-carry-accept-all"
              className="rounded-md bg-oe-blue px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-50"
            >
              {t('takeoff_compare.carry_accept_matched', { defaultValue: 'Carry matched, review each' })}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PositionDeltas({ deltas, currency }: { deltas: TakeoffPositionDelta[]; currency: string | null }) {
  const { t } = useTranslation();
  if (deltas.length === 0) return null;
  return (
    <div className="mb-4 rounded-lg border border-border-light p-3" data-testid="takeoff-position-deltas">
      <div className="text-[11px] font-medium text-content-tertiary mb-2">
        {t('takeoff_compare.position_deltas', { defaultValue: 'Quantity change per BOQ position' })}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] text-content-tertiary">
            <th className="text-left font-medium pb-1">{t('takeoff_compare.position', { defaultValue: 'Position' })}</th>
            <th className="text-right font-medium pb-1">{t('takeoff_compare.qty_in_boq', { defaultValue: 'In BOQ' })}</th>
            <th className="text-right font-medium pb-1">{t('takeoff_compare.qty_before', { defaultValue: 'Before' })}</th>
            <th className="text-right font-medium pb-1">{t('takeoff_compare.qty_after', { defaultValue: 'After' })}</th>
            <th className="text-right font-medium pb-1">{t('takeoff_compare.qty_delta', { defaultValue: 'Delta' })}</th>
            <th className="text-right font-medium pb-1">{t('takeoff_compare.cost', { defaultValue: 'Cost' })}</th>
          </tr>
        </thead>
        <tbody>
          {deltas.map((d) => (
            <tr key={d.position_id} className="border-t border-border-light" data-testid="takeoff-position-delta">
              <td className="py-1 pr-2 truncate max-w-[10rem]" title={d.description ?? undefined}>
                <span className="font-medium text-content-primary">{d.ordinal ?? '?'}</span>
                {d.carried_pending > 0 && (
                  <Badge variant="warning" className="ml-1 text-[9px]">
                    {t('takeoff_compare.carried_pending_short', {
                      defaultValue: '{{n}} to review',
                      n: d.carried_pending,
                    })}
                  </Badge>
                )}
              </td>
              <td className="py-1 text-end tabular-nums text-content-tertiary">
                {d.boq_quantity != null ? fmtFixed(Number(d.boq_quantity), 2) : '—'}
              </td>
              <td className="py-1 text-end tabular-nums">{fmtFixed(d.old_quantity, 2)}</td>
              <td className="py-1 text-end tabular-nums">{fmtFixed(d.new_quantity, 2)}</td>
              <td
                className={clsx(
                  'py-1 text-end tabular-nums font-semibold',
                  d.delta_quantity > 0
                    ? 'text-amber-600'
                    : d.delta_quantity < 0
                      ? 'text-oe-blue'
                      : 'text-content-tertiary',
                )}
              >
                {d.delta_quantity > 0 ? '+' : ''}
                {fmtFixed(d.delta_quantity, 2)} {d.unit ?? ''}
              </td>
              <td className="py-1 text-right">
                {d.cost_impact != null && currency ? (
                  <MoneyDisplay amount={d.cost_impact} currency={currency} colorize className="text-xs" />
                ) : (
                  <span className="text-content-tertiary">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  confirming,
  onConfirm,
}: {
  rows: TakeoffMeasurementDiffRow[];
  hideUnchanged: boolean;
  confirming: boolean;
  onConfirm: (measurementId: string) => void;
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
          {r.carry_status === 'needs_review' && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2" data-testid="takeoff-carried-row">
              <Badge variant="warning" className="text-[9px]">
                {t('takeoff_compare.carried_needs_review', { defaultValue: 'Carried, needs review' })}
              </Badge>
              {r.scale_check === 'changed' && (
                <span className="text-[10px] text-amber-600">
                  {t('takeoff_compare.scale_changed', {
                    defaultValue: 'New sheet has a different scale: value recomputed from the same points',
                  })}
                </span>
              )}
              {r.scale_check === 'unverified' && (
                <span className="text-[10px] text-amber-600">
                  {t('takeoff_compare.scale_unverified', {
                    defaultValue: 'New sheet is not calibrated: old scale kept',
                  })}
                </span>
              )}
              <button
                type="button"
                onClick={() => onConfirm(r.measurement_id)}
                disabled={confirming}
                className="ml-auto rounded border border-border-light px-2 py-0.5 text-[10px] font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
              >
                {t('takeoff_compare.carry_confirm', { defaultValue: 'Confirm' })}
              </button>
            </div>
          )}
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
