// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <MultiCurrencyTotal> — honest cross-currency aggregation display.
//
// Why this exists (Wave 10 audit):
//   Several rollups across the app (CRM pipeline stage totals, PropDev
//   "contracted value" KPI, Finance dashboard cards, …) used to sum
//   line items whose ``currency`` field could differ row to row, then
//   stamp the resulting (arithmetically meaningless) sum with the
//   *first-seen* currency code. A pipeline column holding €100k + $50k
//   would show "$150,000" or "€150,000" depending on row order —
//   silently wrong in either case.
//
// Policy (no FX, no silent fallback):
//   * We never convert between currencies in the UI. Backend follow-up
//     may add admin-opt-in FX conversion; until then, honesty beats
//     convenience.
//   * Items are grouped by ISO-4217 code and summed per group.
//   * Per-currency totals are rendered through <MoneyDisplay>, which
//     handles locale formatting and the "currency not set" em-dash.
//   * Three variants cover the three layout shapes the audit flagged:
//        - inline:    "€100k + $50k + £25k" — for compact lists
//                     (pipeline column headers, table footers).
//        - collapsed: collapses to a single line + an aside with the
//                     full breakdown. Best for KPI tiles where space
//                     is at a premium.
//        - kpi:       a primary-currency total (matches the surrounding
//                     KPI tile's accent) with a small "+ other
//                     currencies" hint when applicable.
//
// Decimal-safety note:
//   The repo has no Decimal-arithmetic dependency (see the architecture guide §
//   constraints — no new deps). We accept ``string`` amounts (the v3
//   Decimal-as-string contract) and parse with parseFloat for
//   summation, matching the convention already used by toNumber/toNum
//   helpers throughout features/{crm,property-dev,finance}. Any
//   precision loss here is identical to what those call sites already
//   tolerated; the win is purely the *currency split*. A future Decimal
//   upgrade can land here in one place without touching call sites.

import { useId, useMemo, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

import { MoneyDisplay } from './MoneyDisplay';
import { fmtList } from '@/shared/lib/formatters';

export interface CurrencyAmount {
  amount: number | string | null | undefined;
  currency: string | null | undefined;
}

export type MultiCurrencyVariant = 'inline' | 'collapsed' | 'kpi';

export interface MultiCurrencyTotalProps {
  /** Raw line items to roll up. Items with no/invalid currency are
   *  silently dropped (with a single dev-mode warning). Items with
   *  ``amount=null`` are skipped without warning. */
  items: CurrencyAmount[];
  /** Layout: see file-header comment for trade-offs. Defaults to
   *  ``inline`` since that matches the existing pre-fix call sites the
   *  closest. */
  variant?: MultiCurrencyVariant;
  /** For ``variant='kpi'`` only — the project/development's default
   *  currency. The KPI tile shows its sum, and a "+ other currencies"
   *  hint when other codes are present. Ignored by other variants. */
  primaryCurrency?: string;
  /** Forwarded to the outer span. */
  className?: string;
  /** Forwarded to each <MoneyDisplay>. */
  compact?: boolean;
}

interface CurrencyGroup {
  currency: string;
  /** Pre-summed total for the group, in the currency's main unit. */
  total: number;
  /** Number of source items that contributed to this group. Useful
   *  for showing "3 deals" in the breakdown popover. */
  count: number;
}

// One-shot dev-mode warning for malformed input. We avoid a per-instance
// ref here because the input is the parent's responsibility (not a
// component prop the user can fix at runtime), and a single console
// breadcrumb is enough.
let warnedMissingCurrency = false;

function groupByCurrency(items: CurrencyAmount[]): CurrencyGroup[] {
  const map = new Map<string, CurrencyGroup>();
  for (const item of items) {
    if (item.amount == null) continue;
    const raw = typeof item.currency === 'string' ? item.currency.trim() : '';
    // Mirror MoneyDisplay's strict-currency policy: drop items whose
    // currency is missing or not in ISO-4217 shape, so we never display
    // a number with a wrong/guessed code.
    if (!raw || !/^[A-Z]{3}$/.test(raw)) {
      if (import.meta.env.DEV && !warnedMissingCurrency) {
        warnedMissingCurrency = true;
        // eslint-disable-next-line no-console
        console.warn(
          '[MultiCurrencyTotal] dropped item with missing/invalid currency',
          item,
        );
      }
      continue;
    }
    const numeric =
      typeof item.amount === 'string' ? parseFloat(item.amount) : item.amount;
    if (!Number.isFinite(numeric)) continue;
    const existing = map.get(raw);
    if (existing) {
      existing.total += numeric;
      existing.count += 1;
    } else {
      map.set(raw, { currency: raw, total: numeric, count: 1 });
    }
  }
  // Stable ordering: alphabetical by ISO code. Avoids the original bug
  // (first-seen drift) and also makes snapshots deterministic for tests.
  return Array.from(map.values()).sort((a, b) =>
    a.currency.localeCompare(b.currency),
  );
}

/**
 * Render N per-currency totals as a chip strip, optionally compacted.
 *
 * This is the "inline" base case the other variants compose on top of.
 */
function InlineChipStrip({
  groups,
  compact,
  className,
}: {
  groups: CurrencyGroup[];
  compact: boolean;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        'inline-flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5',
        className,
      )}
    >
      {groups.map((group, idx) => (
        <span key={group.currency} className="inline-flex items-baseline">
          {idx > 0 && (
            <span className="mr-1 text-content-tertiary" aria-hidden="true">
              +
            </span>
          )}
          <MoneyDisplay
            amount={group.total}
            currency={group.currency}
            compact={compact}
          />
        </span>
      ))}
    </span>
  );
}

