// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Threshold alert banner + editor for the Coordination Hub.
 *
 * The backend ships a complete configurable-threshold subsystem
 * (`GET/PUT /projects/{id}/thresholds`) that evaluates four real metrics
 * (open clashes, high-severity clashes, open cost-impact as % of budget,
 * model staleness) and returns a sorted `alerts[]` list of whatever is
 * currently in breach. This module surfaces that work:
 *
 *   • `ThresholdAlertBanner` renders the in-breach metrics as a banner
 *     above the KPI cards (error rows first), replacing the old hardcoded
 *     `open >= 50` client-side traffic light that ignored the configured,
 *     per-project, operator-editable thresholds.
 *   • `ThresholdEditorModal` lets an EDITOR/MANAGER/ADMIN tune the warn /
 *     error value and the enabled flag per metric. Each save calls the
 *     real PUT endpoint and invalidates the dashboard + thresholds queries
 *     so the banner reflects the new configuration on the next tick.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Activity, CheckCircle2 } from 'lucide-react';

import { Button, WideModal, WideModalField } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { updateCoordinationThreshold } from './api';
import type {
  CoordinationThresholdsResponse,
  ThresholdAlert,
  ThresholdRow,
} from './types';

/** Human-readable, localised label for each known metric key. */
function useMetricLabel(): (metric: string) => string {
  const { t } = useTranslation();
  return (metric: string): string => {
    switch (metric) {
      case 'open_clashes_total':
        return t('coordination_hub.metric_open_clashes_total', {
          defaultValue: 'Open clashes (total)',
        });
      case 'high_severity_clashes':
        return t('coordination_hub.metric_high_severity_clashes', {
          defaultValue: 'High-severity open clashes',
        });
      case 'open_cost_impact_pct_of_budget':
        return t('coordination_hub.metric_cost_impact_pct', {
          defaultValue: 'Open cost impact (% of budget)',
        });
      case 'model_age_days_max':
        return t('coordination_hub.metric_model_age', {
          defaultValue: 'Days since last model upload',
        });
      default:
        return metric;
    }
  };
}

