// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage 3 "why this rate" mapping trace (WP7, design 3.3 / 4.3).
//
// The matcher runs three named, observable passes per group (semantic
// candidates, unit/scale reconcile, rate-sanity vs a benchmark band) and
// writes the trace onto the group. This renders that trace as a compact,
// expandable per-pass story so the human can see exactly how a rate was
// chosen before confirming it. AI proposes, the human confirms - so the
// trace and the confidence are always in view.
//
// A rate that falls outside the per-run benchmark band gets a visible
// outlier badge with a plain-words tooltip; the real DB rate is never
// dropped, only flagged for review. The trace is display-only provenance:
// a missing / empty trace renders nothing rather than ever throwing.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ChevronDown,
  ChevronRight,
  Search,
  Ruler,
  ShieldCheck,
  AlertTriangle,
  HelpCircle,
} from 'lucide-react';
import type { MappingPass, MappingTrace as MappingTraceData } from '../api';

/** A short, layperson label + icon per pass name. Unknown future pass names
 *  fall back to the raw key so the component never blanks out. */
function passMeta(name: string): { icon: typeof Search; labelKey: string; labelFallback: string } {
  switch (name) {
    case 'semantic':
      return {
        icon: Search,
        labelKey: 'aiest.map.pass_semantic',
        labelFallback: 'Find candidates',
      };
    case 'unit_scale':
      return {
        icon: Ruler,
        labelKey: 'aiest.map.pass_unit_scale',
        labelFallback: 'Reconcile units',
      };
    case 'rate_sanity':
      return {
        icon: ShieldCheck,
        labelKey: 'aiest.map.pass_rate_sanity',
        labelFallback: 'Sanity-check the rate',
      };
    default:
      return { icon: Search, labelKey: '', labelFallback: name };
  }
}

/**
 * The standalone outlier badge with a plain-words tooltip. Rendered both in
 * the card header (for the chosen rate) and inline on a flagged alternative.
 * Visible by design so a suspect rate is never confirmed unseen.
 */
export function OutlierBadge({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
        className,
      )}
      title={t('aiest.map.outlier_tooltip', {
        defaultValue:
          'This rate is far from the typical price for this kind of work in the catalogue. We kept the real rate but flagged it so you can review it before accepting.',
      })}
      data-testid="aiest-outlier-badge"
    >
      <AlertTriangle className="h-3 w-3" />
      {t('aiest.map.outlier', { defaultValue: 'Rate outlier' })}
    </span>
  );
}

function PassRow({ pass }: { pass: MappingPass }) {
  const { t } = useTranslation();
  const meta = passMeta(pass.pass);
  const Icon = meta.icon;
  const bench = pass.benchmark;
  const hasOutliers = (bench?.outliers ?? 0) > 0;

  return (
    <li className="flex items-start gap-2" data-testid="aiest-trace-pass" data-pass={pass.pass}>
      <Icon
        className={clsx(
          'mt-0.5 h-3.5 w-3.5 shrink-0',
          hasOutliers ? 'text-amber-500' : 'text-content-tertiary',
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-xs font-medium text-content-primary">
            {meta.labelKey
              ? t(meta.labelKey, { defaultValue: meta.labelFallback })
              : meta.labelFallback}
          </span>
          <span className="text-[11px] text-content-tertiary">
            {t('aiest.map.kept_dropped', {
              defaultValue: '{{kept}} kept, {{dropped}} demoted',
              kept: pass.kept,
              dropped: pass.dropped,
            })}
          </span>
        </div>
        {pass.notes && (
          <div className="mt-0.5 text-[11px] leading-snug text-content-secondary">{pass.notes}</div>
        )}
        {/* Rate-sanity benchmark band: the catalogue-relative bounds used to
            flag outliers. Shown as median-relative multipliers so the band is
            currency- and catalogue-agnostic (e.g. "0.5x to 8x of the median").*/}
        {bench && bench.band_low != null && bench.band_high != null && (
          <div className="mt-0.5 text-[11px] text-content-tertiary">
            {t('aiest.map.band', {
              defaultValue: 'Plausible band: {{low}}x to {{high}}x of the median rate',
              low: bench.band_low,
              high: bench.band_high,
            })}
            {hasOutliers && (
              <span className="ml-1.5 inline-flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-3 w-3" />
                {t('aiest.map.band_outliers', {
                  defaultValue: '{{n}} flagged',
                  n: bench.outliers,
                })}
              </span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export interface MappingTraceProps {
  trace: MappingTraceData | null | undefined;
  /** Start expanded (e.g. when the chosen rate is a flagged outlier so the
   *  reason is in view without a click). */
  defaultOpen?: boolean;
}

/**
 * The collapsible "why this rate" trace: a header toggle plus the ordered
 * per-pass list. Renders nothing when there is no trace yet (an unmatched
 * group), keeping the field honest.
 */
export function MappingTrace({ trace, defaultOpen = false }: MappingTraceProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);

  const passes = trace?.passes ?? [];
  if (passes.length === 0) return null;

  return (
    <div className="rounded-lg border border-border-light bg-surface-muted/40" data-testid="aiest-mapping-trace">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        )}
        <HelpCircle className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
        <span className="text-xs font-medium text-content-secondary">
          {t('aiest.map.why_this_rate', { defaultValue: 'Why this rate' })}
        </span>
        <span className="ml-auto text-[11px] text-content-tertiary">
          {t('aiest.map.n_passes', { defaultValue: '{{n}} passes', n: passes.length })}
        </span>
      </button>

      {open && (
        <div className="space-y-2 border-t border-border-light px-2.5 py-2">
          <ol className="space-y-2">
            {passes.map((p, i) => (
              <PassRow key={`${p.pass}-${i}`} pass={p} />
            ))}
          </ol>

          <div className="flex flex-wrap items-center gap-2 border-t border-border-light pt-2 text-[11px] text-content-tertiary">
            {trace?.final_method && (
              <span>
                {t('aiest.map.final_method', {
                  defaultValue: 'Chosen by: {{method}}',
                  method: t(`aiest.method.${trace.final_method}`, {
                    defaultValue: trace.final_method,
                  }),
                })}
              </span>
            )}
            {trace?.needs_human_reason && (
              <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                <AlertTriangle className="h-3 w-3" />
                {t('aiest.map.needs_human', {
                  defaultValue: 'Parked for review: every rate is an outlier',
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