export function MultiCurrencyTotal({
  items,
  variant = 'inline',
  primaryCurrency,
  className,
  compact = false,
}: MultiCurrencyTotalProps) {
  const { t } = useTranslation();
  const tooltipId = useId();
  const [showBreakdown, setShowBreakdown] = useState(false);

  const groups = useMemo(() => groupByCurrency(items), [items]);

  // Empty list — match MoneyDisplay's "no data" rendering so the API
  // is interchangeable as a drop-in replacement.
  if (groups.length === 0) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  // Single currency — degrade to plain MoneyDisplay rendering for all
  // variants. The whole point of this component is the multi-currency
  // case; in the homogeneous case it must be visually identical to
  // what the page used to render so we don't churn the UI for the 99%
  // tenant.
  if (groups.length === 1) {
    const only = groups[0]!;
    return (
      <MoneyDisplay
        amount={only.total}
        currency={only.currency}
        compact={compact}
        className={className}
      />
    );
  }

  // From here down: multi-currency rendering.

  if (variant === 'inline') {
    return (
      <InlineChipStrip
        groups={groups}
        compact={compact}
        className={className}
      />
    );
  }

  if (variant === 'kpi') {
    // KPI variant: show the primary-currency total prominently, plus a
    // small "other currencies" hint that expands into a breakdown.
    // If no primaryCurrency is supplied, or it isn't present in the
    // groups, fall back to the largest-by-count group so the headline
    // figure is still meaningful (rather than rendering an em-dash on
    // a tile labelled "Contracted value").
    const primaryGroup =
      (primaryCurrency &&
        groups.find((g) => g.currency === primaryCurrency.toUpperCase())) ||
      groups.slice().sort((a, b) => b.count - a.count)[0]!;
    const others = groups.filter((g) => g.currency !== primaryGroup.currency);
    return (
      <span className={clsx('inline-flex flex-col items-start', className)}>
        <MoneyDisplay
          amount={primaryGroup.total}
          currency={primaryGroup.currency}
          compact={compact}
        />
        {others.length > 0 && (
          <span
            className="mt-0.5 text-2xs text-content-tertiary"
            title={t('multiCurrency.includes_other', {
              defaultValue: 'Includes amounts in other currencies',
            })}
          >
            {t('multiCurrency.plus_other_n', {
              defaultValue: '+ {{count}} other',
              count: others.length,
            })}
            {' · '}
            {fmtList(others.map((g) => g.currency))}
          </span>
        )}
      </span>
    );
  }

  // variant === 'collapsed'
  const label = t('multiCurrency.mixed_n_label', {
    defaultValue: 'Mixed ({{count}} currencies)',
    count: groups.length,
  });
  return (
    <span className={clsx('relative inline-flex items-baseline gap-1', className)}>
      <button
        type="button"
        className="cursor-help underline decoration-dotted underline-offset-2 text-content-secondary hover:text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 rounded"
        aria-describedby={tooltipId}
        aria-expanded={showBreakdown}
        onClick={() => setShowBreakdown((s) => !s)}
        onMouseEnter={() => setShowBreakdown(true)}
        onMouseLeave={() => setShowBreakdown(false)}
        onFocus={() => setShowBreakdown(true)}
        onBlur={() => setShowBreakdown(false)}
      >
        {label}
      </button>
      {showBreakdown && (
        <span
          id={tooltipId}
          role="tooltip"
          className="absolute top-full left-0 z-50 mt-1 min-w-[12rem] rounded-lg border border-divider bg-surface-primary p-2 shadow-lg"
        >
          <span className="mb-1 block text-2xs uppercase tracking-wider text-content-tertiary">
            {t('multiCurrency.hover_breakdown', {
              defaultValue: 'Breakdown by currency',
            })}
          </span>
          <span className="flex flex-col gap-0.5 text-xs">
            {groups.map((g) => (
              <span key={g.currency} className="flex justify-between gap-3">
                <span className="font-medium text-content-secondary">
                  {g.currency}
                </span>
                <MoneyDisplay
                  amount={g.total}
                  currency={g.currency}
                  compact={compact}
                />
              </span>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}
