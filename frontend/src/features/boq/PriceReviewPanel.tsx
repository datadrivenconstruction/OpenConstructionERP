/**
 * PriceReviewPanel — Shows price check results as reviewable suggestions.
 *
 * Each anomaly shows: current rate vs suggested rate, difference, and
 * Accept/Ignore buttons. User reviews each suggestion before applying.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, X, AlertTriangle, TrendingDown, TrendingUp, CheckCheck } from 'lucide-react';
import { Button } from '@/shared/ui';
import { fmtWithCurrency } from './boqHelpers';
import type { Position } from './api';

interface AnomalyEntry {
  severity: string;
  message: string;
  suggestion: number;
}

interface PriceReviewPanelProps {
  anomalyMap: Map<string, AnomalyEntry>;
  positions: Position[];
  currencyCode: string;
  locale: string;
  onApply: (positionId: string, suggestedRate: number) => void;
  onIgnore: (positionId: string) => void;
  onApplyAll: () => void;
  onDismiss: () => void;
}

export function PriceReviewPanel({
  anomalyMap,
  positions,
  currencyCode,
  locale,
  onApply,
  onIgnore,
  onApplyAll,
  onDismiss,
}: PriceReviewPanelProps) {
  const { t } = useTranslation();

  const items = useMemo(() => {
    const result: Array<{
      id: string;
      ordinal: string;
      description: string;
      currentRate: number;
      suggestedRate: number;
      diff: number;
      diffPct: number;
      severity: string;
      message: string;
    }> = [];

    for (const [posId, anomaly] of anomalyMap.entries()) {
      const pos = positions.find((p) => p.id === posId);
      if (!pos) continue;
      const current = pos.unit_rate;
      const suggested = anomaly.suggestion;
      const diff = suggested - current;
      const diffPct = current > 0 ? (diff / current) * 100 : 0;
      result.push({
        id: posId,
        ordinal: pos.ordinal,
        description: pos.description,
        currentRate: current,
        suggestedRate: suggested,
        diff,
        diffPct,
        severity: anomaly.severity,
        message: anomaly.message,
      });
    }

    return result.sort((a, b) => Math.abs(b.diffPct) - Math.abs(a.diffPct));
  }, [anomalyMap, positions]);

  if (items.length === 0) return null;

  return (
    <div className="rounded-xl border border-amber-200/50 dark:border-amber-800/30 bg-amber-50/30 dark:bg-amber-950/10 p-4 mt-4 animate-card-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-amber-500" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('boq.price_review_title', { defaultValue: 'Price Check Results' })}
          </h3>
          <span className="rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-2xs font-bold text-amber-700 dark:text-amber-300">
            {items.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" icon={<CheckCheck size={14} />} onClick={onApplyAll}>
            {t('boq.apply_all_suggestions', { defaultValue: 'Apply All' })}
          </Button>
          <button onClick={onDismiss} aria-label={t('common.close', { defaultValue: 'Close' })} className="p-1 rounded-md hover:bg-surface-secondary transition-colors">
            <X size={14} className="text-content-tertiary" />
          </button>
        </div>
      </div>

      <p className="text-xs text-content-secondary mb-3">
        {t('boq.price_review_desc', { defaultValue: 'Review each suggestion below. Accept to update the rate, or ignore to keep your current price.' })}
      </p>

      {/* Items */}
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary p-3"
          >
            {/* Position info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-content-tertiary">{item.ordinal}</span>
                <span className="text-sm font-medium text-content-primary truncate">{item.description}</span>
              </div>
              <div className="flex items-center gap-3 mt-1">
                {/* Current rate */}
                <div className="text-xs">
                  <span className="text-content-tertiary">{t('boq.current', { defaultValue: 'Current' })}: </span>
                  <span className="font-mono font-medium text-content-secondary">
                    {fmtWithCurrency(item.currentRate, locale, currencyCode)}
                  </span>
                </div>

                {/* Arrow */}
                <span className="text-content-quaternary">&rarr;</span>

                {/* Suggested rate */}
                <div className="text-xs">
                  <span className="text-content-tertiary">{t('boq.suggested', { defaultValue: 'Suggested' })}: </span>
                  <span className={`font-mono font-bold ${item.diff < 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                    {fmtWithCurrency(item.suggestedRate, locale, currencyCode)}
                  </span>
                </div>

                {/* Diff */}
                <div className={`flex items-center gap-0.5 text-2xs font-bold ${item.diff < 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                  {item.diff < 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
                  {item.diffPct > 0 ? '+' : ''}{item.diffPct.toFixed(0)}%
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => onApply(item.id, item.suggestedRate)}
                aria-label={`${t('boq.accept', { defaultValue: 'Accept' })} — ${item.ordinal}`}
                className="flex items-center gap-1 rounded-md bg-emerald-50 dark:bg-emerald-950/30 px-2.5 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 transition-colors"
              >
                <Check size={12} />
                {t('boq.accept', { defaultValue: 'Accept' })}
              </button>
              <button
                onClick={() => onIgnore(item.id)}
                aria-label={`${t('boq.ignore', { defaultValue: 'Ignore' })} — ${item.ordinal}`}
                className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium text-content-tertiary hover:bg-surface-secondary transition-colors"
              >
                <X size={12} />
                {t('boq.ignore', { defaultValue: 'Ignore' })}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
