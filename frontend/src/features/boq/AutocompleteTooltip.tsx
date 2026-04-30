/**
 * AutocompleteTooltip — rich hover preview for BOQ description-cell suggestions.
 *
 * Phase F of v2.7.0. The BOQ description cell uses an autocomplete that
 * fetches cost-database matches as the user types; each suggestion is a
 * single line (description + code). After 300 ms of mouse hover the
 * AutocompleteInput renders this tooltip alongside the dropdown so the
 * estimator can see:
 *
 *   • the full (untruncated) description,
 *   • the code + region badges,
 *   • the unit + native-currency rate,
 *   • a labor / material / equipment cost breakdown (when present),
 *   • the classification path (collection › department › section),
 *   • a "Tab to insert" hint,
 *   • a variants-available indicator when the cost item has 2+ CWICR
 *     abstract-resource variants.
 *
 * Behavioural rules (per spec):
 *   • Anchored at ``anchorRect.right + 8 px`` so it never visually
 *     obscures the dropdown row.
 *   • Auto-flips to the LEFT side when it would overflow the right edge
 *     of the viewport.
 *   • Rendered in a portal at ``document.body`` so it can escape any
 *     ``overflow: hidden`` ancestor of the dropdown.
 *   • ``pointer-events: none`` — the tooltip never steals focus or
 *     clicks from the input.
 *   • Respects ``prefers-reduced-motion`` (no fade-in animation).
 *
 * Mobile / touch detection is the AutocompleteInput's job (see
 * ``AutocompleteInput.tsx``); this component assumes it's only rendered
 * on hover-capable devices.
 */

import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { HardHat, Wrench, Package, Layers, Sparkles, CornerDownLeft } from 'lucide-react';
import type { CostAutocompleteItem } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

const TOOLTIP_WIDTH = 320; // px
const VIEWPORT_GUTTER = 8; // px — gap between dropdown and tooltip
const VIEWPORT_PADDING = 12; // px — keep the tooltip clear of the edge

