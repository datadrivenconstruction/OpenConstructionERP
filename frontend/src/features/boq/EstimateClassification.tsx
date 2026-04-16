import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronUp, Info } from 'lucide-react';
import { boqApi } from './api';
import { ApiError } from '@/shared/lib/api';

/* ── Class color & style mapping ──────────────────────────────────────── */

interface ClassStyle {
  bg: string;
  text: string;
  border: string;
  ring: string;
  barColor: string;
}

const CLASS_STYLES: Record<number, ClassStyle> = {
  5: {
    bg: 'bg-semantic-error-bg',
    text: 'text-semantic-error',
    border: 'border-semantic-error/30',
    ring: 'ring-semantic-error/20',
    barColor: 'bg-semantic-error',
  },
  4: {
    bg: 'bg-semantic-warning-bg',
    text: 'text-[#b45309]',
    border: 'border-semantic-warning/30',
    ring: 'ring-semantic-warning/20',
    barColor: 'bg-semantic-warning',
  },
  3: {
    bg: 'bg-amber-50 dark:bg-amber-950/30',
    text: 'text-amber-700 dark:text-amber-400',
    border: 'border-amber-300/40',
    ring: 'ring-amber-200/30',
    barColor: 'bg-amber-500',
  },
  2: {
    bg: 'bg-oe-blue-subtle',
    text: 'text-oe-blue',
    border: 'border-oe-blue/30',
    ring: 'ring-oe-blue/20',
    barColor: 'bg-oe-blue',
  },
  1: {
    bg: 'bg-semantic-success-bg',
    text: 'text-semantic-success',
    border: 'border-semantic-success/30',
    ring: 'ring-semantic-success/20',
    barColor: 'bg-semantic-success',
  },
};

const DEFAULT_CLASS_STYLE: ClassStyle = {
  bg: 'bg-semantic-error-bg',
  text: 'text-semantic-error',
  border: 'border-semantic-error/30',
  ring: 'ring-semantic-error/20',
  barColor: 'bg-semantic-error',
};

function getClassStyle(cls: number): ClassStyle {
  return CLASS_STYLES[cls] ?? DEFAULT_CLASS_STYLE;
}

/* ── Accuracy range bar ──────────────────────────────────────────────── */

function AccuracyBar({
  low,
  high,
  style,
}: {
  low: string;
  high: string;
  style: ClassStyle;
}) {
  // Parse percentage strings like "-50%" and "+100%"
  const lowNum = parseInt(low.replace('%', ''), 10);
  const highNum = parseInt(high.replace('%', ''), 10);

  // Map to 0-100 scale: -50% maps to 0, +100% maps to 100
  // We use a range of -50 to +100 as the full scale
  const scaleMin = -50;
  const scaleMax = 100;
  const range = scaleMax - scaleMin;

  const leftPct = Math.max(0, Math.min(100, ((lowNum - scaleMin) / range) * 100));
  const rightPct = Math.max(0, Math.min(100, ((highNum - scaleMin) / range) * 100));
  const barWidth = rightPct - leftPct;

  // Center marker position (0% = project estimate)
  const centerPct = ((0 - scaleMin) / range) * 100;

  return (
    <div className="relative w-full h-6 rounded-md bg-surface-secondary overflow-hidden">
      {/* Accuracy range fill */}
      <div
        className={`absolute top-0 bottom-0 ${style.barColor} opacity-25 rounded`}
        style={{ left: `${leftPct}%`, width: `${barWidth}%` }}
      />
      {/* Left label */}
      <span
        className="absolute top-0.5 text-2xs font-mono font-medium"
        style={{ left: `${Math.max(leftPct, 1)}%` }}
      >
        <span className={style.text}>{low}</span>
      </span>
      {/* Right label */}
      <span
        className="absolute top-0.5 text-2xs font-mono font-medium"
        style={{ left: `${Math.min(rightPct - 1, 95)}%`, transform: 'translateX(-100%)' }}
      >
        <span className={style.text}>{high}</span>
      </span>
      {/* Center line (0% = estimate) */}
      <div
        className="absolute top-0 bottom-0 w-px bg-content-tertiary"
        style={{ left: `${centerPct}%` }}
      />
      {/* Bottom tick labels */}
      <span
        className="absolute bottom-0 text-[9px] text-content-tertiary font-mono"
        style={{ left: `${centerPct}%`, transform: 'translateX(-50%)' }}
      >
        0%
      </span>
    </div>
  );
}

/* ── Definition level indicator ─────────────────────────────────────── */

function DefinitionBar({
  low,
  high,
  style,
}: {
  low: number;
  high: number;
  style: ClassStyle;
}) {
  return (
    <div className="relative w-full h-3 rounded-full bg-surface-secondary overflow-hidden">
      <div
        className={`absolute top-0 bottom-0 ${style.barColor} opacity-40 rounded-full`}
        style={{ left: `${low}%`, width: `${high - low}%` }}
      />
      <div
        className={`absolute top-0 bottom-0 ${style.barColor} rounded-full`}
        style={{ left: `${low}%`, width: `${Math.min(high - low, (high + low) / 2 - low)}%` }}
      />
    </div>
  );
}

/* ── Metric row ─────────────────────────────────────────────────────── */

