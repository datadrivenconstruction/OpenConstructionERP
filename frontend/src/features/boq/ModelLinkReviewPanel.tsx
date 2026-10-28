// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModelLinkReviewPanel — Feature 1 review/confirm UI.
 *
 * Triggers the BOQ-wide "re-pull bound quantities" probe (read-only,
 * never mutates), then lists every stale position with old → new →
 * delta and a per-row Apply / Skip choice. Apply is the explicit human
 * confirm step (the architecture guide §7): only the rows the user ticked are written.
 *
 * Every string goes through i18n `t()`; numbers are rendered via the
 * locale-aware `Intl.NumberFormat` (no hardcoded formatting/currency).
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, RefreshCw, ArrowRight, CheckCircle2, X } from 'lucide-react';
import clsx from 'clsx';
import { Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi, type QuantityLinkRefreshRow } from './api';

export interface ModelLinkReviewPanelProps {
  boqId: string;
  locale: string;
  isOpen: boolean;
  onClose: () => void;
  /** Called after a successful apply so the editor can refetch the BOQ. */
  onApplied: () => void;
}

export function ModelLinkReviewPanel({
  boqId,
  locale,
  isOpen,
  onClose,
  onApplied,
}: ModelLinkReviewPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [rows, setRows] = useState<QuantityLinkRefreshRow[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const numberFmt = useMemo(
    () =>
      new Intl.NumberFormat(locale || undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 4,
      }),
    [locale],
  );
  const fmt = useCallback(
    (v: string | null) => {
      if (v == null || v === '') return '—';
      const n = Number(v);
      return Number.isFinite(n) ? numberFmt.format(n) : v;
    },
    [numberFmt],
  );

  const refreshMutation = useMutation({
    mutationFn: () => boqApi.refreshQuantityLinks(boqId),
    onSuccess: (res) => {
      setRows(res.rows);
      // Pre-tick only the rows that actually changed.
      setSelected(
        new Set(res.rows.filter((r) => r.changed).map((r) => r.link_id)),
      );
      if (res.checked === 0) {
        addToast({
          type: 'info',
          title: t('boq.model_review_no_links', {
            defaultValue: 'No model links in this BOQ',
          }),
        });
      }
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.model_review_refresh_failed', {
          defaultValue: 'Refresh from model failed',
        }),
        message: e.message,
      });
    },
  });

  const applyMutation = useMutation({
    mutationFn: (linkIds: string[]) =>
      boqApi.applyQuantityLinks(boqId, linkIds),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      onApplied();
      addToast({
        type: 'success',
        title: t('boq.model_review_applied', {
          defaultValue: '{{count}} quantity update(s) applied',
          count: res.applied,
        }),
      });
      setRows(null);
      setSelected(new Set());
      onClose();
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.model_review_apply_failed', {
          defaultValue: 'Apply failed',
        }),
        message: e.message,
      });
    },
  });

  const toggleRow = useCallback((linkId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(linkId)) next.delete(linkId);
      else next.add(linkId);
      return next;
    });
  }, []);

  const staleRows = useMemo(
    () => (rows ?? []).filter((r) => r.changed || r.status !== 'active'),
    [rows],
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.model_review_title', {
          defaultValue: 'Model quantity review',
        })}
        className="relative ml-auto flex h-full w-[420px] flex-col bg-surface-elevated border-l border-border shadow-2xl animate-slide-in-right"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <RefreshCw size={16} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.model_review_title', { defaultValue: 'Model quantity review' })}
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

        {/* Refresh action */}
        <div className="border-b border-border p-3">
          <Button
            variant="secondary"
            size="sm"
            className="w-full"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <RefreshCw size={14} className="mr-1" />
            )}
            {t('boq.model_review_refresh', { defaultValue: 'Refresh from model' })}
          </Button>
          <p className="text-2xs text-content-tertiary mt-2">
            {t('boq.model_review_hint', {
              defaultValue:
                'Re-pulls bound quantities against the latest model version. Nothing changes until you Apply.',
            })}
          </p>
        </div>

        {/* Stale rows */}
        <div className="flex-1 overflow-y-auto">
          {rows == null ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <RefreshCw size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-secondary">
                {t('boq.model_review_run', {
                  defaultValue: 'Run a refresh to see model-driven changes.',
                })}
              </p>
            </div>
          ) : staleRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <CheckCircle2 size={32} className="text-semantic-success mb-3" />
              <p className="text-sm text-content-secondary">
                {t('boq.model_review_all_synced', {
                  defaultValue: 'All linked quantities are in sync with the model.',
                })}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border-light">
              {staleRows.map((r) => {
                const checked = selected.has(r.link_id);
                const deltaNum = Number(r.delta);
                return (
                  <li key={r.link_id} className="px-4 py-3">
                    <label className="flex items-start gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleRow(r.link_id)}
                        className="mt-0.5 accent-oe-blue"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-content-primary truncate">
                            {r.ordinal} — {r.description}
                          </span>
                          {r.status !== 'active' && (
                            <Badge
                              variant={r.status === 'broken' ? 'error' : 'warning'}
                              size="sm"
                            >
                              {t(`boq.model_link_status_${r.status}`, {
                                defaultValue: r.status,
                              })}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-2xs font-mono">
                          <span className="text-content-tertiary">
                            {fmt(r.old_quantity)}
                          </span>
                          <ArrowRight size={11} className="text-content-quaternary" />
                          <span className="text-content-primary font-semibold">
                            {fmt(r.new_quantity)}
                          </span>
                          <span className="text-content-tertiary">{r.unit}</span>
                          {Number.isFinite(deltaNum) && deltaNum !== 0 && (
                            <span
                              className={clsx(
                                'ml-1 font-medium',
                                deltaNum > 0
                                  ? 'text-emerald-600 dark:text-emerald-400'
                                  : 'text-red-600 dark:text-red-400',
                              )}
                            >
                              {deltaNum > 0 ? '+' : ''}
                              {fmt(r.delta)}
                            </span>
                          )}
                        </div>
                        <p className="text-2xs text-content-tertiary mt-1">
                          {r.aggregation}({r.quantity_field}) ·{' '}
                          {t('boq.model_link_elem_count', {
                            defaultValue: '{{count}} element(s)',
                            count: r.contributing_elements.length,
                          })}
                          {r.missing_element_ids.length > 0
                            ? ` · ${t('boq.model_review_missing', {
                                defaultValue: '{{count}} missing',
                                count: r.missing_element_ids.length,
                              })}`
                            : ''}
                        </p>
                        {r.message && (
                          <p className="text-2xs text-amber-600 dark:text-amber-400 mt-0.5">
                            {r.message}
                          </p>
                        )}
                      </div>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Apply footer */}
        {staleRows.length > 0 && (
          <div className="border-t border-border p-3">
            <Button
              variant="primary"
              size="sm"
              className="w-full"
              disabled={selected.size === 0 || applyMutation.isPending}
              onClick={() => applyMutation.mutate(Array.from(selected))}
            >
              {applyMutation.isPending ? (
                <Loader2 size={14} className="mr-1 animate-spin" />
              ) : (
                <CheckCircle2 size={14} className="mr-1" />
              )}
              {t('boq.model_review_apply', {
                defaultValue: 'Apply {{count}} selected',
                count: selected.size,
              })}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
