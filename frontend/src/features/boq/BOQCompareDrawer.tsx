// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQCompareDrawer — Feature 2 ("estimate baseline + line-level compare").
 *
 * Reuses the VersionHistoryDrawer right-side drawer shell. The user
 * picks another BOQ in the same project (typically a revision created
 * via "Create revision") and sees a side-by-side, line-by-line classified
 * diff: added / removed / qty-changed / rate-changed, with base-currency
 * money deltas (the backend rebases via the project FX table — the UI
 * never re-derives currency).
 *
 * Pure read. Every string is i18n; numbers use locale-aware formatting.
 */

import { useState, useMemo, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { X, GitCompare, Loader2, ArrowRight } from 'lucide-react';
import clsx from 'clsx';
import { Badge } from '@/shared/ui';
import { boqApi } from './api';
import { CHANGE_VARIANT, filterCompareRows, showsPair } from './compareHelpers';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export interface BOQCompareDrawerProps {
  /** The BOQ acting as the comparison baseline (reference frame). */
  boqId: string;
  projectId: string;
  isOpen: boolean;
  onClose: () => void;
  /**
   * The estimate this BOQ was derived from (`parent_estimate_id`), if any.
   * Set for revisions and what-if scenarios. Drives the revision-aware
   * picker: the baseline is pre-selected and grouped at the top.
   */
  parentEstimateId?: string | null;
}

export function BOQCompareDrawer({
  boqId,
  projectId,
  isOpen,
  onClose,
  parentEstimateId,
}: BOQCompareDrawerProps) {
  const { t } = useTranslation();
  const [otherId, setOtherId] = useState<string>('');
  const [hideUnchanged, setHideUnchanged] = useState(true);

  // Close on Escape (mirrors VersionHistoryDrawer).
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () =>
      document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [isOpen, onClose]);

  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: isOpen && !!projectId,
  });

  // Classify the other BOQs by their lineage to this one so the picker can
  // surface the baseline + related revisions first instead of one flat list.
  const groups = useMemo(() => {
    const all = (boqs ?? []).filter((b) => b.id !== boqId);
    const baseline = parentEstimateId
      ? all.find((b) => b.id === parentEstimateId) ?? null
      : null;
    const revisions = all.filter((b) => b.parent_estimate_id === boqId);
    const siblings = parentEstimateId
      ? all.filter(
          (b) => b.parent_estimate_id === parentEstimateId && b.id !== baseline?.id,
        )
      : [];
    const used = new Set<string>(
      [
        baseline?.id,
        ...revisions.map((b) => b.id),
        ...siblings.map((b) => b.id),
      ].filter(Boolean) as string[],
    );
    const others = all.filter((b) => !used.has(b.id));
    return { baseline, revisions, siblings, others };
  }, [boqs, boqId, parentEstimateId]);

  // For a derived estimate (revision / scenario), default the comparison to
  // its baseline so the common "scenario vs baseline" diff is one step. Only
  // seeds an empty pick; never overrides a manual choice.
  useEffect(() => {
    if (isOpen && parentEstimateId && !otherId) {
      setOtherId(parentEstimateId);
    }
  }, [isOpen, parentEstimateId, otherId]);

  const {
    data: cmp,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['boq-compare', boqId, otherId],
    queryFn: () => boqApi.compareBoqs(boqId, otherId),
    enabled: isOpen && !!boqId && !!otherId,
    retry: false,
  });

  const fmt = useCallback(
    (v: string | null) => {
      if (v == null || v === '') return '—';
      const n = Number(v);
      // The locale is read inside the call, not held in a memoised formatter:
      // a language change does not remount the drawer, so a formatter built on
      // mount would go on writing the language it opened in.
      return Number.isFinite(n) ? n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 }) : v;
    },
    [],
  );

  const visibleRows = useMemo(
    () => filterCompareRows(cmp?.rows ?? [], hideUnchanged),
    [cmp, hideUnchanged],
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.compare_title', { defaultValue: 'Compare estimates' })}
        className="relative ml-auto flex h-full w-[560px] flex-col bg-surface-elevated border-l border-border shadow-2xl animate-slide-in-right"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <GitCompare size={16} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.compare_title', { defaultValue: 'Compare estimates' })}
            </h3>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Other-BOQ picker */}
        <div className="border-b border-border p-3 space-y-2">
          <label className="block">
            <span className="block text-2xs font-medium text-content-secondary mb-1">
              {t('boq.compare_against', { defaultValue: 'Compare against' })}
            </span>
            <select
              value={otherId}
              onChange={(e) => setOtherId(e.target.value)}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            >
              <option value="">
                {t('boq.compare_pick', { defaultValue: '- Select a BOQ -' })}
              </option>
              {groups.baseline && (
                <optgroup label={t('boq.compare_group_baseline', { defaultValue: 'Baseline' })}>
                  <option value={groups.baseline.id}>{groups.baseline.name}</option>
                </optgroup>
              )}
              {groups.revisions.length > 0 && (
                <optgroup
                  label={t('boq.compare_group_revisions', {
                    defaultValue: 'Revisions of this estimate',
                  })}
                >
                  {groups.revisions.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {groups.siblings.length > 0 && (
                <optgroup
                  label={t('boq.compare_group_siblings', { defaultValue: 'Other revisions' })}
                >
                  {groups.siblings.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {groups.others.length > 0 && (
                <optgroup
                  label={t('boq.compare_group_other', { defaultValue: 'Other estimates' })}
                >
                  {groups.others.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            <input
              type="checkbox"
              checked={hideUnchanged}
              onChange={(e) => setHideUnchanged(e.target.checked)}
              className="accent-oe-blue"
            />
            {t('boq.compare_hide_unchanged', {
              defaultValue: 'Hide unchanged lines',
            })}
          </label>
          {groups.baseline && otherId !== groups.baseline.id && (
            <button
              type="button"
              onClick={() => setOtherId(groups.baseline!.id)}
              className="text-2xs font-medium text-oe-blue hover:underline"
            >
              {t('boq.compare_to_baseline', { defaultValue: 'Compare to baseline' })}
            </button>
          )}
        </div>

        {/* Summary */}
        {cmp && (
          <div className="border-b border-border px-4 py-3">
            <div className="flex flex-wrap gap-1.5 mb-2">
              <Badge variant="success" size="sm">
                {t('boq.compare_added', { defaultValue: 'Added' })}: {cmp.summary.added}
              </Badge>
              <Badge variant="error" size="sm">
                {t('boq.compare_removed', { defaultValue: 'Removed' })}:{' '}
                {cmp.summary.removed}
              </Badge>
              <Badge variant="warning" size="sm">
                {t('boq.compare_qty', { defaultValue: 'Qty' })}:{' '}
                {cmp.summary.qty_changed}
              </Badge>
              <Badge variant="warning" size="sm">
                {t('boq.compare_rate', { defaultValue: 'Rate' })}:{' '}
                {cmp.summary.rate_changed}
              </Badge>
              <Badge variant="neutral" size="sm">
                {t('boq.compare_unchanged', { defaultValue: 'Unchanged' })}:{' '}
                {cmp.summary.unchanged}
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="text-content-tertiary">
                {fmt(cmp.summary.old_direct_cost_base)}
              </span>
              <ArrowRight size={11} className="text-content-quaternary" />
              <span className="text-content-primary font-semibold">
                {fmt(cmp.summary.new_direct_cost_base)}
              </span>
              <span className="text-content-tertiary">
                {cmp.summary.base_currency}
              </span>
              {(() => {
                const d = Number(cmp.summary.direct_cost_delta_base);
                if (!Number.isFinite(d) || d === 0) return null;
                return (
                  <span
                    className={clsx(
                      'ml-1 font-medium',
                      d > 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-red-600 dark:text-red-400',
                    )}
                  >
                    {d > 0 ? '+' : ''}
                    {fmt(cmp.summary.direct_cost_delta_base)}
                  </span>
                );
              })()}
            </div>
          </div>
        )}

        {/* Rows */}
        <div className="flex-1 overflow-y-auto">
          {!otherId ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <GitCompare size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-secondary">
                {t('boq.compare_select_hint', {
                  defaultValue: 'Pick another BOQ above to see a line-by-line diff.',
                })}
              </p>
            </div>
          ) : isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-content-tertiary" />
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <p className="text-sm text-semantic-error">
                {t('boq.compare_error', {
                  defaultValue: 'Could not compare these BOQs.',
                })}
              </p>
              <p className="text-2xs text-content-tertiary mt-1">
                {error instanceof Error ? error.message : ''}
              </p>
            </div>
          ) : visibleRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <p className="text-sm text-content-secondary">
                {t('boq.compare_no_diff', {
                  defaultValue: 'No differences between these BOQs.',
                })}
              </p>
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-elevated border-b border-border-light">
                <tr className="text-2xs text-content-tertiary text-left">
                  <th className="px-3 py-2 font-medium">
                    {t('boq.compare_col_line', { defaultValue: 'Line' })}
                  </th>
                  <th className="px-2 py-2 font-medium text-right">
                    {t('boq.compare_col_qty', { defaultValue: 'Qty' })}
                  </th>
                  <th className="px-2 py-2 font-medium text-right">
                    {t('boq.compare_col_rate', { defaultValue: 'Rate' })}
                  </th>
                  <th className="px-2 py-2 font-medium text-right">
                    {t('boq.compare_col_delta', { defaultValue: 'Δ base' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {visibleRows.map((r) => {
                  const d = Number(r.total_delta_base);
                  return (
                    <tr
                      key={r.match_key}
                      className="hover:bg-surface-secondary/40"
                    >
                      <td className="px-3 py-2 align-top">
                        <div className="flex items-center gap-1.5">
                          <Badge
                            variant={CHANGE_VARIANT[r.change_type]}
                            size="sm"
                          >
                            {t(`boq.compare_ct_${r.change_type}`, {
                              defaultValue: r.change_type,
                            })}
                          </Badge>
                          <span className="font-medium text-content-primary">
                            {r.ordinal}
                          </span>
                        </div>
                        <p className="text-2xs text-content-tertiary mt-0.5 truncate max-w-[200px]">
                          {r.description}
                        </p>
                      </td>
                      <td className="px-2 py-2 align-top text-right font-mono text-2xs">
                        {showsPair(r.change_type, 'qty') ? (
                          <span>
                            <span className="text-content-tertiary">
                              {fmt(r.old_quantity)}
                            </span>
                            <br />
                            <span className="text-content-primary font-semibold">
                              {fmt(r.new_quantity)}
                            </span>
                          </span>
                        ) : (
                          <span className="text-content-secondary">
                            {fmt(r.new_quantity ?? r.old_quantity)}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2 align-top text-right font-mono text-2xs">
                        {showsPair(r.change_type, 'rate') ? (
                          <span>
                            <span className="text-content-tertiary">
                              {fmt(r.old_unit_rate)}
                            </span>
                            <br />
                            <span className="text-content-primary font-semibold">
                              {fmt(r.new_unit_rate)}
                            </span>
                          </span>
                        ) : (
                          <span className="text-content-secondary">
                            {fmt(r.new_unit_rate ?? r.old_unit_rate)}
                          </span>
                        )}
                      </td>
                      <td
                        className={clsx(
                          'px-2 py-2 align-top text-right font-mono text-2xs font-medium',
                          Number.isFinite(d) && d > 0
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : Number.isFinite(d) && d < 0
                              ? 'text-red-600 dark:text-red-400'
                              : 'text-content-tertiary',
                        )}
                      >
                        {Number.isFinite(d) && d !== 0
                          ? `${d > 0 ? '+' : ''}${fmt(r.total_delta_base)}`
                          : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
