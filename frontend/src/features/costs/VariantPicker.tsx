// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// VariantPicker — portal popover that lets the user choose one of N
// CWICR abstract-resource price variants when applying a cost item to a
// BOQ position.  Pattern mirrors `features/boq/grid/BIMQuantityPicker.tsx`:
//
//   * portal-rendered into `document.body` so AG Grid clipping and modal
//     stacking contexts cannot hide it;
//   * anchored to a DOM element (typically the row's Add button);
//   * Esc / outside-click / explicit close all call `onClose()`;
//   * Apply does NOT auto-close — parent owns the close lifecycle so it
//     can sequence multiple pickers in a multi-select flow.
//
// Reused primitives: KvList, Kv, QtyTile, Badge from '@/shared/ui'.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Badge, Button, KvList, Kv, QtyTile } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import type { CostVariant, VariantStats } from './api';

/* ── Props ────────────────────────────────────────────────────────────── */

export interface VariantPickerProps {
  variants: CostVariant[];
  stats: VariantStats;
  /** Pre-selected row.  When omitted, the row whose price equals
   *  `stats.median` is preferred; otherwise `floor(len/2)`. */
  defaultIndex?: number;
  /** Anchor element used to position the popover.  When `null`, the
   *  popover renders centered on screen as a graceful fallback. */
  anchorEl: HTMLElement | null;
  unitLabel: string;
  currency: string;
  onApply: (chosen: CostVariant) => void;
  onClose: () => void;
}

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
    // Unknown currency code — fall back to plain number + ISO suffix.
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
  override?: number,
): number {
  if (
    override != null &&
    override >= 0 &&
    override < variants.length
  ) {
    return override;
  }
  const medianIdx = variants.findIndex(
    (v) => Math.abs(v.price - stats.median) < 0.01,
  );
  if (medianIdx >= 0) return medianIdx;
  return Math.floor(variants.length / 2);
}

/* ── Component ────────────────────────────────────────────────────────── */

export function VariantPicker({
  variants,
  stats,
  defaultIndex,
  anchorEl,
  unitLabel,
  currency,
  onApply,
  onClose,
}: VariantPickerProps) {
  const { t } = useTranslation();
  const popoverRef = useRef<HTMLDivElement>(null);

  const [selectedIdx, setSelectedIdx] = useState<number>(() =>
    resolveDefaultIndex(variants, stats, defaultIndex),
  );

  // Anchor rect — re-read on mount and on scroll/resize so a long-lived
  // picker still tracks the anchor.  Falls back to centered placement
  // when no anchor is provided.
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(() =>
    anchorEl ? anchorEl.getBoundingClientRect() : null,
  );
  useEffect(() => {
    if (!anchorEl) return;
    const update = () => setAnchorRect(anchorEl.getBoundingClientRect());
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [anchorEl]);

  // Close on Escape.
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

  // Close on outside click.
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  // Compute portal style — match BIMQuantityPicker logic but a touch wider
  // because variant labels can be long.
  const POPOVER_WIDTH = 360;
  const POPOVER_MAX_HEIGHT = 480;
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
    const top = anchorRect.bottom + 4;
    const left = Math.min(
      Math.max(8, anchorRect.left),
      window.innerWidth - POPOVER_WIDTH - 8,
    );
    if (top + POPOVER_MAX_HEIGHT > window.innerHeight) {
      const flippedTop = Math.max(8, anchorRect.top - POPOVER_MAX_HEIGHT - 4);
      return { position: 'fixed', left, top: flippedTop, zIndex: 10000 };
    }
    return { position: 'fixed', left, top, zIndex: 10000 };
  }, [anchorRect]);

  const medianIdx = useMemo(
    () => variants.findIndex((v) => Math.abs(v.price - stats.median) < 0.01),
    [variants, stats.median],
  );

  const chosen = variants[selectedIdx];

  const handleApply = () => {
    if (chosen) onApply(chosen);
  };

  const popover = (
    <div
      ref={popoverRef}
      role="dialog"
      aria-modal="true"
      aria-label={t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
      className="bg-surface-elevated border border-border-light dark:border-border-dark
                 rounded-xl shadow-2xl flex flex-col overflow-hidden"
      style={{ ...style, width: POPOVER_WIDTH, maxHeight: POPOVER_MAX_HEIGHT }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold text-content-primary truncate">
            {t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
          </span>
          <span className="text-2xs text-content-tertiary tabular-nums shrink-0">
            ({variants.length})
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

      {/* Stats */}
      <div className="px-4 py-3 border-b border-border-light bg-surface-secondary/20 shrink-0">
        <KvList>
          <Kv
            label={t('costs.variant_min', { defaultValue: 'Min' })}
            value={<span className="tabular-nums">{formatPrice(stats.min, currency)}</span>}
          />
          <Kv
            label={t('costs.variant_median', { defaultValue: 'Median' })}
            value={<span className="tabular-nums font-medium">{formatPrice(stats.median, currency)}</span>}
          />
          <Kv
            label={t('costs.variant_max', { defaultValue: 'Max' })}
            value={<span className="tabular-nums">{formatPrice(stats.max, currency)}</span>}
          />
          <Kv
            label={t('costs.variant_count', { defaultValue: 'Count' })}
            value={<span className="tabular-nums">{stats.count}</span>}
          />
        </KvList>
      </div>

      {/* Variant list */}
      <div
        className="flex-1 overflow-y-auto"
        role="radiogroup"
        aria-label={t('costs.choose_variant', { defaultValue: 'Choose price variant' })}
      >
        {variants.map((v, idx) => {
          const isSel = idx === selectedIdx;
          const isMedian = idx === medianIdx;
          return (
            <button
              key={v.index}
              type="button"
              role="radio"
              aria-checked={isSel}
              onClick={() => setSelectedIdx(idx)}
              className={`w-full flex items-start gap-2.5 px-4 py-2 text-left border-b border-border-light/50 last:border-b-0 transition-colors ${
                isSel
                  ? 'bg-oe-blue-subtle/20'
                  : 'hover:bg-surface-secondary/60'
              }`}
            >
              {/* Radio circle */}
              <span
                className={`mt-0.5 h-4 w-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                  isSel ? 'border-oe-blue' : 'border-content-quaternary'
                }`}
              >
                {isSel && <span className="h-2 w-2 rounded-full bg-oe-blue" />}
              </span>

              {/* Label + footer */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span
                    className="text-xs font-medium text-content-primary truncate"
                    title={v.label}
                  >
                    {v.label}
                  </span>
                  {isMedian && (
                    <Badge variant="blue" size="sm">
                      {t('costs.variant_default_median_chip', { defaultValue: 'Median' })}
                    </Badge>
                  )}
                </div>
                {v.price_per_unit != null && (
                  <div className="text-2xs text-content-tertiary mt-0.5 tabular-nums">
                    {t('costs.variant_per_unit', { defaultValue: 'Per unit' })}
                    {': '}
                    {v.price_per_unit.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </div>
                )}
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
        })}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-border-light bg-surface-secondary/30 flex items-center justify-end gap-2 shrink-0">
        <Button variant="secondary" size="sm" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleApply}
          disabled={!chosen}
        >
          {t('common.apply', { defaultValue: 'Apply' })}
        </Button>
      </div>
    </div>
  );

  return createPortal(popover, document.body);
}