export interface AutocompleteTooltipProps {
  /** The suggestion the user is hovering. */
  item: CostAutocompleteItem;
  /** Bounding rect of the dropdown row the tooltip should anchor to. */
  anchorRect: DOMRect;
  /** Currency symbol or ISO code to display next to the rate / breakdown. */
  currencySymbol: string;
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

/**
 * Build the classification path the tooltip footer renders. Walks the
 * known CWICR keys (``collection`` → ``department`` → ``section`` →
 * ``subsection``) and skips empty / sentinel values. Empty result means
 * the row carried no classification — the section then hides.
 */
function buildClassificationPath(classification: Record<string, string>): string[] {
  const order: (keyof typeof classification)[] = ['collection', 'department', 'section', 'subsection'];
  const out: string[] = [];
  for (const key of order) {
    const v = classification[key];
    if (typeof v === 'string' && v.trim() && v !== '__unspecified__') {
      out.push(v.trim());
    }
  }
  return out;
}

/** Format a numeric value for display. Uses the active i18n locale. */
function formatNumber(value: number): string {
  return new Intl.NumberFormat(getIntlLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/** True when the user's OS asks for reduced motion. SSR-safe. */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/* ── Component ───────────────────────────────────────────────────────── */

export function AutocompleteTooltip({
  item,
  anchorRect,
  currencySymbol,
}: AutocompleteTooltipProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement | null>(null);

  // Final position. Computed in a layout effect so we can flip the
  // tooltip when it would overflow the viewport's right edge.
  const [position, setPosition] = useState<{ left: number; top: number }>(() => ({
    left: anchorRect.right + VIEWPORT_GUTTER,
    top: anchorRect.top,
  }));

  useLayoutEffect(() => {
    if (typeof window === 'undefined') return;
    const node = ref.current;
    // ``offsetWidth`` / ``offsetHeight`` return 0 in JSDOM and during the
    // first paint before the browser has a chance to compute layout —
    // fall back to the fixed sizes so the flip math still produces a
    // sensible result instead of always thinking the tooltip is empty.
    const measuredHeight = node && node.offsetHeight > 0 ? node.offsetHeight : 240;
    const measuredWidth = node && node.offsetWidth > 0 ? node.offsetWidth : TOOLTIP_WIDTH;

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let left = anchorRect.right + VIEWPORT_GUTTER;
    if (left + measuredWidth + VIEWPORT_PADDING > viewportWidth) {
      // Flip to the LEFT side of the dropdown row.
      left = Math.max(VIEWPORT_PADDING, anchorRect.left - measuredWidth - VIEWPORT_GUTTER);
    }
    let top = anchorRect.top;
    // Pin into the viewport vertically so we never disappear off-screen.
    if (top + measuredHeight + VIEWPORT_PADDING > viewportHeight) {
      top = Math.max(VIEWPORT_PADDING, viewportHeight - measuredHeight - VIEWPORT_PADDING);
    }
    if (top < VIEWPORT_PADDING) top = VIEWPORT_PADDING;

    setPosition({ left, top });
  }, [anchorRect.left, anchorRect.right, anchorRect.top, item.code]);

  const reduceMotion = useMemo(() => prefersReducedMotion(), []);

  const classificationPath = buildClassificationPath(item.classification ?? {});
  const breakdown = item.cost_breakdown ?? undefined;
  const hasBreakdown =
    !!breakdown &&
    ((breakdown.labor_cost ?? 0) > 0 ||
      (breakdown.material_cost ?? 0) > 0 ||
      (breakdown.equipment_cost ?? 0) > 0);

  const variantCount =
    item.metadata_?.variant_count ??
    (Array.isArray(item.metadata_?.variants) ? item.metadata_!.variants!.length : 0);
  const hasVariants = variantCount >= 2;

  const node = (
    <div
      ref={ref}
      role="tooltip"
      data-testid="autocomplete-tooltip"
      style={{
        position: 'fixed',
        left: position.left,
        top: position.top,
        width: TOOLTIP_WIDTH,
        pointerEvents: 'none',
        zIndex: 10000,
      }}
      className={
        'rounded-lg border border-border-light dark:border-border-dark ' +
        'bg-surface-elevated shadow-2xl text-content-primary ' +
        (reduceMotion ? '' : 'animate-fade-in')
      }
    >
      {/* ── Header: full description + code/region badges ──────────── */}
      <div className="px-3 py-2 border-b border-border-light dark:border-border-dark bg-gradient-to-r from-violet-50/60 to-blue-50/60 dark:from-violet-950/30 dark:to-blue-950/30 rounded-t-lg">
        <p
          className="text-sm font-medium text-content-primary leading-snug"
          data-testid="autocomplete-tooltip-description"
        >
          {item.description}
        </p>
        <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-secondary text-content-secondary">
            {item.code}
          </span>
          {item.region && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 font-medium"
              data-testid="autocomplete-tooltip-region"
            >
              {item.region}
            </span>
          )}
        </div>
      </div>

      {/* ── Body: rate + cost breakdown ─────────────────────────────── */}
      <div className="px-3 py-2.5 space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] uppercase tracking-wider text-content-tertiary">
            {t('boq.autocomplete_tooltip_rate_per_unit', { defaultValue: 'Rate per unit' })}
          </span>
          <span className="text-sm font-semibold tabular-nums">
            {formatNumber(item.rate)} {currencySymbol}
            <span className="ml-1 text-[10px] text-content-tertiary uppercase">
              {t('boq.autocomplete_tooltip_unit', { defaultValue: '/' })}
              {item.unit}
            </span>
          </span>
        </div>

        {hasBreakdown && (
          <div
            className="border-t border-border-light/60 pt-2 space-y-1"
            data-testid="autocomplete-tooltip-breakdown"
          >
            {(breakdown?.labor_cost ?? 0) > 0 && (
              <BreakdownRow
                icon={<HardHat size={12} className="text-amber-600" />}
                label={t('boq.autocomplete_tooltip_labor', { defaultValue: 'Labor' })}
                value={`${formatNumber(breakdown!.labor_cost!)} ${currencySymbol}`}
              />
            )}
            {(breakdown?.material_cost ?? 0) > 0 && (
              <BreakdownRow
                icon={<Package size={12} className="text-emerald-600" />}
                label={t('boq.autocomplete_tooltip_material', { defaultValue: 'Material' })}
                value={`${formatNumber(breakdown!.material_cost!)} ${currencySymbol}`}
              />
            )}
            {(breakdown?.equipment_cost ?? 0) > 0 && (
              <BreakdownRow
                icon={<Wrench size={12} className="text-sky-600" />}
                label={t('boq.autocomplete_tooltip_equipment', { defaultValue: 'Equipment' })}
                value={`${formatNumber(breakdown!.equipment_cost!)} ${currencySymbol}`}
              />
            )}
          </div>
        )}
      </div>

      {/* ── Footer: classification path + variant + Tab hint ───────── */}
      {(classificationPath.length > 0 || hasVariants) && (
        <div className="px-3 py-2 border-t border-border-light dark:border-border-dark space-y-1.5">
          {classificationPath.length > 0 && (
            <div
              className="flex items-start gap-1.5 text-[11px] text-content-secondary"
              data-testid="autocomplete-tooltip-classification"
            >
              <Layers size={11} className="mt-0.5 shrink-0 text-content-tertiary" />
              <span className="leading-snug">
                <span className="text-[9px] uppercase tracking-wider text-content-tertiary mr-1">
                  {t('boq.autocomplete_tooltip_classification', {
                    defaultValue: 'Classification',
                  })}
                </span>
                <span>{classificationPath.join(' › ')}</span>
              </span>
            </div>
          )}
          {hasVariants && (
            <div
              className="flex items-center gap-1.5 text-[11px] text-violet-600 dark:text-violet-400"
              data-testid="autocomplete-tooltip-variants"
            >
              <Sparkles size={11} className="shrink-0" />
              <span>
                {t('boq.autocomplete_tooltip_variants_available', {
                  count: variantCount,
                  defaultValue: `${variantCount} variants available`,
                })}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="px-3 py-1.5 border-t border-border-light dark:border-border-dark bg-surface-secondary/40 rounded-b-lg flex items-center gap-1.5 text-[10px] text-content-tertiary">
        <CornerDownLeft size={11} className="shrink-0" />
        <span>
          {t('boq.autocomplete_tooltip_tab_to_insert', {
            defaultValue: 'Tab or Enter to insert',
          })}
        </span>
      </div>
    </div>
  );

  if (typeof document === 'undefined') return null;
  return createPortal(node, document.body);
}

interface BreakdownRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}

function BreakdownRow({ icon, label, value }: BreakdownRowProps) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="flex items-center gap-1.5 text-content-secondary">
        {icon}
        {label}
      </span>
      <span className="tabular-nums font-mono text-content-primary">{value}</span>
    </div>
  );
}
