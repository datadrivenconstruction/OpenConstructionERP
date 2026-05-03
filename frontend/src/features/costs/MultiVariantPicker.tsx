// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MultiVariantPicker — centered modal that handles a CostItem with MULTIPLE
// independent variant slots in one go.
//
// The single-slot case (one CWICR rate that splits into N alternatives) is
// served by VariantPicker.tsx — a portal popover anchored to a button. That
// flow is fine when there's one decision to make.
//
// The multi-slot case is different. A CWICR row whose components include
// 2+ abstract resources — concrete grade × rebar diameter × formwork type —
// needs the user to make N decisions before the position is meaningful. The
// previous behaviour silently stamped median defaults on every slot and
// hoped the user would discover the per-resource re-pick pills later. They
// often didn't. This modal makes the choice explicit and bulk-fast:
//
//   * One card per variant slot, vertically stacked, always visible.
//   * Each card shows the resource name, unit, qty, and the currently
//     selected variant with delta-vs-mean chip.
//   * Click the card to expand its full variant list inline — compact
//     rows with a radio control, label, unit price, and delta. Only one
//     card expands at a time so the modal height stays bounded.
//   * Bulk action bar at the top: "Median for all", "Mean for all",
//     "Cheapest for all", "Most expensive for all" — one click to seed
//     all slots, then refine individually.
//   * Live subtotal at the bottom: Σ (selected variant price × slot qty).
//   * Apply or Cancel. Cancel falls back to the previous silent-default
//     behaviour (median per slot) so power users aren't slowed down.

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  X,
  Check,
  ChevronDown,
  ChevronRight,
  Layers3,
  Wand2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import type { CostVariant, VariantStats } from './api';

/* ── Types ────────────────────────────────────────────────────────────── */

/** One independent variant decision the user has to make for a position.
 *  Slot ids are stable within a position so the parent can route each pick
 *  back to the right `metadata.resources[i]` entry. */
export interface VariantSlot {
  slotId: string;
  name: string;
  unit: string;
  /** Per-unit qty applied to this slot when the position is created.
   *  Multiplied with the chosen variant price for the live subtotal. */
  quantity: number;
  variants: CostVariant[];
  stats: VariantStats;
  currency: string;
}

/** What the user chose for one slot. */
export type SlotPick =
  | { kind: 'variant'; variant: CostVariant }
  | { kind: 'default'; strategy: 'mean' | 'median' };

export interface MultiVariantPickerResult {
  /** Map of slotId → pick. Every slot in the input is present here on apply. */
  picks: Record<string, SlotPick>;
  /** When true, the caller should re-use these picks for every remaining
   *  multi-variant item in the batch instead of opening the modal again.
   *  Slot-name matching across items is the caller's responsibility — this
   *  flag just authorises the fast-forward. */
  applyToAll?: boolean;
}