function MetricRow({
  label,
  value,
  total,
  pct,
}: {
  label: string;
  value: number;
  total: number;
  pct: number;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-content-secondary">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-content-tertiary tabular-nums">
          {value}/{total}
        </span>
        <div className="w-16 h-1.5 rounded-full bg-surface-secondary overflow-hidden">
          <div
            className="h-full rounded-full bg-oe-blue transition-all"
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        <span className="w-10 text-right font-mono text-content-primary tabular-nums">
          {pct.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────────── */

export function EstimateClassification({ boqId }: { boqId: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const { data: classification, isLoading } = useQuery({
    queryKey: ['boq-classification', boqId],
    queryFn: () => boqApi.getClassification(boqId),
    enabled: !!boqId,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 2;
    },
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border-light bg-surface-elevated p-4 animate-pulse">
        <div className="h-5 w-48 bg-surface-secondary rounded" />
        <div className="mt-3 h-12 bg-surface-secondary rounded" />
      </div>
    );
  }

  if (!classification) return null;

  const style = getClassStyle(classification.estimate_class);
  const { metrics } = classification;

  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden">
      {/* ── Header: clickable to expand ──────────────────────────────── */}
      <button
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between gap-4 px-5 py-4 hover:bg-surface-secondary/50 transition-colors text-left"
      >
        <div className="flex items-center gap-4">
          {/* Class badge — large number */}
          <div
            className={`flex items-center justify-center w-12 h-12 rounded-xl ${style.bg} ${style.border} border ring-1 ${style.ring}`}
          >
            <span className={`text-2xl font-bold tabular-nums ${style.text}`}>
              {classification.estimate_class}
            </span>
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('boq.aace_class', { defaultValue: 'AACE Class' })}{' '}
                {classification.estimate_class}
              </h3>
              <span className={`text-xs font-medium ${style.text}`}>
                {classification.class_label}
              </span>
            </div>
            <p className="text-xs text-content-tertiary mt-0.5">
              {t('boq.aace_accuracy', { defaultValue: 'Accuracy' })}:{' '}
              <span className="font-mono font-medium text-content-secondary">
                {classification.accuracy_low} / {classification.accuracy_high}
              </span>
              {' · '}
              {t('boq.aace_definition', { defaultValue: 'Definition' })}:{' '}
              <span className="font-mono font-medium text-content-secondary">
                {classification.definition_level_low}%{' '}
                {t('boq.aace_to', { defaultValue: 'to' })}{' '}
                {classification.definition_level_high}%
              </span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {expanded ? (
            <ChevronUp size={16} className="text-content-tertiary" />
          ) : (
            <ChevronDown size={16} className="text-content-tertiary" />
          )}
        </div>
      </button>

      {/* ── Expanded details ─────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-border-light px-5 py-4 space-y-5 animate-fade-in">
          {/* Accuracy range visualization */}
          <div>
            <div className="text-xs font-medium text-content-secondary mb-2">
              {t('boq.aace_accuracy_range', { defaultValue: 'Accuracy Range' })}
            </div>
            <AccuracyBar
              low={classification.accuracy_low}
              high={classification.accuracy_high}
              style={style}
            />
          </div>

          {/* Definition level */}
          <div>
            <div className="flex items-center justify-between text-xs mb-1.5">
              <span className="font-medium text-content-secondary">
                {t('boq.aace_definition_level', { defaultValue: 'Definition Level' })}
              </span>
              <span className="font-mono text-content-primary">
                {classification.definition_level_low}% - {classification.definition_level_high}%
              </span>
            </div>
            <DefinitionBar
              low={classification.definition_level_low}
              high={classification.definition_level_high}
              style={style}
            />
          </div>

          {/* Methodology */}
          <div className="flex gap-2 p-3 rounded-lg bg-surface-secondary/50">
            <Info size={14} className="text-content-tertiary shrink-0 mt-0.5" />
            <div>
              <div className="text-xs font-medium text-content-secondary mb-0.5">
                {t('boq.aace_methodology', { defaultValue: 'Methodology' })}
              </div>
              <p className="text-xs text-content-tertiary leading-relaxed">
                {classification.methodology}
              </p>
            </div>
          </div>

          {/* Metrics breakdown */}
          <div>
            <div className="text-xs font-medium text-content-secondary mb-2">
              {t('boq.aace_metrics', { defaultValue: 'Classification Metrics' })}
            </div>
            <div className="space-y-2">
              <MetricRow
                label={t('boq.aace_positions', { defaultValue: 'Positions' })}
                value={metrics.total_positions}
                total={metrics.total_positions}
                pct={metrics.total_positions > 0 ? 100 : 0}
              />
              <MetricRow
                label={t('boq.aace_with_rates', { defaultValue: 'With unit rates' })}
                value={metrics.positions_with_rates}
                total={metrics.total_positions}
                pct={metrics.rate_completeness_pct}
              />
              <MetricRow
                label={t('boq.aace_with_resources', { defaultValue: 'Fully resourced' })}
                value={metrics.positions_with_resources}
                total={metrics.total_positions}
                pct={metrics.resource_completeness_pct}
              />
              <MetricRow
                label={t('boq.aace_with_classification', { defaultValue: 'With classification' })}
                value={metrics.positions_with_classification}
                total={metrics.total_positions}
                pct={metrics.classification_completeness_pct}
              />
            </div>
          </div>

          {/* AACE reference note */}
          <p className="text-[10px] text-content-tertiary leading-relaxed">
            {t('boq.aace_reference', {
              defaultValue:
                'Based on AACE International Recommended Practice 18R-97. Classification is auto-detected from BOQ completeness metrics.',
            })}
          </p>
        </div>
      )}
    </div>
  );
}
