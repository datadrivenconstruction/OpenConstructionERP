// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// VariantPicker — portal popover that lets the user choose one of N
// CWICR abstract-resource price variants when applying a cost item to a
// BOQ position.
//
// v2.6.24 redesign — when CWICR variants carry long descriptive labels
// ("Ready-mix concrete C30/37, 32mm agg, S3 slump, supplier: ..."), a
// single-line truncated row was unreadable. The picker now:
//
//   * widens to 520 px (max-w 92vw on small screens) so two-line labels fit;
//   * shows the FULL label, wrapped, with a clamp at 3 lines + tooltip;
//   * surfaces a delta-vs-mean chip per row so the user can see how each
//     variant deviates from the average at a glance;
//   * adds a search input (visible when ≥ 6 variants) to narrow by keyword;
//   * adds a sort dropdown (default / price asc / price desc / label).
//
// Keyboard / portal behaviour preserved from the original implementation:
//   * portal-rendered into `document.body` so AG Grid clipping cannot hide it;
//   * anchored to a DOM element (typically the row's Add button);
//   * Esc / outside-click / explicit close all call `onClose()`;
//   * Apply does NOT auto-close — parent owns the close lifecycle so it
//     can sequence multiple pickers in a multi-select flow.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { X, Search, ArrowUpDown } from 'lucide-react';
import { Badge, Button, KvList, Kv, QtyTile } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import type { CostVariant, VariantStats } from './api';

/* ── Props ────────────────────────────────────────────────────────────── */

export interface VariantPickerProps {
  variants: CostVariant[];
  stats: VariantStats;
  /** Pre-selected row.  When omitted, the row whose price matches
   *  `stats[defaultStrategy]` is preferred; otherwise `floor(len/2)`. */
  defaultIndex?: number;
  /** Which `VariantStats` field drives the auto-default.  `"mean"` is the
   *  production default for new applies (matches CostX/iTWO behaviour);
   *  `"median"` is kept for the legacy panel that tags the median row in
   *  the cost-DB browser. */
  defaultStrategy?: 'mean' | 'median';
  /** Anchor element used to position the popover.  When `null`, the
   *  popover renders centered on screen as a graceful fallback. */
  anchorEl: HTMLElement | null;
  unitLabel: string;
  currency: string;
  onApply: (chosen: CostVariant) => void;
  /** Optional one-click "use average" path — when supplied, the picker
   *  surfaces an extra footer button that applies the mean rate without
   *  forcing the user to pick a row.  The argument is the strategy that
   *  was honoured (passed up so the parent can stamp `variant_default`). */
  onUseDefault?: (strategy: 'mean' | 'median') => void;
  onClose: () => void;
}

type SortMode = 'default' | 'price_asc' | 'price_desc' | 'label';

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Format a price in the given currency using the active i18n locale. */
function formatPrice(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: currency || 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    const n = new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
    return currency ? `${n} ${currency}` : n;
  }
}

/** Resolve the initial selected index per the design rule. */
function resolveDefaultIndex(
  variants: CostVariant[],
  stats: VariantStats,
  strategy: 'mean' | 'median',
  override?: number,
): number {
  if (override != null && override >= 0 && override < variants.length) {
    return override;
  }
  const target = strategy === 'mean' ? stats.mean : stats.median;
  const exactIdx = variants.findIndex((v) => Math.abs(v.price - target) < 0.01);
  if (exactIdx >= 0) return exactIdx;
  let bestIdx = 0;
  let bestDelta = Number.POSITIVE_INFINITY;
  for (let i = 0; i < variants.length; i++) {
    const variant = variants[i];
    if (!variant) continue;
    const delta = Math.abs(variant.price - target);
    if (delta < bestDelta) {
      bestDelta = delta;
      bestIdx = i;
    }
  }
  return bestIdx;
}

/** Signed % deviation of `price` vs `mean`. Returns null when mean is 0
 *  (degenerate dataset where every variant has the same price). */
function deltaVsMean(price: number, mean: number): number | null {
  if (!mean || mean === 0) return null;
  return ((price - mean) / mean) * 100;
}

/** Format the delta chip — keeps the sign explicit and rounds to whole %
 *  for visual stability. Returns "—" for zero-tolerant matches so we don't
 *  show "+0%" / "-0%" jitter. */