/** Coerce the wire value (Decimal-as-string) to a finite number for display. */
function toNum(v: string | number): number {
  const n = typeof v === 'number' ? v : Number.parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

/** Trim trailing zeros so "50.0000" renders as "50". */
function fmt(v: string | number): string {
  const n = toNum(v);
  // 99999 is the sentinel "no model ever uploaded" value — render it as ∞.
  if (n >= 99999) return '∞';
  return String(Number(n.toFixed(2)));
}

// ── Alert banner ────────────────────────────────────────────────────────────

export interface ThresholdAlertBannerProps {
  data: CoordinationThresholdsResponse | undefined;
  /** Fallback open-clash count used only while thresholds are still loading. */
  fallbackOpenClashes?: number;
}

/**
 * Project-health banner driven by the backend threshold evaluation.
 * Tone follows the most-severe alert: rose for any error, amber for any
 * warn, emerald when nothing is in breach. Lists every in-breach metric so
 * high-severity / cost-impact / model-age breaches colour the banner too,
 * not just raw open-clash count.
 */
export function ThresholdAlertBanner({
  data,
  fallbackOpenClashes = 0,
}: ThresholdAlertBannerProps) {
  const { t } = useTranslation();
  const metricLabel = useMetricLabel();

  // Until the thresholds endpoint answers we degrade to a light open-clash
  // heuristic so the banner is never blank, but the moment real evaluation
  // lands the configured thresholds take over.
  const alerts: ThresholdAlert[] = data?.alerts ?? [];
  const hasError = alerts.some((a) => a.level === 'error');
  const hasWarn = alerts.length > 0;

  const tone = hasError ? 'rose' : hasWarn ? 'amber' : 'emerald';

  const palette = {
    emerald: {
      ring: 'ring-emerald-400/20',
      bg: 'from-emerald-50 to-teal-50/40 dark:from-emerald-500/10 dark:to-teal-500/5',
      icon: 'text-emerald-600 dark:text-emerald-400',
      Icon: CheckCircle2,
      title: t('coordination.health_ok_title', { defaultValue: 'All clear' }),
    },
    amber: {
      ring: 'ring-amber-400/20',
      bg: 'from-amber-50 to-orange-50/40 dark:from-amber-500/10 dark:to-orange-500/5',
      icon: 'text-amber-600 dark:text-amber-400',
      Icon: Activity,
      title: t('coordination.health_attention_title', {
        defaultValue: 'Coordination in progress',
      }),
    },
    rose: {
      ring: 'ring-rose-400/30',
      bg: 'from-rose-50 to-orange-50/50 dark:from-rose-500/10 dark:to-orange-500/5',
      icon: 'text-rose-600 dark:text-rose-400',
      Icon: AlertTriangle,
      title: t('coordination.health_alert_title', {
        defaultValue: 'Attention required',
      }),
    },
  }[tone];

  const Icon = palette.Icon;

  // Subtitle line: when clear, a reassurance; otherwise a count of breaches.
  const subtitle =
    tone === 'emerald'
      ? data
        ? t('coordination_hub.health_all_within_thresholds', {
            defaultValue: 'Every coordination metric is within its configured threshold.',
          })
        : fallbackOpenClashes > 0
          ? t('coordination_hub.health_open_clashes_pending', {
              defaultValue: '{{open}} open clash(es). Loading configured thresholds…',
              open: fallbackOpenClashes,
            })
          : t('coordination.health_ok_msg_v2', {
              defaultValue: 'No open clashes on this project.',
            })
      : t('coordination_hub.health_breaches', {
          defaultValue: '{{count}} metric(s) over threshold.',
          count: alerts.length,
        });

  return (
    <div
      data-testid="coordination-health-banner"
      className={`relative overflow-hidden rounded-2xl border border-white/40 bg-gradient-to-br ${palette.bg} ring-1 ${palette.ring} px-5 py-4 backdrop-blur-xl dark:border-white/5`}
    >
      <div className="flex items-start gap-3">
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/70 backdrop-blur dark:bg-slate-900/60 ${palette.icon}`}
        >
          <Icon size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {palette.title}
          </h3>
          <p className="text-xs text-content-secondary">{subtitle}</p>
          {alerts.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-1.5" data-testid="coordination-alert-list">
              {alerts.map((a) => (
                <li
                  key={a.metric}
                  data-testid={`coordination-alert-${a.metric}`}
                  className={
                    a.level === 'error'
                      ? 'inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-[11px] font-medium text-rose-800 dark:bg-rose-500/15 dark:text-rose-200'
                      : 'inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-200'
                  }
                  title={a.message}
                >
                  {metricLabel(a.metric)}: {fmt(a.current_value)} /{' '}
                  {fmt(a.threshold_value)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Editor modal ──────────────────────────────────────────────────────────

interface RowDraft {
  warn: string;
  error: string;
  enabled: boolean;
}

export interface ThresholdEditorModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  rows: ThresholdRow[];
}

/**
 * Per-metric warn / error / enabled editor. One row per known metric; Save
 * fires a PUT per changed row (the backend validates warn <= error and
 * 422s an inverted pair, which we surface as an error toast). On success
 * we invalidate the thresholds + dashboard queries so the banner refreshes.
 */
export function ThresholdEditorModal({
  open,
  onClose,
  projectId,
  rows,
}: ThresholdEditorModalProps) {
  const { t } = useTranslation();
  const metricLabel = useMetricLabel();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({});

  // Re-seed the draft from the latest rows whenever the modal opens so the
  // editor never shows stale values after a previous save.
  useEffect(() => {
    if (!open) return;
    const next: Record<string, RowDraft> = {};
    for (const r of rows) {
      next[r.metric] = {
        warn: String(toNum(r.warn_value)),
        error: String(toNum(r.error_value)),
        enabled: r.enabled,
      };
    }
    setDrafts(next);
  }, [open, rows]);

  const mutation = useMutation({
    mutationFn: async () => {
      // Only PUT rows whose values actually changed — keeps the audit log
      // and updated_at column clean, and dodges the "empty payload"
      // validator on untouched rows.
      const changed = rows.filter((r) => {
        const d = drafts[r.metric];
        if (!d) return false;
        return (
          toNum(d.warn) !== toNum(r.warn_value) ||
          toNum(d.error) !== toNum(r.error_value) ||
          d.enabled !== r.enabled
        );
      });
      for (const r of changed) {
        const d = drafts[r.metric]!;
        await updateCoordinationThreshold(projectId, r.metric, {
          warn_value: toNum(d.warn),
          error_value: toNum(d.error),
          enabled: d.enabled,
        });
      }
      return changed.length;
    },
    onSuccess: (changedCount) => {
      addToast({
        type: 'success',
        title:
          changedCount > 0
            ? t('coordination_hub.thresholds_saved', {
                defaultValue: 'Thresholds updated',
              })
            : t('coordination_hub.thresholds_no_change', {
                defaultValue: 'No changes to save',
              }),
      });
      void queryClient.invalidateQueries({
        queryKey: ['coordination-thresholds', projectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ['coordination-dashboard', projectId],
      });
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('coordination_hub.thresholds_save_failed', {
          defaultValue: 'Could not save thresholds',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const setField = (metric: string, patch: Partial<RowDraft>) => {
    setDrafts((prev) => ({
      ...prev,
      [metric]: { ...prev[metric]!, ...patch },
    }));
  };

  // Client-side mirror of the backend warn<=error guard so the operator
  // sees the mistake before the round-trip 422s.
  const invalidRows = rows.filter((r) => {
    const d = drafts[r.metric];
    if (!d) return false;
    return toNum(d.warn) > toNum(d.error);
  });
  const hasInvalid = invalidRows.length > 0;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={mutation.isPending}
      size="lg"
      title={t('coordination_hub.thresholds_title', {
        defaultValue: 'Alert thresholds',
      })}
      subtitle={t('coordination_hub.thresholds_subtitle', {
        defaultValue:
          'Set the warn and error levels that turn this project red. Leave a metric disabled to mute its alert.',
      })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={hasInvalid}
            data-testid="coordination-thresholds-save"
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {rows.map((r) => {
          const d = drafts[r.metric];
          if (!d) return null;
          const inverted = toNum(d.warn) > toNum(d.error);
          return (
            <div
              key={r.metric}
              data-testid={`coordination-threshold-row-${r.metric}`}
              className="rounded-xl border border-border-light bg-surface-secondary/30 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-content-primary">
                  {metricLabel(r.metric)}
                </span>
                <label className="inline-flex items-center gap-2 text-xs text-content-secondary">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    onChange={(e) => setField(r.metric, { enabled: e.target.checked })}
                    className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue"
                  />
                  {t('coordination_hub.threshold_enabled', {
                    defaultValue: 'Enabled',
                  })}
                </label>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <WideModalField
                  label={t('coordination_hub.threshold_warn', {
                    defaultValue: 'Warn at',
                  })}
                  error={
                    inverted
                      ? t('coordination_hub.threshold_inverted', {
                          defaultValue: 'Warn must be ≤ Error',
                        })
                      : undefined
                  }
                >
                  <input
                    type="number"
                    min={0}
                    step="any"
                    value={d.warn}
                    disabled={!d.enabled}
                    onChange={(e) => setField(r.metric, { warn: e.target.value })}
                    className="h-9 rounded-lg border border-border bg-surface px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue disabled:opacity-50"
                  />
                </WideModalField>
                <WideModalField
                  label={t('coordination_hub.threshold_error', {
                    defaultValue: 'Error at',
                  })}
                >
                  <input
                    type="number"
                    min={0}
                    step="any"
                    value={d.error}
                    disabled={!d.enabled}
                    onChange={(e) => setField(r.metric, { error: e.target.value })}
                    className="h-9 rounded-lg border border-border bg-surface px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue disabled:opacity-50"
                  />
                </WideModalField>
              </div>
            </div>
          );
        })}
      </div>
    </WideModal>
  );
}