interface MultiVariantPickerProps {
  /** Title shown in the modal header — typically the position description. */
  positionTitle: string;
  /** Two or more slots. The single-slot fast path uses VariantPicker. */
  slots: VariantSlot[];
  /** Optional progress chip ("Item N of M") for batch-add flows where the
   *  modal opens once per cost item. Omit when there's a single position. */
  batchProgress?: { current: number; total: number };
  /** When the user is mid-batch (more multi-variant items waiting after
   *  this one), the modal exposes an "Apply to remaining N items" CTA.
   *  Omit or set to 0 to hide that affordance. */
  remainingCount?: number;
  /** Optional pre-seed when the previous item was applied with
   *  `applyToAll`. Slot-name matched by the caller; used as the initial
   *  picks instead of the default median baseline. */
  suggestedPicks?: Record<string, SlotPick>;
  onApply: (result: MultiVariantPickerResult) => void;
  onCancel: () => void;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

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

function cheapest(variants: CostVariant[]): CostVariant | null {
  if (!variants.length) return null;
  return variants.reduce((a, b) => (a.price <= b.price ? a : b));
}
function priciest(variants: CostVariant[]): CostVariant | null {
  if (!variants.length) return null;
  return variants.reduce((a, b) => (a.price >= b.price ? a : b));
}

interface DeltaInfo { text: string; tone: 'pos' | 'neg' | 'flat' }
function deltaVsMean(price: number, mean: number): DeltaInfo {
  if (!mean || mean === 0) return { text: '—', tone: 'flat' };
  const pct = Math.round(((price - mean) / mean) * 100);
  if (pct === 0) return { text: '0%', tone: 'flat' };
  return { text: `${pct > 0 ? '+' : ''}${pct}%`, tone: pct > 0 ? 'pos' : 'neg' };
}

/** Resolve the slot's effective unit-rate from a pick. */
function rateFromPick(pick: SlotPick, stats: VariantStats): number {
  if (pick.kind === 'variant') return pick.variant.price;
  return pick.strategy === 'mean' ? stats.mean : stats.median;
}

/** Slot label for the resource — prefers `common_start + label`, falls back
 *  to the variant's own `full_label`, then bare `label`. Mirrors the same
 *  resolution VariantPicker uses, so labels stay consistent across surfaces. */
function pickDisplayLabel(slot: VariantSlot, pick: SlotPick): string {
  if (pick.kind === 'variant') {
    const v = pick.variant;
    const full = (v.full_label || '').trim();
    if (full) return full;
    const cs = (slot.stats.common_start || '').trim();
    return cs ? `${cs} ${v.label}`.trim() : v.label;
  }
  return pick.strategy === 'mean' ? 'average' : 'median';
}

/* ── Component ────────────────────────────────────────────────────────── */

export function MultiVariantPicker({
  positionTitle,
  slots,
  batchProgress,
  remainingCount = 0,
  suggestedPicks,
  onApply,
  onCancel,
}: MultiVariantPickerProps) {
  const { t } = useTranslation();

  // Initial picks: median per slot — same baseline the silent default used,
  // so the running total shown matches what the user would have got without
  // engaging the modal. When `suggestedPicks` is provided (caller threading
  // the previous item's apply-to-all decision), that wins per-slot; slots
  // not present in the suggestions fall back to median.
  const [picks, setPicks] = useState<Record<string, SlotPick>>(() => {
    const seed: Record<string, SlotPick> = {};
    for (const s of slots) {
      const carried = suggestedPicks?.[s.slotId];
      // Defensive — only carry picks whose target variant still exists
      // in the new slot's variant list. CWICR rows can have different
      // variant indices even under the same slot name, so a stale index
      // would otherwise stamp a phantom rate.
      if (carried?.kind === 'variant') {
        const stillThere = s.variants.some((v) => v.index === carried.variant.index);
        seed[s.slotId] = stillThere
          ? carried
          : { kind: 'default', strategy: 'median' };
      } else if (carried?.kind === 'default') {
        seed[s.slotId] = carried;
      } else {
        seed[s.slotId] = { kind: 'default', strategy: 'median' };
      }
    }
    return seed;
  });

  // Only one slot card expands at a time so the modal stays a fixed height.
  const [expandedSlot, setExpandedSlot] = useState<string | null>(
    slots[0]?.slotId ?? null,
  );

  /** Apply button gets initial focus so screen readers announce it as the
   *  default action and Enter immediately confirms the median-baseline picks
   *  without having to tab through every slot card. */
  const applyButtonRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    applyButtonRef.current?.focus();
  }, []);

  /* Esc to cancel · Enter to apply (when focus is not inside an editable
   *  control — defensive, but the modal has no inputs today). */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
        return;
      }
      if (
        e.key === 'Enter' &&
        !e.shiftKey &&
        !e.ctrlKey &&
        !e.metaKey &&
        !(
          e.target instanceof HTMLElement &&
          (e.target.tagName === 'INPUT' ||
            e.target.tagName === 'TEXTAREA' ||
            e.target.isContentEditable)
        )
      ) {
        e.preventDefault();
        onApply({ picks });
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel, onApply, picks]);

  const subtotal = useMemo(() => {
    let sum = 0;
    for (const s of slots) {
      const p = picks[s.slotId];
      if (!p) continue;
      // Use ?? not || — qty of 0 is a legitimate slot value (e.g. rebar=0
      // for an unreinforced section). The || 1 fallback would inflate the
      // subtotal by treating zero-qty slots as 1 unit each.
      sum += rateFromPick(p, s.stats) * (s.quantity ?? 1);
    }
    return sum;
  }, [picks, slots]);

  const subtotalCurrency = slots[0]?.currency || 'USD';

  /* Bulk actions. Each one is idempotent — re-clicking always re-seeds. */
  const applyAll = (
    resolver: (slot: VariantSlot) => SlotPick,
  ): void => {
    const next: Record<string, SlotPick> = {};
    for (const s of slots) {
      next[s.slotId] = resolver(s);
    }
    setPicks(next);
  };

  const allMedian = () => applyAll(() => ({ kind: 'default', strategy: 'median' }));
  const allMean = () => applyAll(() => ({ kind: 'default', strategy: 'mean' }));
  const allCheapest = () =>
    applyAll((s) => {
      const v = cheapest(s.variants);
      return v ? { kind: 'variant', variant: v } : { kind: 'default', strategy: 'median' };
    });
  const allPriciest = () =>
    applyAll((s) => {
      const v = priciest(s.variants);
      return v ? { kind: 'variant', variant: v } : { kind: 'default', strategy: 'median' };
    });

  /* Per-slot pick handlers. */
  const setSlotPick = (slotId: string, pick: SlotPick) => {
    setPicks((cur) => ({ ...cur, [slotId]: pick }));
  };

  /* Only fully-resolved picks ship in the apply payload — defaults stay
   *  defaults so the backend stamps the right `variant_default` provenance. */
  const handleApply = () => onApply({ picks });
  const handleApplyToAll = () => onApply({ picks, applyToAll: true });

  return createPortal(
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
      onClick={onCancel}
      data-testid="multi-variant-picker-backdrop"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="mvp-title"
        className="w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col rounded-2xl bg-surface-primary shadow-2xl border border-border-light overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()}
        data-testid="multi-variant-picker"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-border-light flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-blue-50 dark:bg-blue-950/30 flex items-center justify-center shrink-0">
            <Layers3 size={20} className="text-oe-blue" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 id="mvp-title" className="text-base font-semibold truncate">
                {t('boq.mvp.title', { defaultValue: 'Choose materials' })}
              </h3>
              {batchProgress && batchProgress.total > 1 && (
                <Badge
                  variant="blue"
                  size="sm"
                  data-testid="mvp-batch-progress"
                >
                  {t('boq.mvp.batch_progress', {
                    defaultValue: 'Item {{current}} of {{total}}',
                    current: batchProgress.current,
                    total: batchProgress.total,
                  })}
                </Badge>
              )}
            </div>
            <p className="text-xs text-content-secondary truncate" title={positionTitle}>
              {positionTitle}
            </p>
            <p className="text-xs text-content-tertiary mt-0.5">
              {t('boq.mvp.subtitle', {
                defaultValue: '{{count}} resource needs a choice',
                defaultValue_other: '{{count}} resources need a choice',
                count: slots.length,
              })}
            </p>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg hover:bg-surface-hover text-content-tertiary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            data-testid="multi-variant-picker-close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Bulk actions */}
        <div className="px-6 py-3 border-b border-border-light bg-surface-secondary/40 flex flex-wrap items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-content-tertiary font-medium me-1">
            <Wand2 size={12} className="inline me-1 -mt-0.5" />
            {t('boq.mvp.bulk_label', { defaultValue: 'Quick fill:' })}
          </span>
          <BulkChip
            onClick={allMedian}
            label={t('boq.mvp.bulk_median', { defaultValue: 'Median for all' })}
            testId="mvp-bulk-median"
          />
          <BulkChip
            onClick={allMean}
            label={t('boq.mvp.bulk_mean', { defaultValue: 'Average for all' })}
            testId="mvp-bulk-mean"
          />
          <BulkChip
            onClick={allCheapest}
            icon={<TrendingDown size={12} />}
            label={t('boq.mvp.bulk_cheapest', { defaultValue: 'Cheapest for all' })}
            testId="mvp-bulk-cheapest"
          />
          <BulkChip
            onClick={allPriciest}
            icon={<TrendingUp size={12} />}
            label={t('boq.mvp.bulk_priciest', { defaultValue: 'Most expensive for all' })}
            testId="mvp-bulk-priciest"
          />
        </div>

        {/* Slots */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {slots.map((slot) => {
            const pick = picks[slot.slotId] ?? { kind: 'default', strategy: 'median' };
            const expanded = expandedSlot === slot.slotId;
            const rate = rateFromPick(pick, slot.stats);
            const lineTotal = rate * (slot.quantity ?? 1);
            const delta = deltaVsMean(rate, slot.stats.mean);
            const displayLabel = pickDisplayLabel(slot, pick);
            return (
              <div
                key={slot.slotId}
                className="rounded-xl border border-border-light bg-surface-primary overflow-hidden"
                data-testid={`mvp-slot-${slot.slotId}`}
              >
                {/* Slot header — always visible, click to expand */}
                <button
                  onClick={() => setExpandedSlot(expanded ? null : slot.slotId)}
                  className="w-full px-4 py-3 flex items-start gap-3 hover:bg-surface-hover text-start"
                  aria-expanded={expanded}
                  aria-controls={`mvp-slot-body-${slot.slotId}`}
                >
                  <div className="mt-0.5 text-content-tertiary shrink-0">
                    {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium truncate">{slot.name}</span>
                      <Badge variant="neutral" size="sm">
                        {t('boq.mvp.slot_variant_count', {
                          defaultValue: '{{n}} options',
                          n: slot.variants.length,
                        })}
                      </Badge>
                    </div>
                    <div className="text-xs text-content-secondary truncate">
                      <span className="text-content-tertiary me-1">
                        {t('boq.mvp.selected_label', { defaultValue: 'Picked:' })}
                      </span>
                      {pick.kind === 'default' ? (
                        <span className="italic">
                          {pick.strategy === 'mean'
                            ? t('boq.mvp.default_mean', { defaultValue: 'average rate' })
                            : t('boq.mvp.default_median', { defaultValue: 'median rate' })}
                        </span>
                      ) : (
                        <span>{displayLabel}</span>
                      )}
                    </div>
                  </div>
                  <div className="text-end shrink-0">
                    <div className="text-sm font-mono font-semibold tabular-nums">
                      {formatPrice(rate, slot.currency)}
                      <span className="text-[10px] text-content-tertiary font-normal ms-1">
                        /{slot.unit}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 justify-end mt-0.5">
                      <span
                        className={
                          'text-[10px] font-mono font-medium ' +
                          (delta.tone === 'pos'
                            ? 'text-rose-600 dark:text-rose-400'
                            : delta.tone === 'neg'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-content-tertiary')
                        }
                      >
                        {delta.text}
                      </span>
                      {slot.quantity > 1 && (
                        <span className="text-[10px] text-content-tertiary">
                          · {formatPrice(lineTotal, slot.currency)}
                        </span>
                      )}
                    </div>
                  </div>
                </button>

                {/* Slot body — expanded variant list */}
                {expanded && (
                  <div
                    id={`mvp-slot-body-${slot.slotId}`}
                    className="border-t border-border-light bg-surface-secondary/30 max-h-72 overflow-y-auto"
                  >
                    <DefaultRow
                      slot={slot}
                      picked={pick.kind === 'default' && pick.strategy === 'median'}
                      onPick={() => setSlotPick(slot.slotId, { kind: 'default', strategy: 'median' })}
                      label={t('boq.mvp.row_median', {
                        defaultValue: 'Median rate · {{price}}',
                        price: formatPrice(slot.stats.median, slot.currency),
                      })}
                      strategy="median"
                    />
                    <DefaultRow
                      slot={slot}
                      picked={pick.kind === 'default' && pick.strategy === 'mean'}
                      onPick={() => setSlotPick(slot.slotId, { kind: 'default', strategy: 'mean' })}
                      label={t('boq.mvp.row_mean', {
                        defaultValue: 'Average rate · {{price}}',
                        price: formatPrice(slot.stats.mean, slot.currency),
                      })}
                      strategy="mean"
                    />
                    <div className="border-t border-border-light/60 my-1" />
                    {slot.variants.map((v) => {
                      const checked = pick.kind === 'variant' && pick.variant.index === v.index;
                      const rowDelta = deltaVsMean(v.price, slot.stats.mean);
                      const label = (v.full_label || '').trim() ||
                        ((slot.stats.common_start || '').trim()
                          ? `${slot.stats.common_start} ${v.label}`.trim()
                          : v.label);
                      return (
                        <button
                          key={v.index}
                          onClick={() =>
                            setSlotPick(slot.slotId, { kind: 'variant', variant: v })
                          }
                          className={
                            'w-full px-4 py-2.5 flex items-start gap-3 text-start hover:bg-surface-hover ' +
                            (checked ? 'bg-blue-50/50 dark:bg-blue-950/30 ring-1 ring-inset ring-oe-blue/30' : '')
                          }
                          data-testid={`mvp-row-${slot.slotId}-${v.index}`}
                        >
                          <div
                            className={
                              'mt-0.5 h-4 w-4 rounded-full border-2 shrink-0 flex items-center justify-center ' +
                              (checked
                                ? 'border-oe-blue bg-oe-blue'
                                : 'border-border')
                            }
                          >
                            {checked && <Check size={10} className="text-white" />}
                          </div>
                          <div className="min-w-0 flex-1">
                            <span className="text-sm leading-snug line-clamp-2">{label}</span>
                          </div>
                          <div className="text-end shrink-0">
                            <span className="text-sm font-mono font-medium tabular-nums">
                              {formatPrice(v.price, slot.currency)}
                            </span>
                            <span
                              className={
                                'block text-[10px] font-mono font-medium mt-0.5 ' +
                                (rowDelta.tone === 'pos'
                                  ? 'text-rose-600 dark:text-rose-400'
                                  : rowDelta.tone === 'neg'
                                    ? 'text-emerald-600 dark:text-emerald-400'
                                    : 'text-content-tertiary')
                              }
                            >
                              {rowDelta.text}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border-light bg-surface-secondary/30 flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-content-tertiary font-medium">
              {t('boq.mvp.subtotal_label', { defaultValue: 'Position rate' })}
            </div>
            <div className="text-lg font-mono font-semibold tabular-nums text-content-primary">
              {formatPrice(subtotal, subtotalCurrency)}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="md"
              onClick={onCancel}
              data-testid="mvp-cancel"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            {remainingCount > 0 && (
              <Button
                variant="secondary"
                size="md"
                onClick={handleApplyToAll}
                data-testid="mvp-apply-to-all"
                title={t('boq.mvp.apply_to_remaining_hint', {
                  defaultValue:
                    'Re-use these picks for all other multi-variant items in this batch',
                })}
              >
                {t('boq.mvp.apply_to_remaining', {
                  defaultValue: 'Apply to remaining {{count}}',
                  count: remainingCount,
                })}
              </Button>
            )}
            <Button
              ref={applyButtonRef}
              variant="primary"
              size="md"
              onClick={handleApply}
              data-testid="mvp-apply"
            >
              {t('boq.mvp.apply', { defaultValue: 'Apply & add to BOQ' })}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ── Sub-components ───────────────────────────────────────────────────── */

function BulkChip({
  onClick,
  label,
  icon,
  testId,
}: {
  onClick: () => void;
  label: string;
  icon?: React.ReactNode;
  testId?: string;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-surface-primary border border-border-light hover:bg-surface-hover text-content-secondary transition-colors"
      data-testid={testId}
    >
      {icon}
      {label}
    </button>
  );
}

function DefaultRow({
  slot,
  picked,
  onPick,
  label,
  strategy,
}: {
  slot: VariantSlot;
  picked: boolean;
  onPick: () => void;
  label: string;
  strategy: 'mean' | 'median';
}) {
  return (
    <button
      onClick={onPick}
      className={
        'w-full px-4 py-2.5 flex items-start gap-3 text-start hover:bg-surface-hover ' +
        (picked ? 'bg-blue-50/50 dark:bg-blue-950/30 ring-1 ring-inset ring-oe-blue/30' : '')
      }
      data-testid={`mvp-row-${slot.slotId}-default-${strategy}`}
    >
      <div
        className={
          'mt-0.5 h-4 w-4 rounded-full border-2 shrink-0 flex items-center justify-center ' +
          (picked ? 'border-oe-blue bg-oe-blue' : 'border-border')
        }
      >
        {picked && <Check size={10} className="text-white" />}
      </div>
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium leading-snug">{label}</span>
      </div>
    </button>
  );
}

/* ── Helper used by callers to build the slots array ──────────────────── */

interface CostItemLike {
  description?: string;
  unit?: string;
  currency?: string;
  metadata_?: {
    variants?: CostVariant[];
    variant_stats?: VariantStats;
  };
  components?: Array<{
    name: string;
    /** CWICR resource_code — used as the variant-catalog dedupe key. */
    code?: string;
    unit: string;
    quantity?: number;
    available_variants?: CostVariant[];
    available_variant_stats?: VariantStats;
  }>;
}

/** Stable hash of a variant catalog by its label sequence — used to detect
 *  when two slots ship the same abstract-resource catalog under different
 *  human-readable names. CWICR rates routinely surface the cost item's
 *  top-level variants as one of the components too (e.g. top-level
 *  "Стоманени конструкции" + comp[0] "Монтаж на метални конструкции" both
 *  resolve to the same 8-variant beam catalog), so dedupe-by-resource_code
 *  alone misses the top-vs-component case. */
export function variantCatalogHash(variants: CostVariant[]): string {
  return variants.map((v) => (v.label || '').trim()).join('|');
}

/** Build the variant-slot list for one CostItem. Order is stable: top-level
 *  catalog variants first (when present), then components in their original
 *  order. The slotId on each entry is the routing key the caller uses to
 *  thread picks back into the position metadata.
 *
 *  Dedupes by ``resource_code`` AND by variant-label-set hash:
 *   - Two components sharing a code (real CWICR shape — e.g.
 *     ``KADX_KATO_KAKASA_KATO`` carries two rows both pointing at
 *     ``KALI-RI-KATO-KANE`` with identical 3-variant catalogs) collapse to
 *     one picker slot.
 *   - The cost-item's top-level catalog often mirrors ``component[0]`` (the
 *     "abstract resource" the rate is built around). When their label sets
 *     match, only the COMPONENT slot is kept — the synthetic top slot is
 *     dropped to stop the modal from showing two identical ▾N cards. */
export function collectVariantSlots(
  item: CostItemLike,
  fallbackCurrency: string,
): VariantSlot[] {
  const itemCurrency = (item.currency && item.currency.trim()) || fallbackCurrency;
  const top = item.metadata_?.variants;
  const topStats = item.metadata_?.variant_stats;

  const components = item.components || [];
  // Pre-compute label-set hashes for every component carrying a catalog so
  // we can decide whether the top slot is a duplicate before pushing.
  const componentHashes = new Set<string>();
  for (const c of components) {
    if (
      c.available_variants &&
      c.available_variants.length >= 2 &&
      c.available_variant_stats
    ) {
      componentHashes.add(variantCatalogHash(c.available_variants));
    }
  }

  const out: VariantSlot[] = [];
  const seenHashes = new Set<string>();
  const seenCodes = new Set<string>();

  if (top && top.length >= 2 && topStats) {
    const topHash = variantCatalogHash(top);
    // Skip the top slot when a component already carries the same catalog —
    // otherwise the user sees two slots with the same options, same price,
    // same delta, and we'd push an unwanted third resource into the BOQ.
    if (!componentHashes.has(topHash)) {
      seenHashes.add(topHash);
      out.push({
        slotId: 'top',
        name: (topStats.common_start || '').trim() || item.description || 'Resource',
        unit: item.unit || 'pcs',
        quantity: 1,
        variants: top,
        stats: topStats,
        currency: itemCurrency,
      });
    }
  }

  for (const [i, c] of components.entries()) {
    if (
      c.available_variants &&
      c.available_variants.length >= 2 &&
      c.available_variant_stats
    ) {
      const code = (c.code || '').trim();
      const codeKey = code || `__c${i}`;
      if (seenCodes.has(codeKey)) continue;
      const hash = variantCatalogHash(c.available_variants);
      if (seenHashes.has(hash)) continue;
      seenCodes.add(codeKey);
      seenHashes.add(hash);
      out.push({
        slotId: `comp:${i}`,
        name: c.name,
        unit: c.unit,
        quantity: c.quantity ?? 1,
        variants: c.available_variants,
        stats: c.available_variant_stats,
        currency: itemCurrency,
      });
    }
  }
  return out;
}