function formatDelta(deltaPct: number | null): { text: string; tone: 'pos' | 'neg' | 'flat' } {
  if (deltaPct === null) return { text: '—', tone: 'flat' };
  if (Math.abs(deltaPct) < 0.5) return { text: '≈ avg', tone: 'flat' };
  const rounded = Math.round(deltaPct);
  return {
    text: `${rounded > 0 ? '+' : ''}${rounded}%`,
    tone: rounded > 0 ? 'pos' : 'neg',
  };
}

/* ── Component ────────────────────────────────────────────────────────── */

export function VariantPicker({
  variants,
  stats,
  defaultIndex,
  defaultStrategy = 'mean',
  anchorEl,
  unitLabel,
  currency,
  onApply,
  onUseDefault,
  onClose,
}: VariantPickerProps) {
  const { t } = useTranslation();
  const popoverRef = useRef<HTMLDivElement>(null);

  /* `selectedIdx` indexes into the ORIGINAL `variants` array, not the
   *  display-sorted/filtered view. That keeps the parent's apply contract
   *  unchanged — it always receives the same `CostVariant` shape regardless
   *  of how the user got there. */
  const [selectedIdx, setSelectedIdx] = useState<number>(() =>
    resolveDefaultIndex(variants, stats, defaultStrategy, defaultIndex),
  );
  const [query, setQuery] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('default');

  /* ── Anchor tracking ─────────────────────────────────────────────── */
  //
  // We measure the anchor ONCE on mount (and again on viewport resize) and
  // freeze the popover at that location. Earlier behaviour also reacted to
  // every ``scroll`` event so the popover would follow the anchor — but
  // when AG Grid scrolls horizontally the anchor moves left/right and the
  // popover ended up jumping side-to-side. Since the popover is rendered
  // into ``document.body`` (position: fixed), we let it stay put and
  // close it explicitly via Esc / outside-click instead. This matches how
  // most popover libraries (Floating UI, Headless UI) behave by default.
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(() =>
    anchorEl ? anchorEl.getBoundingClientRect() : null,
  );
  useEffect(() => {
    if (!anchorEl) return;
    const update = () => setAnchorRect(anchorEl.getBoundingClientRect());
    update();
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
    };
  }, [anchorEl]);

  /* ── Esc / outside-click ─────────────────────────────────────────── */
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', handleKey, { capture: true });
    return () => document.removeEventListener('keydown', handleKey, { capture: true });
  }, [onClose]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  /* ── Width / placement ───────────────────────────────────────────── */
  const POPOVER_WIDTH = 520;
  const POPOVER_MAX_HEIGHT = 560;
  const style = useMemo<React.CSSProperties>(() => {
    if (!anchorRect) {
      return {
        position: 'fixed',
        left: '50%',
        top: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 10000,
      };
    }
    const desiredWidth = Math.min(POPOVER_WIDTH, window.innerWidth - 16);
    const top = anchorRect.bottom + 4;
    const left = Math.min(
      Math.max(8, anchorRect.left),
      window.innerWidth - desiredWidth - 8,
    );
    if (top + POPOVER_MAX_HEIGHT > window.innerHeight) {
      const flippedTop = Math.max(8, anchorRect.top - POPOVER_MAX_HEIGHT - 4);
      return { position: 'fixed', left, top: flippedTop, zIndex: 10000 };
    }
    return { position: 'fixed', left, top, zIndex: 10000 };
  }, [anchorRect]);

  /* ── Default chip — index in the original list ───────────────────── */
  const defaultIdx = useMemo(
    () => resolveDefaultIndex(variants, stats, defaultStrategy),
    [variants, stats, defaultStrategy],
  );

  /* ── Display rows: filter then sort. Each row carries its original
   *      index so clicking any row updates `selectedIdx` correctly. ── */
  const displayRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const indexed = variants.map((v, originalIdx) => ({ v, originalIdx }));
    const filtered = q
      ? indexed.filter(({ v }) => v.label.toLowerCase().includes(q))
      : indexed;
    const sorted = [...filtered];
    switch (sortMode) {
      case 'price_asc':
        sorted.sort((a, b) => a.v.price - b.v.price);
        break;
      case 'price_desc':
        sorted.sort((a, b) => b.v.price - a.v.price);
        break;
      case 'label':
        sorted.sort((a, b) => a.v.label.localeCompare(b.v.label));
        break;
      case 'default':
      default:
        // Original CWICR order — leaves the canonical variant at index 0.
        break;
    }
    return sorted;
  }, [variants, query, sortMode]);

  const chosen = variants[selectedIdx];
  const showSearch = variants.length >= 6;

  const handleApply = () => {
    if (chosen) onApply(chosen);
  };
  const handleUseDefault = () => {
    onUseDefault?.(defaultStrategy);
  };

  const defaultChipLabel =
    defaultStrategy === 'mean'
      ? t('costs.variant_default_mean_chip', { defaultValue: 'Average' })
      : t('costs.variant_default_median_chip', { defaultValue: 'Median' });

  const popover = (
    <div
      ref={popoverRef}
      role="dialog"
      aria-modal="true"
      aria-label={t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
      className="bg-surface-elevated border border-border-light dark:border-border-dark
                 rounded-xl shadow-2xl flex flex-col overflow-hidden"
      style={{
        ...style,
        width: 'min(520px, calc(100vw - 16px))',
        maxHeight: POPOVER_MAX_HEIGHT,
      }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 shrink-0">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-sm font-semibold text-content-primary truncate">
            {t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
          </span>
          <span className="text-2xs text-content-tertiary tabular-nums shrink-0">
            {variants.length === 1
              ? t('costs.variant_count_one', { defaultValue: '1 option' })
              : t('costs.variant_count_n', {
                  defaultValue: '{{count}} options',
                  count: variants.length,
                })}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="h-6 w-6 flex items-center justify-center rounded text-content-tertiary
                     hover:text-content-primary hover:bg-surface-tertiary transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* ── Common base name (shared across all variants) ──────────────
       *   When the imported CWICR row carries
       *   ``price_abstract_resource_common_start``, that string is the
       *   shared base name (e.g. "Ready-mix concrete"). Showing it once
       *   here keeps the variant rows below short and scannable — they
       *   render only the distinguishing variable_part. The full name
       *   (common + variable) is stamped onto the BOQ resource row on
       *   apply, so the estimator sees the concrete pick in their grid.
       */}
      {stats.common_start && (
        <div className="px-4 py-2.5 border-b border-border-light bg-oe-blue-subtle/20 shrink-0">
          <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-0.5">
            {t('costs.variant_common_base', { defaultValue: 'Material / Resource' })}
          </div>
          <div className="text-sm font-semibold text-content-primary leading-snug break-words">
            {stats.common_start}
          </div>
        </div>
      )}

      {/* ── Stats banner ────────────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-border-light bg-surface-secondary/20 shrink-0">
        <KvList>
          <Kv
            label={t('costs.variant_min', { defaultValue: 'Min' })}
            value={
              <span className="tabular-nums">{formatPrice(stats.min, currency)}</span>
            }
          />
          <Kv
            label={t('costs.variant_mean', { defaultValue: 'Avg' })}
            value={
              <span className="tabular-nums font-medium">
                {formatPrice(stats.mean, currency)}
              </span>
            }
          />
          <Kv
            label={t('costs.variant_median', { defaultValue: 'Median' })}
            value={
              <span className="tabular-nums">{formatPrice(stats.median, currency)}</span>
            }
          />
          <Kv
            label={t('costs.variant_max', { defaultValue: 'Max' })}
            value={
              <span className="tabular-nums">{formatPrice(stats.max, currency)}</span>
            }
          />
        </KvList>
      </div>

      {/* ── Search + Sort toolbar (only for ≥6 variants) ────────────── */}
      {showSearch && (
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-light bg-surface-primary shrink-0">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <Search size={14} className="text-content-tertiary shrink-0" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('costs.variant_search_placeholder', {
                defaultValue: 'Filter variants by keyword…',
              })}
              className="flex-1 min-w-0 bg-transparent text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-1">
            <ArrowUpDown size={12} className="text-content-tertiary" />
            <select
              value={sortMode}
              onChange={(e) => setSortMode(e.target.value as SortMode)}
              className="bg-transparent text-2xs text-content-secondary focus:outline-none cursor-pointer"
              title={t('costs.variant_sort', { defaultValue: 'Sort variants' })}
            >
              <option value="default">
                {t('costs.variant_sort_default', { defaultValue: 'Default' })}
              </option>
              <option value="price_asc">
                {t('costs.variant_sort_price_asc', { defaultValue: 'Price ↑' })}
              </option>
              <option value="price_desc">
                {t('costs.variant_sort_price_desc', { defaultValue: 'Price ↓' })}
              </option>
              <option value="label">
                {t('costs.variant_sort_label', { defaultValue: 'Name A→Z' })}
              </option>
            </select>
          </div>
        </div>
      )}

      {/* ── Variant list ────────────────────────────────────────────── */}
      <div
        className="flex-1 overflow-y-auto"
        role="radiogroup"
        aria-label={t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
      >
        {displayRows.length === 0 ? (
          <div className="px-6 py-8 text-center text-xs text-content-tertiary">
            {t('costs.variant_no_match', {
              defaultValue: 'No variants match your filter.',
            })}
          </div>
        ) : (
          displayRows.map(({ v, originalIdx }) => {
            const isSel = originalIdx === selectedIdx;
            const isDefault = originalIdx === defaultIdx;
            const delta = formatDelta(deltaVsMean(v.price, stats.mean));
            return (
              <button
                key={v.index}
                type="button"
                role="radio"
                aria-checked={isSel}
                onClick={() => setSelectedIdx(originalIdx)}
                className={`w-full flex items-start gap-3 px-4 py-3 text-left border-b border-border-light/50 last:border-b-0 transition-colors ${
                  isSel
                    ? 'bg-oe-blue-subtle/20 ring-1 ring-inset ring-oe-blue/30'
                    : 'hover:bg-surface-secondary/60'
                }`}
                data-testid={`variant-row-${originalIdx}`}
              >
                {/* Radio circle */}
                <span
                  className={`mt-1 h-4 w-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                    isSel ? 'border-oe-blue' : 'border-content-quaternary'
                  }`}
                >
                  {isSel && <span className="h-2 w-2 rounded-full bg-oe-blue" />}
                </span>

                {/* Label + chips + per-unit info */}
                <div className="flex-1 min-w-0">
                  <p
                    className="text-sm leading-snug text-content-primary [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical] overflow-hidden break-words"
                    title={v.label}
                  >
                    {v.label}
                  </p>

                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {isDefault && (
                      <Badge variant="blue" size="sm">
                        {defaultChipLabel}
                      </Badge>
                    )}
                    <span
                      className={
                        delta.tone === 'pos'
                          ? 'inline-flex items-center rounded-full bg-amber-500/15 px-1.5 py-0.5 text-2xs font-semibold text-amber-700 dark:text-amber-300 tabular-nums'
                          : delta.tone === 'neg'
                          ? 'inline-flex items-center rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-2xs font-semibold text-emerald-700 dark:text-emerald-300 tabular-nums'
                          : 'inline-flex items-center rounded-full bg-surface-tertiary px-1.5 py-0.5 text-2xs font-medium text-content-secondary tabular-nums'
                      }
                      title={t('costs.variant_delta_tooltip', {
                        defaultValue: 'Difference vs the average rate',
                      })}
                    >
                      {delta.text}
                    </span>
                    {v.price_per_unit != null && (
                      <span className="text-2xs text-content-tertiary tabular-nums">
                        {t('costs.variant_per_unit', { defaultValue: 'Per unit' })}
                        {': '}
                        {v.price_per_unit.toLocaleString(undefined, {
                          maximumFractionDigits: 4,
                        })}
                      </span>
                    )}
                  </div>
                </div>

                {/* Price tile */}
                <div className="shrink-0">
                  <QtyTile
                    label={t('costs.rate', { defaultValue: 'Rate' })}
                    value={v.price}
                    unit={`${currency}${unitLabel ? `/${unitLabel}` : ''}`}
                  />
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <div className="px-4 py-2.5 border-t border-border-light bg-surface-secondary/30 flex items-center justify-between gap-2 shrink-0">
        {onUseDefault ? (
          <button
            type="button"
            onClick={handleUseDefault}
            className="text-2xs text-oe-blue hover:underline font-medium"
            data-testid="variant-picker-use-default"
            title={t('costs.variant_use_default_tooltip', {
              defaultValue:
                'Apply the average rate without picking a specific variant. You can refine later by clicking the row.',
            })}
          >
            {defaultStrategy === 'mean'
              ? t('costs.variant_use_average', { defaultValue: 'Use average rate' })
              : t('costs.variant_use_median', { defaultValue: 'Use median rate' })}
          </button>
        ) : (
          <span aria-hidden="true" />
        )}
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleApply}
            disabled={!chosen}
            data-testid="variant-picker-apply"
          >
            {t('common.apply', { defaultValue: 'Apply' })}
          </Button>
        </div>
      </div>
    </div>
  );

  return createPortal(popover, document.body);
}
